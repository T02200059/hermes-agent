"""Tests for feishu guide card queue integration in owner/feishu/steer_card.py."""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace

import pytest

from owner.feishu import steer_card
from owner.patches import queue_cancel_patch as qcp


@pytest.fixture(autouse=True)
def _clean_token_state():
    qcp._token_state.clear()
    yield
    qcp._token_state.clear()


@pytest.fixture
def lark_card_stubs(monkeypatch):
    """Stub lark_oapi card callback types used by handle_guide_card_action."""

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

    # Only inject the leaf module; real lark_oapi package may already exist.
    monkeypatch.setitem(sys.modules, mod_name, mod)
    return Resp, Card


def test_build_done_card_queue_has_no_cancel_button():
    """Lifecycle UI moved to queue status card — done card is static."""
    card = steer_card.build_done_card(
        "queue",
        "do the thing",
        "Alice",
        guide_id="g1",
        queue_token="tok-xyz",
    )
    assert card["header"]["title"]["content"].startswith("✅")
    body = card["body"]["elements"]
    assert not any(el.get("tag") == "button" for el in body)
    assert "do the thing" in body[0]["content"]


def test_build_done_card_steer_has_no_cancel():
    card = steer_card.build_done_card("steer", "nudge", "Bob", guide_id="g2")
    assert not any(el.get("tag") == "button" for el in card["body"]["elements"])


def test_build_queue_cancelled_and_failed_cards():
    ok = steer_card.build_queue_cancelled_card("hello world", "Alice")
    assert "已取消" in ok["header"]["title"]["content"] or "已撤销" in ok["header"]["title"]["content"]
    fail = steer_card.build_queue_cancel_failed_card("hello world", "Alice")
    assert "无法取消" in fail["header"]["title"]["content"] or "无法撤销" in fail["header"]["title"]["content"]
    assert "/stop" in fail["body"]["elements"][0]["content"]


def test_handle_cancel_queue_legacy_ok(lark_card_stubs):
    adapter = SimpleNamespace(_pending_messages={}, _owner_gateway_runner=None)
    qcp.register_scheduled_token("tok1", text="preview text")

    result = steer_card.handle_guide_card_action(
        adapter=adapter,
        action_value={
            "hermes_feishu_guide": "cancel_queue",
            "queue_token": "tok1",
            "user_input": "preview text",
            "user_name": "Alice",
        },
        event=SimpleNamespace(operator=SimpleNamespace(open_id="ou_1")),
    )
    assert result is not None
    title = result.card.data["header"]["title"]["content"]
    assert "已取消" in title or "已撤销" in title


def test_handle_cancel_queue_legacy_not_found(lark_card_stubs):
    adapter = SimpleNamespace(_pending_messages={}, _owner_gateway_runner=None)
    result = steer_card.handle_guide_card_action(
        adapter=adapter,
        action_value={
            "hermes_feishu_guide": "cancel_queue",
            "queue_token": "missing-token",
            "user_input": "x",
            "user_name": "Bob",
        },
        event=SimpleNamespace(operator=None),
    )
    assert result is not None
    title = result.card.data["header"]["title"]["content"]
    assert "无法取消" in title or "无法撤销" in title


def test_submit_queue_morphs_to_status_card(lark_card_stubs, monkeypatch):
    routed = {}

    def fake_route(adapter, command, open_id, state, *, queue_token=None):
        routed["command"] = command
        routed["queue_token"] = queue_token

    monkeypatch.setattr(steer_card, "_route_guide_command", fake_route)
    monkeypatch.setattr(
        steer_card, "operator_display_name", lambda adapter, open_id: "Carol"
    )

    adapter = SimpleNamespace(
        _guide_card_state={"g-q": {"source": SimpleNamespace(chat_id="oc_1")}},
        _app_id="app",
        _app_secret="sec",
    )
    result = steer_card.handle_guide_card_action(
        adapter=adapter,
        action_value={
            "hermes_feishu_guide": "submit",
            "guide_id": "g-q",
            "action_key": "queue",
            "form_value": {"guide_input": "run later"},
        },
        event=SimpleNamespace(
            operator=SimpleNamespace(open_id="ou_c"),
            context=SimpleNamespace(open_message_id="om_card_1", open_chat_id="oc_1"),
        ),
    )
    assert routed["command"] == "/queue run later"
    assert routed["queue_token"]
    assert qcp._token_state[routed["queue_token"]]["status"] == "scheduled"
    assert qcp._token_state[routed["queue_token"]]["text"] == "run later"
    assert qcp._token_state[routed["queue_token"]]["card_message_id"] == "om_card_1"
    assert result is not None
    # Morphs into queue status card (not static done card)
    assert "已排队" in result.card.data["header"]["title"]["content"]
    row = result.card.data["body"]["elements"][1]
    buttons = [col["elements"][0] for col in row["columns"]]
    assert any(b["value"].get("hermes_queue_card") == "cancel" for b in buttons)
    assert all(b["value"]["queue_token"] == routed["queue_token"] for b in buttons)


def test_requeue_same_text_after_cancel_is_not_dropped():
    """[owner-patch P1-1] A cancelled token must not swallow a re-sent
    queue request with identical text: the enqueue hook retires the stale
    token and lets the event queue normally instead of returning early."""
    # Simulate: user queued "run later", cancelled it, then re-sends.
    qcp.register_scheduled_token(
        "tok-cancelled", text="run later", session_key="sess1"
    )
    qcp._token_state["tok-cancelled"]["status"] = "cancelled"

    calls = {}

    class FakeAdapter:
        pass

    class FakeEvent:
        def __init__(self):
            self.text = "run later"

    class FakeRunner:
        def __init__(self):
            self.enqueued = []

        def _enqueue_fifo(self, session_key, event, adapter):
            calls["enqueued"] = True
            self.enqueued.append((session_key, event, adapter))

    runner = FakeRunner()
    event = FakeEvent()
    # monkeypatch the originals so the wrapper calls through to the fake
    # (unbound method: the wrapper invokes it as original(self, ...)).
    import owner.patches.queue_cancel_patch as _qcp

    original = _qcp._originals.get("_enqueue_fifo")
    _qcp._originals["_enqueue_fifo"] = FakeRunner._enqueue_fifo
    try:
        _qcp._enqueue_fifo(runner, "sess1", event, FakeAdapter())
    finally:
        if original is None:
            _qcp._originals.pop("_enqueue_fifo", None)
        else:
            _qcp._originals["_enqueue_fifo"] = original

    # The stale cancelled token was retired, and the event still queued.
    assert "tok-cancelled" not in _qcp._token_state
    assert calls.get("enqueued") is True
    assert runner.enqueued[0][1] is event
