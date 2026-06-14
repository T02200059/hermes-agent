"""Blocking event-based approval queue for memory proposals.

Mirrors ``tools.approval`` for dangerous-command approvals:
- Thread-safe per-session queue of pending memory proposals
- Agent thread blocks on ``threading.Event`` until user responds
- User clicks a button or replies ``/approve`` / ``/deny`` → resolve the queue
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from agent.i18n import t

logger = logging.getLogger(__name__)


@dataclass
class _MemoryApprovalEntry:
    """One pending memory proposal inside a gateway session."""

    session_key: str
    action: str            # "add", "replace", "remove"
    target: str            # "memory" or "user"
    old_text: str          # for replace/remove
    new_content: str       # for add/replace
    event: threading.Event = field(default_factory=threading.Event)
    result: Optional[str] = None  # "approve" | "deny"


_lock = threading.RLock()
_memory_queues: Dict[str, List[_MemoryApprovalEntry]] = {}
_memory_notify_cbs: Dict[str, Callable[[_MemoryApprovalEntry], None]] = {}


def _get_session_key() -> str:
    """Resolve the current session key for memory proposal scoping."""
    try:
        from tools.approval import get_current_session_key
        key = get_current_session_key()
        # An empty string is a valid dict key but no queue will ever be
        # registered under it, causing the proposal to hang forever.
        return key if key else "default"
    except Exception:
        return "default"


def submit_memory_proposal(
    action: str,
    target: str,
    old_text: str,
    new_content: str,
    session_key: Optional[str] = None,
) -> _MemoryApprovalEntry:
    """Submit a memory proposal and return the entry (caller blocks on entry.event)."""
    entry = _MemoryApprovalEntry(
        session_key=session_key or _get_session_key(),
        action=action,
        target=target,
        old_text=old_text,
        new_content=new_content,
    )
    with _lock:
        _memory_queues.setdefault(entry.session_key, []).append(entry)
    return entry


def has_memory_proposal(session_key: str) -> bool:
    """Return True when this session has a pending memory proposal."""
    with _lock:
        queue = _memory_queues.get(session_key, [])
        return any(e.result is None for e in queue)


def resolve_memory_approval(session_key: str, choice: str) -> int:
    """Unblock the oldest pending memory proposal for this session.

    Returns the number of entries resolved (0 means nothing was pending).
    """
    with _lock:
        queue = _memory_queues.get(session_key, [])
        if not queue:
            return 0
        for entry in queue:
            if entry.result is None:
                entry.result = choice
                entry.event.set()
                return 1
        return 0


def clear_memory_proposal(session_key: str) -> int:
    """Clear all pending memory proposals for a session.

    Called on session-boundary cleanup so blocked agent threads unwind.
    Returns the number of entries cancelled.
    """
    with _lock:
        entries = _memory_queues.pop(session_key, [])
    cancelled = 0
    for entry in entries:
        if entry.result is None:
            entry.result = "deny"
            entry.event.set()
            cancelled += 1
    return cancelled


def wait_for_memory_approval(entry: _MemoryApprovalEntry, timeout: float) -> str:
    """Block on the entry's event until resolved or timeout fires.

    Polls in 1-second slices so the agent's inactivity heartbeat keeps
    firing — without this, ``Event.wait(timeout=600)`` blocks the thread
    for 10 minutes with zero activity touches and the gateway's inactivity
    watchdog kills the agent while the user is still typing.

    Returns the resolved result string ("approve" | "deny"), or "timeout".
    """
    deadline = time.monotonic() + max(timeout, 0.0)
    activity_state = {"last_touch": time.monotonic(), "start": time.monotonic()}

    try:
        from tools.environments.base import touch_activity_if_due
    except Exception:
        touch_activity_if_due = None

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        if entry.event.wait(timeout=min(1.0, remaining)):
            break
        if touch_activity_if_due is not None:
            touch_activity_if_due(activity_state, "waiting for memory approval")

    return entry.result or "timeout"


def register_memory_notify(session_key: str, cb: Callable[[_MemoryApprovalEntry], None]) -> None:
    """Register a per-session callback for sending memory proposals to the user."""
    with _lock:
        _memory_notify_cbs[session_key] = cb


def unregister_memory_notify(session_key: str) -> None:
    """Unregister and cancel all pending memory proposals for a session."""
    with _lock:
        _memory_notify_cbs.pop(session_key, None)
    clear_memory_proposal(session_key)


def _notify(session_key: str, entry: _MemoryApprovalEntry) -> None:
    """Invoke the registered notify callback for a session, if any."""
    with _lock:
        cb = _memory_notify_cbs.get(session_key)
    if cb is None:
        return
    try:
        cb(entry)
    except Exception as exc:
        logger.warning("Memory approval notify failed: %s", exc)


def get_memory_timeout() -> int:
    """Read memory approval timeout from config (falls back to approval timeout)."""
    try:
        from hermes_cli.config import load_config
        cfg = load_config() or {}
        agent_cfg = cfg.get("agent", {}) or {}
        timeout = int(agent_cfg.get("memory_approval_timeout", 0))
        if timeout > 0:
            return timeout
    except Exception:
        pass
    try:
        from tools.approval import _get_approval_timeout
        return _get_approval_timeout()
    except Exception:
        return 600


# ---------------------------------------------------------------------------
# Gateway command helpers
# ---------------------------------------------------------------------------

def handle_approve_command(session_key: str) -> Optional[str]:
    """Resolve the oldest pending memory proposal with ``approve``.

    Returns a user-facing message when a memory proposal was resolved, or
    ``None`` when no memory proposal is pending (caller should fall through
    to dangerous-command approval handling).
    """
    if not has_memory_proposal(session_key):
        return None

    count = resolve_memory_approval(session_key, "approve")
    if not count:
        return None

    logger.info("User approved %d memory proposal(s) via /approve", count)
    return t("gateway.approve.singular", count=count)


def handle_deny_command(session_key: str) -> Optional[str]:
    """Resolve the oldest pending memory proposal with ``deny``.

    Returns a user-facing message when a memory proposal was resolved, or
    ``None`` when no memory proposal is pending (caller should fall through
    to dangerous-command approval handling).
    """
    if not has_memory_proposal(session_key):
        return None

    count = resolve_memory_approval(session_key, "deny")
    if not count:
        return None

    logger.info("User denied %d memory proposal(s) via /deny", count)
    return t("gateway.deny.denied_singular")
