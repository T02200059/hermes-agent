"""Tests for Feishu interactive card approval buttons."""

import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Ensure the repo root is importable
# ---------------------------------------------------------------------------
_repo = str(Path(__file__).resolve().parents[2])
if _repo not in sys.path:
    sys.path.insert(0, _repo)


# ---------------------------------------------------------------------------
# Minimal Feishu mock so FeishuAdapter can be imported without lark-oapi
# ---------------------------------------------------------------------------
def _ensure_feishu_mocks():
    """Provide stubs for lark-oapi / aiohttp.web so the import succeeds."""
    if importlib.util.find_spec("lark_oapi") is None and "lark_oapi" not in sys.modules:
        mod = MagicMock()
        for name in (
            "lark_oapi", "lark_oapi.api.im.v1",
            "lark_oapi.event", "lark_oapi.event.callback_type",
        ):
            sys.modules.setdefault(name, mod)
    if importlib.util.find_spec("aiohttp") is None and "aiohttp" not in sys.modules:
        aio = MagicMock()
        sys.modules.setdefault("aiohttp", aio)
        sys.modules.setdefault("aiohttp.web", aio.web)


_ensure_feishu_mocks()

from gateway.config import PlatformConfig
import plugins.platforms.feishu.adapter as feishu_module
from plugins.platforms.feishu.adapter import FeishuAdapter
from owner.feishu.sender_name_cache import FeishuSenderNameCache


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_adapter() -> FeishuAdapter:
    """Create a FeishuAdapter with mocked internals."""
    config = PlatformConfig(enabled=True)
    adapter = FeishuAdapter(config)
    adapter._client = MagicMock()
    return adapter


def _make_card_action_data(
    action_value: dict,
    chat_id: str = "oc_12345",
    open_id: str = "ou_user1",
    token: str = "tok_abc",
) -> SimpleNamespace:
    """Create a mock Feishu card action callback data object."""
    return SimpleNamespace(
        event=SimpleNamespace(
            token=token,
            context=SimpleNamespace(open_chat_id=chat_id),
            operator=SimpleNamespace(open_id=open_id),
            action=SimpleNamespace(
                tag="button",
                value=action_value,
            ),
        ),
    )


def _close_submitted_coro(coro, _loop):
    """Close scheduled coroutines in sync-handler tests to avoid unawaited warnings."""
    coro.close()
    return SimpleNamespace(add_done_callback=lambda *_args, **_kwargs: None)


# ===========================================================================
# send_exec_approval — interactive card with buttons
# ===========================================================================

