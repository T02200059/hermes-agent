"""Tests for owner.memory proposal approval queue, tool, and Feishu cards."""

import json
import threading
import time
from unittest.mock import MagicMock

import pytest

from owner.memory.gateway import (
    clear_memory_proposal,
    handle_approve_command,
    handle_deny_command,
    has_memory_proposal,
    register_memory_notify,
    resolve_memory_approval,
    submit_memory_proposal,
    unregister_memory_notify,
    wait_for_memory_approval,
)
from owner.memory.schema import MEMORY_PROPOSE_SCHEMA
from owner.memory.tool import memory_propose_tool


class TestMemoryGateway:
    def test_submit_and_resolve_approve(self):
        entry = submit_memory_proposal("add", "memory", "", "new fact", session_key="sess-1")
        assert has_memory_proposal("sess-1") is True
        assert resolve_memory_approval("sess-1", "approve") == 1
        assert entry.result == "approve"
        assert has_memory_proposal("sess-1") is False

    def test_resolve_fifo_order(self):
        e1 = submit_memory_proposal("add", "memory", "", "first", session_key="sess-2")
        e2 = submit_memory_proposal("add", "memory", "", "second", session_key="sess-2")
        assert resolve_memory_approval("sess-2", "approve") == 1
        assert e1.result == "approve"
        assert e2.result is None

    def test_resolve_no_pending_returns_zero(self):
        assert resolve_memory_approval("no-such-session", "approve") == 0

    def test_clear_memory_proposal(self):
        entry = submit_memory_proposal("add", "memory", "", "x", session_key="sess-3")
        assert clear_memory_proposal("sess-3") == 1
        assert entry.result == "deny"
        assert entry.event.is_set()

    def test_wait_for_memory_approval_timeout(self):
        entry = submit_memory_proposal("add", "memory", "", "x", session_key="sess-4")
        result = wait_for_memory_approval(entry, timeout=0.05)
        assert result == "timeout"

    def test_wait_for_memory_approval_resolved(self):
        entry = submit_memory_proposal("add", "memory", "", "x", session_key="sess-5")

        def _resolve():
            time.sleep(0.05)
            resolve_memory_approval("sess-5", "approve")

        t = threading.Thread(target=_resolve)
        t.start()
        result = wait_for_memory_approval(entry, timeout=2.0)
        t.join()
        assert result == "approve"

    def test_notify_callback(self):
        """Verify unregister_memory_notify cleans up pending proposals."""
        entry = submit_memory_proposal("add", "memory", "", "x", session_key="sess-6")
        unregister_memory_notify("sess-6")
        assert entry.result == "deny"

    def test_handle_approve_command(self):
        submit_memory_proposal("add", "memory", "", "x", session_key="sess-7")
        msg = handle_approve_command("sess-7")
        assert msg is not None
        assert has_memory_proposal("sess-7") is False

    def test_handle_deny_command(self):
        submit_memory_proposal("add", "memory", "", "x", session_key="sess-8")
        msg = handle_deny_command("sess-8")
        assert msg is not None
        assert has_memory_proposal("sess-8") is False

    def test_handle_commands_no_pending(self):
        assert handle_approve_command("no-sess") is None
        assert handle_deny_command("no-sess") is None

    def test_notify_callback_invoked_by_tool(self):
        """Verify notify callback fires when memory_propose_tool submits a proposal."""
        calls = []
        store = MagicMock()
        store.add.return_value = {"success": True}

        def _cb(entry):
            calls.append(entry)
            resolve_memory_approval(entry.session_key, "approve")

        register_memory_notify("default", _cb)
        try:
            result = memory_propose_tool("add", "memory", "", "fact", store=store)
        finally:
            unregister_memory_notify("default")

        assert len(calls) == 1
        assert calls[0].action == "add"
        assert calls[0].target == "memory"
        data = json.loads(result)
        assert data["approved"] is True


