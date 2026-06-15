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
        assert set(params.keys()) == {"action", "target", "old_text", "new_content"}

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
