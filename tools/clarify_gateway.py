"""Gateway-side clarify primitive (blocking event-based queue).

The ``clarify`` tool needs to ask the user a question and block the agent
thread until they respond.  In CLI mode this is trivial — ``input()`` is
synchronous.  In gateway mode the agent runs on a worker thread while the
event loop handles the user's reply, so we need a thread-safe primitive
that:

  * stores a pending clarify request (with a generated ``clarify_id``),
  * blocks the agent thread on an ``Event``,
  * resolves the wait when the gateway's button-callback or text-intercept
    fires ``resolve_gateway_clarify(clarify_id, response)``,
  * supports timeouts so a user who never responds does NOT hang the agent
    thread forever (which would also pin the gateway's running-agent guard).

State is module-level (same shape as ``tools.approval``) so platform
adapters can call ``resolve_gateway_clarify`` without holding a back-
reference to the ``GatewayRunner`` instance.

Two delivery paths from the adapter:

  1. **Button UI** — adapters override ``send_clarify`` to render inline
     buttons (e.g. Telegram ``InlineKeyboardMarkup``).  The button
     callback resolves with the chosen string.  A final "Other (type
     answer)" button enters text-capture mode for free-form responses.

  2. **Text fallback** — adapters without rich UI render a numbered list.
     The user replies with a number ("2") or with free text; the gateway's
     ``_handle_message`` intercepts the reply and resolves directly.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from tools.clarify_tool import CLARIFY_SESSION_CLEARED_SENTINEL

logger = logging.getLogger(__name__)

# [owner] DEBUG: dedicated clarify trace logger that ALWAYS writes to a
# standalone file, independent of the root logger configuration. This
# survives any per-component filter / level misconfiguration that could
# swallow logger.warning() in the gateway worker thread. Remove once the
# premature-timeout race is located.
import os as _os
import time as _time_module

def _trace(msg: str, *args) -> None:
    """Always-on trace writer to ~/.hermes/logs/clarify-trace.log."""
    try:
        from hermes_constants import get_hermes_home as _ghh
        _path = _ghh() / "logs" / "clarify-trace.log"
    except Exception:
        _path = _os.path.expanduser("~/.hermes/logs/clarify-trace.log")
    try:
        _ts = _time_module.strftime("%Y-%m-%d %H:%M:%S")
        _tid = threading.get_ident()
        _full = f"{_ts} tid={_tid} " + (msg % args if args else msg) + "\n"
        with open(_path, "a", encoding="utf-8") as _f:
            _f.write(_full)
    except Exception:
        pass


# =========================================================================
# Module-level state
# =========================================================================

@dataclass
class _ClarifyEntry:
    """One pending clarify request inside a gateway session."""
    clarify_id: str
    session_key: str
    question: str
    # [owner] clarify: choices are normalized {"display", "key"} dicts
    choices: Optional[List[Dict[str, Optional[str]]]]
    event: threading.Event = field(default_factory=threading.Event)
    response: Optional[str] = None
    awaiting_text: bool = False  # set when user picked "Other" or clarify is open-ended

    def signature(self) -> Dict[str, object]:
        return {
            "clarify_id": self.clarify_id,
            "session_key": self.session_key,
            "question": self.question,
            "choices": list(self.choices) if self.choices else None,
        }


_lock = threading.RLock()
# clarify_id → _ClarifyEntry  (primary lookup for button callbacks)
_entries: Dict[str, _ClarifyEntry] = {}
# session_key → list[clarify_id]  (FIFO; for text-fallback intercept and session cleanup)
_session_index: Dict[str, List[str]] = {}


# =========================================================================
# Public API — agent-thread side
# =========================================================================

def register(
    clarify_id: str,
    session_key: str,
    question: str,
    choices: Optional[List[Any]],
) -> _ClarifyEntry:
    """Register a pending clarify request and return the entry.

    The caller (gateway clarify_callback) will then send the prompt to the
    user and block on ``wait_for_response(clarify_id, timeout)``.

    ``choices`` items should be normalized ``{"display", "key"}`` dicts as
    produced by ``owner.clarify.choice_normalizer``. Legacy string lists are
    tolerated but adapters should read ``c["display"]`` for rendering.
    """
    # [owner] clarify: keep choices as normalized dicts for adapters
    normalized_choices = list(choices) if choices else None
    entry = _ClarifyEntry(
        clarify_id=clarify_id,
        session_key=session_key,
        question=question,
        choices=normalized_choices,
        # Open-ended (no choices) → next message IS the response, no buttons needed.
        awaiting_text=not bool(choices),
    )
    with _lock:
        _entries[clarify_id] = entry
        _session_index.setdefault(session_key, []).append(clarify_id)
    _trace("register(clarify_id=%s, session_key=%s, choices=%s)", clarify_id, session_key, bool(choices))
    return entry


def wait_for_response(clarify_id: str, timeout: float) -> Optional[str]:
    """Block on the entry's event until resolved or timeout fires.

    Polls in 1-second slices so the agent's inactivity heartbeat keeps
    firing — without this, ``Event.wait(timeout=600)`` blocks the thread
    for 10 minutes with zero activity touches and the gateway's inactivity
    watchdog kills the agent while the user is still typing.

    Returns the resolved response string, or ``None`` on timeout.
    """
    import time as _time
    _wait_start = _time.monotonic()
    _trace("wait_for_response ENTER clarify_id=%s timeout=%.0fs", clarify_id, timeout)
    with _lock:
        entry = _entries.get(clarify_id)
    if entry is None:
        # [owner] clarify race defense: register() ran moments ago, so the
        # entry vanishing before wait_for_response() even starts can only be
        # a concurrent clear_session() (session boundary, /new, /stop, run
        # finally, etc.) — NOT a genuine user-inactivity timeout. Returning
        # None here would make _clarify_callback_sync fire the misleading
        # "未在 N 分钟内收到回复" notice seconds after the card was sent,
        # which is the exact bug we are fixing. Map this case to the session
        # -cleared sentinel so the gateway stops the turn quietly (still
        # raises ClarifyTimeout via clarify_tool, so the agent loop exits
        # cleanly) without the wrong timeout notice.
        _trace(
            "wait_for_response(%s): ENTRY NOT FOUND (concurrent clear_session?) "
            "— returning CLARIFY_SESSION_CLEARED_SENTINEL (not None)",
            clarify_id,
        )
        logger.warning(
            "[clarify] wait_for_response(%s): entry not found at start "
            "(cleared during card send?) — treating as session-cleared, "
            "NOT as user-inactivity timeout",
            clarify_id,
        )
        return CLARIFY_SESSION_CLEARED_SENTINEL

    try:
        from tools.environments.base import touch_activity_if_due
    except Exception:  # pragma: no cover - optional
        touch_activity_if_due = None

    deadline = _time.monotonic() + max(timeout, 0.0)
    activity_state = {"last_touch": _time.monotonic(), "start": _time.monotonic()}
    _resolved_by_event = False
    # [owner] DEBUG: race detector — if the event is ALREADY set when we
    # enter the loop but response is still None, someone set the event
    # without going through resolve_gateway_clarify (which always writes
    # response first). That is the smoking gun for the premature-timeout
    # bug. Log it loudly so we can find the culprit from the stack.
    if entry.event.is_set() and entry.response is None:
        import traceback as _tb_evt
        _trace(
            "wait_for_response(%s): RACE DETECTED — event already set but response is None. "
            "This entry was signalled without resolve_gateway_clarify. Stack:\n%s",
            clarify_id, "".join(_tb_evt.format_stack()),
        )
        logger.error(
            "[clarify] wait_for_response(%s): RACE — event set but response is None",
            clarify_id,
        )
    while True:
        remaining = deadline - _time.monotonic()
        if remaining <= 0:
            break
        if entry.event.wait(timeout=min(1.0, remaining)):
            _resolved_by_event = True
            break
        if touch_activity_if_due is not None:
            touch_activity_if_due(activity_state, "waiting for user clarify response")

    with _lock:
        # Remove from indices regardless of resolution outcome.
        _entries.pop(clarify_id, None)
        ids = _session_index.get(entry.session_key)
        if ids and clarify_id in ids:
            ids.remove(clarify_id)
            if not ids:
                _session_index.pop(entry.session_key, None)

    _elapsed = _time.monotonic() - _wait_start
    if _resolved_by_event:
        _trace(
            "wait_for_response(%s): RESOLVED BY EVENT after %.2fs (timeout=%.0fs) response=%r",
            clarify_id, _elapsed, timeout, entry.response,
        )
        logger.info(
            "[clarify] wait_for_response(%s): resolved by event after %.2fs "
            "(timeout=%.0fs) — response=%r",
            clarify_id, _elapsed, timeout, entry.response,
        )
    else:
        _trace(
            "wait_for_response(%s): DEADLINE reached after %.2fs (timeout=%.0fs) response=%r",
            clarify_id, _elapsed, timeout, entry.response,
        )
        logger.warning(
            "[clarify] wait_for_response(%s): DEADLINE reached after %.2fs "
            "(timeout=%.0fs) — response=%r",
            clarify_id, _elapsed, timeout, entry.response,
        )
    # [owner] clarify race defense: if the event fired but entry.response
    # is still None/empty, someone set the event without going through
    # resolve_gateway_clarify() (which always writes response before
    # setting the event). This is the race detector's smoking gun. Treat
    # it as session-cleared (not as user-inactivity timeout) so the
    # gateway stops quietly without the misleading "未在 N 分钟内收到回复"
    # notice. A genuine timeout is handled by the deadline branch above,
    # which also reaches this point with response=None but
    # _resolved_by_event=False — and that case genuinely IS user
    # inactivity, so it must keep returning None to fire the notice.
    if not entry.response and _resolved_by_event:
        _trace(
            "wait_for_response(%s): event fired but response is empty — "
            "returning CLARIFY_SESSION_CLEARED_SENTINEL (race defense)",
            clarify_id,
        )
        return CLARIFY_SESSION_CLEARED_SENTINEL
    return entry.response


# =========================================================================
# Public API — gateway / adapter side
# =========================================================================

def resolve_gateway_clarify(clarify_id: str, response: str) -> bool:
    """Unblock the agent thread waiting on ``clarify_id``.

    Returns True if an entry was found and resolved, False otherwise
    (already resolved, expired, or never existed).
    """
    import traceback as _tb
    with _lock:
        entry = _entries.get(clarify_id)
        if entry is None:
            _trace("resolve_gateway_clarify(%s, %r): NO ENTRY FOUND", clarify_id, response)
            logger.info(
                "[clarify] resolve_gateway_clarify(%s, %r): no entry found",
                clarify_id, response,
            )
            return False
    # [owner] DEBUG: diagnose premature-timeout bug — empty response causes
    # the gateway to treat it as a timeout (response == "").
    if not response:
        _trace(
            "resolve_gateway_clarify(%s, %r): EMPTY RESPONSE, caller stack:\n%s",
            clarify_id, response, "".join(_tb.format_stack()),
        )
        logger.warning(
            "[clarify] resolve_gateway_clarify(%s, %r): EMPTY response — "
            "will trigger timeout path in gateway. Caller stack:\n%s",
            clarify_id, response,
            "".join(_tb.format_stack()[-8:-1]),
        )
    else:
        _trace("resolve_gateway_clarify(%s, %r): RESOLVING", clarify_id, response[:80])
        logger.info(
            "[clarify] resolve_gateway_clarify(%s, %r): resolving",
            clarify_id, response[:80],
        )
    entry.response = str(response) if response is not None else ""
    entry.event.set()
    _trace("resolve_gateway_clarify(%s): event.set() done, response=%r", clarify_id, entry.response)
    return True


def get_pending_for_session(session_key: str) -> Optional[_ClarifyEntry]:
    """Return the OLDEST pending clarify entry for a session, or None.

    Used by the text-fallback intercept in ``_handle_message`` — when a
    clarify is awaiting a free-form text response, the next user message
    in that session is captured as the answer.
    """
    with _lock:
        ids = _session_index.get(session_key) or []
        for cid in ids:
            entry = _entries.get(cid)
            if entry is None:
                continue
            if entry.awaiting_text:
                return entry
        return None


def mark_awaiting_text(clarify_id: str) -> bool:
    """Flip an entry into text-capture mode (user picked the 'Other' button).

    Returns True if the entry exists and was flipped, False otherwise.
    """
    with _lock:
        entry = _entries.get(clarify_id)
        if entry is None:
            return False
        entry.awaiting_text = True
        return True


def has_pending(session_key: str) -> bool:
    """Return True when this session has at least one pending clarify entry."""
    with _lock:
        ids = _session_index.get(session_key) or []
        return any(_entries.get(cid) is not None for cid in ids)


def clear_session(session_key: str) -> int:
    """Resolve and drop every pending clarify for a session.

    Used by session-boundary cleanup (e.g. ``/new``, gateway shutdown,
    cached-agent eviction) so blocked agent threads don't hang past the
    end of their session.  Returns the number of entries cancelled.
    """
    import traceback as _tb
    with _lock:
        ids = list(_session_index.pop(session_key, []) or [])
        entries = [_entries.pop(cid, None) for cid in ids]
    cancelled = 0
    for entry in entries:
        if entry is None:
            continue
        # [owner] DEBUG: diagnose premature-timeout bug — log who clears.
        _trace(
            "clear_session(%s): cancelling entry clarify_id=%s, caller stack:\n%s",
            session_key, entry.clarify_id, "".join(_tb.format_stack()),
        )
        logger.warning(
            "[clarify] clear_session(%s): cancelling entry clarify_id=%s. "
            "Caller stack:\n%s",
            session_key, entry.clarify_id,
            "".join(_tb.format_stack()[-8:-1]),
        )
        # [owner] clarify session cleanup sentinel (see owner/clarify/timeout_handler.py)
        # Use a dedicated sentinel so session-boundary cleanup is not confused
        # with a real user response or a natural timeout.
        entry.response = CLARIFY_SESSION_CLEARED_SENTINEL
        entry.event.set()
        cancelled += 1
    return cancelled


# =========================================================================
# Config
# =========================================================================

def get_clarify_timeout() -> int:
    """Read the clarify response timeout (seconds) from config.

    Defaults to 600 (10 minutes) — long enough for the user to type a
    thoughtful response, short enough that an abandoned prompt eventually
    unblocks the agent thread instead of pinning the running-agent guard
    forever.

    Reads ``agent.clarify_timeout`` from config.yaml.
    """
    try:
        from hermes_cli.config import load_config
        cfg = load_config() or {}
        agent_cfg = cfg.get("agent", {}) or {}
        return int(agent_cfg.get("clarify_timeout", 600))
    except Exception:
        return 600


# =========================================================================
# Per-session notify hook (gateway → adapter bridge)
# =========================================================================
# Mirrors tools.approval's _gateway_notify_cbs: the gateway registers a
# per-session callback that sends the clarify prompt to the user.  The
# callback bridges sync→async (runs on the agent thread; schedules the
# adapter ``send_clarify`` call on the event loop).

_notify_cbs: Dict[str, Callable[[_ClarifyEntry], None]] = {}


def register_notify(session_key: str, cb: Callable[[_ClarifyEntry], None]) -> None:
    """Register a per-session notify callback used by ``clarify_callback``."""
    with _lock:
        _notify_cbs[session_key] = cb


def unregister_notify(session_key: str) -> None:
    """Drop the per-session notify callback and cancel any pending clarify entries."""
    with _lock:
        _notify_cbs.pop(session_key, None)
    # Cancel any pending entries so blocked threads unwind when the run
    # ends (interrupt, completion, gateway shutdown).
    clear_session(session_key)


def get_notify(session_key: str) -> Optional[Callable[[_ClarifyEntry], None]]:
    with _lock:
        return _notify_cbs.get(session_key)