class TestMemoryProposeTool:
    def test_schema(self):
        assert MEMORY_PROPOSE_SCHEMA["name"] == "memory_propose"
        params = MEMORY_PROPOSE_SCHEMA["parameters"]["properties"]
        # Dual shape: single-op fields + operations array. required is only
        # target so either shape can be selected by the model.
        assert set(params.keys()) == {"action", "target", "old_text", "new_content", "operations"}
        assert MEMORY_PROPOSE_SCHEMA["parameters"]["required"] == ["target"]
        op_item = params["operations"]["items"]
        assert set(op_item["properties"].keys()) == {"action", "content", "old_text"}
        assert op_item["required"] == ["action"]

    def test_invalid_action(self):
        result = memory_propose_tool("bad_action", "memory", "", "x")
        data = json.loads(result)
        assert data["approved"] is False
        assert data["reason"] == "invalid_action"

    def test_invalid_target(self):
        result = memory_propose_tool("add", "bad_target", "", "x")
        data = json.loads(result)
        assert data["approved"] is False
        assert data["reason"] == "invalid_target"

    def test_no_store_after_approve(self):
        def _auto_approve(entry):
            resolve_memory_approval(entry.session_key, "approve")

        register_memory_notify("default", _auto_approve)
        try:
            result = memory_propose_tool("add", "memory", "", "fact")
        finally:
            unregister_memory_notify("default")
        data = json.loads(result)
        assert data["approved"] is False
        assert data["reason"] == "no_store"

    def test_approved_write(self):
        store = MagicMock()
        store.add.return_value = {"success": True}

        def _auto_approve(entry):
            resolve_memory_approval(entry.session_key, "approve")

        register_memory_notify("default", _auto_approve)
        try:
            result = memory_propose_tool("add", "memory", "", "fact", store=store)
        finally:
            unregister_memory_notify("default")
        data = json.loads(result)
        assert data["approved"] is True
        store.add.assert_called_once_with("memory", "fact")

    def test_denied(self):
        def _auto_deny(entry):
            resolve_memory_approval(entry.session_key, "deny")

        register_memory_notify("default", _auto_deny)
        try:
            result = memory_propose_tool("add", "memory", "", "x", store=MagicMock())
        finally:
            unregister_memory_notify("default")
        data = json.loads(result)
        assert data["approved"] is False
        assert data["reason"] == "denied_by_user"

    def test_replace_write(self):
        store = MagicMock()
        store.replace.return_value = {"success": True}

        def _auto_approve(entry):
            resolve_memory_approval(entry.session_key, "approve")

        register_memory_notify("default", _auto_approve)
        try:
            result = memory_propose_tool("replace", "user", "old", "new", store=store)
        finally:
            unregister_memory_notify("default")
        data = json.loads(result)
        assert data["approved"] is True
        store.replace.assert_called_once_with("user", "old", "new")


