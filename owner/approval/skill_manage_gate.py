"""Feishu skill_manage write gate — owner customization.

Strict skill approval for gateway Feishu sessions when the active profile is
on the ``owner.approvals.skill_manage.profiles`` whitelist in patch.yaml.

Behavior (v1):
- Only ``skill_manage`` write actions are gated (not skills_list / skill_view).
- Only Feishu/Lark sessions escalate; CLI and other platforms are no-ops.
- Ordinary file tools / terminal are intentionally out of scope (bypass OK).
- When the gate is active for the profile, background_review skill evolution
  is suppressed (``review_skills=False``). Curator is not touched.
- Wait blocks the agent thread (same human-gate as exec approval).
- Approval cards go to ``approval_home_chat_id`` (e.g. 效率为王), NOT the
  conversation chat that triggered skill_manage. Multi-profile routing decides
  which profile runs the conversation; the home is only the approval sink.
- Default wait timeout is 24h (configurable); activity is kept warm so the
  gateway inactivity watchdog does not kill the turn.
- Deny / timeout hard-stops the turn (``agent.interrupt``) so the model cannot
  retry or jailbreak in the same turn.
- YOLO does not bypass this gate.

Integration:
- pre_tool_call hook in owner-extensions (runs the gate, returns block or None)
- AIAgent._spawn_background_review thin wrap (suppress skill review)
- tools.approval._get_approval_timeout context override (24h wait)

Removable: deleting this module + unregistering hooks restores stock behavior.
"""

from __future__ import annotations

import contextvars
import logging
import threading
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Sequence, Set

logger = logging.getLogger(__name__)

WRITE_ACTIONS: frozenset[str] = frozenset({
    "create",
    "edit",
    "patch",
    "delete",
    "write_file",
    "remove_file",
})

FEISHU_PLATFORMS: frozenset[str] = frozenset({"feishu", "lark"})

# 24 hours — skill SKILL.md review can take a long time; keep warm via
# activity touches so agent.gateway_timeout (inactivity) does not fire.
DEFAULT_TIMEOUT_SECONDS = 24 * 60 * 60

_timeout_override: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar(
    "skill_manage_approval_timeout",
    default=None,
)

# Process-global gateway ref for resolving the live agent (activity + interrupt).
_GATEWAY_REF: Any = None
_GATEWAY_LOCK = threading.Lock()

_orig_get_approval_timeout = None
_bg_spawn_patched = False
_timeout_patched = False


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _load_skill_manage_cfg() -> Dict[str, Any]:
    try:
        from owner.patch_config import load_patch_config

        owner = load_patch_config() or {}
        cfg = owner.get("approvals", {}).get("skill_manage", {})
        return cfg if isinstance(cfg, dict) else {}
    except Exception:
        return {}


def get_timeout_seconds() -> int:
    cfg = _load_skill_manage_cfg()
    raw = cfg.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
    try:
        val = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_SECONDS
    return max(val, 1)


def get_approval_home_chat_id() -> str:
    """Fixed Feishu chat that receives skill_manage approval cards.

    Distinct from the conversation chat: multi-profile routing can put the
    agent turn anywhere; approvals always land on this home when set.
    """
    cfg = _load_skill_manage_cfg()
    for key in ("approval_home_chat_id", "approval_chat_id"):
        raw = cfg.get(key)
        if raw is not None and str(raw).strip():
            return str(raw).strip()
    return ""


def is_gate_enabled() -> bool:
    """True when patch says enabled AND current profile is on the whitelist."""
    cfg = _load_skill_manage_cfg()
    if not cfg.get("enabled", False):
        return False
    profiles = cfg.get("profiles") or []
    if not isinstance(profiles, list) or not profiles:
        return False
    allowed = {str(p).strip() for p in profiles if str(p).strip()}
    if not allowed:
        return False
    return _current_profile() in allowed


def should_suppress_background_skill_review() -> bool:
    """Profile-level: when gate is on, disable bg skill evolution by default."""
    if not is_gate_enabled():
        return False
    cfg = _load_skill_manage_cfg()
    # Default true when key absent
    return bool(cfg.get("disable_background_skill_review", True))