class TestFeishuExecApproval:
    """Test send_exec_approval sends an interactive card."""

    @pytest.mark.asyncio
    async def test_sends_interactive_card(self):
        adapter = _make_adapter()

        mock_response = SimpleNamespace(
            success=lambda: True,
            data=SimpleNamespace(message_id="msg_001"),
        )
        with patch.object(
            adapter, "_feishu_send_with_retry", new_callable=AsyncMock,
            return_value=mock_response,
        ) as mock_send:
            result = await adapter.send_exec_approval(
                chat_id="oc_12345",
                command="rm -rf /important",
                session_key="agent:main:feishu:group:oc_12345",
                description="dangerous deletion",
            )

        assert result.success is True
        assert result.message_id == "msg_001"

        mock_send.assert_called_once()
        kwargs = mock_send.call_args[1]
        assert kwargs["chat_id"] == "oc_12345"
        assert kwargs["msg_type"] == "interactive"

        # Verify card payload contains the command and buttons
        card = json.loads(kwargs["payload"])
        assert card["header"]["template"] == "orange"
        assert "rm -rf /important" in card["elements"][0]["content"]
        assert "dangerous deletion" in card["elements"][0]["content"]

        # Check buttons — default allow_permanent=false shows 3 buttons
        actions = card["elements"][1]["actions"]
        assert len(actions) == 3
        action_names = [a["value"]["hermes_action"] for a in actions]
        assert action_names == ["approve_once", "approve_session", "deny"]
        assert "permanently" in card["elements"][0]["content"].lower() or "disabled" in card["elements"][0]["content"].lower()

    @pytest.mark.asyncio
    async def test_allow_permanent_true_shows_always_button(self):
        adapter = _make_adapter()

        mock_response = SimpleNamespace(
            success=lambda: True,
            data=SimpleNamespace(message_id="msg_001"),
        )
        # patch the owner free function (the static was moved during extraction)
        with patch("owner.feishu.approval.get_allow_permanent", return_value=True), patch.object(
            adapter, "_feishu_send_with_retry", new_callable=AsyncMock,
            return_value=mock_response,
        ) as mock_send:
            await adapter.send_exec_approval(
                chat_id="oc_12345",
                command="ls",
                session_key="s",
            )

        card = json.loads(mock_send.call_args[1]["payload"])
        actions = card["elements"][1]["actions"]
        assert len(actions) == 4
        assert [a["value"]["hermes_action"] for a in actions] == [
            "approve_once", "approve_session", "approve_always", "deny"
        ]
        assert "disabled" not in card["elements"][0]["content"].lower()

    @pytest.mark.asyncio
    async def test_smart_denied_shows_once_deny_only_with_explain_copy(self):
        """Smart DENY owner override: once/deny only + explicit one-shot copy."""
        adapter = _make_adapter()

        mock_response = SimpleNamespace(
            success=lambda: True,
            data=SimpleNamespace(message_id="msg_sd"),
        )
        with patch.object(
            adapter, "_feishu_send_with_retry", new_callable=AsyncMock,
            return_value=mock_response,
        ) as mock_send:
            await adapter.send_exec_approval(
                chat_id="oc_12345",
                command="rm -rf /",
                session_key="s",
                description="destructive wipe",
                smart_denied=True,
            )

        card = json.loads(mock_send.call_args[1]["payload"])
        assert card["header"]["template"] == "red"
        title = card["header"]["title"]["content"]
        assert "Smart DENY" in title or "智能审批" in title or "Allow Once Only" in title or "仅可允许一次" in title

        actions = card["elements"][1]["actions"]
        assert [a["value"]["hermes_action"] for a in actions] == [
            "approve_once", "deny"
        ]

        body = card["elements"][0]["content"]
        assert "destructive wipe" in body
        # Explain why session/always are unavailable (en or zh catalog).
        assert (
            "single operation" in body.lower()
            or "仅限本次" in body
            or "one operation" in body.lower()
            or "本次执行一次" in body
        )
        # Note should call out that Session / Always are not offered.
        assert (
            "Session" in body
            or "Always" in body
            or "本次会话" in body
            or "永久允许" in body
        )

    @pytest.mark.asyncio
    async def test_pre_warms_sender_name_cache(self):
        import plugins.platforms.feishu.adapter as feishu_mod

        feishu_mod._owner_lazy.clear()
        adapter = _make_adapter()
        # Cleaned: no longer directly poke legacy private adapter._sender_name_cache.
        # The thin implementation still schedules the (patched) delegate for this test's compatibility.

        mock_response = SimpleNamespace(
            success=lambda: True,
            data=SimpleNamespace(message_id="msg_001"),
        )
        with patch.object(
            adapter, "_feishu_send_with_retry", new_callable=AsyncMock,
            return_value=mock_response,
        ), patch.object(
            adapter, "_resolve_sender_name_from_api", new_callable=AsyncMock,
        ) as mock_resolve:
            await adapter.send_exec_approval(
                chat_id="oc_12345",
                command="ls",
                session_key="s",
                sender_open_id="ou_user1",
                sender_is_bot=False,
            )
            # Yield event loop so fire-and-forget task from pre_warm_sender_name executes
            await asyncio.sleep(0)
        mock_resolve.assert_called_once_with("ou_user1", is_bot=False)

    @pytest.mark.asyncio
    async def test_stores_approval_state(self):
        adapter = _make_adapter()

        mock_response = SimpleNamespace(
            success=lambda: True,
            data=SimpleNamespace(message_id="msg_002"),
        )
        with patch.object(
            adapter, "_feishu_send_with_retry", new_callable=AsyncMock,
            return_value=mock_response,
        ):
            await adapter.send_exec_approval(
                chat_id="oc_12345",
                command="echo test",
                session_key="my-session-key",
            )

        assert len(adapter._approval_state) == 1
        approval_id = list(adapter._approval_state.keys())[0]
        state = adapter._approval_state[approval_id]
        assert state["session_key"] == "my-session-key"
        assert state["message_id"] == "msg_002"
        assert state["chat_id"] == "oc_12345"
        assert state["command"] == "echo test"


