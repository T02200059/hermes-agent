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


def test_cancel_overflow_via_session_field_view_not_dict():
    """Regression: runner._queued_events is SessionFieldView, not dict.

    isinstance(view, dict) was False, so overflow cancels always failed while
    the agent turn was still running (pending slot already occupied).
    """
    from collections.abc import MutableMapping

    class FakeView(MutableMapping):
        def __init__(self, data):
            self._data = data

        def __getitem__(self, k):
            return self._data[k]

        def __setitem__(self, k, v):
            self._data[k] = v

        def __delitem__(self, k):
            del self._data[k]

        def __iter__(self):
            return iter(self._data)

        def __len__(self):
            return len(self._data)

    token = "t-ov"
    qcp.register_scheduled_token(token, text="queued later", session_key="sess-a")
    target = SimpleNamespace(text="queued later", metadata={})
    setattr(target, qcp._EVENT_TOKEN_ATTR, token)
    qcp._token_state[token]["status"] = "enqueued"

    head = SimpleNamespace(text="something else")
    data = {"sess-a": [target]}
    view = FakeView(data)
    assert not isinstance(view, dict)

    runner = SimpleNamespace(_queued_events=view)
    adapter = SimpleNamespace(
        _pending_messages={"sess-a": head},
        _owner_gateway_runner=runner,
    )

    assert qcp.cancel_queued_by_token(adapter, token) == "ok"
    assert data.get("sess-a") in (None, []) or "sess-a" not in data or data["sess-a"] == []
    assert qcp._token_state[token]["status"] == "cancelled"
    # Head in pending slot untouched
    assert adapter._pending_messages["sess-a"] is head


def test_cancel_by_text_fallback_when_stamp_missing():
    token = "t-txt"
    qcp.register_scheduled_token(token, text="do later", session_key="sess-a")
    qcp._token_state[token]["status"] = "enqueued"
    # No _owner_queue_token attr — only text matches registered meta
    event = SimpleNamespace(text="do later", metadata={})
    adapter = SimpleNamespace(
        _pending_messages={"sess-a": event},
        _owner_gateway_runner=SimpleNamespace(_queued_events={}),
    )
    assert qcp.cancel_queued_by_token(adapter, token) == "ok"
    assert "sess-a" not in adapter._pending_messages
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


def test_process_now_promotes_to_head_and_interrupts():
    token = "t-pn"
    qcp.register_scheduled_token(token, text="later", session_key="sess-a")
    head = SimpleNamespace(text="first")
    target = SimpleNamespace(text="later")
    setattr(target, qcp._EVENT_TOKEN_ATTR, token)
    qcp._token_state[token]["status"] = "enqueued"

    agent = MagicMock()
    state = SimpleNamespace(turn=SimpleNamespace(agent=agent))
    runner = SimpleNamespace(
        _queued_events={"sess-a": [target]},
        _peek_session_state=lambda sk: state if sk == "sess-a" else None,
    )
    adapter = SimpleNamespace(
        _pending_messages={"sess-a": head},
        _owner_gateway_runner=runner,
    )

    assert qcp.process_now_by_token(adapter, token) == "ok"
    assert adapter._pending_messages["sess-a"] is target
    assert runner._queued_events["sess-a"][0] is head
    agent.interrupt.assert_called_once()
    assert qcp._token_state[token]["status"] == "process_now"


def test_bind_card_message_id():
    qcp.register_scheduled_token("t-bind", text="x")
    qcp.bind_card_message_id("t-bind", "om_99", session_key="sk1")
    meta = qcp.get_token_meta("t-bind")
    assert meta["card_message_id"] == "om_99"
    assert meta["session_key"] == "sk1"
    assert qcp.token_has_card("t-bind")


def test_steer_queued_by_token_ok():
    token = "t-steer"
    qcp.register_scheduled_token(token, text="please adjust", session_key="sess-a")
    qcp._token_state[token]["status"] = "enqueued"
    event = SimpleNamespace(text="please adjust", metadata={})
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
    assert qcp.steer_queued_by_token(adapter, token) == "ok"
    agent.steer.assert_called_once_with("please adjust")
    assert "sess-a" not in adapter._pending_messages
    assert qcp._token_state[token]["status"] == "steered"


def test_steer_queued_reseat_on_reject():
    token = "t-steer-rej"
    qcp.register_scheduled_token(token, text="nope", session_key="sess-a")
    qcp._token_state[token]["status"] = "enqueued"
    event = SimpleNamespace(text="nope", metadata={})
    setattr(event, qcp._EVENT_TOKEN_ATTR, token)

    agent = MagicMock()
    agent.steer.return_value = False
    state = SimpleNamespace(turn=SimpleNamespace(agent=agent))
    runner = SimpleNamespace(
        _queued_events={},
        _peek_session_state=lambda sk: state if sk == "sess-a" else None,
    )
    adapter = SimpleNamespace(
        _pending_messages={"sess-a": event},
        _owner_gateway_runner=runner,
    )
    assert qcp.steer_queued_by_token(adapter, token) == "rejected"
    # Reseated so the queue item is not lost
    assert adapter._pending_messages["sess-a"] is event
    assert qcp._token_state[token]["status"] == "enqueued"


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
