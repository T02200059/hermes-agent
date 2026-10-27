"""[owner] C13 recap — auto trigger after long-conversation idle.

Grok Build (``session_recap.rs``) fires a "where was I" recap when the user
returns from idle. Feishu has no TUI focus signal, so we treat **quiet after a
completed turn** as the end of a long chat:

1. ``on_session_end`` (per completed turn) schedules ``idle_seconds`` (default 180).
2. New inbound (``pre_gateway_dispatch``) or ``agent_loop_stopped`` cancels it.
3. Timer fires → gate (min user turns + watermark) → same notice as ``/recap``.

Defaults match Grok: ``min_user_turns=3``, ``idle_seconds=180``. Config under
``explainers.recap.auto`` in overlay.yaml.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Dict, List, Optional, Tuple

from owner.explainers.common import normalize_platform
from owner.explainers.config import load_kind_config, resolve_enabled
from owner.explainers.recap.explain import explain_from_messages
from owner.explainers.recap.gate import (
    MIN_TURNS_FOR_AUTO_RECAP,
    RECAP_MIN_IDLE_SECONDS,
    recap_gate,
)
from owner.explainers.recap.prompt import format_delivery
from owner.explainers.recap.watermark import load_recap_watermark, save_recap_watermark

logger = logging.getLogger("hermes.owner.explainers.recap")

_AUTO_DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "min_user_turns": MIN_TURNS_FOR_AUTO_RECAP,
    "idle_seconds": RECAP_MIN_IDLE_SECONDS,
}

# Synthetic / control prefixes — not real user main turns (align C15 guard).
_SYNTHETIC_PREFIXES = (
    "[ASYNC DELEGATION",
    "[BACKGROUND",
    "[SYSTEM",
    "[OWNER",
    "[Hermes",
)

_GATEWAY_REF: Any = None
_ADAPTERS: dict[str, Any] = {}
_REF_LOCK = threading.Lock()

# session_id / gateway_session_key → (platform, chat_id)
_SESSION_ROUTES: dict[str, tuple[str, str]] = {}
_ROUTE_LOCK = threading.Lock()

# session_id → {timer, epoch, platform, chat_id}
_PENDING: dict[str, dict[str, Any]] = {}
_PENDING_LOCK = threading.Lock()
_EPOCH = 0


def load_auto_config(cfg: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Merge overlay ``explainers.recap.auto`` over Grok-aligned defaults."""
    merged = dict(_AUTO_DEFAULTS)
    raw_auto: dict[str, Any] = {}
    try:
        kind_cfg = cfg if isinstance(cfg, dict) else load_kind_config("recap")
        block = kind_cfg.get("auto") if isinstance(kind_cfg, dict) else None
        if isinstance(block, dict):
            raw_auto.update(block)
    except Exception:
        pass
    if not raw_auto:
        try:
            from owner.explainers.config import _raw_explainers

            root = _raw_explainers().get("recap") or {}
            if isinstance(root, dict) and isinstance(root.get("auto"), dict):
                raw_auto.update(root["auto"])
        except Exception:
            pass
    if "enabled" in raw_auto:
        merged["enabled"] = bool(raw_auto.get("enabled"))
    for key, default in (("min_user_turns", MIN_TURNS_FOR_AUTO_RECAP), ("idle_seconds", RECAP_MIN_IDLE_SECONDS)):
        if key in raw_auto:
            try:
                merged[key] = max(0, int(raw_auto[key]))
            except (TypeError, ValueError):
                merged[key] = default
    if merged["min_user_turns"] < 1:
        merged["min_user_turns"] = MIN_TURNS_FOR_AUTO_RECAP
    if merged["idle_seconds"] < 0:
        merged["idle_seconds"] = RECAP_MIN_IDLE_SECONDS
    return merged


def count_user_turns(messages: list[Any]) -> int:
    """Count real user prompts (skip tool/system/synthetic)."""
    n = 0
    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        if str(msg.get("role") or "").strip().lower() != "user":
            continue
        text = msg.get("content")
        if isinstance(text, list):
            parts = []
            for part in text:
                if isinstance(part, str):
                    parts.append(part)
                elif isinstance(part, dict) and part.get("type") in {"text", "input_text"}:
                    parts.append(str(part.get("text") or ""))
            text = "\n".join(parts)
        if not isinstance(text, str):
            text = str(text or "")
        stripped = text.lstrip()
        if not stripped:
            continue
        if stripped.startswith(_SYNTHETIC_PREFIXES):
            continue
        # Slash-only control with no user payload — still a turn for watermark
        # purposes (user actively engaged); count it.
        n += 1
    return n


def register_hooks(ctx: Any) -> None:
    ctx.register_hook("pre_gateway_dispatch", _on_pre_gateway_dispatch)
    ctx.register_hook("on_session_end", _on_session_end)
    ctx.register_hook("agent_loop_stopped", _on_agent_loop_stopped)
    ctx.register_hook("on_session_reset", _on_session_reset)
    logger.debug("recap_auto hooks registered")