def _current_profile() -> str:
    try:
        from hermes_cli.profiles import get_active_profile_name

        name = get_active_profile_name() or "default"
        return str(name).strip() or "default"
    except Exception:
        return "default"


def _session_platform() -> str:
    try:
        from gateway.session_context import get_session_env

        return (get_session_env("HERMES_SESSION_PLATFORM", "") or "").strip().lower()
    except Exception:
        try:
            import os

            return (os.getenv("HERMES_SESSION_PLATFORM", "") or "").strip().lower()
        except Exception:
            return ""


def _is_background_review() -> bool:
    try:
        from tools.skill_provenance import is_background_review

        return bool(is_background_review())
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Escalation decision
# ---------------------------------------------------------------------------

def should_escalate(tool_name: str, args: Optional[Dict[str, Any]]) -> bool:
    """Whether this tool call must wait for human approval."""
    if tool_name != "skill_manage":
        return False
    if not is_gate_enabled():
        return False
    if _session_platform() not in FEISHU_PLATFORMS:
        return False
    # Background review should not be spawned when gate is on; if it still
    # reaches here, refuse (no human on the fork).
    if _is_background_review():
        return True
    action = str((args or {}).get("action") or "").strip()
    return action in WRITE_ACTIONS


def build_approval_message(args: Optional[Dict[str, Any]]) -> str:
    args = args or {}
    action = str(args.get("action") or "?").strip()
    name = str(args.get("name") or "?").strip()
    parts = [
        f"skill_manage {action} '{name}'",
        "— 需确认后才写入技能库。",
        "批准后继续本轮；拒绝/超时将结束本轮，请勿换方式重试。",
    ]
    file_path = args.get("file_path")
    if file_path:
        parts.append(f"file_path={file_path}")
    category = args.get("category")
    if category:
        parts.append(f"category={category}")
    return " ".join(parts)


def rule_key_for_args(args: Optional[Dict[str, Any]]) -> str:
    action = str((args or {}).get("action") or "unknown").strip() or "unknown"
    return f"skill_manage:{action}"


# ---------------------------------------------------------------------------
# Gateway / agent helpers (activity keepalive + hard stop)
# ---------------------------------------------------------------------------

def cache_gateway(gateway: Any) -> None:
    global _GATEWAY_REF
    if gateway is None:
        return
    with _GATEWAY_LOCK:
        _GATEWAY_REF = gateway


def _resolve_running_agent() -> Any:
    try:
        from tools.approval import get_current_session_key

        session_key = get_current_session_key(default="") or ""
    except Exception:
        session_key = ""
    if not session_key:
        return None
    with _GATEWAY_LOCK:
        gw = _GATEWAY_REF
    if gw is None:
        return None
    agents = getattr(gw, "_running_agents", None) or {}
    agent = agents.get(session_key)
    # Pending sentinel has no interrupt / activity API
    if agent is None or not hasattr(agent, "interrupt"):
        return None
    return agent


def _prepare_activity_keepalive() -> None:
    """Bind activity callback + touch so gateway inactivity timeout stays green."""
    agent = _resolve_running_agent()
    if agent is None:
        return
    try:
        from tools.environments.base import set_activity_callback

        touch = getattr(agent, "_touch_activity", None)
        if callable(touch):
            set_activity_callback(touch)
            touch("waiting for skill_manage approval")
    except Exception:
        logger.debug("skill_manage_gate: activity keepalive setup failed", exc_info=True)


def _resolve_feishu_adapter() -> Any:
    with _GATEWAY_LOCK:
        gw = _GATEWAY_REF
    if gw is None:
        return None
    adapters = getattr(gw, "adapters", {}) or {}
    try:
        from gateway.config import Platform

        adapter = adapters.get(Platform.FEISHU)
    except Exception:
        adapter = None
    if adapter is None:
        adapter = adapters.get("feishu")
    return adapter


def _resolve_live_loop(adapter: Any) -> Any:
    candidates = []
    if adapter is not None:
        candidates.append(getattr(adapter, "_loop", None))
        candidates.append(getattr(adapter, "_ws_thread_loop", None))
    with _GATEWAY_LOCK:
        gw = _GATEWAY_REF
    if gw is not None:
        candidates.append(getattr(gw, "_loop", None))
    for loop in candidates:
        if loop is None:
            continue
        try:
            if getattr(loop, "is_closed", lambda: False)():
                continue
        except Exception:
            continue
        return loop
    return None