class TestMemoryProposalFeishuCard:
    """Tests for the Feishu interactive card building functions."""

    @pytest.fixture(autouse=True)
    def _zh_locale(self, monkeypatch):
        monkeypatch.setenv("HERMES_LANGUAGE", "zh")

    def test_resolve_button_approve(self):
        from owner.feishu.memory_proposal import resolve_memory_proposal_button
        assert resolve_memory_proposal_button({"hermes_action": "memory_approve"}) == "approve"

    def test_resolve_button_deny(self):
        from owner.feishu.memory_proposal import resolve_memory_proposal_button
        assert resolve_memory_proposal_button({"hermes_action": "memory_deny"}) == "deny"

    def test_resolve_button_unknown(self):
        from owner.feishu.memory_proposal import resolve_memory_proposal_button
        assert resolve_memory_proposal_button({"hermes_action": "other"}) is None
        assert resolve_memory_proposal_button({}) is None
        assert resolve_memory_proposal_button([]) is None  # type: ignore[arg-type]  # non-dict input

    def test_build_card_has_required_structure(self):
        from owner.feishu.memory_proposal import build_memory_proposal_card
        card = build_memory_proposal_card(
            action="add", target="memory", old_text="", new_content="test",
            session_key="sess-card-1",
        )
        assert card["config"]["wide_screen_mode"] is True
        assert "header" in card
        assert card["header"]["template"] == "purple"
        elements = card["elements"]
        assert len(elements) == 2
        actions = elements[1]["actions"]
        assert len(actions) == 2
        assert actions[0]["value"]["hermes_action"] == "memory_approve"
        assert actions[1]["value"]["hermes_action"] == "memory_deny"
        assert actions[0]["value"]["session_key"] == "sess-card-1"

    def test_build_card_render_content(self):
        from owner.feishu.memory_proposal import build_memory_proposal_card
        card = build_memory_proposal_card(
            action="replace", target="user", old_text="old entry",
            new_content="new entry", session_key="sess-card-2",
        )
        markdown = card["elements"][0]["content"]
        assert "old entry" in markdown
        assert "new entry" in markdown

    def test_build_resolved_card_approved(self):
        from owner.feishu.memory_proposal import build_resolved_memory_proposal_card
        card = build_resolved_memory_proposal_card(choice="approve")
        assert card["header"]["template"] == "green"
        assert "批准" in card["header"]["title"]["content"]

    def test_build_resolved_card_denied(self):
        from owner.feishu.memory_proposal import build_resolved_memory_proposal_card
        card = build_resolved_memory_proposal_card(choice="deny")
        assert card["header"]["template"] == "red"
        assert "拒绝" in card["header"]["title"]["content"]

    def test_action_label(self):
        from owner.feishu.memory_proposal import _action_label
        assert _action_label("add") == "添加"
        assert _action_label("replace") == "替换"
        assert _action_label("remove") == "删除"
        assert _action_label("unknown") == "unknown"

    def test_build_memory_proposal_card_batch(self):
        """Batch card: title shows op count + body lists every op."""
        from owner.feishu.memory_proposal import build_memory_proposal_card
        operations = [
            {"action": "add", "content": "a" * 100},
            {"action": "remove", "old_text": "old entry text"},
            {"action": "replace", "old_text": "x", "content": "y"},
        ]
        card = build_memory_proposal_card(
            target="memory", operations=operations, session_key="sess-batch-1",
        )
        # Batch title carries the count.
        title = card["header"]["title"]["content"]
        assert "批量" in title
        assert "3" in title

        # Markdown body lists each op with its index.
        markdown = card["elements"][0]["content"]
        assert "(1/3)" in markdown
        assert "(2/3)" in markdown
        assert "(3/3)" in markdown
        # add op preview is the content (truncated + ellipsis).
        assert "a" in markdown
        assert "…" in markdown
        # remove op shows old_text.
        assert "old entry text" in markdown
        # replace op shows old → new.
        assert "x" in markdown and "y" in markdown

        # Approve/deny buttons still present, bound to the session.
        actions = card["elements"][1]["actions"]
        assert actions[0]["value"]["session_key"] == "sess-batch-1"
        assert actions[1]["value"]["session_key"] == "sess-batch-1"

    def test_build_memory_proposal_card_single_backward_compat(self):
        """Legacy 4-field call (no operations) still renders the single-op card."""
        from owner.feishu.memory_proposal import build_memory_proposal_card
        card = build_memory_proposal_card(
            action="add", target="memory", old_text="", new_content="single op",
            session_key="sess-single-1",
        )
        # Single-op title has no batch suffix.
        title = card["header"]["title"]["content"]
        assert "批量" not in title
        assert title == "💾 Memory 提案确认"

        # Markdown body keeps the legacy single-op structure.
        markdown = card["elements"][0]["content"]
        assert "single op" in markdown
        assert "**目标**" in markdown
        assert "**操作**" in markdown

    def test_build_memory_proposal_card_batch_collapse(self):
        """Past the collapse threshold, only the first 3 ops are shown + footer."""
        from owner.feishu.memory_proposal import build_memory_proposal_card
        operations = [{"action": "add", "content": f"op-{i}"} for i in range(7)]
        card = build_memory_proposal_card(
            target="memory", operations=operations, session_key="sess-batch-big",
        )
        markdown = card["elements"][0]["content"]
        # First three indices present.
        assert "(1/7)" in markdown
        assert "(2/7)" in markdown
        assert "(3/7)" in markdown
        # Ops 4-7 collapsed — neither index lines nor their content shown.
        assert "(4/7)" not in markdown
        assert "op-5" not in markdown
        assert "op-6" not in markdown
        # Collapse footer present with the right count.
        assert "还有 4 条操作" in markdown


