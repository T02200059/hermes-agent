"""Tests for owner.memory proposal approval queue and tool."""

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
        calls = []

        def _cb(entry):
            calls.append(entry)

        register_memory_notify("sess-6", _cb)
        entry = submit_memory_proposal("add", "memory", "", "x", session_key="sess-6")
        # _notify is internal; exercise via public unregister path to ensure no crash.
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
        # Register a callback that auto-approves so the tool can complete.
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