def _make_home_approval_notify(session_key: str, home_chat_id: str):
    """Notify callback that sends the approval card to the fixed home chat.

    Session correlation still uses *session_key* (the conversation that is
    blocked). Card clicks in the home chat resolve that same session.

    On sub-profiles (send_only), button values are tagged with
    ``hermes_profile`` so the main gateway WS can route the click back here.
    """

    def _notify(approval_data: dict) -> None:
        adapter = _resolve_feishu_adapter()
        if adapter is None:
            raise RuntimeError("Feishu adapter unavailable for skill approval home send")
        if getattr(type(adapter), "send_exec_approval", None) is None:
            raise RuntimeError("Feishu adapter has no send_exec_approval")

        loop = _resolve_live_loop(adapter)
        if loop is None:
            raise RuntimeError("No live event loop for skill approval home send")

        import asyncio

        cmd = approval_data.get("command", "")
        desc = approval_data.get("description", "skill_manage approval")
        allow_permanent = bool(approval_data.get("allow_permanent", False))

        # Tag buttons for multi-profile click routing (main WS → this profile).
        _tag_token = None
        try:
            from hermes_cli.profiles import get_active_profile_name
            from owner.feishu import approval as feishu_approval_mod
            from owner.feishu.card_sender import _inject_profile_tag

            profile_tag = get_active_profile_name() or ""
            if profile_tag and profile_tag not in ("default", "custom"):
                _orig_build = feishu_approval_mod.build_approval_card

                def _tagged_build(*args, **kwargs):
                    card = _orig_build(*args, **kwargs)
                    try:
                        _inject_profile_tag(card, profile_tag)
                    except Exception:
                        pass
                    return card

                feishu_approval_mod.build_approval_card = _tagged_build
                _tag_token = (_orig_build, feishu_approval_mod)
        except Exception:
            logger.debug(
                "skill_manage_gate: profile tag wrap skipped", exc_info=True,
            )

        try:
            coro = adapter.send_exec_approval(
                chat_id=home_chat_id,
                command=cmd,
                session_key=session_key,
                description=desc,
                metadata={"chat_type": "group"},
                allow_permanent=allow_permanent,
                smart_denied=bool(approval_data.get("smart_denied", False)),
            )
            fut = asyncio.run_coroutine_threadsafe(coro, loop)
            result = fut.result(timeout=20)
        finally:
            if _tag_token is not None:
                _orig_build, mod = _tag_token
                mod.build_approval_card = _orig_build

        if not getattr(result, "success", False):
            err = getattr(result, "error", None) or "unknown send error"
            raise RuntimeError(f"skill approval home send failed: {err}")
        logger.info(
            "skill_manage_gate: approval card sent to home chat_id=%s session=%s",
            home_chat_id,
            session_key,
        )

    return _notify


def hard_stop_turn(reason: str) -> None:
    """End the current agent turn so the model cannot continue after deny."""
    agent = _resolve_running_agent()
    if agent is not None:
        try:
            agent.interrupt(reason)
            logger.info("skill_manage_gate: hard-stopped turn via agent.interrupt")
            return
        except Exception:
            logger.warning(
                "skill_manage_gate: agent.interrupt failed; falling back",
                exc_info=True,
            )
            try:
                agent._interrupt_requested = True
            except Exception:
                pass
    try:
        from tools.interrupt import set_interrupt

        set_interrupt(True)
    except Exception:
        logger.debug("skill_manage_gate: set_interrupt failed", exc_info=True)


# ---------------------------------------------------------------------------
# Timeout override for tools.approval._await_gateway_decision
# ---------------------------------------------------------------------------

@contextmanager
def approval_timeout_override(seconds: int):
    token = _timeout_override.set(int(seconds))
    try:
        yield
    finally:
        _timeout_override.reset(token)


def _patched_get_approval_timeout() -> int:
    override = _timeout_override.get()
    if override is not None:
        return int(override)
    if _orig_get_approval_timeout is not None:
        return int(_orig_get_approval_timeout())
    return 60


