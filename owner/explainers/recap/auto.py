"""[owner] C13 recap — auto trigger after a long turn or a long end message.

Auto recap is for turns that took too long or ended with a long assistant
reply — not for waiting on the user's next message.

1. ``on_session_end`` of a normally completed turn immediately evaluates
   the gate and, if it passes, generates the same notice as ``/recap``.
2. Trigger: a new user main turn since the watermark, and either
   turn duration ``>= min_turn_seconds`` (default 180; user message →
   session end) **or** latest visible assistant reply
   ``>= min_assistant_chars`` (default 800; 0 disables).
3. Interrupted / failed / incomplete turns are skipped. ``agent_loop_stopped``
   records a mark used only when ``on_session_end`` flags are ambiguous.
4. Manual ``/recap`` stays immediate and ignores these automatic thresholds.

Config under ``explainers.recap.auto``. ``min_turn_seconds`` is the
canonical duration key; overlay ``idle_seconds`` is still read as a
fallback and no longer means "wait after the turn ends".
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any, Optional

from owner.explainers.common import (
    coerce_session_source,
    normalize_platform,
    pack_explainer_route,
    reply_anchor_from_source,
    send_metadata_for_thread,
    unpack_explainer_route,
)
from owner.explainers.config import load_kind_config, resolve_enabled
from owner.explainers.recap.explain import explain_from_messages
from owner.explainers.recap.gate import (
    MIN_ASSISTANT_CHARS_FOR_AUTO_RECAP,
    MIN_TURNS_FOR_AUTO_RECAP,
    RECAP_MIN_TURN_SECONDS,
    recap_gate,
)
from owner.explainers.recap.prompt import format_delivery
from owner.explainers.recap.watermark import load_recap_watermark, save_recap_watermark

logger = logging.getLogger("hermes.owner.explainers.recap")

_AUTO_DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "min_user_turns": MIN_TURNS_FOR_AUTO_RECAP,  # parsed for compat; not an auto trigger
    "min_turn_seconds": RECAP_MIN_TURN_SECONDS,
    "min_assistant_chars": MIN_ASSISTANT_CHARS_FOR_AUTO_RECAP,
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

# session_id / gateway_session_key → (platform, chat_id, thread_id, reply_to_message_id)
_SESSION_ROUTES: dict[str, tuple[str, str, str, str]] = {}
_ROUTE_LOCK = threading.Lock()

# session_id / session_key → unix time of the inbound user message that started this turn
_TURN_STARTED: dict[str, float] = {}
# session_id / session_key → interrupt mark from agent_loop_stopped
_INTERRUPTED: set[str] = set()
_STATE_LOCK = threading.Lock()


def _raw_auto_block(cfg: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Return the overlay/test ``auto`` dict, not merged registry defaults."""
    if isinstance(cfg, dict) and isinstance(cfg.get("auto"), dict):
        return dict(cfg["auto"])
    try:
        from owner.explainers.config import _raw_explainers

        root = _raw_explainers().get("recap") or {}
        if isinstance(root, dict) and isinstance(root.get("auto"), dict):
            return dict(root["auto"])
    except Exception:
        pass
    return {}


