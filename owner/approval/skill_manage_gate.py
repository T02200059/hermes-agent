"""Feishu skill approval gate - owner customization.

Strict skill approval for gateway Feishu sessions when the active profile is
on the ``feishu.skill_approval.profiles`` whitelist in patch_feishu_profile.yaml.

Behavior (v2):
- Only ``skill_manage`` write actions are gated (not skills_list / skill_view).
- Only Feishu/Lark sessions escalate; CLI and other platforms are no-ops.
- Ordinary file tools / terminal are intentionally out of scope (bypass OK).
- When the gate is active for the profile, background_review skill evolution
  is suppressed (``review_skills=False``). Curator is not touched.
- Wait blocks the agent thread (same human-gate as exec approval).
- Approval cards are self-built (owner/feishu/skill_approval_card.py) and sent
  via ``send_card_via_rest`` to ``approval_home_chat_id``.  Button clicks are
  handled by a dedicated ``hermes_action == "skill_approval_gate"`` dispatch
  branch that calls ``resolve_gateway_approval`` directly.
- A "waiting for approval" text message is sent to the origin conversation
  chat so the user knows the agent is blocked.
- Default wait timeout is 24h (configurable); activity is kept warm so the
  gateway inactivity watchdog does not kill the turn.
- Deny / timeout hard-stops the turn (``agent.interrupt``) so the model cannot
  retry or jailbreak in the same turn.
- YOLO does not bypass this gate.

Config source: ``~/.hermes/patch_feishu_profile.yaml`` under
``feishu.skill_approval`` (profile-level, not global).

Integration:
- pre_tool_call hook in owner-extensions (runs the gate, returns block or None)
- AIAgent._spawn_background_review thin wrap (suppress skill review)
- tools.approval._get_approval_timeout context override (24h wait)
- adapter._dispatch_card_action: ``skill_approval_gate`` branch -> handle_card_click

Removable: deleting this module + unregistering hooks restores stock behavior.
"""

from __future__ import annotations

import asyncio
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

# 24 hours - skill SKILL.md review can take a long time; keep warm via
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
# Config (reads from patch_feishu_profile.yaml, not patch.yaml)
# ---------------------------------------------------------------------------

def _load_skill_approval_cfg() -> Dict[str, Any]:
    """Load ``feishu.skill_approval`` from patch_feishu_profile.yaml."""
    try:
        from owner.patch_config import load_patch_feishu_profile_config

        data = load_patch_feishu_profile_config() or {}
        feishu = data.get("feishu", {})
        if not isinstance(feishu, dict):
            return {}
        cfg = feishu.get("skill_approval", {})
        return cfg if isinstance(cfg, dict) else {}
    except Exception:
        return {}


# Backward compat alias
_load_skill_manage_cfg = _load_skill_approval_cfg


def get_timeout_seconds() -> int:
    cfg = _load_skill_approval_cfg()
    raw = cfg.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
    try:
        val = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_SECONDS
    return max(val, 1)


def get_approval_home_chat_id() -> str:
    """Fixed Feishu chat that receives skill approval cards.

    Distinct from the conversation chat: multi-profile routing can put the
    agent turn anywhere; approvals always land on this home when set.
    """
    cfg = _load_skill_approval_cfg()
    for key in ("approval_home_chat_id", "approval_chat_id"):
        raw = cfg.get(key)
        if raw is not None and str(raw).strip():
            return str(raw).strip()
    return ""


def is_gate_enabled() -> bool:
    """True when config says enabled AND current profile is on the whitelist."""
    cfg = _load_skill_approval_cfg()
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
    cfg = _load_skill_approval_cfg()
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


def _get_origin_chat_id() -> str:
    """Get the chat_id of the conversation that triggered the skill_manage call."""
    try:
        from gateway.session_context import get_session_env

        return get_session_env("HERMES_SESSION_CHAT_ID", "") or ""
    except Exception:
        return ""


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
        "- 需确认后才写入技能库。",
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
            touch("waiting for skill approval")
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