def _on_pre_gateway_dispatch(**kwargs: Any) -> None:
    """Cache gateway/adapters/route; cancel pending auto (user returned)."""
    global _GATEWAY_REF
    gateway = kwargs.get("gateway")
    event = kwargs.get("event")
    source = kwargs.get("source")
    session_key = str(
        kwargs.get("session_key")
        or kwargs.get("gateway_session_key")
        or getattr(event, "session_key", "")
        or ""
    )
    platform = ""
    chat_id = ""
    if source is not None:
        platform = str(getattr(source, "platform", "") or "")
        chat_id = str(getattr(source, "chat_id", "") or "")
    if event is not None:
        platform = platform or str(getattr(event, "platform", "") or "")
        chat_id = chat_id or str(getattr(event, "chat_id", "") or "")
    platform = normalize_platform(platform)

    if gateway is not None:
        try:
            adapters = getattr(gateway, "adapters", {}) or {}
            with _REF_LOCK:
                _GATEWAY_REF = gateway
                for key, adapter in adapters.items():
                    k = str(getattr(key, "value", key) or "").lower()
                    if k:
                        _ADAPTERS[k] = adapter
        except Exception:
            logger.debug("recap_auto cache adapters failed", exc_info=True)

    sid_hint = ""
    if event is not None:
        sid_hint = str(getattr(event, "session_id", "") or "")
    if session_key and platform and chat_id:
        with _ROUTE_LOCK:
            _SESSION_ROUTES[session_key] = (platform, chat_id)
            if ":" in session_key:
                _SESSION_ROUTES[session_key.split(":")[-1]] = (platform, chat_id)
            if sid_hint:
                _SESSION_ROUTES[sid_hint] = (platform, chat_id)

    # User spoke → cancel idle auto for this conversation.
    for key in (sid_hint, session_key, session_key.split(":")[-1] if ":" in session_key else ""):
        if key:
            cancel_pending(key)


def _on_session_end(**kwargs: Any) -> None:
    try:
        if kwargs.get("interrupted") or kwargs.get("failed"):
            return
        if kwargs.get("completed") is False:
            return
        session_id = str(kwargs.get("session_id") or "").strip()
        if not session_id:
            return
        platform = normalize_platform(kwargs.get("platform") or "")
        route_platform, chat_id = _lookup_route(session_id, platform)
        platform = platform or route_platform
        if not resolve_enabled("recap", platform, chat_id or None):
            return
        auto_cfg = load_auto_config()
        if not auto_cfg.get("enabled", True):
            return
        if not chat_id:
            # No messaging route (CLI-only) — skip auto notice.
            return
        schedule_auto_recap(
            session_id,
            platform=platform,
            chat_id=chat_id,
            idle_seconds=float(auto_cfg["idle_seconds"]),
            min_user_turns=int(auto_cfg["min_user_turns"]),
        )
    except Exception:
        logger.debug("recap_auto on_session_end failed", exc_info=True)


def _on_agent_loop_stopped(**kwargs: Any) -> None:
    sid = str(kwargs.get("session_id") or kwargs.get("session_key") or "").strip()
    if sid:
        cancel_pending(sid)
        if ":" in sid:
            cancel_pending(sid.split(":")[-1])


def _on_session_reset(**kwargs: Any) -> None:
    sid = str(kwargs.get("session_id") or "").strip()
    if sid:
        cancel_pending(sid)


def schedule_auto_recap(
    session_id: str,
    *,
    platform: str,
    chat_id: str,
    idle_seconds: float = RECAP_MIN_IDLE_SECONDS,
    min_user_turns: int = MIN_TURNS_FOR_AUTO_RECAP,
) -> None:
    """Cancel any prior timer and schedule a new idle auto-recap."""
    global _EPOCH
    sid = str(session_id or "").strip()
    if not sid:
        return
    cancel_pending(sid)
    delay = max(0.0, float(idle_seconds))
    with _PENDING_LOCK:
        _EPOCH += 1
        epoch = _EPOCH

        def _fire() -> None:
            with _PENDING_LOCK:
                entry = _PENDING.get(sid)
                if not entry or entry.get("epoch") != epoch:
                    return
                _PENDING.pop(sid, None)
            try:
                run_auto_recap(
                    sid,
                    platform=str(entry.get("platform") or platform),
                    chat_id=str(entry.get("chat_id") or chat_id),
                    min_user_turns=int(entry.get("min_user_turns") or min_user_turns),
                    idle_ok=True,
                )
            except Exception:
                logger.debug("recap_auto fire failed", exc_info=True)

        timer = threading.Timer(delay, _fire)
        timer.daemon = True
        _PENDING[sid] = {
            "timer": timer,
            "epoch": epoch,
            "platform": platform,
            "chat_id": chat_id,
            "min_user_turns": min_user_turns,
        }
        timer.start()
    logger.debug(
        "recap_auto scheduled session=%s idle=%.1fs platform=%s",
        sid,
        delay,
        platform,
    )


