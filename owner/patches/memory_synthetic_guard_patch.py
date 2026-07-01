"""[owner] Guard: skip memory recall/sync for synthetic system messages.

Background-process completions, async-delegation results, watch-pattern
matches, and CLI->gateway handoffs re-enter the conversation as synthetic
messages (text beginning with well-known protocol prefixes). They are NOT
genuine user input, so they must not:

  - trigger ``prefetch_all`` (recall) -- a query keyed on
    ``[ASYNC DELEGATION COMPLETE -- ...]`` pollutes recall relevance and
    wastes a provider round-trip;
  - be mirrored into external memory stores via ``sync_all`` /
    ``queue_prefetch_all`` -- the synthetic block is not durable
    conversational truth the user authored;
  - be reported to providers as a new user turn via ``on_turn_start``.

Implemented as a runtime patch on ``MemoryManager`` methods, mirroring the
``openviking_sync_recall_patch`` pattern: ``apply_patch`` / ``revert_patch``
pair, ``_originals`` dict preserves the un-patched implementations. No
official source file is modified.

The guard is a pure prefix check against stable, protocol-level markers
emitted by ``tools/process_registry.py::format_process_notification`` and
``gateway/run.py::_process_handoff``. These markers are intentional system
notifications (the formatter comments call them "self-contained
re-injection" / "system-generated"), so they are far more stable than
skill-scaffolding detection, which already relies on a similar prefix
contract (``_strip_skill_scaffolding``).

See ``owner/docs/memory-synthetic-recall-guard.md`` for the full design.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

import agent.memory_manager as _mm

logger = logging.getLogger(__name__)

# Patch state.
_originals: Dict[str, Any] = {}
_applied: bool = False

# Protocol-level prefixes that mark a message as system-generated (not real
# user input). All formatters live in:
#   - tools/process_registry.py::format_process_notification
#     (async delegation, bg process completion, watch match)
#   - gateway/run.py::_process_handoff  (CLI->gateway handoff notice)
# These are stable, intentional markers -- if a new synthetic re-injection
# type is added, append its prefix here.
_SYNTHETIC_PREFIXES = (
    "[ASYNC DELEGATION BATCH COMPLETE — ",
    "[ASYNC DELEGATION COMPLETE — ",
    "[IMPORTANT: Background process ",
    "[Session was just handed off from CLI",
)


def _is_synthetic(query: Any) -> bool:
    """Return True if ``query`` is a known synthetic system message.

    Tolerates leading whitespace (some injection paths may prepend a
    newline/space). Non-string or empty input is treated as non-synthetic
    so the original methods' own handling (empty -> skip) still applies.
    """
    if not isinstance(query, str) or not query:
        return False
    return query.lstrip().startswith(_SYNTHETIC_PREFIXES)


# ---------------------------------------------------------------------------
# Replacement implementations -- guard then delegate to the original.
# ---------------------------------------------------------------------------

def _prefetch_all(self, query: str, *, session_id: str = "") -> str:
    """Recall guard: skip prefetch for synthetic system messages."""
    if _is_synthetic(query):
        logger.debug(
            "memory_synthetic_guard: skipped prefetch_all (synthetic msg, "
            "prefix=%.40s)",
            query[:40],
        )
        return ""
    return _originals["prefetch_all"](self, query, session_id=session_id)


def _queue_prefetch_all(self, query: str, *, session_id: str = "") -> None:
    """Next-turn warmup guard: skip for synthetic system messages."""
    if _is_synthetic(query):
        logger.debug(
            "memory_synthetic_guard: skipped queue_prefetch_all (synthetic)"
        )
        return
    _originals["queue_prefetch_all"](self, query, session_id=session_id)


def _on_turn_start(self, turn_number: int, message: str, **kwargs) -> None:
    """Turn-start notification guard: synthetic messages are not real turns."""
    if _is_synthetic(message):
        logger.debug(
            "memory_synthetic_guard: skipped on_turn_start (synthetic msg)"
        )
        return
    _originals["on_turn_start"](self, turn_number, message, **kwargs)


def _sync_all(
    self,
    user_content: str,
    assistant_content: str,
    *,
    session_id: str = "",
    **kwargs,
) -> None:
    """Write guard: do not mirror synthetic messages into memory stores."""
    if _is_synthetic(user_content):
        logger.debug(
            "memory_synthetic_guard: skipped sync_all (synthetic user msg)"
        )
        return
    _originals["sync_all"](
        self,
        user_content,
        assistant_content,
        session_id=session_id,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Patch registration -- idempotent apply / revert.
# ---------------------------------------------------------------------------

def apply_patch() -> None:
    """Patch ``MemoryManager`` recall/sync methods with the synthetic guard.

    Idempotent: repeated calls are no-ops once applied. ``revert_patch``
    restores the originals exactly.
    """
    global _applied
    if _applied:
        return
    _originals["prefetch_all"] = _mm.MemoryManager.prefetch_all
    _originals["queue_prefetch_all"] = _mm.MemoryManager.queue_prefetch_all
    _originals["on_turn_start"] = _mm.MemoryManager.on_turn_start
    _originals["sync_all"] = _mm.MemoryManager.sync_all
    _mm.MemoryManager.prefetch_all = _prefetch_all
    _mm.MemoryManager.queue_prefetch_all = _queue_prefetch_all
    _mm.MemoryManager.on_turn_start = _on_turn_start
    _mm.MemoryManager.sync_all = _sync_all
    _applied = True
    logger.info("memory_synthetic_guard_patch applied")


def revert_patch() -> None:
    """Restore the original ``MemoryManager`` methods.

    Idempotent: safe to call even if the patch was never applied.
    """
    global _applied
    for _name in (
        "prefetch_all",
        "queue_prefetch_all",
        "on_turn_start",
        "sync_all",
    ):
        _orig = _originals.pop(_name, None)
        if _orig is not None:
            setattr(_mm.MemoryManager, _name, _orig)
    _applied = False
    logger.info("memory_synthetic_guard_patch reverted")
