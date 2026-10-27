"""C26-feishu-picker: Feishu /providers model picker card builders + dispatch."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from owner.feishu import model_picker as mp


def test_build_provider_card_buttons_sorted():
    card = mp.build_provider_card(
        "pid-1",
        [
            {"slug": "zeta", "name": "Z", "models": ["m1"]},
            {"slug": "alpha", "name": "Alpha", "models": ["a", "b"]},
        ],
    )
    assert card["schema"] == "2.0"
    assert card["header"]["template"] == "blue"
    buttons = [e for e in card["body"]["elements"] if e.get("tag") == "button"]
    assert [b["value"]["provider"] for b in buttons] == ["alpha", "zeta"]
    assert buttons[0]["value"]["hermes_model_picker"] == "provider"
    assert buttons[0]["value"]["picker_id"] == "pid-1"


def test_build_model_card_has_back():
    card = mp.build_model_card("pid", "damodel", "Damodel", ["glm-5.1", "glm-5.2"])
    buttons = [e for e in card["body"]["elements"] if e.get("tag") == "button"]
    assert buttons[0]["value"] == {
        "hermes_model_picker": "confirm",
        "picker_id": "pid",
        "provider": "damodel",
        "model": "glm-5.1",
    }
    assert buttons[-1]["value"]["hermes_model_picker"] == "back"


def test_build_done_card():
    card = mp.build_done_card("damodel", "glm-5.1", "张三")
    assert card["header"]["template"] == "green"
    assert "glm-5.1" in card["header"]["title"]["content"]
    assert "张三" in card["body"]["elements"][0]["content"]


@pytest.mark.asyncio
async def test_send_model_picker_card_caches_state():
    adapter = MagicMock()
    adapter._model_picker_state = {}
    adapter.send_card = AsyncMock(
        return_value=SimpleNamespace(success=True, message_id="mid-1")
    )
    source = SimpleNamespace(chat_id="oc_x")
    rows = [{"slug": "damodel", "name": "Damodel", "models": ["m"]}]
    await mp.send_model_picker_card(
        adapter, chat_id="oc_x", providers=rows, source=source,
    )
    assert len(adapter._model_picker_state) == 1
    st = next(iter(adapter._model_picker_state.values()))
    assert st["providers"] == rows
    assert st["source"] is source
    adapter.send_card.assert_awaited_once()
    card = adapter.send_card.await_args.kwargs["card"]
    assert any(e.get("tag") == "button" for e in card["body"]["elements"])


def test_handle_picker_provider_step_updates_card():
    rows = [{"slug": "damodel", "name": "Damodel", "models": ["m1", "m2"]}]
    adapter = MagicMock()
    adapter._model_picker_state = {"pid": {"providers": rows, "source": object()}}
    resp = mp.handle_picker_action(
        adapter=adapter,
        action_value={"hermes_model_picker": "provider", "picker_id": "pid", "provider": "damodel"},
        event=SimpleNamespace(),
    )
    assert resp is not None
    # When lark_oapi is available, card is set; otherwise toast/None still non-empty path
    card = getattr(resp, "card", None)
    if card is not None and getattr(card, "data", None):
        buttons = [e for e in card.data["body"]["elements"] if e.get("tag") == "button"]
        assert any(b["value"].get("model") == "m1" for b in buttons)


def test_handle_picker_stale_session_toasts():
    adapter = MagicMock()
    adapter._model_picker_state = {}
    resp = mp.handle_picker_action(
        adapter=adapter,
        action_value={"hermes_model_picker": "provider", "picker_id": "gone", "provider": "x"},
        event=SimpleNamespace(),
    )
    assert resp is not None
    toast = getattr(resp, "toast", None)
    if toast is not None:
        assert "过期" in getattr(toast, "content", "")


def test_handle_picker_back_rebuilds_providers():
    rows = [{"slug": "a", "name": "A", "models": ["m"]}]
    adapter = MagicMock()
    adapter._model_picker_state = {"pid": {"providers": rows, "source": object()}}
    resp = mp.handle_picker_action(
        adapter=adapter,
        action_value={"hermes_model_picker": "back", "picker_id": "pid"},
        event=SimpleNamespace(),
    )
    assert resp is not None
    card = getattr(resp, "card", None)
    if card is not None and getattr(card, "data", None):
        buttons = [e for e in card.data["body"]["elements"] if e.get("tag") == "button"]
        assert buttons[0]["value"]["provider"] == "a"


def test_handle_picker_confirm_pops_state_and_routes():
    source = SimpleNamespace(chat_id="oc_x")
    adapter = MagicMock()
    adapter._model_picker_state = {
        "pid": {"providers": [{"slug": "damodel", "models": ["m"]}], "source": source},
    }
    adapter._loop = object()
    submitted = []

    def _submit(_loop, coro):
        submitted.append(coro)
        coro.close()  # do not leave unawaited coroutine warning

    adapter._submit_on_loop = _submit
    with patch("owner.feishu.model_picker.operator_display_name", return_value="用户甲"):
        resp = mp.handle_picker_action(
            adapter=adapter,
            action_value={
                "hermes_model_picker": "confirm",
                "picker_id": "pid",
                "provider": "damodel",
                "model": "m",
            },
            event=SimpleNamespace(operator=SimpleNamespace(open_id="ou_1")),
        )
    assert "pid" not in adapter._model_picker_state
    assert len(submitted) == 1
    assert resp is not None
    card = getattr(resp, "card", None)
    if card is not None and getattr(card, "data", None):
        assert card.data["header"]["template"] == "green"


def test_dispatch_model_picker_action_delegates():
    adapter = MagicMock()
    with patch.object(mp, "handle_picker_action", return_value="ok") as handle:
        out = mp.dispatch_model_picker_action(
            adapter,
            event=SimpleNamespace(),
            action_value={"hermes_model_picker": "back", "picker_id": "x"},
            loop=None,
        )
    assert out == "ok"
    handle.assert_called_once()


def test_adapter_exposes_send_model_picker_card():
    from plugins.platforms.feishu.adapter import FeishuAdapter

    assert hasattr(FeishuAdapter, "send_model_picker_card")
    assert hasattr(FeishuAdapter, "_handle_model_picker_action")
