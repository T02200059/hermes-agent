"""[owner] Feishu /queue lifecycle: cancel, process_now, freeze-on-execute.

Token transport (IMPORTANT — do NOT put tokens in ``message_id``):
  Feishu uses ``event.message_id`` as ``reply_to``. Stamping synthetic ids
  there broke acks and reply anchors. Instead:

  1. ``register_scheduled_token(token, text=..., card_meta=...)`` on submit
  2. Wrapped ``_enqueue_fifo`` matches prompt text, stamps
     ``event._owner_queue_token``, binds runner on the adapter
  3. Cancel / process_now scan pending/overflow for that attribute
  4. Wrapped ``_dequeue_pending_event`` freezes the Feishu queue status card
     when a stamped item starts execution (REST patch →「已开始执行」终态)

Also patches ``MemoryManager._prefetch_provider`` so a rapid FIFO follow-up
waits briefly for an in-flight end-of-turn ``queue_prefetch`` instead of
skipping openviking recall (which dropped the viking recall card for queue
turns that fire immediately after the previous turn ends).

Also patches ``GatewayRunner._busy_queue_command`` so Feishu busy ``/queue``
sends the interactive queue status card (non-Feishu keeps text ack).

Removable via ``revert_patch()``.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Mapping, MutableMapping
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# token -> {"status": scheduled|enqueued|cancelled|executed|process_now, "text": str, ...card}
# Guarded by _token_lock: cancel / enqueue / freeze threads all touch this map.
_token_state: Dict[str, Dict[str, Any]] = {}
_token_lock = threading.Lock()

_originals: Dict[str, Any] = {}
_applied: bool = False

_EVENT_TOKEN_ATTR = "_owner_queue_token"
# Also stored under event.metadata for durability / easier debugging.
_META_TOKEN_KEY = "_owner_queue_token"


def make_queue_message_id(token: str) -> str:
    """Deprecated helper kept for tests/compat — do not put on MessageEvent.message_id."""
    return f"owner-q:{token}"


def parse_queue_token(message_id: Any) -> Optional[str]:
    """Legacy parse of owner-q message_id stamps (no longer written)."""
    if not isinstance(message_id, str) or not message_id.startswith("owner-q:"):
        return None
    token = message_id[len("owner-q:") :].strip()
    return token or None


def _stamp_event(event: Any, token: str) -> None:
    """Stamp cancel token on a FIFO MessageEvent (attr + metadata)."""
    if event is None or not token:
        return
    try:
        setattr(event, _EVENT_TOKEN_ATTR, token)
    except Exception:
        logger.warning(
            "[owner queue] setattr stamp failed token=%s",
            token[:8],
            exc_info=True,
        )
    try:
        md = getattr(event, "metadata", None)
        if isinstance(md, dict):
            md[_META_TOKEN_KEY] = token
        else:
            # MessageEvent.metadata defaults to a dict; recreate if stripped.
            try:
                event.metadata = {_META_TOKEN_KEY: token}
            except Exception:
                pass
    except Exception:
        logger.debug("[owner queue] metadata stamp failed token=%s", token[:8], exc_info=True)


def event_matches_token(event: Any, token: str) -> bool:
    """True when the FIFO event belongs to this cancel token.

    Match order:
      1. ``event._owner_queue_token`` attribute
      2. ``event.metadata['_owner_queue_token']``
      3. prompt text fallback against registered token meta (covers missed stamps)
    """
    if not token or event is None:
        return False
    if getattr(event, _EVENT_TOKEN_ATTR, None) == token:
        return True
    md = getattr(event, "metadata", None)
    if isinstance(md, dict) and md.get(_META_TOKEN_KEY) == token:
        return True
    # Text fallback: only when this event is not stamped for a *different* token.
    other = getattr(event, _EVENT_TOKEN_ATTR, None)
    if other and other != token:
        return False
    if isinstance(md, dict):
        other_md = md.get(_META_TOKEN_KEY)
        if other_md and other_md != token:
            return False
    with _token_lock:
        meta = _token_state.get(token) or {}
        needle = (meta.get("text") or "").strip()
        status = meta.get("status")
    if not needle or status in ("cancelled", "executed", "steered"):
        return False
    return (getattr(event, "text", None) or "").strip() == needle


def _overflow_mapping(runner: Any) -> Optional[MutableMapping]:
    """Return the runner overflow map.

    IMPORTANT: after SessionState migration, ``runner._queued_events`` is a
    ``SessionFieldView`` (MutableMapping), **not** a plain ``dict``. Older
    code used ``isinstance(..., dict)`` and silently skipped all overflow
    cancels — the common case when the pending slot is already occupied.
    """
    if runner is None:
        return None
    queued = getattr(runner, "_queued_events", None)
    if isinstance(queued, MutableMapping):
        return queued
    if isinstance(queued, Mapping):
        # Read-only Mapping — still usable for scan; mutations may fail.
        return queued  # type: ignore[return-value]
    return None


def register_scheduled_token(
    token: str,
    text: str = "",
    *,
    card_message_id: str = "",
    chat_id: str = "",
    user_input: str = "",
    user_name: str = "",
    app_id: str = "",
    app_secret: str = "",
    session_key: str = "",
    source: Any = None,
) -> None:
    """Mark a token as submitted; optionally bind Feishu card identity for freeze."""
    if not token:
        return
    with _token_lock:
        _token_state[token] = {
            "status": "scheduled",
            "text": (text or "").strip(),
            "card_message_id": (card_message_id or "").strip(),
            "chat_id": (chat_id or "").strip(),
            "user_input": user_input or text or "",
            "user_name": user_name or "",
            "app_id": app_id or "",
            "app_secret": app_secret or "",
            "session_key": (session_key or "").strip(),
            "source": source,
        }


def get_token_meta(token: Optional[str]) -> Dict[str, Any]:
    """Snapshot of token metadata (empty dict if unknown)."""
    if not token:
        return {}
    with _token_lock:
        return dict(_token_state.get(token) or {})


def bind_card_message_id(token: str, message_id: str, **extra: Any) -> None:
    """Attach Feishu card message_id (and optional fields) after send_card."""
    if not token or not message_id:
        return
    with _token_lock:
        meta = _token_state.get(token)
        if not meta:
            return
        meta["card_message_id"] = str(message_id).strip()
        for key, value in extra.items():
            if value is not None and value != "":
                meta[key] = value
        _token_state[token] = meta


def token_has_card(token: Optional[str]) -> bool:
    """True when a Feishu status card is already bound to this token."""
    if not token:
        return False
    with _token_lock:
        meta = _token_state.get(token) or {}
        return bool(meta.get("card_message_id"))


def find_scheduled_token_for_text(text: str) -> Optional[str]:
    """Return first scheduled/cancelled token registered for this prompt text."""
    return _match_token_for_text(text)


def should_skip_dispatch(token: Optional[str]) -> bool:
    """True when cancel/steer won the race before the synthetic /queue was handled."""
    if not token:
        return False
    with _token_lock:
        meta = _token_state.get(token) or {}
        return meta.get("status") in ("cancelled", "steered")


def resolve_runner_from_adapter(adapter: Any) -> Any:
    """Best-effort GatewayRunner lookup from an adapter instance."""
    runner = getattr(adapter, "_owner_gateway_runner", None)
    if runner is not None:
        return runner
    handler = getattr(adapter, "_message_handler", None)
    bound = getattr(handler, "__self__", None)
    if bound is not None and hasattr(bound, "_enqueue_fifo"):
        try:
            adapter._owner_gateway_runner = bound
        except Exception:
            pass
        return bound
    return None


def _promote_overflow_head(runner: Any, adapter: Any, session_key: str) -> None:
    """After removing the pending-slot head, promote overflow[0] into the slot."""
    if runner is None or adapter is None or not session_key:
        return
    queued = _overflow_mapping(runner)
    if queued is None:
        return
    try:
        overflow = queued.get(session_key)
    except Exception:
        return
    if not overflow:
        return
    next_event = overflow.pop(0)
    if not overflow:
        try:
            queued.pop(session_key, None)
        except Exception:
            # SessionFieldView may use __delitem__
            try:
                del queued[session_key]
            except Exception:
                pass
    pending = getattr(adapter, "_pending_messages", None)
    if isinstance(pending, MutableMapping):
        pending[session_key] = next_event


def _pending_mapping(adapter: Any) -> Optional[MutableMapping]:
    pending = getattr(adapter, "_pending_messages", None)
    if isinstance(pending, MutableMapping):
        return pending
    return None


def _remove_from_fifo(adapter: Any, token: str) -> bool:
    """Remove matching item from pending slot or overflow. True if removed."""
    runner = resolve_runner_from_adapter(adapter)

    pending = _pending_mapping(adapter)
    if pending is not None:
        for session_key, event in list(pending.items()):
            if event_matches_token(event, token):
                pending.pop(session_key, None)
                _promote_overflow_head(runner, adapter, session_key)
                logger.info(
                    "[owner queue-cancel] removed pending slot session=%s token=%s",
                    session_key,
                    token[:8],
                )
                return True

    queued = _overflow_mapping(runner)
    if queued is not None:
        for session_key, overflow in list(queued.items()):
            if not overflow:
                continue
            # overflow is the live list on SessionState.conversation.queued_events
            for idx, event in enumerate(list(overflow)):
                if event_matches_token(event, token):
                    del overflow[idx]
                    if not overflow:
                        try:
                            queued.pop(session_key, None)
                        except Exception:
                            try:
                                del queued[session_key]
                            except Exception:
                                pass
                    logger.info(
                        "[owner queue-cancel] removed overflow[%d] session=%s token=%s",
                        idx,
                        session_key,
                        token[:8],
                    )
                    return True

    # Last resort: walk SessionState directly (covers runner without legacy view).
    if runner is not None and hasattr(runner, "_sessions_map"):
        try:
            sessions = runner._sessions_map()
        except Exception:
            sessions = None
        if isinstance(sessions, dict):
            for session_key, state in list(sessions.items()):
                overflow = getattr(
                    getattr(state, "conversation", None), "queued_events", None
                )
                if not overflow:
                    continue
                for idx, event in enumerate(list(overflow)):
                    if event_matches_token(event, token):
                        del overflow[idx]
                        logger.info(
                            "[owner queue-cancel] removed session-state overflow[%d] "
                            "session=%s token=%s",
                            idx,
                            session_key,
                            token[:8],
                        )
                        return True
    return False


def cancel_queued_by_token(adapter: Any, token: str) -> str:
    """Remove one owner-tagged /queue item.

    Returns:
        ``"ok"`` — item removed, or cancel armed before enqueue (race win).
        ``"not_found"`` — already running / already gone / unknown token.
        ``"invalid"`` — empty token / missing adapter.
    """
    if adapter is None or not token:
        return "invalid"

    if _remove_from_fifo(adapter, token):
        with _token_lock:
            meta = _token_state.get(token) or {}
            meta["status"] = "cancelled"
            _token_state[token] = meta
        return "ok"

    with _token_lock:
        meta = _token_state.get(token)
        status = (meta or {}).get("status")
        # Pre-enqueue (or race before stamp): arm cancel so enqueue drops it.
        if meta and status in ("scheduled", "process_now"):
            # process_now that never landed in FIFO — still cancellable.
            meta["status"] = "cancelled"
            logger.info(
                "[owner queue-cancel] armed pre-enqueue cancel token=%s was=%s",
                token[:8],
                status,
            )
            return "ok"

    logger.info(
        "[owner queue-cancel] token not found (already running or gone) "
        "token=%s state=%s",
        token[:8],
        status,
    )
    return "not_found"


def _pop_event_by_token(adapter: Any, token: str) -> Tuple[Any, str]:
    """Remove FIFO event stamped with token.

    Returns:
        ``(event, session_key)`` or ``(None, "")`` if not found.
    """
    if adapter is None or not token:
        return None, ""
    runner = resolve_runner_from_adapter(adapter)

    pending = _pending_mapping(adapter)
    if pending is not None:
        for session_key, event in list(pending.items()):
            if event_matches_token(event, token):
                pending.pop(session_key, None)
                # Do NOT promote overflow here — caller will re-seat this event.
                logger.info(
                    "[owner queue] pop pending slot session=%s token=%s",
                    session_key,
                    token[:8],
                )
                return event, session_key

    queued = _overflow_mapping(runner)
    if queued is not None:
        for session_key, overflow in list(queued.items()):
            if not overflow:
                continue
            for idx, event in enumerate(list(overflow)):
                if event_matches_token(event, token):
                    del overflow[idx]
                    if not overflow:
                        try:
                            queued.pop(session_key, None)
                        except Exception:
                            try:
                                del queued[session_key]
                            except Exception:
                                pass
                    logger.info(
                        "[owner queue] pop overflow[%d] session=%s token=%s",
                        idx,
                        session_key,
                        token[:8],
                    )
                    return event, session_key
    return None, ""


def steer_queued_by_token(adapter: Any, token: str) -> str:
    """Convert a queued item into a mid-run ``/steer`` injection.

    Removes the item from FIFO (so it will not also run as a full turn), then
    calls ``running_agent.steer(text)``.

    Returns:
        ``"ok"`` — steered into the current turn.
        ``"not_found"`` — already running / gone / unknown token.
        ``"no_agent"`` — no running agent with steer().
        ``"rejected"`` — agent.steer() returned False (empty / unavailable).
        ``"invalid"`` — empty token / missing adapter / empty text.
    """
    if adapter is None or not token:
        return "invalid"

    with _token_lock:
        meta = dict(_token_state.get(token) or {})
        status = meta.get("status")
        if not meta:
            return "not_found"
        if status in ("cancelled", "executed", "steered"):
            return "not_found"

    text = str(meta.get("user_input") or meta.get("text") or "").strip()
    if not text:
        return "invalid"

    session_key = str(meta.get("session_key") or "").strip()
    event, found_key = _pop_event_by_token(adapter, token)
    if found_key:
        session_key = session_key or found_key

    # Pre-enqueue (scheduled) can still steer from registered text.
    if event is None and status not in ("scheduled", "process_now"):
        # enqueued/process_now but not found in FIFO
        if status == "enqueued":
            return "not_found"
        # process_now without event — fall through with text only
        if status != "process_now":
            return "not_found"

    def _reseat() -> None:
        """Put the event back if steer fails after we already popped it."""
        if event is None or not session_key:
            return
        pending = _pending_mapping(adapter)
        if pending is None:
            return
        existing = pending.get(session_key)
        if existing is not None and not event_matches_token(existing, token):
            runner = resolve_runner_from_adapter(adapter)
            queued = _overflow_mapping(runner)
            if queued is not None:
                try:
                    overflow = queued.get(session_key)
                    if overflow is None:
                        overflow = []
                        queued[session_key] = overflow
                    overflow.insert(0, existing)
                except Exception:
                    logger.warning(
                        "[owner queue] steer reseat overflow failed",
                        exc_info=True,
                    )
        pending[session_key] = event
        _stamp_event(event, token)

    runner = resolve_runner_from_adapter(adapter)
    if runner is None or not session_key:
        # No runner: still mark steered-intent if scheduled so enqueue drops;
        # but without agent we cannot actually inject.
        _reseat()
        logger.info(
            "[owner queue] steer no runner/session token=%s session=%s",
            token[:8],
            session_key or "-",
        )
        return "no_agent"

    agent = None
    try:
        peek = getattr(runner, "_peek_session_state", None)
        state = peek(session_key) if callable(peek) else None
        agent = getattr(getattr(state, "turn", None), "agent", None) if state else None
        try:
            import gateway.run as gateway_run

            sentinel = getattr(gateway_run, "_AGENT_PENDING_SENTINEL", None)
        except Exception:
            sentinel = None
        if agent is sentinel:
            agent = None
    except Exception:
        logger.warning("[owner queue] steer agent lookup failed", exc_info=True)
        agent = None

    if agent is None or not hasattr(agent, "steer"):
        _reseat()
        return "no_agent"

    try:
        accepted = bool(agent.steer(text))
    except Exception:
        logger.warning(
            "[owner queue] steer() raised token=%s session=%s",
            token[:8],
            session_key,
            exc_info=True,
        )
        _reseat()
        return "rejected"

    if not accepted:
        _reseat()
        logger.info(
            "[owner queue] steer rejected token=%s session=%s",
            token[:8],
            session_key,
        )
        return "rejected"

    with _token_lock:
        cur = _token_state.get(token) or {}
        cur["status"] = "steered"
        if session_key:
            cur["session_key"] = session_key
        _token_state[token] = cur

    logger.info(
        "[owner queue] steered token=%s session=%s text_len=%d",
        token[:8],
        session_key,
        len(text),
    )
    return "ok"


def process_now_by_token(adapter: Any, token: str) -> str:
    """Promote a tagged queue item to the FIFO head and interrupt the run.

    Returns:
        ``"ok"`` — item is head of queue; interrupt requested if agent busy.
        ``"not_found"`` — already running / gone / unknown.
        ``"invalid"`` — empty token / missing adapter.
    """
    if adapter is None or not token:
        return "invalid"

    with _token_lock:
        meta = dict(_token_state.get(token) or {})
        status = meta.get("status")
        if status in ("cancelled", "executed"):
            return "not_found"
        if not meta:
            return "not_found"

    # Already the pending-slot head for its session — just interrupt.
    pending = _pending_mapping(adapter)
    already_head = False
    session_key = str(meta.get("session_key") or "").strip()
    if pending is not None:
        if session_key and event_matches_token(pending.get(session_key), token):
            already_head = True
        elif not session_key:
            for sk, ev in pending.items():
                if event_matches_token(ev, token):
                    session_key = sk
                    already_head = True
                    break

    if not already_head:
        event, found_key = _pop_event_by_token(adapter, token)
        if found_key:
            session_key = session_key or found_key
        if event is None:
            # Still scheduled (not yet enqueued) — mark process_now intent.
            with _token_lock:
                cur = _token_state.get(token)
                if cur and cur.get("status") == "scheduled":
                    cur["status"] = "process_now"
                    _token_state[token] = cur
                    logger.info(
                        "[owner queue] process_now armed pre-enqueue token=%s",
                        token[:8],
                    )
                else:
                    return "not_found"
        elif session_key and pending is not None:
            # Seat as head: push current head to overflow front if occupied.
            existing = pending.get(session_key)
            if existing is not None and not event_matches_token(existing, token):
                runner = resolve_runner_from_adapter(adapter)
                queued = _overflow_mapping(runner)
                if queued is not None:
                    try:
                        overflow = queued.get(session_key)
                        if overflow is None:
                            overflow = []
                            queued[session_key] = overflow
                        overflow.insert(0, existing)
                    except Exception:
                        logger.warning(
                            "[owner queue] process_now push-head overflow failed",
                            exc_info=True,
                        )
            pending[session_key] = event
            _stamp_event(event, token)
        elif event is not None and not session_key:
            # Popped but cannot re-seat — put back on a synthetic overflow if possible.
            logger.warning(
                "[owner queue] process_now lost session_key token=%s; re-enqueue failed",
                token[:8],
            )
            return "not_found"

    with _token_lock:
        cur = _token_state.get(token) or {}
        if cur.get("status") not in ("cancelled", "executed"):
            cur["status"] = "process_now"
            if session_key:
                cur["session_key"] = session_key
            _token_state[token] = cur

    # Soft-interrupt running agent WITHOUT clearing pending (unlike /stop).
    _interrupt_session(adapter, session_key, meta.get("source"))
    logger.info(
        "[owner queue] process_now ok token=%s session=%s already_head=%s",
        token[:8],
        session_key or "-",
        already_head,
    )
    return "ok"


def _interrupt_session(adapter: Any, session_key: str, source: Any = None) -> None:
    """Best-effort soft interrupt so the pending head drains next."""
    if not session_key:
        return
    runner = resolve_runner_from_adapter(adapter)
    if runner is None:
        return
    try:
        # GatewayRunner uses a pending sentinel object — skip if not a real agent.
        peek = getattr(runner, "_peek_session_state", None)
        if not callable(peek):
            return
        state = peek(session_key)
        agent = getattr(getattr(state, "turn", None), "agent", None) if state else None
        if agent is None:
            return
        sentinel = getattr(runner, "_AGENT_PENDING_SENTINEL", None)
        # Sentinel is module-level in gateway.run; resolve via originals/import.
        try:
            import gateway.run as gateway_run

            sentinel = getattr(gateway_run, "_AGENT_PENDING_SENTINEL", sentinel)
        except Exception:
            pass
        if agent is sentinel:
            return
        if hasattr(agent, "interrupt"):
            agent.interrupt()
            logger.info(
                "[owner queue] interrupted agent for process_now session=%s",
                session_key,
            )
    except Exception:
        logger.warning(
            "[owner queue] process_now interrupt failed session=%s",
            session_key,
            exc_info=True,
        )


def _match_token_for_text(text: str) -> Optional[str]:
    """Return the first scheduled/cancelled token registered for this prompt text."""
    needle = (text or "").strip()
    if not needle:
        return None
    with _token_lock:
        for token, meta in _token_state.items():
            if meta.get("text") != needle:
                continue
            if meta.get("status") in ("scheduled", "cancelled"):
                return token
    return None


def _freeze_card_for_token(token: str) -> None:
    """Best-effort REST update of the Feishu guide card to「已执行」."""
    # Snapshot under lock so freeze daemon races safely with cancel/enqueue.
    with _token_lock:
        meta = dict(_token_state.get(token) or {})
    if meta.get("status") == "cancelled":
        return
    message_id = meta.get("card_message_id") or ""
    if not message_id:
        logger.info(
            "[owner queue-cancel] skip freeze: no card_message_id token=%s",
            token[:8],
        )
        return

    app_id = meta.get("app_id") or ""
    app_secret = meta.get("app_secret") or ""
    if not app_id or not app_secret:
        # Fall back to env (same as other owner Feishu REST helpers).
        import os
        app_id = app_id or os.environ.get("FEISHU_APP_ID", "")
        app_secret = app_secret or os.environ.get("FEISHU_APP_SECRET", "")
    if not app_id or not app_secret:
        logger.warning("[owner queue-cancel] freeze skipped: missing FEISHU credentials")
        return

    try:
        import asyncio

        from owner.feishu.clarify_card import patch_message_via_rest
        from owner.feishu.queue_card import build_queue_executed_card

        card = build_queue_executed_card(
            str(meta.get("user_input") or meta.get("text") or ""),
            str(meta.get("user_name") or "用户"),
        )

        async def _patch() -> None:
            ok = await patch_message_via_rest(
                app_id=app_id,
                app_secret=app_secret,
                message_id=message_id,
                card=card,
            )
            logger.info(
                "[owner queue-cancel] freeze card token=%s message_id=%s ok=%s",
                token[:8],
                message_id[:16],
                ok,
            )

        # This runs on a dedicated daemon thread (no running loop).
        asyncio.run(_patch())
    except Exception:
        logger.warning(
            "[owner queue-cancel] freeze card failed token=%s",
            token[:8],
            exc_info=True,
        )


def notify_queue_started(token: str) -> None:
    """Mark token executed and freeze the guide card (non-blocking)."""
    if not token:
        return
    with _token_lock:
        meta = _token_state.get(token)
        if not meta:
            return
        if meta.get("status") in ("cancelled", "executed"):
            return
        meta["status"] = "executed"
        _token_state[token] = meta
    # Don't block the gateway dequeue path on Feishu REST.
    threading.Thread(
        target=_freeze_card_for_token,
        args=(token,),
        daemon=True,
        name=f"owner-queue-freeze-{token[:8]}",
    ).start()


def _enqueue_fifo(self, session_key: str, queued_event: Any, adapter: Any) -> None:
    """Wrap original enqueue: runner back-ref + stamp/drop owner queue tokens."""
    if adapter is not None:
        try:
            adapter._owner_gateway_runner = self
        except Exception:
            pass

    text = getattr(queued_event, "text", None) or ""
    # Prefer pre-stamped token (attr or metadata) over text match.
    token = getattr(queued_event, _EVENT_TOKEN_ATTR, None)
    if not token:
        md = getattr(queued_event, "metadata", None)
        if isinstance(md, dict):
            token = md.get(_META_TOKEN_KEY)
    if not token:
        token = _match_token_for_text(text)
    if token:
        with _token_lock:
            meta = _token_state.get(token) or {}
            if meta.get("status") in ("cancelled", "steered"):
                logger.info(
                    "[owner queue-cancel] drop enqueue for %s token=%s session=%s",
                    meta.get("status"),
                    token[:8],
                    session_key,
                )
                return None
            _stamp_event(queued_event, token)
            meta["status"] = "enqueued"
            meta["session_key"] = session_key
            # Prefer credentials from the live adapter when available.
            if adapter is not None:
                app_id = getattr(adapter, "_app_id", None) or ""
                app_secret = getattr(adapter, "_app_secret", None) or ""
                if app_id:
                    meta["app_id"] = app_id
                if app_secret:
                    meta["app_secret"] = app_secret
            _token_state[token] = meta

    return _originals["_enqueue_fifo"](self, session_key, queued_event, adapter)


async def _busy_queue_command(self, event: Any, quick_key: str, source: Any) -> Any:
    """Feishu: mint token + send queue status card; other platforms unchanged."""
    is_feishu = False
    try:
        from gateway.config import Platform

        is_feishu = getattr(source, "platform", None) == Platform.FEISHU
    except Exception:
        is_feishu = False

    queue_token: Optional[str] = None
    queued_text = ""
    if is_feishu:
        try:
            queued_text = (event.get_command_args() or "").strip()
        except Exception:
            queued_text = (getattr(event, "text", None) or "").strip()
            if queued_text.lower().startswith("/queue"):
                queued_text = queued_text[6:].strip()
            elif queued_text.lower().startswith("/q "):
                queued_text = queued_text[3:].strip()
        has_media = bool(getattr(event, "media_urls", None))
        # Guide-card path already registered a token + bound the card.
        existing = _match_token_for_text(queued_text) if queued_text else None
        if existing and token_has_card(existing):
            queue_token = existing
            try:
                setattr(event, _EVENT_TOKEN_ATTR, existing)
            except Exception:
                pass
            with _token_lock:
                meta = _token_state.get(existing) or {}
                meta["session_key"] = quick_key
                _token_state[existing] = meta
        elif queued_text or has_media:
            import uuid as _uuid

            queue_token = str(_uuid.uuid4())
            user_name = str(getattr(source, "user_name", None) or "") or "用户"
            chat_id = str(getattr(source, "chat_id", None) or "")
            register_scheduled_token(
                queue_token,
                text=queued_text,
                chat_id=chat_id,
                user_input=queued_text,
                user_name=user_name,
                session_key=quick_key,
                source=source,
            )
            try:
                setattr(event, _EVENT_TOKEN_ATTR, queue_token)
            except Exception:
                pass

    result = await _originals["_busy_queue_command"](self, event, quick_key, source)

    if not is_feishu or not queue_token:
        return result

    # Usage / validation failure — leave text reply, drop token.
    try:
        from agent.i18n import t

        usage = t("gateway.queue_usage")
    except Exception:
        usage = ""
    if isinstance(result, str) and usage and result == usage:
        with _token_lock:
            _token_state.pop(queue_token, None)
        return result
    if isinstance(result, str) and (
        result.startswith("Usage:") or result.startswith("用法")
    ):
        with _token_lock:
            _token_state.pop(queue_token, None)
        return result

    # Guide path already has a card — suppress text ack only.
    if token_has_card(queue_token):
        return None

    adapter = None
    try:
        adapter = self._adapter_for_source(source)
    except Exception:
        adapter = None
    if adapter is None or not hasattr(adapter, "send_queue_status_card"):
        return result

    try:
        depth = 0
        try:
            depth = int(self._queue_depth(quick_key, adapter=adapter) or 0)
        except Exception:
            depth = 0
        user_name = str(getattr(source, "user_name", None) or "") or "用户"
        send_result = await adapter.send_queue_status_card(
            chat_id=str(getattr(source, "chat_id", "") or ""),
            user_input=queued_text,
            user_name=user_name,
            queue_token=queue_token,
            depth=depth,
            source=source,
        )
        message_id = getattr(send_result, "message_id", None) or ""
        if message_id:
            bind_card_message_id(
                queue_token,
                str(message_id),
                session_key=quick_key,
                chat_id=str(getattr(source, "chat_id", "") or ""),
                app_id=str(getattr(adapter, "_app_id", "") or ""),
                app_secret=str(getattr(adapter, "_app_secret", "") or ""),
            )
        if getattr(send_result, "success", False):
            return None
    except Exception:
        logger.warning(
            "[owner queue] Feishu queue status card failed; keeping text ack",
            exc_info=True,
        )
    return result


def _dequeue_pending_event(adapter: Any, session_key: str) -> Any:
    """Wrap dequeue: freeze guide card when an owner-tagged queue item starts."""
    event = _originals["_dequeue_pending_event"](adapter, session_key)
    if event is not None:
        token = getattr(event, _EVENT_TOKEN_ATTR, None)
        if token:
            try:
                notify_queue_started(token)
            except Exception:
                logger.debug(
                    "[owner queue-cancel] notify_queue_started failed",
                    exc_info=True,
                )
    return event


def _prefetch_provider(self, provider: Any, query: str, *, session_id: str = "") -> str:
    """Wait for in-flight end-of-turn prefetch before skipping a rapid follow-up.

    Queue FIFO drains the next turn immediately after the previous turn ends.
    The previous turn's ``queue_prefetch_all`` often still holds the external
    prefetch thread, so the stock implementation skips openviking entirely
    (DEBUG log only) — no memory injection and no viking recall card.
    """
    if getattr(provider, "name", "") != "builtin":
        try:
            with self._external_prefetch_lock:
                existing = self._external_prefetch_threads.get(provider.name)
            if existing is not None and existing.is_alive():
                timeout = float(getattr(self, "_external_prefetch_timeout", 5.0) or 5.0)
                wait_s = min(timeout, 3.0)
                logger.info(
                    "[owner queue-cancel] waiting up to %.1fs for in-flight %s prefetch "
                    "before follow-up recall",
                    wait_s,
                    provider.name,
                )
                existing.join(wait_s)
                with self._external_prefetch_lock:
                    cur = self._external_prefetch_threads.get(provider.name)
                    if cur is existing and not existing.is_alive():
                        self._external_prefetch_threads.pop(provider.name, None)
        except Exception:
            logger.debug(
                "[owner queue-cancel] prefetch wait failed (non-fatal)",
                exc_info=True,
            )
    return _originals["_prefetch_provider"](self, provider, query, session_id=session_id)


def apply_patch() -> None:
    """Monkey-patch enqueue/dequeue + prefetch wait. Idempotent."""
    global _applied
    if _applied:
        return

    try:
        import gateway.run as gateway_run
    except ImportError:
        logger.warning("queue_cancel_patch: gateway.run not importable; skip")
        return

    runner_cls = getattr(gateway_run, "GatewayRunner", None)
    if runner_cls is None or not hasattr(runner_cls, "_enqueue_fifo"):
        logger.warning("queue_cancel_patch: GatewayRunner._enqueue_fifo missing; skip")
        return

    _originals["_enqueue_fifo"] = runner_cls._enqueue_fifo
    runner_cls._enqueue_fifo = _enqueue_fifo

    if hasattr(gateway_run, "_dequeue_pending_event"):
        _originals["_dequeue_pending_event"] = gateway_run._dequeue_pending_event
        gateway_run._dequeue_pending_event = _dequeue_pending_event

    if hasattr(runner_cls, "_busy_queue_command"):
        _originals["_busy_queue_command"] = runner_cls._busy_queue_command
        runner_cls._busy_queue_command = _busy_queue_command

    try:
        import agent.memory_manager as mm

        if hasattr(mm.MemoryManager, "_prefetch_provider"):
            _originals["_prefetch_provider"] = mm.MemoryManager._prefetch_provider
            mm.MemoryManager._prefetch_provider = _prefetch_provider
    except Exception:
        logger.warning(
            "queue_cancel_patch: MemoryManager prefetch wait not applied",
            exc_info=True,
        )

    _applied = True
    logger.info("queue_cancel_patch applied")


def revert_patch() -> None:
    """Restore originals and clear token state."""
    global _applied
    if not _applied:
        with _token_lock:
            _token_state.clear()
        return
    try:
        import gateway.run as gateway_run

        runner_cls = getattr(gateway_run, "GatewayRunner", None)
        if runner_cls is not None and "_enqueue_fifo" in _originals:
            runner_cls._enqueue_fifo = _originals["_enqueue_fifo"]
        if runner_cls is not None and "_busy_queue_command" in _originals:
            runner_cls._busy_queue_command = _originals["_busy_queue_command"]
        if "_dequeue_pending_event" in _originals:
            gateway_run._dequeue_pending_event = _originals["_dequeue_pending_event"]
    except Exception:
        logger.warning("queue_cancel_patch: revert gateway failed", exc_info=True)

    try:
        import agent.memory_manager as mm

        if "_prefetch_provider" in _originals:
            mm.MemoryManager._prefetch_provider = _originals["_prefetch_provider"]
    except Exception:
        logger.warning("queue_cancel_patch: revert memory failed", exc_info=True)

    _originals.clear()
    with _token_lock:
        _token_state.clear()
    _applied = False
    logger.info("queue_cancel_patch reverted")