def _resolve_live_loop() -> Any:
    """Find a live event loop from adapter or gateway."""
    adapter = _resolve_feishu_adapter()
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


def _send_origin_chat_notice(
    *,
    action: str,
    name: str,
    origin_chat_id: str,
    home_chat_id: str,
) -> None:
    """Send a 'waiting for approval' text message to the origin conversation chat.

    This tells the user in the sub-profile's conversation that the agent is
    blocked waiting for approval.  The actual approval card goes to the home
    chat (approval group).
    """
    if not origin_chat_id or origin_chat_id == home_chat_id:
        return  # same chat, don't send twice

    adapter = _resolve_feishu_adapter()
    if adapter is None:
        return

    loop = _resolve_live_loop()
    if loop is None:
        return

    msg = (
        f"⏳ skill_manage {action} '{name}' 需要审批。\n"
        "审批卡片已发送到审批专属群，请等待审批结果。\n"
        "本轮将等待审批结果（最长 24h）。"
    )

    async def _send() -> None:
        try:
            await adapter.send(chat_id=origin_chat_id, content=msg)
        except Exception as exc:
            logger.warning(
                "skill_manage_gate: origin chat notice failed: %s", exc,
            )

    try:
        asyncio.run_coroutine_threadsafe(_send(), loop).result(timeout=10)
    except Exception as exc:
        logger.warning(
            "skill_manage_gate: origin chat notice dispatch failed: %s", exc,
        )


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
# Notify callback: send self-built approval card to home chat
# ---------------------------------------------------------------------------

def _make_home_approval_notify(
    session_key: str,
    home_chat_id: str,
    *,
    action: str,
    name: str,
    args: Dict[str, Any],
    profile: str,
    origin_chat_id: str,
):
    """Build a notify callback that sends a self-built skill approval card.

    Uses ``owner.feishu.skill_approval_card.send_skill_approval_card`` (via
    ``send_card_via_rest``) instead of ``send_exec_approval``.  The card
    carries ``session_key`` + ``chat_id`` in button values so clicks can
    resolve via ``resolve_gateway_approval``.
    """

    def _notify(approval_data: dict) -> None:
        adapter = _resolve_feishu_adapter()
        if adapter is None:
            raise RuntimeError("Feishu adapter unavailable for skill approval")

        loop = _resolve_live_loop()
        if loop is None:
            raise RuntimeError("No live event loop for skill approval card send")

        from owner.feishu.skill_approval_card import send_skill_approval_card

        coro = send_skill_approval_card(
            adapter,
            chat_id=home_chat_id,
            action=action,
            name=name,
            args=args,
            profile=profile,
            origin_chat_id=origin_chat_id,
            session_key=session_key,
            metadata={"chat_type": "group"},
        )
        fut = asyncio.run_coroutine_threadsafe(coro, loop)
        result = fut.result(timeout=20)

        if not getattr(result, "success", False):
            err = getattr(result, "error", None) or "unknown send error"
            raise RuntimeError(f"skill approval card send failed: {err}")
        logger.info(
            "skill_manage_gate: approval card sent to home chat_id=%s session=%s",
            home_chat_id,
            session_key,
        )

    return _notify


# ---------------------------------------------------------------------------
# Main gate (called from pre_tool_call)
# ---------------------------------------------------------------------------