def apply_timeout_patch() -> None:
    """Monkey-patch tools.approval._get_approval_timeout for 24h skill waits."""
    global _orig_get_approval_timeout, _timeout_patched
    if _timeout_patched:
        return
    try:
        import tools.approval as approval_mod

        _orig_get_approval_timeout = approval_mod._get_approval_timeout
        approval_mod._get_approval_timeout = _patched_get_approval_timeout
        _timeout_patched = True
        logger.debug("skill_manage_gate: _get_approval_timeout patched")
    except Exception:
        logger.warning("skill_manage_gate: timeout patch failed", exc_info=True)


# ---------------------------------------------------------------------------
# Background skill review suppression
# ---------------------------------------------------------------------------

def apply_background_skill_suppress_patch() -> None:
    """Wrap AIAgent._spawn_background_review to force review_skills=False.

    Lazy-safe: ``run_agent`` may be partially initialized when plugins register
    (circular import). Retry on later gateway/tool hooks via
    :func:`ensure_patches`.
    """
    global _bg_spawn_patched
    if _bg_spawn_patched:
        return
    try:
        import run_agent as run_agent_mod

        AIAgent = getattr(run_agent_mod, "AIAgent", None)
        if AIAgent is None:
            return
        orig = AIAgent._spawn_background_review
    except Exception:
        logger.debug(
            "skill_manage_gate: AIAgent not ready for bg suppress (will retry)",
            exc_info=True,
        )
        return

    def _wrapped(
        self,
        messages_snapshot,
        review_memory: bool = False,
        review_skills: bool = False,
    ):
        if review_skills and should_suppress_background_skill_review():
            logger.info(
                "skill_manage_gate: suppressing background skill review "
                "(profile=%s)",
                _current_profile(),
            )
            review_skills = False
            if not review_memory:
                return None
        return orig(
            self,
            messages_snapshot,
            review_memory=review_memory,
            review_skills=review_skills,
        )

    AIAgent._spawn_background_review = _wrapped  # type: ignore[method-assign]
    _bg_spawn_patched = True
    logger.debug("skill_manage_gate: background skill suppress patch applied")


def ensure_patches() -> None:
    """Idempotent retry for patches that may fail early due to import order."""
    apply_timeout_patch()
    apply_background_skill_suppress_patch()


# ---------------------------------------------------------------------------
# Main gate (called from pre_tool_call)
# ---------------------------------------------------------------------------

