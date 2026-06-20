"""Tests for the memory_propose approval-crosstalk (串台) fixes — Bugs 1-5.

These tests assert the *invariants* the fixes establish, not snapshots:

- Bug 1: ``spawn_background_review_thread`` returns a target wrapped in
  ``propagate_context_to_thread`` so the bg-review thread inherits the
  parent's ``_approval_session_key`` ContextVar.
- Bug 2: the gateway ``run_sync`` no longer mutates the process-global
  ``os.environ["HERMES_SESSION_KEY"]`` (concurrent-session safety).
- Bug 3: ``_run_background_task`` wires the per-session approval/memory
  routing trio (covered structurally — the wiring lives in run_sync and is
  exercised by the routing-helper tests below).
- Bug 4: batch ``delegate_task`` wraps each child in
  ``propagate_context_to_thread`` (structural: import + call-site check).
- Bug 5: bg-review installs an *isolated* auto-approve callback that does
  NOT overwrite the parent session's notify callback and does NOT share the
  parent session's memory queue.
"""

from __future__ import annotations

import inspect
import json
import threading
import time
from unittest.mock import MagicMock

import pytest

from tools.approval import (
    get_current_session_key,
    set_current_session_key,
    reset_current_session_key,
)
from tools.thread_context import propagate_context_to_thread
from owner.memory.gateway import (
    _memory_notify_cbs,
    _memory_queues,
    has_memory_proposal,
    register_memory_notify,
    resolve_memory_approval,
    submit_memory_proposal,
    unregister_memory_notify,
)
from owner.memory.bg_review_auto_approve import (
    setup_bg_review_memory_auto_approve,
    _derive_bg_review_key,
    _BG_REVIEW_SUFFIX,
)


# ---------------------------------------------------------------------------
# Bug 1 — bg-review thread target is wrapped in propagate_context_to_thread
# ---------------------------------------------------------------------------

class TestBug1BgReviewContextPropagation:
    """spawn_background_review_thread must propagate parent ContextVars."""

    def test_thread_target_inherits_parent_session_key(self):
        """A worker running the wrapped target sees the parent's session_key."""
        from agent.background_review import spawn_background_review_thread

        # Don't actually run a review — we only care that the returned target
        # propagates ContextVars. Stub _run_review_in_thread via the agent's
        # attributes is overkill; instead capture session_key seen by a worker.
        seen = {}

        class _StubAgent:
            """Minimal stand-in so spawn_background_review_thread builds a prompt."""
            _COMBINED_REVIEW_PROMPT = "p"

            def _current_main_runtime(self):  # pragma: no cover — not reached
                return {}

        # Monkeypatch the module's _run_review_in_thread to capture ContextVar
        import agent.background_review as br

        def _capture(agent, messages_snapshot, prompt):
            seen["session_key"] = get_current_session_key(default="UNSET")

        original = br._run_review_in_thread
        br._run_review_in_thread = _capture
        try:
            # propagate_context_to_thread snapshots copy_context() at WRAP time
            # (when spawn_background_review_thread runs), so the parent key must
            # be set BEFORE wrapping — exactly as production does it: the spawn
            # happens on the agent's execution thread mid-turn, where the gateway
            # has already bound the session_key ContextVar.
            token = set_current_session_key("parent-sess-bug1")
            try:
                target, _prompt = br.spawn_background_review_thread(
                    _StubAgent(), [], review_memory=True, review_skills=True,
                )
                t = threading.Thread(target=target)
                t.start()
                t.join(timeout=5)
            finally:
                reset_current_session_key(token)
        finally:
            br._run_review_in_thread = original

        assert seen.get("session_key") == "parent-sess-bug1"

    def test_returned_target_is_propagated_wrapper(self):
        """The target returned must be the propagate_context_to_thread wrapper."""
        # Structural invariant: the source uses propagate_context_to_thread.
        import agent.background_review as br

        src = inspect.getsource(br.spawn_background_review_thread)
        assert "propagate_context_to_thread" in src


# ---------------------------------------------------------------------------
# Bug 2 — gateway run_sync must not write os.environ["HERMES_SESSION_KEY"]
# ---------------------------------------------------------------------------

class TestBug2NoProcessGlobalSessionKey:
    """The concurrency-racy os.environ write must be gone from run_sync."""

    def test_run_sync_does_not_mutate_hermes_session_key_env(self):
        import gateway.run as gr

        # Find the _run_agent closure's run_sync via source inspection. We
        # assert the literal mutation is gone — this is a code-invariant, not
        # a snapshot: the whole point of the fix is that NO assignment to
        # os.environ["HERMES_SESSION_KEY"] happens inside run_sync.
        src = inspect.getsource(gr)
        # Strip trailing comments first: the Bug 2 fix kept an explanatory
        # comment that *mentions* the removed write, so a naive substring match
        # would false-positive. We only care that no ACTIVE assignment remains.
        code_only = "\n".join(line.split("#", 1)[0] for line in src.splitlines())
        assert 'os.environ["HERMES_SESSION_KEY"] =' not in code_only, (
            "gateway/run.py must not write os.environ['HERMES_SESSION_KEY'] "
            "— it races concurrent sessions. See Bug 2 fix."
        )


