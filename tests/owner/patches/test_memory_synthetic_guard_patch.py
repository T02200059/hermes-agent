"""Tests for owner/patches/memory_synthetic_guard_patch.py.

Asserts behavioral contracts (not snapshots):
  - synthetic-prefixed messages skip recall/sync entirely
  - genuine user messages pass through to the original implementation
  - apply/revert is idempotent and restores exact originals
"""

from __future__ import annotations

import logging

import pytest

import agent.memory_manager as memory_manager
from owner.patches.memory_synthetic_guard_patch import (
    _is_synthetic,
    apply_patch,
    revert_patch,
)


@pytest.fixture(autouse=True)
def _ensure_reverted():
    """Start and end each test with the patch reverted (clean baseline)."""
    revert_patch()
    yield
    revert_patch()


# ---------------------------------------------------------------------------
# Fake MemoryManager + provider -- exercises the real patched methods
# without touching network or real provider backends.
# ---------------------------------------------------------------------------

class _RecordingProvider:
    """Minimal provider that records every call made to it.

    Carries a ``name`` so ``MemoryManager.add_provider`` accepts it as a
    non-builtin external provider (it reads ``provider.name``).
    """

    name = "test-recording"

    def __init__(self) -> None:
        self.prefetch_calls: list[str] = []
        self.queue_prefetch_calls: list[str] = []
        self.sync_calls: list[tuple] = []
        self.on_turn_start_calls: list[tuple] = []

    def prefetch(self, query, *, session_id=""):
        self.prefetch_calls.append(query)
        return f"[recalled:{query}]"

    def queue_prefetch(self, query, *, session_id=""):
        self.queue_prefetch_calls.append(query)

    def sync_turn(self, user, asst, *, session_id="", **kw):
        self.sync_calls.append((user, asst))

    def on_turn_start(self, turn_number, message, **kwargs):
        self.on_turn_start_calls.append((turn_number, message))

    def get_tool_schemas(self):
        # MemoryManager.add_provider indexes tool schemas; none needed here.
        return []


def _make_manager() -> memory_manager.MemoryManager:
    """Build a real MemoryManager with one recording provider attached."""
    mgr = memory_manager.MemoryManager()
    mgr.add_provider(_RecordingProvider())
    return mgr


# ---------------------------------------------------------------------------
# Synthetic-prefix detection
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "[ASYNC DELEGATION COMPLETE — abc-123]",
    "[ASYNC DELEGATION BATCH COMPLETE — xyz]",
    "[IMPORTANT: Background process sess-1 completed normally (exit code 0).]",
    "[IMPORTANT: Background process s matched watch pattern \"err\".\n...",
    "[Session was just handed off from CLI (\"title\") to this channel.",
])
def test_is_synthetic_detects_all_known_prefixes(text):
    assert _is_synthetic(text) is True


def test_is_synthetic_tolerates_leading_whitespace():
    assert _is_synthetic("  \n [ASYNC DELEGATION COMPLETE — id]") is True


@pytest.mark.parametrize("text", [
    "",
    None,
    12345,
    "What's the weather today?",
    "[ASYNC DELEGATION COMPLETE]",          # missing the " — " separator
    "[IMPORTANT: something else entirely]",  # not a background-process notice
    " [ IMPORTANT: Background process x",   # space inside the bracket
])
def test_is_synthetic_rejects_non_synthetic(text):
    assert _is_synthetic(text) is False


# ---------------------------------------------------------------------------
# prefetch_all -- the primary recall entry point
# ---------------------------------------------------------------------------

def test_prefetch_all_skips_synthetic_query():
    apply_patch()
    mgr = _make_manager()
    result = mgr.prefetch_all("[ASYNC DELEGATION COMPLETE — id]")
    assert result == ""
    # Provider was never consulted -- no wasted recall round-trip.
    assert mgr._providers[0].prefetch_calls == []


def test_prefetch_all_passes_through_genuine_query():
    apply_patch()
    mgr = _make_manager()
    result = mgr.prefetch_all("How do I deploy the service?")
    assert result == "[recalled:How do I deploy the service?]"
    assert mgr._providers[0].prefetch_calls == ["How do I deploy the service?"]


# ---------------------------------------------------------------------------
# queue_prefetch_all -- next-turn warmup
# ---------------------------------------------------------------------------

def test_queue_prefetch_all_skips_synthetic():
    apply_patch()
    mgr = _make_manager()
    mgr.queue_prefetch_all("[IMPORTANT: Background process s exited]")
    assert mgr._providers[0].queue_prefetch_calls == []


def test_queue_prefetch_all_passes_through_genuine():
    apply_patch()
    mgr = _make_manager()
    mgr.queue_prefetch_all("continue the refactor")
    assert mgr._providers[0].queue_prefetch_calls == ["continue the refactor"]


# ---------------------------------------------------------------------------
# on_turn_start -- turn notification
# ---------------------------------------------------------------------------

def test_on_turn_start_skips_synthetic():
    apply_patch()
    mgr = _make_manager()
    mgr.on_turn_start(3, "[Session was just handed off from CLI")
    assert mgr._providers[0].on_turn_start_calls == []


def test_on_turn_start_passes_through_genuine():
    apply_patch()
    mgr = _make_manager()
    mgr.on_turn_start(3, "hello there", platform="cli")
    assert mgr._providers[0].on_turn_start_calls == [(3, "hello there")]


# ---------------------------------------------------------------------------
# sync_all -- write/mirror guard
# ---------------------------------------------------------------------------

def test_sync_all_skips_synthetic_user_content():
    apply_patch()
    mgr = _make_manager()
    mgr.sync_all(
        "[ASYNC DELEGATION BATCH COMPLETE — id]",
        "ok, noted the results",
        session_id="s1",
    )
    assert mgr._providers[0].sync_calls == []


def test_sync_all_passes_through_genuine():
    apply_patch()
    mgr = _make_manager()
    mgr.sync_all("what is 2+2", "4", session_id="s1", messages=[{"role": "user"}])
    assert mgr._providers[0].sync_calls == [("what is 2+2", "4")]


# ---------------------------------------------------------------------------
# apply / revert idempotency and restoration
# ---------------------------------------------------------------------------

def test_apply_is_idempotent():
    apply_patch()
    apply_patch()  # second call must be a no-op
    assert memory_manager.MemoryManager.prefetch_all.__name__ == "_prefetch_all"


def test_revert_restores_originals():
    orig_prefetch = memory_manager.MemoryManager.prefetch_all
    orig_queue = memory_manager.MemoryManager.queue_prefetch_all
    orig_turn = memory_manager.MemoryManager.on_turn_start
    orig_sync = memory_manager.MemoryManager.sync_all

    apply_patch()
    assert memory_manager.MemoryManager.prefetch_all is not orig_prefetch

    revert_patch()
    assert memory_manager.MemoryManager.prefetch_all is orig_prefetch
    assert memory_manager.MemoryManager.queue_prefetch_all is orig_queue
    assert memory_manager.MemoryManager.on_turn_start is orig_turn
    assert memory_manager.MemoryManager.sync_all is orig_sync


def test_revert_is_safe_when_never_applied():
    # Should not raise even if patch was never applied.
    revert_patch()
    revert_patch()


def test_genuine_message_works_without_patch_applied():
    """Baseline: with the patch OFF, everything passes through (no regression)."""
    mgr = _make_manager()
    mgr.prefetch_all("hello")
    assert mgr._providers[0].prefetch_calls == ["hello"]
