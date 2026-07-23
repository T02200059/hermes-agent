"""Tests for owner/patches/queue_cancel_patch.py."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from owner.patches import queue_cancel_patch as qcp


@pytest.fixture(autouse=True)
def _clean_token_state():
    qcp._token_state.clear()
    yield
    qcp._token_state.clear()
    if qcp._applied:
        qcp.revert_patch()


def test_event_matches_token_via_attr():
    ev = SimpleNamespace()
    setattr(ev, qcp._EVENT_TOKEN_ATTR, "tok1")
    assert qcp.event_matches_token(ev, "tok1")
    assert not qcp.event_matches_token(ev, "other")


def test_cancel_pending_slot_promotes_overflow():
    token = "t-slot"
    qcp.register_scheduled_token(token, text="first")
    head = SimpleNamespace(text="first")
    setattr(head, qcp._EVENT_TOKEN_ATTR, token)
    qcp._token_state[token]["status"] = "enqueued"
    overflow_item = SimpleNamespace(text="second")

    adapter = SimpleNamespace(
        _pending_messages={"sess-a": head},
        _owner_gateway_runner=None,
    )
    runner = SimpleNamespace(_queued_events={"sess-a": [overflow_item]})
    adapter._owner_gateway_runner = runner

    assert qcp.cancel_queued_by_token(adapter, token) == "ok"
    assert adapter._pending_messages["sess-a"] is overflow_item
    assert qcp._token_state[token]["status"] == "cancelled"


def test_cancel_scheduled_before_enqueue():
    token = "t-race"
    qcp.register_scheduled_token(token, text="later")
    adapter = SimpleNamespace(_pending_messages={}, _owner_gateway_runner=None)
    assert qcp.cancel_queued_by_token(adapter, token) == "ok"
    assert qcp.should_skip_dispatch(token)


def test_cancel_already_running_returns_not_found():
    token = "t-gone"
    qcp.register_scheduled_token(token, text="gone")
    qcp._token_state[token]["status"] = "enqueued"
    adapter = SimpleNamespace(
        _pending_messages={},
        _owner_gateway_runner=SimpleNamespace(_queued_events={}),
    )
    assert qcp.cancel_queued_by_token(adapter, token) == "not_found"


def test_enqueue_wrapper_stamps_token_and_drops_cancelled():
    qcp.apply_patch()
    import gateway.run as gateway_run

    calls = []
    qcp._originals["_enqueue_fifo"] = (
        lambda self, session_key, queued_event, adapter: calls.append(queued_event)
    )
    runner = gateway_run.GatewayRunner.__new__(gateway_run.GatewayRunner)
    adapter = SimpleNamespace(_app_id="id", _app_secret="sec")

    token = "t-drop"
    qcp.register_scheduled_token(token, text="drop me")
    qcp._token_state[token]["status"] = "cancelled"
    gateway_run.GatewayRunner._enqueue_fifo(
        runner, "sk", SimpleNamespace(text="drop me"), adapter
    )
    assert calls == []

    token2 = "t-keep"
    qcp.register_scheduled_token(token2, text="keep me")
    event2 = SimpleNamespace(text="keep me")
    gateway_run.GatewayRunner._enqueue_fifo(runner, "sk2", event2, adapter)
    assert len(calls) == 1
    assert getattr(event2, qcp._EVENT_TOKEN_ATTR) == token2
    assert qcp._token_state[token2]["status"] == "enqueued"


def test_dequeue_notifies_started(monkeypatch):
    qcp.apply_patch()
    import gateway.run as gateway_run

    token = "t-run"
    qcp.register_scheduled_token(
        token,
        text="run me",
        card_message_id="om_card_1",
        user_input="run me",
        user_name="Alice",
    )
    qcp._token_state[token]["status"] = "enqueued"
    event = SimpleNamespace(text="run me")
    setattr(event, qcp._EVENT_TOKEN_ATTR, token)

    notified = []
    monkeypatch.setattr(qcp, "notify_queue_started", lambda t: notified.append(t))

    qcp._originals["_dequeue_pending_event"] = lambda adapter, sk: event
    out = gateway_run._dequeue_pending_event(SimpleNamespace(), "sess")
    assert out is event
    assert notified == [token]


def test_build_queue_executed_card():
    from owner.feishu.steer_card import build_queue_executed_card

    card = build_queue_executed_card("hello", "Bob")
    assert "已开始执行" in card["header"]["title"]["content"]
    assert card["header"]["template"] == "blue"
    assert not any(el.get("tag") == "button" for el in card["body"]["elements"])


def test_apply_patch_idempotent():
    qcp.apply_patch()
    qcp.apply_patch()
    assert qcp._applied is True
    qcp.revert_patch()
    assert qcp._applied is False


def test_prefetch_provider_waits_for_inflight(monkeypatch):
    qcp.apply_patch()
    import agent.memory_manager as mm

    joined = []

    class _Alive:
        def is_alive(self):
            return True

        def join(self, timeout=None):
            joined.append(timeout)

    class _Dead:
        def is_alive(self):
            return False

        def join(self, timeout=None):
            joined.append(timeout)

    mm_inst = mm.MemoryManager.__new__(mm.MemoryManager)
    mm_inst._external_prefetch_lock = __import__("threading").Lock()
    alive = _Alive()
    mm_inst._external_prefetch_threads = {"openviking": alive}
    mm_inst._external_prefetch_timeout = 5.0

    # After join, mark dead so cleanup can pop
    def _join(timeout=None):
        joined.append(timeout)
        mm_inst._external_prefetch_threads["openviking"] = _Dead()

    alive.join = _join

    called = []

    def original(self, provider, query, *, session_id=""):
        called.append(query)
        return "ctx"

    qcp._originals["_prefetch_provider"] = original
    provider = SimpleNamespace(name="openviking")
    result = mm.MemoryManager._prefetch_provider(
        mm_inst, provider, "queue2", session_id="s1"
    )
    assert result == "ctx"
    assert joined  # waited
    assert called == ["queue2"]