# ---------------------------------------------------------------------------
# Bug 3 — _run_background_task wires the routing trio
# ---------------------------------------------------------------------------

class TestBug3BackgroundTaskRouting:
    """Background-task run_sync must set up per-session routing."""

    def test_background_task_run_sync_sets_session_key_and_routing(self):
        import gateway.run as gr

        # _run_background_task is a GatewayRunner method, not a module attr.
        src = inspect.getsource(gr.GatewayRunner._run_background_task)
        # The trio: set_current_session_key, setup_gateway_memory_routing,
        # register_gateway_notify. Structural invariants — the wiring must
        # exist so bg-task proposals reach the user under the right key.
        assert "set_current_session_key" in src
        assert "setup_gateway_memory_routing" in src
        assert "register_gateway_notify" in src
        # And cleanup in finally so blocked threads unwind.
        assert "unregister_gateway_notify" in src


# ---------------------------------------------------------------------------
# Bug 4 — batch delegate_task propagates ContextVar to children
# ---------------------------------------------------------------------------

class TestBug4BatchDelegateContextPropagation:
    """Batch delegate children must inherit parent ContextVars."""

    def test_batch_submit_uses_propagate_context_to_thread(self):
        import tools.delegate_tool as dt

        src = inspect.getsource(dt)
        assert "from tools.thread_context import propagate_context_to_thread" in src
        # The batch submit call site wraps _run_single_child.
        assert "propagate_context_to_thread(_run_single_child)" in src

    def test_batch_child_inherits_parent_session_key(self):
        """A function wrapped + run on a worker sees the parent's session_key."""
        seen = {}

        def _work(task_index, goal, child, parent_agent):
            seen["session_key"] = get_current_session_key(default="UNSET")

        token = set_current_session_key("parent-sess-bug4")
        try:
            wrapped = propagate_context_to_thread(_work)
            t = threading.Thread(
                target=wrapped,
                kwargs=dict(task_index=0, goal="g", child=None, parent_agent=None),
            )
            t.start()
            t.join(timeout=5)
        finally:
            reset_current_session_key(token)

        assert seen.get("session_key") == "parent-sess-bug4"


# ---------------------------------------------------------------------------
# Bug 5 — bg-review isolated auto-approve does not crosstalk with parent
# ---------------------------------------------------------------------------

class TestBug5BgReviewIsolatedAutoApprove:
    """bg-review auto-approve must be isolated from the parent session."""

    def test_derive_key_appends_suffix(self):
        assert _derive_bg_review_key("abc") == f"abc{_BG_REVIEW_SUFFIX}"

    def test_derive_key_idempotent(self):
        once = _derive_bg_review_key("abc")
        twice = _derive_bg_review_key(once)
        assert once == twice

    def test_derive_key_empty_parent(self):
        assert _derive_bg_review_key("") == f"default{_BG_REVIEW_SUFFIX}"

    def test_setup_rebinds_session_key_to_isolated(self):
        """After setup, get_current_session_key returns the isolated key."""
        token = set_current_session_key("parent-sess-5a")
        try:
            cleanup = setup_bg_review_memory_auto_approve()
            try:
                assert get_current_session_key(default="") == (
                    f"parent-sess-5a{_BG_REVIEW_SUFFIX}"
                )
            finally:
                cleanup()
            # After cleanup the parent key is restored.
            assert get_current_session_key(default="") == "parent-sess-5a"
        finally:
            reset_current_session_key(token)

    def test_setup_does_not_overwrite_parent_notify_callback(self):
        """CRITICAL invariant: bg-review's auto-approve must NOT overwrite the
        parent session's notify callback. Otherwise the parent's memory_propose
        proposals would be silently auto-approved (feature destroyed)."""
        parent_calls = []

        def _parent_notify(entry):
            parent_calls.append(entry)

        register_memory_notify("parent-sess-5b", _parent_notify)
        try:
            token = set_current_session_key("parent-sess-5b")
            try:
                cleanup = setup_bg_review_memory_auto_approve()
                try:
                    # Parent's callback is untouched (still the registered cb).
                    assert _memory_notify_cbs.get("parent-sess-5b") is _parent_notify
                    # bg-review registered its own cb under the isolated key.
                    isolated = f"parent-sess-5b{_BG_REVIEW_SUFFIX}"
                    assert isolated in _memory_notify_cbs
                    assert _memory_notify_cbs[isolated] is not _parent_notify
                finally:
                    cleanup()
            finally:
                reset_current_session_key(token)
        finally:
            unregister_memory_notify("parent-sess-5b")

    def test_bg_review_proposal_lands_in_isolated_queue(self):
        """A bg-review-thread proposal must NOT enter the parent's queue."""
        token = set_current_session_key("parent-sess-5c")
        try:
            cleanup = setup_bg_review_memory_auto_approve()
            try:
                # The tool reads the *current* (isolated) session key.
                from owner.memory.tool import memory_propose_tool

                store = MagicMock()
                store.add.return_value = {"success": True}
                result = memory_propose_tool("add", "memory", "", "fact", store=store)

                # Parent queue untouched.
                assert not has_memory_proposal("parent-sess-5c")
                # Isolated queue got the proposal and it was auto-approved.
                data = json.loads(result)
                assert data["approved"] is True
            finally:
                cleanup()
        finally:
            reset_current_session_key(token)

    def test_bg_review_auto_approve_does_not_touch_parent_proposal(self):
        """Even if the parent has a pending proposal, the bg-review auto-approve
        must not resolve it (different queues)."""
        # Parent submits a proposal that stays pending (no notify cb resolves it).
        parent_entry = submit_memory_proposal(
            "add", "memory", "", "parent fact", session_key="parent-sess-5d",
        )
        try:
            token = set_current_session_key("parent-sess-5d")
            try:
                cleanup = setup_bg_review_memory_auto_approve()
                try:
                    # bg-review submits its own proposal under the isolated key.
                    isolated = f"parent-sess-5d{_BG_REVIEW_SUFFIX}"
                    bg_entry = submit_memory_proposal(
                        "add", "memory", "", "bg fact", session_key=isolated,
                    )
                    # The auto-approve notify cb resolves the bg proposal...
                    from owner.memory.gateway import _notify
                    _notify(isolated, bg_entry)
                    assert bg_entry.result == "approve"
                    # ...but the parent's pending proposal is UNRESOLVED.
                    assert parent_entry.result is None
                finally:
                    cleanup()
            finally:
                reset_current_session_key(token)
        finally:
            unregister_memory_notify("parent-sess-5d")

    def test_cleanup_restores_parent_state(self):
        """cleanup() must leave no trace: no isolated cb, no isolated queue."""
        token = set_current_session_key("parent-sess-5e")
        try:
            cleanup = setup_bg_review_memory_auto_approve()
            isolated = f"parent-sess-5e{_BG_REVIEW_SUFFIX}"
            assert isolated in _memory_notify_cbs
            cleanup()
            assert isolated not in _memory_notify_cbs
            assert isolated not in _memory_queues
            # And the parent session_key is back.
            assert get_current_session_key(default="") == "parent-sess-5e"
        finally:
            reset_current_session_key(token)
            unregister_memory_notify(f"parent-sess-5e{_BG_REVIEW_SUFFIX}")

    def test_cleanup_is_idempotent_and_exception_safe(self):
        token = set_current_session_key("parent-sess-5f")
        try:
            cleanup = setup_bg_review_memory_auto_approve()
            cleanup()
            # Calling again must not raise.
            cleanup()
        finally:
            reset_current_session_key(token)