# ===========================================================================
# send_update_prompt — interactive card with buttons
# ===========================================================================

class TestFeishuUpdatePrompt:
    """Test send_update_prompt sends an interactive card."""

    @pytest.mark.asyncio
    async def test_sends_interactive_card(self):
        adapter = _make_adapter()

        mock_response = SimpleNamespace(
            success=lambda: True,
            data=SimpleNamespace(message_id="msg_up_001"),
        )
        with patch.object(
            adapter, "_feishu_send_with_retry", new_callable=AsyncMock,
            return_value=mock_response,
        ) as mock_send:
            result = await adapter.send_update_prompt(
                chat_id="oc_12345",
                prompt="Restore stashed changes after update?",
                default="y",
                session_key="agent:main:feishu:group:oc_12345",
                metadata={"thread_id": "th_1"},
            )

        assert result.success is True
        assert result.message_id == "msg_up_001"

        kwargs = mock_send.call_args[1]
        assert kwargs["chat_id"] == "oc_12345"
        assert kwargs["msg_type"] == "interactive"
        assert kwargs["metadata"] == {"thread_id": "th_1"}

        card = json.loads(kwargs["payload"])
        assert card["header"]["template"] == "orange"
        assert "Restore stashed changes after update?" in card["elements"][0]["content"]
        assert "Default: `y`" in card["elements"][0]["content"]
        actions = card["elements"][1]["actions"]
        assert [a["value"]["hermes_update_prompt_action"] for a in actions] == ["y", "n"]


# ===========================================================================
# _resolve_approval — approval state pop + gateway resolution
# ===========================================================================

class TestResolveApproval:
    """Test _resolve_approval pops state and calls resolve_gateway_approval."""

    @pytest.mark.asyncio
    async def test_resolves_once(self):
        adapter = _make_adapter()
        adapter._approval_state[1] = {
            "session_key": "agent:main:feishu:group:oc_12345",
            "message_id": "msg_001",
            "chat_id": "oc_12345",
        }

        with patch("tools.approval.resolve_gateway_approval", return_value=1) as mock_resolve:
            await adapter._resolve_approval(1, "once", "Norbert", open_id="ou_user1", chat_id="oc_12345")

        mock_resolve.assert_called_once_with("agent:main:feishu:group:oc_12345", "once")
        assert 1 not in adapter._approval_state


    @pytest.mark.asyncio
    async def test_unauthorized_click_does_not_resolve(self):
        adapter = _make_adapter()
        adapter._admins = {"ou_admin"}
        adapter._approval_state[5] = {
            "session_key": "sess-5",
            "message_id": "msg_005",
            "chat_id": "oc_12345",
        }

        with patch("tools.approval.resolve_gateway_approval") as mock_resolve:
            await adapter._resolve_approval(5, "once", "Mallory", open_id="ou_intruder", chat_id="oc_12345")

        mock_resolve.assert_not_called()
        assert 5 in adapter._approval_state


# ===========================================================================
# _handle_card_action_event — non-approval card actions
# ===========================================================================

class TestNonApprovalCardAction:
    """Non-approval card actions should still route as synthetic commands."""

    @pytest.mark.asyncio
    async def test_routes_as_synthetic_command(self):
        adapter = _make_adapter()

        data = _make_card_action_data(
            action_value={"custom_action": "something_else"},
            token="tok_normal",
        )

        with (
            patch.object(
                adapter, "_resolve_sender_profile", new_callable=AsyncMock,
                return_value={"user_id": "ou_u", "user_name": "Dave", "user_id_alt": None},
            ),
            patch.object(adapter, "get_chat_info", new_callable=AsyncMock, return_value={"name": "Test Chat"}),
            patch.object(adapter, "_handle_message_with_guards", new_callable=AsyncMock) as mock_handle,
        ):
            await adapter._handle_card_action_event(data)

        mock_handle.assert_called_once()
        event = mock_handle.call_args[0][0]
        assert "/card button" in event.text


# ===========================================================================
# _on_card_action_trigger — inline card response for approval actions
# ===========================================================================

class _FakeCallBackCard:
    def __init__(self):
        self.type = None
        self.data = None


class _FakeP2Response:
    def __init__(self):
        self.card = None