def _coerce_nonneg_int(value: Any, default: int) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def load_auto_config(cfg: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Merge overlay ``explainers.recap.auto`` over defaults.

    ``min_turn_seconds`` is canonical. If it is absent, ``idle_seconds`` is
    used as the duration floor so existing overlays keep working. That old
    key no longer means "idle after the turn ends".
    """
    merged = dict(_AUTO_DEFAULTS)
    raw_auto = _raw_auto_block(cfg)
    if "enabled" in raw_auto:
        merged["enabled"] = bool(raw_auto.get("enabled"))
    if "min_user_turns" in raw_auto:
        merged["min_user_turns"] = _coerce_nonneg_int(
            raw_auto["min_user_turns"], MIN_TURNS_FOR_AUTO_RECAP
        )
    if merged["min_user_turns"] < 1:
        merged["min_user_turns"] = MIN_TURNS_FOR_AUTO_RECAP
    if "min_assistant_chars" in raw_auto:
        merged["min_assistant_chars"] = _coerce_nonneg_int(
            raw_auto["min_assistant_chars"], MIN_ASSISTANT_CHARS_FOR_AUTO_RECAP
        )
    # 0 keeps the char OR path disabled.
    if merged["min_assistant_chars"] < 0:
        merged["min_assistant_chars"] = MIN_ASSISTANT_CHARS_FOR_AUTO_RECAP
    if "min_turn_seconds" in raw_auto:
        merged["min_turn_seconds"] = _coerce_nonneg_int(
            raw_auto["min_turn_seconds"], RECAP_MIN_TURN_SECONDS
        )
    elif "idle_seconds" in raw_auto:
        merged["min_turn_seconds"] = _coerce_nonneg_int(
            raw_auto["idle_seconds"], RECAP_MIN_TURN_SECONDS
        )
    else:
        merged["min_turn_seconds"] = RECAP_MIN_TURN_SECONDS
    return merged


def _user_text(msg: dict[str, Any]) -> str:
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
    return text


def _is_real_user_turn(msg: Any) -> bool:
    if not isinstance(msg, dict):
        return False
    if str(msg.get("role") or "").strip().lower() != "user":
        return False
    stripped = _user_text(msg).lstrip()
    if not stripped:
        return False
    if stripped.startswith(_SYNTHETIC_PREFIXES):
        return False
    return True


def count_user_turns(messages: list[Any]) -> int:
    """Count real user prompts (skip tool/system/synthetic)."""
    return sum(1 for msg in (messages or []) if _is_real_user_turn(msg))


def _content_chars(content: Any) -> int:
    """Visible text length for one message content field."""
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and part.get("type") in {"text", "input_text"}:
                parts.append(str(part.get("text") or ""))
        return len("".join(parts).strip())
    if content is None:
        return 0
    return len(str(content).strip())


def latest_assistant_chars(messages: list[Any]) -> int:
    """Length of the latest non-empty assistant reply (user-visible final text)."""
    last = 0
    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        if str(msg.get("role") or "").strip().lower() != "assistant":
            continue
        n = _content_chars(msg.get("content"))
        if n > 0:
            last = n
    return last


def _coerce_epoch(value: Any) -> Optional[float]:
    """Best-effort unix seconds; None if missing or unusable."""
    if value is None or value is False:
        return None
    if isinstance(value, (int, float)):
        ts = float(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            ts = float(text)
        except ValueError:
            return None
    else:
        return None
    if ts > 1e12:  # milliseconds
        ts /= 1000.0
    if ts <= 0:
        return None
    return ts


def latest_user_turn_started_at(messages: list[Any]) -> Optional[float]:
    """Timestamp of the latest real user main-turn message, not the first turn."""
    last: Optional[float] = None
    for msg in messages or []:
        if not _is_real_user_turn(msg):
            continue
        ts = _coerce_epoch(msg.get("timestamp"))
        if ts is not None:
            last = ts
    return last


def resolve_turn_seconds(
    messages: list[Any],
    *,
    inbound_started_at: Optional[float] = None,
    ended_at: Optional[float] = None,
    session_id: str = "",
) -> Optional[float]:
    """Seconds from this turn's user message to session end, or None if unknown.

    Prefers the latest real user-message timestamp. If an inbound hook time is
    clearly later, the current user message may not be in the transcript yet
    and the inbound time is used instead. Does not invent a wait.
    """
    end = float(ended_at if ended_at is not None else time.time())
    msg_ts = latest_user_turn_started_at(messages)
    inbound = _coerce_epoch(inbound_started_at)
    start: Optional[float] = None
    source = ""
    if msg_ts is not None and inbound is not None and inbound > msg_ts + 1.0:
        start, source = inbound, "inbound"
    elif msg_ts is not None:
        start, source = msg_ts, "message"
    elif inbound is not None:
        start, source = inbound, "inbound"
    if start is None:
        logger.info(
            "recap_auto no reliable turn start session=%s; skip duration path",
            session_id or "-",
        )
        return None
    if end < start:
        logger.info(
            "recap_auto turn end before start session=%s source=%s; skip duration path",
            session_id or "-",
            source,
        )
        return None
    return end - start


def _remember_turn_start(*keys: str, started_at: Optional[float] = None) -> None:
    ts = float(started_at if started_at is not None else time.time())
    with _STATE_LOCK:
        for key in keys:
            k = str(key or "").strip()
            if k:
                _TURN_STARTED[k] = ts


def _pop_turn_start(*keys: str) -> Optional[float]:
    found: Optional[float] = None
    with _STATE_LOCK:
        for key in keys:
            k = str(key or "").strip()
            if not k:
                continue
            ts = _TURN_STARTED.pop(k, None)
            if ts is not None and (found is None or ts > found):
                found = ts
    return found


def _mark_interrupted(*keys: str) -> None:
    with _STATE_LOCK:
        for key in keys:
            k = str(key or "").strip()
            if k:
                _INTERRUPTED.add(k)


def _pop_interrupt_mark(*keys: str) -> bool:
    hit = False
    with _STATE_LOCK:
        for key in keys:
            k = str(key or "").strip()
            if k and k in _INTERRUPTED:
                _INTERRUPTED.discard(k)
                hit = True
    return hit


def _clear_turn_state(*keys: str) -> None:
    with _STATE_LOCK:
        for key in keys:
            k = str(key or "").strip()
            if not k:
                continue
            _TURN_STARTED.pop(k, None)
            _INTERRUPTED.discard(k)


def _session_keys(session_id: str, *extra: str) -> tuple[str, ...]:
    keys: list[str] = []
    for key in (session_id, *extra):
        k = str(key or "").strip()
        if k and k not in keys:
            keys.append(k)
            if ":" in k:
                tail = k.split(":")[-1]
                if tail and tail not in keys:
                    keys.append(tail)
    return tuple(keys)


def register_hooks(ctx: Any) -> None:
    ctx.register_hook("pre_gateway_dispatch", _on_pre_gateway_dispatch)
    ctx.register_hook("on_session_end", _on_session_end)
    ctx.register_hook("agent_loop_stopped", _on_agent_loop_stopped)
    ctx.register_hook("on_session_reset", _on_session_reset)
    logger.debug("recap_auto hooks registered")


def _coerce_source(raw: Any) -> Any:
    """Accept SessionSource, dict (post_admission shape), or None."""
    return coerce_session_source(raw)


def _platform_chat_from_source(source: Any) -> tuple[str, str, str, str]:
    if source is None:
        return pack_explainer_route("", "")
    platform = normalize_platform(getattr(source, "platform", "") or "")
    chat_id = str(getattr(source, "chat_id", "") or "").strip()
    thread_id = str(getattr(source, "thread_id", "") or "").strip()
    reply_to = reply_anchor_from_source(source)
    return pack_explainer_route(platform, chat_id, thread_id, reply_to)


def _resolve_inbound_source(**kwargs: Any) -> Any:
    """Official ``pre_gateway_dispatch`` passes ``event`` + ``gateway`` only.

    Platform/chat_id live on ``event.source`` (SessionSource), not top-level
    MessageEvent fields. Also accept an explicit ``source`` kwarg for tests /
    ``post_gateway_admission``-style callers.
    """
    source = _coerce_source(kwargs.get("source"))
    if source is not None:
        return source
    event = kwargs.get("event")
    if event is not None:
        return _coerce_source(getattr(event, "source", None))
    return None


def _derive_session_key(gateway: Any, source: Any, event: Any, kwargs: dict[str, Any]) -> str:
    session_key = str(
        kwargs.get("session_key")
        or kwargs.get("gateway_session_key")
        or getattr(event, "session_key", "")
        or ""
    ).strip()
    if session_key:
        return session_key
    if gateway is not None and source is not None:
        try:
            key = getattr(gateway, "_session_key_for_source", None)
            if callable(key):
                derived = key(source)
                if isinstance(derived, str) and derived.strip():
                    return derived.strip()
        except Exception:
            logger.debug("recap_auto derive session_key via gateway failed", exc_info=True)
        store = getattr(gateway, "session_store", None)
        if store is not None:
            try:
                gen = getattr(store, "_generate_session_key", None)
                if callable(gen):
                    derived = gen(source)
                    if isinstance(derived, str) and derived.strip():
                        return derived.strip()
            except Exception:
                logger.debug("recap_auto derive session_key via store failed", exc_info=True)
    if source is not None:
        try:
            from gateway.session import build_session_key

            derived = build_session_key(source)
            if isinstance(derived, str) and derived.strip():
                return derived.strip()
        except Exception:
            logger.debug("recap_auto build_session_key failed", exc_info=True)
    return ""


def _remember_route(
    *,
    platform: str,
    chat_id: str,
    session_key: str = "",
    sid_hint: str = "",
    gateway: Any = None,
    thread_id: str = "",
    reply_to_message_id: str = "",
) -> None:
    if not platform or not chat_id:
        return
    keys: list[str] = []
    if session_key:
        keys.append(session_key)
        if ":" in session_key:
            keys.append(session_key.split(":")[-1])
    if sid_hint:
        keys.append(sid_hint)
    # Gateway routing: map current session_id under the same route so
    # on_session_end(session_id=…) can find chat_id without fuzzy match.
    if gateway is not None and session_key:
        store = getattr(gateway, "session_store", None)
        if store is not None:
            try:
                lookup = getattr(store, "lookup_by_session_key", None)
                entry = lookup(session_key) if callable(lookup) else None
                if entry is not None:
                    eid = str(getattr(entry, "session_id", "") or "").strip()
                    if eid:
                        keys.append(eid)
            except Exception:
                logger.debug("recap_auto remember route via session_key failed", exc_info=True)
    if not keys:
        return
    route = pack_explainer_route(platform, chat_id, thread_id, reply_to_message_id)
    with _ROUTE_LOCK:
        for key in keys:
            if key:
                _SESSION_ROUTES[key] = route


def _route_from_gateway(session_id: str) -> tuple[str, str, str, str]:
    """Fall back to SessionStore origin when the in-memory route cache missed."""
    sid = str(session_id or "").strip()
    if not sid:
        return pack_explainer_route("", "")
    with _REF_LOCK:
        gw = _GATEWAY_REF
    if gw is None:
        return pack_explainer_route("", "")
    store = getattr(gw, "session_store", None)
    if store is None:
        return pack_explainer_route("", "")
    try:
        lookup = getattr(store, "lookup_by_session_id", None)
        entry = lookup(sid) if callable(lookup) else None
    except Exception:
        logger.debug("recap_auto gateway routing lookup failed", exc_info=True)
        return pack_explainer_route("", "")
    if entry is None:
        return pack_explainer_route("", "")
    origin = getattr(entry, "origin", None)
    platform, chat_id, thread_id, reply_to = _platform_chat_from_source(origin)
    if not platform:
        platform = normalize_platform(getattr(entry, "platform", "") or "")
    if not chat_id:
        return pack_explainer_route(platform, "")
    # Seed cache for subsequent ends / cancels.
    sk = str(getattr(entry, "session_key", "") or "").strip()
    _remember_route(
        platform=platform,
        chat_id=chat_id,
        session_key=sk,
        sid_hint=sid,
        gateway=None,
        thread_id=thread_id,
        reply_to_message_id=reply_to,
    )
    return pack_explainer_route(platform, chat_id, thread_id, reply_to)



def _on_pre_gateway_dispatch(**kwargs: Any) -> None:
    """Cache gateway/adapters/route; record this inbound as the turn start."""
    global _GATEWAY_REF
    gateway = kwargs.get("gateway")
    event = kwargs.get("event")
    source = _resolve_inbound_source(**kwargs)
    platform, chat_id, thread_id, reply_to = _platform_chat_from_source(source)
    # Legacy / test shapes: rare top-level fields on the event itself.
    if event is not None:
        if not platform:
            platform = normalize_platform(getattr(event, "platform", "") or "")
        if not chat_id:
            chat_id = str(getattr(event, "chat_id", "") or "").strip()
        if not thread_id:
            # Only event.source.thread_id (already tried) or a native event.thread_id.
            # Never event.root_id — that is a quote, not a topic.
            thread_id = str(getattr(event, "thread_id", "") or "").strip()
        if not reply_to:
            reply_to = reply_anchor_from_source(source, event)
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

    session_key = _derive_session_key(gateway, source, event, kwargs)
    sid_hint = ""
    if event is not None:
        sid_hint = str(getattr(event, "session_id", "") or "").strip()
    store_sid = ""
    if gateway is not None and session_key:
        store = getattr(gateway, "session_store", None)
        if store is not None:
            try:
                lookup = getattr(store, "lookup_by_session_key", None)
                entry = lookup(session_key) if callable(lookup) else None
                if entry is not None:
                    store_sid = str(getattr(entry, "session_id", "") or "").strip()
            except Exception:
                pass
    _remember_route(
        platform=platform,
        chat_id=chat_id,
        session_key=session_key,
        sid_hint=sid_hint or store_sid,
        gateway=gateway,
        thread_id=thread_id,
        reply_to_message_id=reply_to,
    )
    # New inbound starts a new turn: remember its time, drop a stale interrupt mark.
    start_keys = _session_keys(sid_hint, session_key, store_sid)
    _remember_turn_start(*start_keys)
    _pop_interrupt_mark(*start_keys)


def _session_end_should_skip(**kwargs: Any) -> bool:
    """Skip interrupted / failed / incomplete turns.

    Official ``turn_finalizer`` sets ``interrupted`` and ``completed=False`` on
    abort. ``agent_loop_stopped`` may fire first; its mark is used only when
    those flags are absent or ambiguous, and is cleared here so it cannot
    poison a later successful turn.
    """
    sid = str(kwargs.get("session_id") or kwargs.get("session_key") or "").strip()
    keys = _session_keys(sid, str(kwargs.get("session_key") or ""))
    marked = _pop_interrupt_mark(*keys)
    if kwargs.get("interrupted") or kwargs.get("failed"):
        return True
    if kwargs.get("completed") is False:
        return True
    if kwargs.get("completed") is True and not kwargs.get("interrupted"):
        return False
    if marked:
        logger.info(
            "recap_auto skip session=%s: agent_loop_stopped mark with ambiguous end flags",
            sid or "-",
        )
        return True
    return False


def _on_session_end(**kwargs: Any) -> None:
    try:
        if _session_end_should_skip(**kwargs):
            sid = str(kwargs.get("session_id") or kwargs.get("session_key") or "").strip()
            _clear_turn_state(*_session_keys(sid, str(kwargs.get("session_key") or "")))
            return
        session_id = str(kwargs.get("session_id") or "").strip()
        if not session_id:
            return
        platform = normalize_platform(kwargs.get("platform") or "")
        route_platform, chat_id, thread_id, reply_to = _lookup_route(session_id, platform)
        platform = platform or route_platform
        if not resolve_enabled("recap", platform, chat_id or None):
            return
        auto_cfg = load_auto_config()
        if not auto_cfg.get("enabled", True):
            return
        if not chat_id:
            # No messaging route (CLI-only) — skip auto notice.
            return
        start_keys = list(_session_keys(session_id, str(kwargs.get("session_key") or "")))
        # Also pop any session_key cached on the gateway entry.
        with _REF_LOCK:
            gw = _GATEWAY_REF
        if gw is not None:
            store = getattr(gw, "session_store", None)
            if store is not None:
                try:
                    lookup = getattr(store, "lookup_by_session_id", None)
                    entry = lookup(session_id) if callable(lookup) else None
                    if entry is not None:
                        sk = str(getattr(entry, "session_key", "") or "").strip()
                        if sk:
                            start_keys.extend(_session_keys(sk))
                except Exception:
                    pass
        inbound_started_at = _pop_turn_start(*start_keys)
        start_auto_recap(
            session_id,
            platform=platform,
            chat_id=chat_id,
            min_turn_seconds=int(auto_cfg.get("min_turn_seconds", RECAP_MIN_TURN_SECONDS)),
            min_assistant_chars=int(
                auto_cfg.get("min_assistant_chars", MIN_ASSISTANT_CHARS_FOR_AUTO_RECAP)
            ),
            thread_id=thread_id,
            reply_to_message_id=reply_to,
            inbound_started_at=inbound_started_at,
            ended_at=time.time(),
        )
    except Exception:
        logger.debug("recap_auto on_session_end failed", exc_info=True)


def _on_agent_loop_stopped(**kwargs: Any) -> None:
    sid = str(kwargs.get("session_id") or kwargs.get("session_key") or "").strip()
    if sid:
        _mark_interrupted(*_session_keys(sid))


def _on_session_reset(**kwargs: Any) -> None:
    sid = str(kwargs.get("session_id") or "").strip()
    if sid:
        _clear_turn_state(*_session_keys(sid))


def start_auto_recap(
    session_id: str,
    *,
    platform: str,
    chat_id: str,
    min_turn_seconds: int = RECAP_MIN_TURN_SECONDS,
    min_assistant_chars: int = MIN_ASSISTANT_CHARS_FOR_AUTO_RECAP,
    thread_id: str = "",
    reply_to_message_id: str = "",
    inbound_started_at: Optional[float] = None,
    ended_at: Optional[float] = None,
    background: bool = True,
) -> None:
    """Evaluate the auto-recap gate immediately and generate if it passes.

    Generation runs on a daemon thread by default so the session-end hook
    does not block on the explainer LLM. There is no idle delay.
    """
    sid = str(session_id or "").strip()
    if not sid:
        return
    kwargs = dict(
        platform=platform,
        chat_id=chat_id,
        min_turn_seconds=int(min_turn_seconds),
        min_assistant_chars=int(min_assistant_chars),
        thread_id=thread_id,
        reply_to_message_id=reply_to_message_id,
        inbound_started_at=inbound_started_at,
        ended_at=ended_at if ended_at is not None else time.time(),
    )

    def _run() -> None:
        try:
            run_auto_recap(sid, **kwargs)
        except Exception:
            logger.debug("recap_auto immediate run failed", exc_info=True)

    if background:
        threading.Thread(target=_run, name=f"recap-auto-{sid[:12]}", daemon=True).start()
    else:
        _run()
    logger.debug("recap_auto started session=%s platform=%s", sid, platform)


def run_auto_recap(
    session_id: str,
    *,
    platform: str,
    chat_id: str,
    min_turn_seconds: int = RECAP_MIN_TURN_SECONDS,
    min_assistant_chars: int = MIN_ASSISTANT_CHARS_FOR_AUTO_RECAP,
    thread_id: str = "",
    reply_to_message_id: str = "",
    inbound_started_at: Optional[float] = None,
    ended_at: Optional[float] = None,
    turn_seconds: Optional[float] = None,
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
    need_secs = int(
        auto_cfg["min_turn_seconds"]
        if "min_turn_seconds" in auto_cfg
        else min_turn_seconds
    )
    need_chars = int(
        auto_cfg["min_assistant_chars"]
        if "min_assistant_chars" in auto_cfg
        else min_assistant_chars
    )

    from owner.explainers.recap.command import _load_messages

    try:
        messages = _load_messages(sid)
    except Exception as exc:
        logger.debug("recap_auto load failed: %s", exc)
        return None

    turns = count_user_turns(messages)
    chars = latest_assistant_chars(messages)
    last = load_recap_watermark(sid)
    if turn_seconds is None:
        turn_seconds = resolve_turn_seconds(
            messages,
            inbound_started_at=inbound_started_at,
            ended_at=ended_at,
            session_id=sid,
        )
    reason = recap_gate(
        turns,
        last,
        auto=True,
        turn_seconds=turn_seconds,
        min_turn_seconds=need_secs,
        assistant_chars=chars,
        min_assistant_chars=need_chars,
    )
    if reason:
        logger.debug(
            "recap_auto skipped session=%s turns=%s chars=%s turn_s=%s last=%s reason=%s",
            sid,
            turns,
            chars,
            turn_seconds,
            last,
            reason,
        )
        return None

    cfg = load_kind_config("recap")
    route_info: dict = {}
    try:
        text = explain_from_messages(messages, cfg=cfg, route_info=route_info, session_id=sid)
    except Exception as exc:
        logger.debug("recap_auto explain failed: %s", exc)
        return None
    body = format_delivery(text or "")
    if not body:
        return None

    if not _send_notice(
        plat, chat_id, body, cfg,
        thread_id=thread_id, reply_to_message_id=reply_to_message_id,
    ):
        return None

    try:
        from owner.explainers.persist import persist_notice

        extra_meta = {"user_turns": turns}
        extra_meta.update(route_info.get("recap_input") or {})
        persist_notice(
            sid,
            "recap",
            body,
            trigger="auto",
            cfg=cfg,
            route_info=route_info,
            extra_meta=extra_meta,
        )
    except Exception:
        logger.debug("recap_auto persist failed", exc_info=True)

    save_recap_watermark(sid, turns)
    logger.info(
        "recap_auto sent session=%s turns=%s chars=%s turn_s=%s platform=%s",
        sid,
        turns,
        chars,
        turn_seconds,
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


def _lookup_route(session_id: str, platform_hint: str) -> tuple[str, str, str, str]:
    sid = str(session_id or "")
    with _ROUTE_LOCK:
        if sid in _SESSION_ROUTES:
            return unpack_explainer_route(_SESSION_ROUTES[sid])
        for key, val in list(_SESSION_ROUTES.items())[-64:]:
            if sid and (sid in key or key.endswith(sid) or key in sid):
                return unpack_explainer_route(val)
    # Gateway routing backfill: SessionEntry.origin when cache was never seeded
    # (e.g. first turn — session_id only exists after prepare, past pre_dispatch).
    gw_platform, gw_chat, gw_thread, gw_reply = _route_from_gateway(sid)
    if gw_chat:
        return pack_explainer_route(
            gw_platform or normalize_platform(platform_hint),
            gw_chat,
            gw_thread,
            gw_reply,
        )
    return pack_explainer_route(normalize_platform(platform_hint), "")


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


def _send_notice(
    platform: str,
    chat_id: str,
    body: str,
    cfg: dict[str, Any],
    *,
    thread_id: str = "",
    reply_to_message_id: str = "",
) -> bool:
    adapter = _resolve_adapter(platform)
    if adapter is None or not chat_id:
        logger.debug("recap_auto skip send (no adapter/chat) platform=%s", platform)
        return False
    loop = _resolve_loop(adapter)
    if loop is None:
        logger.debug("recap_auto no event loop for send")
        return False
    metadata = send_metadata_for_thread(thread_id, reply_to_message_id)

    async def _send() -> None:
        await adapter.send(chat_id, body, metadata=metadata)

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