def run_gate(tool_name: str, args: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Run the skill_manage approval gate.

    Returns:
        None — proceed with the tool (not gated, or approved).
        ``{"action": "block", "message": "..."}`` — deny / timeout / error;
        turn is hard-stopped on deny/timeout.
    """
    if not should_escalate(tool_name, args):
        return None

    args = args if isinstance(args, dict) else {}
    action = str(args.get("action") or "").strip()
    name = str(args.get("name") or "").strip()
    reason = build_approval_message(args)
    pattern_key = f"plugin_rule:{rule_key_for_args(args)}"
    timeout_s = get_timeout_seconds()

    # Background fork: no human — hard block without wait
    if _is_background_review():
        msg = (
            f"BLOCKED: skill_manage {action} '{name}' refused during "
            "background review while owner.approvals.skill_manage is active."
        )
        hard_stop_turn(msg)
        return {"action": "block", "message": msg}

    try:
        from tools.approval import (
            _await_gateway_decision,
            _gateway_notify_cbs,
            _lock,
            approve_session,
            get_current_session_key,
            is_approved,
        )
        from agent.redact import redact_sensitive_text
    except Exception as exc:
        msg = f"BLOCKED: skill_manage approval infrastructure unavailable ({exc})"
        hard_stop_turn(msg)
        return {"action": "block", "message": msg}

    session_key = get_current_session_key(default="") or ""
    if not session_key:
        msg = "BLOCKED: skill_manage approval requires a gateway session key."
        hard_stop_turn(msg)
        return {"action": "block", "message": msg}

    # Session-scoped re-approval for the same action (once/session buttons)
    if is_approved(session_key, pattern_key):
        logger.info(
            "skill_manage_gate: session allowlist hit key=%s", pattern_key,
        )
        return None

    # Prefer fixed approval home (e.g. 效率为王). Fall back to the session's
    # gateway notify (current conversation chat) only when home is unset.
    home_chat_id = get_approval_home_chat_id()
    notify_cb = None
    if home_chat_id:
        # Still require a registered gateway session so resolve_gateway_approval
        # can unblock this turn; the card itself goes to the home chat.
        with _lock:
            has_channel = session_key in _gateway_notify_cbs
        if not has_channel:
            msg = (
                "BLOCKED: skill_manage requires a gateway session with an "
                "approval channel, but none is registered for this session."
            )
            hard_stop_turn(msg)
            return {"action": "block", "message": msg}
        notify_cb = _make_home_approval_notify(session_key, home_chat_id)
    else:
        with _lock:
            notify_cb = _gateway_notify_cbs.get(session_key)
        if notify_cb is None:
            msg = (
                "BLOCKED: skill_manage requires interactive Feishu approval, "
                "but no gateway approval channel is registered for this session "
                "(and approval_home_chat_id is not set)."
            )
            hard_stop_turn(msg)
            return {"action": "block", "message": msg}

    # Permanent button follows owner.approvals.allow_permanent (default false)
    allow_permanent = False
    try:
        from owner.feishu.approval import get_allow_permanent

        allow_permanent = bool(get_allow_permanent())
    except Exception:
        allow_permanent = False

    display_target = f"<skill_manage {action} {name}>"
    # Include origin session hint so reviewers in the home group know context.
    origin_hint = ""
    try:
        from gateway.session_context import get_session_env

        origin_chat = get_session_env("HERMES_SESSION_CHAT_ID", "") or ""
        if origin_chat and origin_chat != home_chat_id:
            origin_hint = f" [from chat {origin_chat}]"
    except Exception:
        origin_hint = ""
    desc = redact_sensitive_text(reason + origin_hint)
    approval_data = {
        "command": redact_sensitive_text(display_target),
        "pattern_key": pattern_key,
        "pattern_keys": [pattern_key],
        "description": desc,
        "allow_permanent": allow_permanent,
    }

    _prepare_activity_keepalive()
    apply_timeout_patch()

    logger.info(
        "skill_manage_gate: waiting for approval action=%s name=%s "
        "timeout_s=%s session=%s home=%s",
        action,
        name,
        timeout_s,
        session_key,
        home_chat_id or "(session chat)",
    )

    with approval_timeout_override(timeout_s):
        decision = _await_gateway_decision(
            session_key, notify_cb, approval_data, surface="skill_manage",
        )

    if decision.get("notify_failed"):
        msg = (
            "BLOCKED: Failed to send skill_manage approval request to Feishu. "
            "Do NOT retry via another path."
        )
        hard_stop_turn(msg)
        return {"action": "block", "message": msg}

    resolved = bool(decision.get("resolved"))
    choice = decision.get("choice")
    deny_reason = decision.get("reason")

    if resolved and choice in {"once", "session", "always"}:
        if choice == "session":
            approve_session(session_key, pattern_key)
        elif choice == "always":
            # Still session-scope for skill writes even if card offered always —
            # permanent allowlist for skill_manage is intentionally avoided.
            approve_session(session_key, pattern_key)
            logger.info(
                "skill_manage_gate: 'always' mapped to session-only for skill writes"
            )
        logger.info(
            "skill_manage_gate: approved choice=%s action=%s name=%s",
            choice, action, name,
        )
        return None

    # deny / timeout / interrupt
    if not resolved:
        detail = "timed out without user response (silence is not consent)"
    elif choice == "deny":
        detail = "denied by user"
    else:
        detail = f"not approved (choice={choice!r})"
    reason_add = ""
    if resolved and deny_reason:
        reason_add = f' Reason: "{deny_reason}".'

    msg = (
        f"BLOCKED: skill_manage {action} '{name}' {detail}.{reason_add} "
        "The write was NOT applied. This turn will stop. "
        "Do NOT retry, rephrase, or use terminal/other tools to write the skill."
    )
    hard_stop_turn(msg)
    logger.info(
        "skill_manage_gate: denied/timeout action=%s name=%s resolved=%s choice=%s",
        action, name, resolved, choice,
    )
    return {"action": "block", "message": msg}


def apply_all_patches() -> None:
    """Idempotent: timeout override + bg skill suppress (best-effort)."""
    ensure_patches()