@pytest.fixture(autouse=False)
def _patch_callback_card_types(monkeypatch):
    """Provide real-ish P2CardActionTriggerResponse / CallBackCard for tests."""
    monkeypatch.setattr(feishu_module, "P2CardActionTriggerResponse", _FakeP2Response)
    monkeypatch.setattr(feishu_module, "CallBackCard", _FakeCallBackCard)
    # Owner helpers import directly from lark_oapi; patch the source and the
    # owner helper module bindings so the fake is used regardless of import order.
    try:
        import lark_oapi.event.callback.model.p2_card_action_trigger as _lark_trigger
        monkeypatch.setattr(_lark_trigger, "P2CardActionTriggerResponse", _FakeP2Response)
        monkeypatch.setattr(_lark_trigger, "CallBackCard", _FakeCallBackCard)
    except Exception:
        pass
    try:
        import owner.feishu.approval as _owner_approval
        monkeypatch.setattr(_owner_approval, "P2CardActionTriggerResponse", _FakeP2Response)
        monkeypatch.setattr(_owner_approval, "CallBackCard", _FakeCallBackCard)
    except Exception:
        pass
    try:
        import owner.feishu.update_prompt as _owner_update_prompt
        monkeypatch.setattr(_owner_update_prompt, "P2CardActionTriggerResponse", _FakeP2Response)
        monkeypatch.setattr(_owner_update_prompt, "CallBackCard", _FakeCallBackCard)
    except Exception:
        pass


