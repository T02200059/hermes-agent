"""C12-feishu-guide: interactive guide card builders + dispatch + command."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from owner.feishu import steer_card as sc


def test_build_guide_card_five_actions():
    card = sc.build_guide_card("gid-1")
    assert card["schema"] == "2.0"
    assert card["header"]["template"] == "blue"
    buttons = [e for e in card["body"]["elements"] if e.get("tag") == "button"]
    assert len(buttons) == 5
    keys = [b["value"]["action_key"] for b in buttons]
    assert keys == ["queue", "steer", "goal", "subgoal", "background"]
    assert buttons[0]["value"]["hermes_feishu_guide"] == "select"
    assert buttons[0]["value"]["guide_id"] == "gid-1"


def test_build_input_card_has_form_and_back():
    card = sc.build_input_card("gid", "steer")
    assert "注入引导" in card["header"]["title"]["content"]
    form = next(e for e in card["body"]["elements"] if e.get("tag") == "form")
    assert form["name"] == "guide_form_gid"
    submit = next(
        e for e in form["elements"]
        if e.get("tag") == "button" and e.get("action_type") == "form_submit"
    )
    assert submit["value"] == {
        "hermes_feishu_guide": "submit",
        "guide_id": "gid",
        "action_key": "steer",
    }
    back = next(
        e for e in card["body"]["elements"]
        if e.get("tag") == "button" and e.get("value", {}).get("hermes_feishu_guide") == "back"
    )
    assert back["value"]["guide_id"] == "gid"


def test_build_input_card_unknown_falls_back_to_guide():
    card = sc.build_input_card("gid", "nope")
    buttons = [e for e in card["body"]["elements"] if e.get("tag") == "button"]
    assert len(buttons) == 5


def test_build_done_card():
    card = sc.build_done_card("goal", "完成迁移", "张三")
    assert card["header"]["template"] == "green"
    content = card["body"]["elements"][0]["content"]
    assert "/goal" in content
    assert "完成迁移" in content
    assert "张三" in content


@pytest.mark.asyncio
async def test_send_guide_card_caches_state():
    adapter = MagicMock()
    adapter._guide_card_state = {}
    adapter.send_card = AsyncMock(
        return_value=SimpleNamespace(success=True, message_id="mid-1")
    )
    source = SimpleNamespace(chat_id="oc_x")
    await sc.send_guide_card(adapter, chat_id="oc_x", source=source)
    assert len(adapter._guide_card_state) == 1
    st = next(iter(adapter._guide_card_state.values()))
    assert st["source"] is source
    adapter.send_card.assert_awaited_once()
    card = adapter.send_card.await_args.kwargs["card"]
    buttons = [e for e in card["body"]["elements"] if e.get("tag") == "button"]
    assert len(buttons) == 5


def test_handle_select_step_updates_card():
    adapter = MagicMock()
    adapter._guide_card_state = {"gid": {"source": object()}}
    resp = sc.handle_guide_card_action(
        adapter=adapter,
        action_value={
            "hermes_feishu_guide": "select",
            "guide_id": "gid",
            "action_key": "steer",
        },
        event=SimpleNamespace(),
    )
    assert resp is not None
    card = getattr(resp, "card", None)
    if card is not None and getattr(card, "data", None):
        form = next(e for e in card.data["body"]["elements"] if e.get("tag") == "form")
        assert "guide_input" in str(form)


def test_handle_back_rebuilds_guide():
    adapter = MagicMock()
    resp = sc.handle_guide_card_action(
        adapter=adapter,
        action_value={"hermes_feishu_guide": "back", "guide_id": "gid"},
        event=SimpleNamespace(),
    )
    assert resp is not None
    card = getattr(resp, "card", None)
    if card is not None and getattr(card, "data", None):
        buttons = [e for e in card.data["body"]["elements"] if e.get("tag") == "button"]
        assert len(buttons) == 5


def test_handle_submit_empty_input_no_route():
    adapter = MagicMock()
    adapter._guide_card_state = {"gid": {"source": SimpleNamespace(chat_id="oc_1")}}
    with patch.object(sc, "_route_guide_command") as route:
        resp = sc.handle_guide_card_action(
            adapter=adapter,
            action_value={
                "hermes_feishu_guide": "submit",
                "guide_id": "gid",
                "action_key": "steer",
                "form_value": {"guide_input": "  "},
            },
            event=SimpleNamespace(operator=SimpleNamespace(open_id="ou_1")),
        )
        route.assert_not_called()
    assert resp is not None


def test_handle_submit_routes_and_done_card():
    adapter = MagicMock()
    adapter._guide_card_state = {"gid": {"source": SimpleNamespace(chat_id="oc_1")}}
    event = SimpleNamespace(operator=SimpleNamespace(open_id="ou_1"))
    with patch.object(sc, "_route_guide_command") as route, patch(
        "owner.feishu.steer_card.operator_display_name", return_value="李四"
    ):
        resp = sc.handle_guide_card_action(
            adapter=adapter,
            action_value={
                "hermes_feishu_guide": "submit",
                "guide_id": "gid",
                "action_key": "steer",
                "form_value": {"guide_input": "改用 pytest"},
            },
            event=event,
        )
        route.assert_called_once()
        args, kwargs = route.call_args
        assert args[1] == "/steer 改用 pytest"
        assert args[2] == "ou_1"
        assert "gid" not in adapter._guide_card_state
    card = getattr(resp, "card", None)
    if card is not None and getattr(card, "data", None):
        assert card.data["header"]["template"] == "green"
        assert "李四" in card.data["body"]["elements"][0]["content"]


def test_dispatch_guide_card_action_delegates():
    adapter = MagicMock()
    event = SimpleNamespace()
    action = {"hermes_feishu_guide": "back", "guide_id": "g"}
    with patch.object(sc, "handle_guide_card_action", return_value="ok") as handle:
        out = sc.dispatch_guide_card_action(
            adapter, event=event, action_value=action, loop=object(),
        )
        handle.assert_called_once_with(
            adapter=adapter, action_value=action, event=event,
        )
        assert out == "ok"


@pytest.mark.asyncio
async def test_feishu_guide_command_sends_card_on_feishu():
    from gateway.config import Platform
    from owner.commands.feishu_guide import handle_feishu_guide_command

    adapter = MagicMock()
    adapter.send_guide_card = AsyncMock()
    source = SimpleNamespace(platform=Platform.FEISHU, chat_id="oc_chat")
    adapters = {Platform.FEISHU: adapter}
    result = await handle_feishu_guide_command(
        "", source=source, adapters=adapters,
    )
    assert result is None
    adapter.send_guide_card.assert_awaited_once()
    kwargs = adapter.send_guide_card.await_args.kwargs
    assert kwargs["chat_id"] == "oc_chat"
    assert kwargs["source"] is source


@pytest.mark.asyncio
async def test_feishu_guide_command_text_fallback_non_feishu():
    from gateway.config import Platform
    from owner.commands.feishu_guide import handle_feishu_guide_command

    source = SimpleNamespace(platform=Platform.TELEGRAM, chat_id="1")
    result = await handle_feishu_guide_command("", source=source, adapters={})
    assert isinstance(result, str)
    assert "/steer" in result
    assert "/feishu-guide" in result


def test_should_bypass_includes_plugin_commands(monkeypatch):
    from hermes_cli import commands as cmd

    monkeypatch.setattr(cmd, "resolve_command", lambda _n: None)
    monkeypatch.setattr(cmd, "is_gateway_known_command", lambda n: n == "feishu-guide")
    assert cmd.should_bypass_active_session("feishu-guide") is True
    assert cmd.should_bypass_active_session("totally-unknown") is False
    assert cmd.should_bypass_active_session(None) is False