def cancel_pending(session_id: str) -> None:
    sid = str(session_id or "").strip()
    if not sid:
        return
    with _PENDING_LOCK:
        entry = _PENDING.pop(sid, None)
    if not entry:
        return
    timer = entry.get("timer")
    if timer is not None:
        try:
            timer.cancel()
        except Exception:
            pass


def pending_count() -> int:
    with _PENDING_LOCK:
        return len(_PENDING)


def run_auto_recap(
    session_id: str,
    *,
    platform: str,
    chat_id: str,
    min_user_turns: int = MIN_TURNS_FOR_AUTO_RECAP,
    idle_ok: bool = True,
) -> Optional[str]:
    """Gate + generate + send. Returns delivery body or None. Updates watermark on success."""
    sid = str(session_id or "").strip()
    plat = normalize_platform(platform)
    if not sid or not chat_id:
        return None
    if not resolve_enabled("recap", plat, chat_id or None):
        return None
    auto_cfg = load_auto_config()
    if not auto_cfg.get("enabled", True):
        return None
    need = int(auto_cfg.get("min_user_turns") or min_user_turns)

    from owner.explainers.recap.command import _load_messages

    try:
        messages = _load_messages(sid)
    except Exception as exc:
        logger.debug("recap_auto load failed: %s", exc)
        return None

    turns = count_user_turns(messages)
    last = load_recap_watermark(sid)
    reason = recap_gate(turns, last, auto=True, idle_ok=idle_ok, min_user_turns=need)
    if reason:
        logger.debug(
            "recap_auto skipped session=%s turns=%s last=%s reason=%s",
            sid,
            turns,
            last,
            reason,
        )
        return None

    cfg = load_kind_config("recap")
    try:
        text = explain_from_messages(messages, cfg=cfg)
    except Exception as exc:
        logger.debug("recap_auto explain failed: %s", exc)
        return None
    body = format_delivery(text or "")
    if not body:
        return None

    if not _send_notice(plat, chat_id, body, cfg):
        return None

    save_recap_watermark(sid, turns)
    logger.info(
        "recap_auto sent session=%s turns=%s platform=%s",
        sid,
        turns,
        plat,
    )
    return body


def note_manual_recap(session_id: str, messages: list[Any]) -> None:
    """Bump watermark after a successful manual ``/recap`` (suppress immediate auto)."""
    sid = str(session_id or "").strip()
    if not sid:
        return
    turns = count_user_turns(messages)
    if turns > 0:
        save_recap_watermark(sid, turns)
    cancel_pending(sid)


def _lookup_route(session_id: str, platform_hint: str) -> tuple[str, str]:
    sid = str(session_id or "")
    with _ROUTE_LOCK:
        if sid in _SESSION_ROUTES:
            return _SESSION_ROUTES[sid]
        for key, val in list(_SESSION_ROUTES.items())[-64:]:
            if sid and (sid in key or key.endswith(sid) or key in sid):
                return val
    return normalize_platform(platform_hint), ""


def _resolve_adapter(platform: str) -> Any:
    p = normalize_platform(platform)
    with _REF_LOCK:
        if p in _ADAPTERS:
            return _ADAPTERS[p]
        if p in {"lark", "feishu"}:
            return _ADAPTERS.get("feishu") or _ADAPTERS.get("lark")
        gw = _GATEWAY_REF
    if gw is None:
        return None
    adapters = getattr(gw, "adapters", {}) or {}
    try:
        from gateway.config import Platform

        enum_key = getattr(Platform, "FEISHU", None) if p in {"feishu", "lark"} else None
        if enum_key is not None and enum_key in adapters:
            return adapters[enum_key]
    except Exception:
        pass
    return adapters.get(p)


def _resolve_loop(adapter: Any) -> Any:
    candidates = []
    if adapter is not None:
        candidates.append(getattr(adapter, "_loop", None))
        candidates.append(getattr(adapter, "_ws_thread_loop", None))
    with _REF_LOCK:
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


def _send_notice(platform: str, chat_id: str, body: str, cfg: dict[str, Any]) -> bool:
    adapter = _resolve_adapter(platform)
    if adapter is None or not chat_id:
        logger.debug("recap_auto skip send (no adapter/chat) platform=%s", platform)
        return False
    loop = _resolve_loop(adapter)
    if loop is None:
        logger.debug("recap_auto no event loop for send")
        return False

    async def _send() -> None:
        await adapter.send(chat_id, body)

    try:
        fut = asyncio.run_coroutine_threadsafe(_send(), loop)
        timeout = max(
            5.0,
            int(cfg.get("timeout_ms") or cfg.get("explainer_timeout_ms") or 30000) / 1000.0 + 5,
        )
        fut.result(timeout=timeout)
        return True
    except Exception as exc:
        logger.debug("recap_auto send failed: %s", exc)
        return False