class TestMemoryProposeBatchTool:
    """Atomic batch behavior of memory_propose_tool — write-path semantics.

    These tests pin down the all-or-nothing contract that distinguishes
    batch shape from N consecutive single-op calls:
      - approve  → exactly one store.apply_batch call with the right args
      - deny     → zero store calls of any kind (no partial state)
      - timeout  → same as deny (zero store calls)
      - write_error (apply_batch returns success=False) → write_error reason
        surfaced, no fallback to single-op paths
    """

    def _resolve_approve_after(self, session_key, **kwargs):
        """Schedule approve resolution after a short delay so memory_propose_tool
        can return after the blocking wait_for_memory_approval completes."""
        def _approve_later():
            time.sleep(0.05)
            resolve_memory_approval(session_key, "approve")
        t = threading.Thread(target=_approve_later, daemon=True)
        t.start()
        return t

    def test_batch_approve_calls_apply_batch_once(self):
        """Approve: store.apply_batch(target, operations) is called exactly once
        with the full ops list — no fallback to add/replace/remove."""
        store = MagicMock()
        store.apply_batch.return_value = {"success": True}

        operations = [
            {"action": "add", "content": "fact one"},
            {"action": "remove", "old_text": "stale entry"},
            {"action": "replace", "old_text": "old", "content": "new"},
        ]
        session_key = "sess-batch-approve"
        self._resolve_approve_after(session_key)

        # memory_propose_tool holds a local reference to _get_session_key via
        # `from owner.memory.gateway import _get_session_key` — patching the
        # gateway module attribute is NOT enough; we must patch the name in the
        # tool module's namespace.
        from owner.memory import tool as _tool_mod
        original = _tool_mod._get_session_key
        _tool_mod._get_session_key = lambda: session_key
        try:
            result = json.loads(memory_propose_tool(
                target="memory", operations=operations, store=store,
            ))
        finally:
            _tool_mod._get_session_key = original

        # Result shape: approved + batch metadata.
        assert result["approved"] is True
        assert result["applied"] == "batch"
        assert result["operations"] == 3
        assert result["target"] == "memory"

        # apply_batch called once with the EXACT ops list.
        store.apply_batch.assert_called_once_with("memory", operations)
        # No fallback to single-op paths.
        store.add.assert_not_called()
        store.replace.assert_not_called()
        store.remove.assert_not_called()

    def test_batch_deny_never_calls_store(self):
        """Deny: zero store calls of any kind — no partial write."""
        store = MagicMock()

        operations = [
            {"action": "add", "content": "would-be fact"},
            {"action": "remove", "old_text": "would-be stale"},
        ]
        session_key = "sess-batch-deny"
        # Resolve deny on the same session_key that submit will use.
        def _deny_later():
            time.sleep(0.05)
            resolve_memory_approval(session_key, "deny")
        threading.Thread(target=_deny_later, daemon=True).start()

        # See note in test_batch_approve_calls_apply_batch_once — patch the
        # name where memory_propose_tool actually looks it up.
        from owner.memory import tool as _tool_mod
        original = _tool_mod._get_session_key
        _tool_mod._get_session_key = lambda: session_key
        try:
            result = json.loads(memory_propose_tool(
                target="memory", operations=operations, store=store,
            ))
        finally:
            _tool_mod._get_session_key = original

        assert result["approved"] is False
        assert result["reason"] == "denied_by_user"
        # Critical invariant: NO store method was invoked.
        store.apply_batch.assert_not_called()
        store.add.assert_not_called()
        store.replace.assert_not_called()
        store.remove.assert_not_called()

    def test_batch_write_error_rolls_back_via_runtime_error(self):
        """apply_batch success=False → write_error reason; the single-op
        fallbacks are NEVER attempted (all-or-nothing semantics)."""
        store = MagicMock()
        store.apply_batch.return_value = {
            "success": False,
            "error": "Replacement would put memory at 2400/2200 chars.",
        }

        operations = [
            {"action": "add", "content": "x" * 500},
            {"action": "replace", "old_text": "short", "content": "y" * 500},
        ]
        session_key = "sess-batch-writeerr"
        self._resolve_approve_after(session_key)

        from owner.memory import tool as _tool_mod
        original = _tool_mod._get_session_key
        _tool_mod._get_session_key = lambda: session_key
        try:
            result = json.loads(memory_propose_tool(
                target="memory", operations=operations, store=store,
            ))
        finally:
            _tool_mod._get_session_key = original

        assert result["approved"] is False
        assert result["reason"] == "write_error"
        assert "2400/2200" in result["message"]
        # No fallback to single-op paths even on failure.
        store.apply_batch.assert_called_once()
        store.add.assert_not_called()
        store.replace.assert_not_called()
        store.remove.assert_not_called()

    def test_batch_large_20_ops_validates_and_submits(self):
        """20-op batch: schema validates, submit creates one entry with all ops,
        the entry carries the full operations list for downstream card render."""
        operations = [
            {"action": "add", "content": f"op-{i} fact"}
            for i in range(20)
        ]
        session_key = "sess-batch-large"

        # Validate via the schema (this is what the LLM model would hit).
        from jsonschema import validate
        validate(
            instance={"target": "memory", "operations": operations},
            schema=MEMORY_PROPOSE_SCHEMA["parameters"],
        )

        # Submit creates a single entry (queue is per-session, not per-op).
        entry = submit_memory_proposal(
            target="memory", operations=operations, session_key=session_key,
        )
        assert entry.operations == operations
        assert len(entry.operations) == 20
        # Deny it so the test exits without hanging the queue.
        resolve_memory_approval(session_key, "deny")
        assert entry.result == "deny"