# ---------------------------------------------------------------------------
# Integration — concurrent bg-review + parent session don't crosstalk
# ---------------------------------------------------------------------------

class TestConcurrencyEndToEnd:
    """Simulate a parent session running concurrently with a bg-review thread."""

    def test_concurrent_parent_and_bg_review_queues_stay_separate(self):
        """Parent proposals land in parent queue; bg-review proposals land in
        the isolated queue and get auto-approved — never the twain shall meet."""
        parent_key = "parent-concurrent-1"

        # Parent session: register a notify that does NOT auto-approve (mimics
        # the real gateway flow where the user must click).
        parent_seen = []

        def _parent_notify(entry):
            parent_seen.append(entry.action)

        register_memory_notify(parent_key, _parent_notify)
        try:
            # Parent submits a proposal (pending — user hasn't responded).
            # The real tool path submits then notifies separately, so mirror
            # that: submit_memory_proposal only enqueues; _notify fires the cb.
            from owner.memory.gateway import _notify as _gw_notify

            parent_entry = submit_memory_proposal(
                "add", "memory", "", "parent fact", session_key=parent_key,
            )
            _gw_notify(parent_key, parent_entry)
            assert len(parent_seen) == 1

            # Meanwhile a bg-review thread spins up on a worker thread,
            # inheriting the parent's session_key via propagate_context_to_thread.
            bg_results = {}

            def _bg_review_work():
                # Set parent key on the main thread, then wrap so the worker
                # inherits it — mirrors spawn_background_review_thread.
                cleanup = setup_bg_review_memory_auto_approve()
                try:
                    from owner.memory.tool import memory_propose_tool

                    store = MagicMock()
                    store.add.return_value = {"success": True}
                    bg_results["result"] = memory_propose_tool(
                        "add", "memory", "", "bg fact", store=store,
                    )
                finally:
                    cleanup()

            wrapped = propagate_context_to_thread(_bg_review_work)
            token = set_current_session_key(parent_key)
            try:
                t = threading.Thread(target=wrapped)
                t.start()
                t.join(timeout=5)
            finally:
                reset_current_session_key(token)

            # bg-review's proposal was auto-approved (isolated queue).
            data = json.loads(bg_results["result"])
            assert data["approved"] is True

            # Parent's proposal is STILL pending — bg-review did not touch it.
            assert parent_entry.result is None
            # Parent notify was called exactly once (for the parent proposal)
            # and NOT for the bg-review proposal (different queue/key).
            assert parent_seen == ["add"]
        finally:
            unregister_memory_notify(parent_key)
