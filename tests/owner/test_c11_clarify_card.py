"""C11-clarify: Feishu interactive clarify card builders + action handler."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from owner.clarify.gateway_helpers import get_choice_display, get_choice_key
from owner.feishu import clarify_card as cc


def test_choice_helpers_string_and_dict():
    assert get_choice_display("plain") == "plain"
    assert get_choice_key("plain") == "plain"
    assert get_choice_display({"display": "标签", "key": "k1"}) == "标签"
    assert get_choice_key({"display": "标签", "key": "k1"}) == "k1"
    assert get_choice_key({"display": "标签", "key": None}) == ""


def test_build_clarify_card_buttons_and_other():
    card = cc.build_clarify_card("选一个？", ["甲", "乙"], "cid-1")
    assert card["schema"] == "2.0"
    assert "选一个？" in card["header"]["title"]["content"]
    buttons = [e for e in card["body"]["elements"] if e.get("tag") == "button"]
    assert len(buttons) == 3  # 2 choices + Other
    assert buttons[0]["value"] == {"clarify_id": "cid-1", "choice": "甲"}
    assert buttons[-1]["value"]["choice"] == "__other__"


def test_build_retired_clarify_card_embeds_notice():
    card = cc.build_retired_clarify_card("Q", ["a"], "已取消")
    md = card["body"]["elements"][0]["content"]
    assert "已取消" in md
    assert card["header"]["template"] == "grey"
    buttons = [e for e in card["body"]["elements"] if e.get("tag") == "button"]
    assert all(b.get("disabled") for b in buttons)


@pytest.mark.asyncio
async def test_send_clarify_open_ended_falls_back_to_text():
    adapter = MagicMock()
    adapter._client = object()
    adapter.send = AsyncMock(return_value=SimpleNamespace(success=True, message_id="m1"))
    adapter._clarify_state = {}
    with patch("tools.clarify_gateway.mark_awaiting_text") as mark:
        result = await cc.send_clarify(
            adapter, chat_id="oc_x", question="随便说", choices=None,
            clarify_id="c1", session_key="s1",
        )
    mark.assert_called_once_with("c1")
    adapter.send.assert_awaited()
    assert result.success is True
    assert adapter._clarify_state == {}


@pytest.mark.asyncio
async def test_send_clarify_caches_state():
    adapter = MagicMock()
    adapter._client = object()
    adapter._clarify_state = {}
    adapter.send_card = AsyncMock(
        return_value=SimpleNamespace(success=True, message_id="mid-9", error=None)
    )
    result = await cc.send_clarify(
        adapter, chat_id="oc_x", question="Q", choices=["A", "B"],
        clarify_id="cid", session_key="sk",
    )
    assert result.message_id == "mid-9"
    st = adapter._clarify_state["cid"]
    assert st["message_id"] == "mid-9"
    assert st["choices"] == ["A", "B"]
    assert st["question"] == "Q"


@pytest.mark.asyncio
async def test_retire_clarify_card_noop_without_message():
    adapter = MagicMock()
    adapter._clarify_state = {"cid": {"question": "Q", "choices": ["a"]}}
    with patch.object(cc, "patch_message_via_rest", new_callable=AsyncMock) as patch_msg:
        await cc.retire_clarify_card(adapter, "cid", "notice")
    patch_msg.assert_not_awaited()
    assert "cid" not in adapter._clarify_state


@pytest.mark.asyncio
async def test_retire_clarify_card_patches():
    adapter = MagicMock()
    adapter._app_id = "app"
    adapter._app_secret = "sec"
    adapter._clarify_state = {
        "cid": {"message_id": "m1", "question": "Q", "choices": ["a"]},
    }
    with patch.object(cc, "patch_message_via_rest", new_callable=AsyncMock) as patch_msg:
        patch_msg.return_value = True
        await cc.retire_clarify_card(adapter, "cid", "超时了")
    patch_msg.assert_awaited_once()
    kwargs = patch_msg.await_args.kwargs
    assert kwargs["message_id"] == "m1"
    assert "超时了" in kwargs["card"]["body"]["elements"][0]["content"]
    assert "cid" not in adapter._clarify_state


def test_handle_clarify_choice_resolves():
    adapter = MagicMock()
    adapter._clarify_state = {
        "cid": {"question": "Q", "choices": ["甲", "乙"], "message_id": "m"},
    }
    with patch("tools.clarify_gateway.resolve_gateway_clarify") as resolve:
        resp = cc.handle_clarify_card_action(
            adapter,
            event=SimpleNamespace(),
            action_value={"clarify_id": "cid", "choice": "甲"},
            loop=None,
        )
    resolve.assert_called_once_with("cid", "甲")
    assert "cid" not in adapter._clarify_state
    # frozen card returned when SDK types available; may be empty response if import fails
    assert resp is not None


def test_handle_clarify_other_returns_input_card():
    adapter = MagicMock()
    adapter._clarify_state = {
        "cid": {"question": "Q", "choices": ["甲"], "message_id": "m"},
    }
    with patch("tools.clarify_gateway.resolve_gateway_clarify") as resolve:
        resp = cc.handle_clarify_card_action(
            adapter,
            event=SimpleNamespace(),
            action_value={"clarify_id": "cid", "choice": "__other__"},
            loop=None,
        )
    resolve.assert_not_called()
    assert "cid" in adapter._clarify_state  # not resolved yet
    assert resp is not None