class TestCardActionCallbackResponse:
    """Test that _on_card_action_trigger returns updated card inline."""

    def test_drops_action_when_loop_not_ready(self, _patch_callback_card_types):
        adapter = _make_adapter()
        adapter._loop = None
        data = _make_card_action_data({"hermes_action": "approve_once", "approval_id": 1})

        with patch("asyncio.run_coroutine_threadsafe") as mock_submit:
            response = adapter._on_card_action_trigger(data)

        assert response is not None
        assert response.card is None
        mock_submit.assert_not_called()

    def test_returns_card_for_approve_action(self, _patch_callback_card_types):
        adapter = _make_adapter()
        adapter._loop = MagicMock()
        adapter._loop.is_closed = MagicMock(return_value=False)
        adapter._allowed_group_users = {"ou_bob"}
        adapter._approval_state[1] = {
            "session_key": "sess-1",
            "message_id": "msg-1",
            "chat_id": "oc_12345",
        }
        data = _make_card_action_data(
            {"hermes_action": "approve_once", "approval_id": 1},
            open_id="ou_bob",
        )
        adapter._user_store.seed_cached_name("ou_bob", "Bob", 9999999999)

        with patch("asyncio.run_coroutine_threadsafe", side_effect=_close_submitted_coro):
            response = adapter._on_card_action_trigger(data)

        assert response is not None
        assert response.card is not None
        assert response.card.type == "raw"
        card = response.card.data
        assert card["header"]["template"] == "green"
        assert "Approved once" in card["header"]["title"]["content"]
        assert "Bob" in card["elements"][0]["content"]


    def test_ignores_expired_cached_name(self, _patch_callback_card_types):
        adapter = _make_adapter()
        adapter._loop = MagicMock()
        adapter._loop.is_closed = MagicMock(return_value=False)
        adapter._allowed_group_users = {"ou_expired"}
        adapter._approval_state[4] = {
            "session_key": "sess-4",
            "message_id": "msg-4",
            "chat_id": "oc_12345",
        }
        data = _make_card_action_data(
            {"hermes_action": "approve_once", "approval_id": 4},
            open_id="ou_expired",
        )
        adapter._user_store.seed_cached_name("ou_expired", "Old Name", 1)

        with patch("asyncio.run_coroutine_threadsafe", side_effect=_close_submitted_coro):
            response = adapter._on_card_action_trigger(data)

        card = response.card.data
        assert "Old Name" not in card["elements"][0]["content"]
        assert "ou_expired" in card["elements"][0]["content"]

    def test_rejects_approval_click_from_unauthorized_user(self, _patch_callback_card_types):
        adapter = _make_adapter()
        adapter._loop = MagicMock()
        adapter._loop.is_closed = MagicMock(return_value=False)
        adapter._group_policy = "allowlist"
        adapter._default_group_policy = "allowlist"
        adapter._allowed_group_users = {"ou_allowed"}
        adapter._approval_state[5] = {
            "session_key": "sess-5",
            "message_id": "msg-5",
            "chat_id": "oc_12345",
        }
        data = _make_card_action_data(
            {"hermes_action": "approve_once", "approval_id": 5},
            open_id="ou_attacker",
        )

        with patch("asyncio.run_coroutine_threadsafe") as mock_submit:
            response = adapter._on_card_action_trigger(data)

        assert response is not None
        assert response.card is None
        mock_submit.assert_not_called()

    def test_rejects_approval_click_when_callback_chat_mismatches(self, _patch_callback_card_types):
        adapter = _make_adapter()
        adapter._loop = MagicMock()
        adapter._loop.is_closed = MagicMock(return_value=False)
        adapter._allowed_group_users = {"ou_bob"}
        adapter._approval_state[6] = {
            "session_key": "sess-6",
            "message_id": "msg-6",
            "chat_id": "oc_expected",
        }
        data = _make_card_action_data(
            {"hermes_action": "approve_once", "approval_id": 6},
            chat_id="oc_mismatch",
            open_id="ou_bob",
        )

        with patch("asyncio.run_coroutine_threadsafe") as mock_submit:
            response = adapter._on_card_action_trigger(data)

        assert response is not None
        assert response.card is None
        mock_submit.assert_not_called()

    def test_returns_card_for_update_prompt_yes(self, _patch_callback_card_types):
        adapter = _make_adapter()
        adapter._loop = MagicMock()
        adapter._loop.is_closed = MagicMock(return_value=False)
        adapter._allowed_group_users = {"ou_bob"}
        adapter._update_prompt_state[1] = {
            "session_key": "sess-up-1",
            "message_id": "msg_up_003",
            "chat_id": "oc_12345",
        }
        data = _make_card_action_data(
            {"hermes_update_prompt_action": "y", "update_prompt_id": 1},
            open_id="ou_bob",
        )
        adapter._user_store.seed_cached_name("ou_bob", "Bob", 9999999999)

        with patch("asyncio.run_coroutine_threadsafe", side_effect=_close_submitted_coro):
            response = adapter._on_card_action_trigger(data)

        assert response is not None
        assert response.card is not None
        card = response.card.data
        assert card["header"]["template"] == "green"
        assert "answered: Yes" in card["header"]["title"]["content"]
        assert "Bob" in card["elements"][0]["content"]

    def test_returns_card_for_update_prompt_no(self, _patch_callback_card_types):
        adapter = _make_adapter()
        adapter._loop = MagicMock()
        adapter._loop.is_closed = MagicMock(return_value=False)
        adapter._allowed_group_users = {"ou_user1"}
        adapter._update_prompt_state[2] = {
            "session_key": "sess-up-2",
            "message_id": "msg_up_004",
            "chat_id": "oc_12345",
        }
        data = _make_card_action_data(
            {"hermes_update_prompt_action": "n", "update_prompt_id": 2},
        )

        with patch("asyncio.run_coroutine_threadsafe", side_effect=_close_submitted_coro):
            response = adapter._on_card_action_trigger(data)

        assert response is not None
        assert response.card is not None
        card = response.card.data
        assert card["header"]["template"] == "red"
        assert "answered: No" in card["header"]["title"]["content"]

    def test_ignores_missing_update_prompt_id(self, _patch_callback_card_types):
        adapter = _make_adapter()
        adapter._loop = MagicMock()
        adapter._loop.is_closed = MagicMock(return_value=False)
        data = _make_card_action_data({"hermes_update_prompt_action": "y"})

        with patch("asyncio.run_coroutine_threadsafe") as mock_submit:
            response = adapter._on_card_action_trigger(data)

        assert response is not None
        assert response.card is None
        mock_submit.assert_not_called()

    def test_already_resolved_update_prompt_returns_no_card(self, _patch_callback_card_types):
        adapter = _make_adapter()
        adapter._loop = MagicMock()
        adapter._loop.is_closed = MagicMock(return_value=False)
        data = _make_card_action_data(
            {"hermes_update_prompt_action": "y", "update_prompt_id": 99},
        )

        with patch("asyncio.run_coroutine_threadsafe") as mock_submit:
            response = adapter._on_card_action_trigger(data)

        assert response is not None
        assert response.card is None
        mock_submit.assert_not_called()

    def test_update_prompt_schedule_failure_returns_no_card(self, _patch_callback_card_types):
        adapter = _make_adapter()
        adapter._loop = MagicMock()
        adapter._loop.is_closed = MagicMock(return_value=False)
        adapter._allowed_group_users = {"ou_user1"}
        adapter._update_prompt_state[1] = {
            "session_key": "sess-up-1",
            "message_id": "msg_up_005",
            "chat_id": "oc_12345",
        }
        data = _make_card_action_data(
            {"hermes_update_prompt_action": "y", "update_prompt_id": 1},
        )

        with patch("asyncio.run_coroutine_threadsafe", side_effect=RuntimeError("loop closed")):
            response = adapter._on_card_action_trigger(data)

        assert response is not None
        assert response.card is None

    def test_update_prompt_unauthorized_operator_returns_no_card(self, _patch_callback_card_types):
        adapter = _make_adapter()
        adapter._loop = MagicMock()
        adapter._loop.is_closed = MagicMock(return_value=False)
        adapter._update_prompt_state[1] = {
            "session_key": "sess-up-1",
            "message_id": "msg_up_006",
            "chat_id": "oc_12345",
        }
        adapter._group_policy = "allowlist"
        adapter._default_group_policy = "allowlist"
        adapter._allowed_group_users = {"ou_allowed"}
        data = _make_card_action_data(
            {"hermes_update_prompt_action": "y", "update_prompt_id": 1},
            open_id="ou_intruder",
        )

        with patch("asyncio.run_coroutine_threadsafe") as mock_submit:
            response = adapter._on_card_action_trigger(data)

        assert response is not None
        assert response.card is None
        mock_submit.assert_not_called()

    def test_update_prompt_empty_allowlists_fail_closed(self, _patch_callback_card_types):
        adapter = _make_adapter()
        adapter._loop = MagicMock()
        adapter._loop.is_closed = MagicMock(return_value=False)
        adapter._group_policy = "allowlist"
        adapter._default_group_policy = "allowlist"
        adapter._update_prompt_state[7] = {
            "session_key": "sess-up-7",
            "message_id": "msg_up_007",
            "chat_id": "oc_12345",
        }
        data = _make_card_action_data(
            {"hermes_update_prompt_action": "y", "update_prompt_id": 7},
            open_id="ou_intruder",
        )

        with patch("asyncio.run_coroutine_threadsafe") as mock_submit:
            response = adapter._on_card_action_trigger(data)

        assert response is not None
        assert response.card is None
        assert 7 in adapter._update_prompt_state
        mock_submit.assert_not_called()

    def test_update_prompt_chat_mismatch_returns_no_card(self, _patch_callback_card_types):
        adapter = _make_adapter()
        adapter._loop = MagicMock()
        adapter._loop.is_closed = MagicMock(return_value=False)
        adapter._allowed_group_users = {"ou_bob"}
        adapter._update_prompt_state[8] = {
            "session_key": "sess-up-8",
            "message_id": "msg_up_008",
            "chat_id": "oc_expected",
        }
        data = _make_card_action_data(
            {"hermes_update_prompt_action": "y", "update_prompt_id": 8},
            chat_id="oc_mismatch",
            open_id="ou_bob",
        )

        with patch("asyncio.run_coroutine_threadsafe") as mock_submit:
            response = adapter._on_card_action_trigger(data)

        assert response is not None
        assert response.card is None
        assert 8 in adapter._update_prompt_state
        mock_submit.assert_not_called()


class TestResolveUpdatePrompt:
    """Test update prompt resolution persists the response file."""

    @pytest.mark.asyncio
    async def test_writes_response_file(self, tmp_path, monkeypatch):
        adapter = _make_adapter()
        monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
        (tmp_path / ".hermes").mkdir()
        adapter._update_prompt_state[1] = {
            "session_key": "sess-up-1",
            "message_id": "msg_up_003",
            "chat_id": "oc_12345",
        }

        await adapter._resolve_update_prompt(1, "y", "Alice")

        assert (tmp_path / ".hermes" / ".update_response").read_text() == "y"
        assert 1 not in adapter._update_prompt_state