def run_gate(tool_name: str, args: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Run the skill approval gate.

    Returns:
        None - proceed with the tool (not gated, or approved).
        ``{"action": "block", "message": "..."}`` - deny / timeout / error;
        turn is hard-stopped on deny/timeout.
    """
    if not should_escalate(tool_name, args):
        return None

    args = args if isinstance(args, dict) else {}
    action = str(args.get("action") or "").strip()
    name = str(args.get("name") or "").strip()
    pattern_key = f"plugin_rule:{rule_key_for_args(args)}"
    timeout_s = get_timeout_seconds()

    # Background fork: no human - hard block without wait
    if _is_background_review():
        msg = (
            f"BLOCKED: skill_manage {action} '{name}' refused during "
            "background review while skill_approval gate is active."
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
    except Exception as exc:
        msg = f"BLOCKED: skill approval infrastructure unavailable ({exc})"
        hard_stop_turn(msg)
        return {"action": "block", "message": msg}

    session_key = get_current_session_key(default="") or ""
    if not session_key:
        msg = "BLOCKED: skill approval requires a gateway session key."
        hard_stop_turn(msg)
        return {"action": "block", "message": msg}

    # Session-scoped re-approval for the same action (once/session buttons)
    if is_approved(session_key, pattern_key):
        logger.info(
            "skill_manage_gate: session allowlist hit key=%s", pattern_key,
        )
        return None

    home_chat_id = get_approval_home_chat_id()
    origin_chat_id = _get_origin_chat_id()
    profile = _current_profile()

    # --- Build the notify callback ---
    # The notify callback sends the self-built approval card to the home chat.
    # We still require a registered gateway session so _await_gateway_decision
    # can unblock this turn; the card itself goes to the home chat.
    if home_chat_id:
        with _lock:
            has_channel = session_key in _gateway_notify_cbs
        if not has_channel:
            msg = (
                "BLOCKED: skill approval requires a gateway session with an "
                "approval channel, but none is registered for this session."
            )
            hard_stop_turn(msg)
            return {"action": "block", "message": msg}
        notify_cb = _make_home_approval_notify(
            session_key, home_chat_id,
            action=action, name=name, args=args,
            profile=profile, origin_chat_id=origin_chat_id,
        )
    else:
        # No home chat configured - fall back to session's gateway notify
        with _lock:
            notify_cb = _gateway_notify_cbs.get(session_key)
        if notify_cb is None:
            msg = (
                "BLOCKED: skill approval requires interactive Feishu approval, "
                "but no gateway approval channel is registered for this session "
                "(and approval_home_chat_id is not set)."
            )
            hard_stop_turn(msg)
            return {"action": "block", "message": msg}

    # --- Send "waiting for approval" notice to origin chat ---
    _send_origin_chat_notice(
        action=action, name=name,
        origin_chat_id=origin_chat_id, home_chat_id=home_chat_id,
    )

    # --- Build approval_data for _await_gateway_decision ---
    # The command/description fields are used for hook logging and fallback
    # display only; the actual card content is built by skill_approval_card.
    from agent.redact import redact_sensitive_text

    display_target = f"<skill_manage {action} {name}>"
    approval_data = {
        "command": redact_sensitive_text(display_target),
        "pattern_key": pattern_key,
        "pattern_keys": [pattern_key],
        "description": redact_sensitive_text(build_approval_message(args)),
        "allow_permanent": False,
    }

    _prepare_activity_keepalive()
    apply_timeout_patch()

    logger.info(
        "skill_manage_gate: waiting for approval action=%s name=%s "
        "timeout_s=%s session=%s home=%s origin=%s",
        action,
        name,
        timeout_s,
        session_key,
        home_chat_id or "(session chat)",
        origin_chat_id or "(none)",
    )

    with approval_timeout_override(timeout_s):
        decision = _await_gateway_decision(
            session_key, notify_cb, approval_data, surface="skill_approval",
        )

    if decision.get("notify_failed"):
        msg = (
            "BLOCKED: Failed to send skill approval request to Feishu. "
            "Do NOT retry via another path."
        )
        hard_stop_turn(msg)
        return {"action": "block", "message": msg}

    resolved = bool(decision.get("resolved"))
    choice = decision.get("choice")
    deny_reason = decision.get("reason")

    # Normalize UI-label leftovers ("approve") so a stale card or a missed
    # map in skill_approval_card still unblocks the turn instead of hard-
    # stopping after a green "已批准" card (false deny).
    if choice == "approve":
        choice = "once"

    if resolved and choice in {"once", "session", "always"}:
        if choice == "session":
            approve_session(session_key, pattern_key)
        elif choice == "always":
            # Still session-scope for skill writes even if card offered always -
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
