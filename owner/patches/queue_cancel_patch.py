"""[owner] Feishu-guide /queue cancel + freeze-on-execute without core edits.

Token transport (IMPORTANT — do NOT put tokens in ``message_id``):
  Feishu uses ``event.message_id`` as ``reply_to``. Stamping synthetic ids
  there broke acks and reply anchors. Instead:

  1. ``register_scheduled_token(token, text=..., card_meta=...)`` on submit
  2. Wrapped ``_enqueue_fifo`` matches prompt text, stamps
     ``event._owner_queue_token``, binds runner on the adapter
  3. Cancel scans pending/overflow for that attribute
  4. Wrapped ``_dequeue_pending_event`` freezes the Feishu card when a stamped
     item starts execution (REST patch →「已执行」终态, 无撤销按钮)

Also patches ``MemoryManager._prefetch_provider`` so a rapid FIFO follow-up
waits briefly for an in-flight end-of-turn ``queue_prefetch`` instead of
skipping openviking recall (which dropped the viking recall card for queue
turns that fire immediately after the previous turn ends).

Removable via ``revert_patch()``.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# token -> {"status": scheduled|enqueued|cancelled|executed, "text": str, ...card}
# Guarded by _token_lock: cancel / enqueue / freeze threads all touch this map.
_token_state: Dict[str, Dict[str, Any]] = {}
_token_lock = threading.Lock()

_originals: Dict[str, Any] = {}
_applied: bool = False

_EVENT_TOKEN_ATTR = "_owner_queue_token"


def make_queue_message_id(token: str) -> str:
    """Deprecated helper kept for tests/compat — do not put on MessageEvent.message_id."""
    return f"owner-q:{token}"


def parse_queue_token(message_id: Any) -> Optional[str]:
    """Legacy parse of owner-q message_id stamps (no longer written)."""
    if not isinstance(message_id, str) or not message_id.startswith("owner-q:"):
        return None
    token = message_id[len("owner-q:") :].strip()
    return token or None


def event_matches_token(event: Any, token: str) -> bool:
    """True when the FIFO event was stamped with this cancel token."""
    if not token or event is None:
        return False
    return getattr(event, _EVENT_TOKEN_ATTR, None) == token


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
        }


def should_skip_dispatch(token: Optional[str]) -> bool:
    """True when cancel won the race before the synthetic /queue was handled."""
    if not token:
        return False
    with _token_lock:
        meta = _token_state.get(token) or {}
        return meta.get("status") == "cancelled"


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
    queued = getattr(runner, "_queued_events", None)
    if not isinstance(queued, dict):
        return
    overflow = queued.get(session_key)
    if not overflow:
        return
    next_event = overflow.pop(0)
    if not overflow:
        queued.pop(session_key, None)
    pending = getattr(adapter, "_pending_messages", None)
    if isinstance(pending, dict):
        pending[session_key] = next_event


def _remove_from_fifo(adapter: Any, token: str) -> bool:
    """Remove matching item from pending slot or overflow. True if removed."""
    runner = resolve_runner_from_adapter(adapter)

    pending = getattr(adapter, "_pending_messages", None)
    if isinstance(pending, dict):
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

    if runner is not None:
        queued = getattr(runner, "_queued_events", None)
        if isinstance(queued, dict):
            for session_key, overflow in list(queued.items()):
                if not overflow:
                    continue
                for idx, event in enumerate(list(overflow)):
                    if event_matches_token(event, token):
                        del overflow[idx]
                        if not overflow:
                            queued.pop(session_key, None)
                        logger.info(
                            "[owner queue-cancel] removed overflow[%d] session=%s token=%s",
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
        if meta and meta.get("status") == "scheduled":
            meta["status"] = "cancelled"
            logger.info(
                "[owner queue-cancel] armed pre-enqueue cancel token=%s",
                token[:8],
            )
            return "ok"
        status = (meta or {}).get("status")

    logger.info(
        "[owner queue-cancel] token not found (already running or gone) "
        "token=%s state=%s",
        token[:8],
        status,
    )
    return "not_found"


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
        from owner.feishu.steer_card import build_queue_executed_card

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
    token = _match_token_for_text(text)
    if token:
        with _token_lock:
            meta = _token_state.get(token) or {}
            if meta.get("status") == "cancelled":
                logger.info(
                    "[owner queue-cancel] drop enqueue for cancelled token=%s session=%s",
                    token[:8],
                    session_key,
                )
                return None
            try:
                setattr(queued_event, _EVENT_TOKEN_ATTR, token)
            except Exception:
                logger.warning(
                    "[owner queue-cancel] failed to stamp token on event token=%s",
                    token[:8],
                )
            meta["status"] = "enqueued"
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
