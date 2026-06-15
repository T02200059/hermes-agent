"""Tests for FeishuApprovalContext state lifecycle."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from owner.feishu.approval import FeishuApprovalContext, resolve_approval


class TestFeishuApprovalContext:
    def test_next_id_increments(self):
        ctx = FeishuApprovalContext()
        a = ctx.next_id()
        b = ctx.next_id()
        assert a != b

    def test_register_and_pop(self):
        ctx = FeishuApprovalContext()
        ctx.register(
            1,
            session_key="sess",
            message_id="msg",
            chat_id="oc_1",
            command="echo hi",
        )
        assert ctx.get(1)["session_key"] == "sess"
        popped = ctx.pop(1)
        assert popped["command"] == "echo hi"
        assert ctx.get(1) is None

    def test_choice_from_action(self):
        assert FeishuApprovalContext.choice_from_action("approve_once") == "once"
        assert FeishuApprovalContext.choice_from_action("unknown") == "deny"

    def test_state_property_alias(self):
        ctx = FeishuApprovalContext()
        ctx.register(7, session_key="s", message_id="m", chat_id="c", command="x")
        assert 7 in ctx.state


class TestResolveApproval:
    @pytest.mark.asyncio
    async def test_unauthorized_operator_leaves_state(self):
        ctx = FeishuApprovalContext()
        ctx.register(1, session_key="s", message_id="m", chat_id="oc_1", command="ls")
        adapter = MagicMock()
        adapter._is_interactive_operator_authorized.return_value = False

        await resolve_approval(ctx, adapter, 1, "once", "User", open_id="ou_x", chat_id="oc_1")

        assert ctx.get(1) is not None
        adapter._is_interactive_operator_authorized.assert_called_once_with("ou_x")

    @pytest.mark.asyncio
    async def test_chat_mismatch_leaves_state(self):
        ctx = FeishuApprovalContext()
        ctx.register(2, session_key="s", message_id="m", chat_id="oc_expected", command="ls")
        adapter = MagicMock()
        adapter._is_interactive_operator_authorized.return_value = True

        await resolve_approval(
            ctx, adapter, 2, "deny", "User", open_id="ou_x", chat_id="oc_wrong"
        )

        assert ctx.get(2) is not None

    @pytest.mark.asyncio
    async def test_success_pops_and_resolves(self, monkeypatch):
        ctx = FeishuApprovalContext()
        ctx.register(3, session_key="sess-key", message_id="m", chat_id="oc_1", command="ls")
        adapter = MagicMock()
        adapter._is_interactive_operator_authorized.return_value = True

        mock_resolve = MagicMock(return_value=1)
        monkeypatch.setattr("tools.approval.resolve_gateway_approval", mock_resolve)

        await resolve_approval(ctx, adapter, 3, "session", "Bob", open_id="ou_x", chat_id="oc_1")

        mock_resolve.assert_called_once_with("sess-key", "session")
        assert ctx.get(3) is None