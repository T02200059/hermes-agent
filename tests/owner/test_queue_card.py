"""Tests for Feishu-only queue status card (owner/feishu/queue_card.py)."""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from owner.feishu import queue_card
from owner.patches import queue_cancel_patch as qcp


@pytest.fixture(autouse=True)
def _clean_token_state():
    qcp._token_state.clear()
    yield
    qcp._token_state.clear()


@pytest.fixture
def lark_card_stubs(monkeypatch):
    class Resp:
        def __init__(self):
            self.card = None

    class Card:
        def __init__(self):
            self.type = None
            self.data = None

    mod_name = "lark_oapi.event.callback.model.p2_card_action_trigger"
    mod = types.ModuleType(mod_name)
    mod.P2CardActionTriggerResponse = Resp
    mod.CallBackCard = Card
    monkeypatch.setitem(sys.modules, mod_name, mod)
    return Resp, Card


def test_build_queue_status_card_has_three_buttons():
    card = queue_card.build_queue_status_card(
        "do the thing",
        "Alice",
        queue_token="tok-xyz",
        depth=2,
    )
    assert "已排队" in card["header"]["title"]["content"]
    assert "do the thing" in card["body"]["elements"][0]["content"]
    assert "2" in card["body"]["elements"][0]["content"]

    row = card["body"]["elements"][1]
    assert row["tag"] == "column_set"
    buttons = [col["elements"][0] for col in row["columns"]]
    labels = [b["text"]["content"] for b in buttons]
    assert any("引导对话" in lb for lb in labels)
    assert any("立即处理" in lb for lb in labels)
    assert any("取消" in lb for lb in labels)
    for b in buttons:
        assert b["value"]["queue_token"] == "tok-xyz"
        assert b["value"]["hermes_queue_card"] in ("steer", "process_now", "cancel")
    steer_btn = next(b for b in buttons if b["value"]["hermes_queue_card"] == "steer")
    assert "do the thing" in steer_btn["value"]["user_input"]


def test_handle_cancel_ok(lark_card_stubs):
    adapter = SimpleNamespace(_pending_messages={}, _owner_gateway_runner=None)
    qcp.register_scheduled_token("tok1", text="preview text")

    result = queue_card.handle_queue_card_action(
        adapter=adapter,
        action_value={
            "hermes_queue_card": "cancel",
            "queue_token": "tok1",
            "user_input": "preview text",
            "user_name": "Alice",
        },
        event=SimpleNamespace(operator=SimpleNamespace(open_id="ou_1")),
    )
    assert result is not None
    assert "已取消" in result.card.data["header"]["title"]["content"]


def test_handle_cancel_not_found(lark_card_stubs):
    adapter = SimpleNamespace(_pending_messages={}, _owner_gateway_runner=None)
    result = queue_card.handle_queue_card_action(
        adapter=adapter,
        action_value={
            "hermes_queue_card": "cancel",
            "queue_token": "missing",
            "user_input": "x",
            "user_name": "Bob",
        },
        event=SimpleNamespace(operator=None),
    )
    assert result is not None
    assert "无法取消" in result.card.data["header"]["title"]["content"]


def test_handle_process_now_promotes_overflow_head(lark_card_stubs):
    token = "tok-pn"
    qcp.register_scheduled_token(token, text="later", session_key="sess-a")
    head = SimpleNamespace(text="first")
    target = SimpleNamespace(text="later")
    setattr(target, qcp._EVENT_TOKEN_ATTR, token)
    qcp._token_state[token]["status"] = "enqueued"

    adapter = SimpleNamespace(
        _pending_messages={"sess-a": head},
        _owner_gateway_runner=None,
    )
    runner = SimpleNamespace(_queued_events={"sess-a": [target]})
    adapter._owner_gateway_runner = runner

    agent = MagicMock()
    state = SimpleNamespace(turn=SimpleNamespace(agent=agent))
    runner._peek_session_state = lambda sk: state if sk == "sess-a" else None

    result = queue_card.handle_queue_card_action(
        adapter=adapter,
        action_value={
            "hermes_queue_card": "process_now",
            "queue_token": token,
            "user_input": "later",
            "user_name": "Carol",
        },
        event=SimpleNamespace(operator=None),
    )
    assert result is not None
    assert "立即处理" in result.card.data["header"]["title"]["content"]
    assert adapter._pending_messages["sess-a"] is target
    assert runner._queued_events["sess-a"][0] is head
    agent.interrupt.assert_called_once()


def test_handle_steer_injects_and_removes_from_fifo(lark_card_stubs):
    token = "tok-st"
    qcp.register_scheduled_token(token, text="nudge me", session_key="sess-a")
    qcp._token_state[token]["status"] = "enqueued"
    event = SimpleNamespace(text="nudge me", metadata={})
    setattr(event, qcp._EVENT_TOKEN_ATTR, token)

    agent = MagicMock()
    agent.steer.return_value = True
    state = SimpleNamespace(turn=SimpleNamespace(agent=agent))
    runner = SimpleNamespace(
        _queued_events={},
        _peek_session_state=lambda sk: state if sk == "sess-a" else None,
    )
    adapter = SimpleNamespace(
        _pending_messages={"sess-a": event},
        _owner_gateway_runner=runner,
    )

    result = queue_card.handle_queue_card_action(
        adapter=adapter,
        action_value={
            "hermes_queue_card": "steer",
            "queue_token": token,
            "user_input": "nudge me",
            "user_name": "Dana",
        },
        event=SimpleNamespace(operator=None),
    )
    assert result is not None
    assert "已引导注入" in result.card.data["header"]["title"]["content"]
    agent.steer.assert_called_once_with("nudge me")
    assert "sess-a" not in adapter._pending_messages
    assert qcp._token_state[token]["status"] == "steered"


def test_handle_guide_alias_also_steers(lark_card_stubs):
    """Older cards used hermes_queue_card=guide — still map to /steer."""
    token = "tok-legacy"
    qcp.register_scheduled_token(token, text="legacy", session_key="sess-b")
    qcp._token_state[token]["status"] = "enqueued"
    event = SimpleNamespace(text="legacy", metadata={})
    setattr(event, qcp._EVENT_TOKEN_ATTR, token)

    agent = MagicMock()
    agent.steer.return_value = True
    state = SimpleNamespace(turn=SimpleNamespace(agent=agent))
    runner = SimpleNamespace(
        _queued_events={},
        _peek_session_state=lambda sk: state if sk == "sess-b" else None,
    )
    adapter = SimpleNamespace(
        _pending_messages={"sess-b": event},
        _owner_gateway_runner=runner,
    )
    result = queue_card.handle_queue_card_action(
        adapter=adapter,
        action_value={"hermes_queue_card": "guide", "queue_token": token},
        event=SimpleNamespace(operator=None),
    )
    assert "已引导注入" in result.card.data["header"]["title"]["content"]
    agent.steer.assert_called_once_with("legacy")
