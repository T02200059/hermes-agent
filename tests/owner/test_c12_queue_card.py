"""C12-queue-card: Feishu /queue 状态卡 + cancel/process_now/steer lifecycle."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from owner.feishu import queue_card as qc
from owner.feishu import steer_card as sc
from owner.patches import queue_cancel_patch as qcp


@pytest.fixture(autouse=True)
def _clean_tokens():
    """Each test starts with an empty token map."""
    with qcp._token_lock:
        qcp._token_state.clear()
    yield
    with qcp._token_lock:
        qcp._token_state.clear()
    if qcp._applied:
        qcp.revert_patch()


def _action_buttons(card: dict) -> list:
    """Collect button values from a Feishu card (including column_set rows)."""
    found = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("tag") == "button" and isinstance(node.get("value"), dict):
                found.append(node["value"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(card)
    return found


# ── card builders ──────────────────────────────────────────────────────────


def test_build_queue_status_card_has_three_actions():
    card = qc.build_queue_status_card("整理 PR", "shu", queue_token="tok-abc")
    assert card["schema"] == "2.0"
    assert "排队" in card["header"]["title"]["content"] or "队列" in card["header"]["title"]["content"]
    values = _action_buttons(card)
    actions = {v.get("hermes_queue_card") for v in values}
    assert actions >= {"cancel", "process_now", "steer"}
    for v in values:
        assert v.get("queue_token") == "tok-abc"


def test_terminal_cards_are_static():
    for builder in (
        qc.build_queue_cancelled_card,
        qc.build_queue_executed_card,
        qc.build_queue_process_now_card,
        qc.build_queue_steered_card,
    ):
        card = builder("内容", "用户")
        assert card["schema"] == "2.0"
        assert not any(
            v.get("hermes_queue_card") for v in _action_buttons(card)
        ), f"{builder.__name__} should have no live action buttons"


def test_started_notify_lists_remaining():
    card = qc.build_queue_started_notify_card(
        "当前项", "shu", remaining=["下一项 A", "下一项 B"]
    )
    body = str(card["body"])
    assert "下一项 A" in body
    assert "下一项 B" in body


# ── token state machine ────────────────────────────────────────────────────


def test_register_and_match_unbound_then_session():
    qcp.register_scheduled_token("t1", text="hello", card_message_id="om_1")
    assert qcp.token_has_card("t1")
    # Unbound match (guide path)
    assert qcp.find_scheduled_token_for_text("hello") == "t1"
    # Session-bound match should NOT steal unbound when asking for a session
    assert qcp.find_scheduled_token_for_text("hello", session_key="sess-a") is None
    # After binding session_key, session match works
    with qcp._token_lock:
        qcp._token_state["t1"]["session_key"] = "sess-a"
    assert qcp.find_scheduled_token_for_text("hello", session_key="sess-a") == "t1"


def test_should_skip_dispatch_after_cancel_status():
    qcp.register_scheduled_token("t2", text="x")
    assert qcp.should_skip_dispatch("t2") is False
    with qcp._token_lock:
        qcp._token_state["t2"]["status"] = "cancelled"
    assert qcp.should_skip_dispatch("t2") is True


def test_event_matches_token_attr_and_text_fallback():
    qcp.register_scheduled_token("t3", text="prompt text")
    ev = SimpleNamespace(text="prompt text", metadata={})
    setattr(ev, qcp._EVENT_TOKEN_ATTR, "t3")
    assert qcp.event_matches_token(ev, "t3") is True

    ev2 = SimpleNamespace(text="prompt text", metadata={})
    assert qcp.event_matches_token(ev2, "t3") is True  # text fallback

    ev3 = SimpleNamespace(text="other", metadata={})
    assert qcp.event_matches_token(ev3, "t3") is False


def test_cancel_removes_from_pending_slot():
    token = "t-cancel"
    qcp.register_scheduled_token(token, text="do work", session_key="sk")
    with qcp._token_lock:
        qcp._token_state[token]["status"] = "enqueued"

    event = SimpleNamespace(text="do work", metadata={})
    qcp._stamp_event(event, token)

    adapter = MagicMock()
    adapter._pending_messages = {"sk": event}
    adapter._owner_gateway_runner = SimpleNamespace(
        _queued_events={},
        _sessions_map=dict,
    )

    status = qcp.cancel_queued_by_token(adapter, token)
    assert status == "ok"
    assert "sk" not in adapter._pending_messages
    assert qcp.get_token_meta(token).get("status") == "cancelled"


def test_enqueue_wrap_stamps_unbound_guide_token():
    """Guide morph registers unbound; enqueue should bind + stamp it."""
    token = "t-guide"
    qcp.register_scheduled_token(token, text="from guide", card_message_id="om_x")

    # Patch onto a fake runner class
    class Runner:
        def _enqueue_fifo(self, session_key, queued_event, adapter):
            self.last = (session_key, queued_event, adapter)

    runner_cls = Runner
    # Manually wire wrap like apply_patch
    qcp._originals["_enqueue_fifo"] = runner_cls._enqueue_fifo
    runner_cls._enqueue_fifo = qcp._enqueue_fifo
    try:
        r = Runner()
        ev = SimpleNamespace(text="from guide", metadata={})
        adapter = MagicMock()
        qcp._enqueue_fifo(r, "sess-1", ev, adapter)
        assert getattr(ev, qcp._EVENT_TOKEN_ATTR) == token
        meta = qcp.get_token_meta(token)
        assert meta.get("status") == "enqueued"
        assert meta.get("session_key") == "sess-1"
        assert adapter._owner_gateway_runner is r
    finally:
        runner_cls._enqueue_fifo = qcp._originals.pop("_enqueue_fifo")


def test_apply_and_revert_patch_idempotent(monkeypatch):
    """Wire onto a fake gateway.run so we do not touch real HERMES_HOME."""
    import sys
    import types

    class FakeRunner:
        def _enqueue_fifo(self, *a, **k):
            return None

        async def _busy_queue_command(self, *a, **k):
            return None

    fake = types.ModuleType("gateway.run")
    fake.GatewayRunner = FakeRunner

    def _dequeue(adapter, session_key):
        return None

    fake._dequeue_pending_event = _dequeue
    monkeypatch.setitem(sys.modules, "gateway.run", fake)
    # Also stub agent.memory_manager import path used only in revert cleanup.
    qcp.apply_patch()
    assert qcp._applied is True
    assert FakeRunner._enqueue_fifo is qcp._enqueue_fifo
    qcp.apply_patch()  # idempotent
    assert qcp._applied is True
    qcp.revert_patch()
    assert qcp._applied is False
    assert FakeRunner._enqueue_fifo is not qcp._enqueue_fifo
    qcp.revert_patch()  # idempotent
    assert qcp._applied is False


# ── guide morph ────────────────────────────────────────────────────────────


def test_guide_queue_submit_morphs_to_status_card():
    adapter = MagicMock()
    adapter._app_id = "cli_x"
    adapter._app_secret = "sec"
    adapter._guide_card_state = {
        "gid": {"source": SimpleNamespace(chat_id="oc_chat")}
    }
    adapter._loop = MagicMock()

    def _accept_and_close(_loop, coro):
        # Mock schedule: consume coro so pytest does not see never-awaited.
        try:
            coro.close()
        except Exception:
            pass
        return True

    adapter._submit_on_loop = MagicMock(side_effect=_accept_and_close)

    event = SimpleNamespace(
        operator=SimpleNamespace(open_id="ou_1"),
        context=SimpleNamespace(open_message_id="om_card", open_chat_id="oc_chat"),
    )
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(sc, "operator_display_name", lambda *_a, **_k: "shu")
        resp = sc.handle_guide_card_action(
            adapter=adapter,
            action_value={
                "hermes_feishu_guide": "submit",
                "guide_id": "gid",
                "action_key": "queue",
                "form_value": {"guide_input": "排队任务"},
            },
            event=event,
        )
    assert resp is not None
    card = getattr(resp, "card", None)
    assert card is not None and getattr(card, "data", None)
    values = _action_buttons(card.data)
    assert any(v.get("hermes_queue_card") == "cancel" for v in values)
    # Token registered with card binding
    tokens = list(qcp._token_state)
    assert len(tokens) == 1
    meta = qcp.get_token_meta(tokens[0])
    assert meta.get("text") == "排队任务"
    assert meta.get("card_message_id") == "om_card"
    assert meta.get("status") == "scheduled"
    adapter._submit_on_loop.assert_called_once()


def test_steer_reexports_queue_cards():
    assert sc.build_queue_cancelled_card("a", "b")["schema"] == "2.0"
    assert sc.build_queue_executed_card("a", "b")["schema"] == "2.0"


# ── harden: fail-open / enabled / submit-failed ────────────────────────────


def test_enqueue_wrap_fail_open_still_calls_original(monkeypatch):
    """Owner stamp/meta exception must not abort stock FIFO enqueue."""
    calls = []

    class Runner:
        def _enqueue_fifo(self, session_key, queued_event, adapter):
            calls.append((session_key, queued_event, adapter))

    qcp._originals["_enqueue_fifo"] = Runner._enqueue_fifo
    Runner._enqueue_fifo = qcp._enqueue_fifo
    try:
        r = Runner()
        ev = SimpleNamespace(text="boom", metadata={})
        adapter = MagicMock()

        def _boom(*_a, **_k):
            raise RuntimeError("stamp boom")

        monkeypatch.setattr(qcp, "_match_token_for_text", _boom)
        qcp._enqueue_fifo(r, "sess-x", ev, adapter)
        assert len(calls) == 1
        assert calls[0][0] == "sess-x"
        assert calls[0][1] is ev
    finally:
        Runner._enqueue_fifo = qcp._originals.pop("_enqueue_fifo")


def test_enqueue_wrap_bypasses_when_disabled(monkeypatch):
    qcp.register_scheduled_token("t-off", text="should not stamp")
    calls = []

    class Runner:
        def _enqueue_fifo(self, session_key, queued_event, adapter):
            calls.append(queued_event)

    qcp._originals["_enqueue_fifo"] = Runner._enqueue_fifo
    Runner._enqueue_fifo = qcp._enqueue_fifo
    try:
        monkeypatch.setattr(qc, "is_queue_card_enabled", lambda: False)
        r = Runner()
        ev = SimpleNamespace(text="should not stamp", metadata={})
        qcp._enqueue_fifo(r, "sess-off", ev, MagicMock())
        assert len(calls) == 1
        assert getattr(ev, qcp._EVENT_TOKEN_ATTR, None) is None
        assert qcp.get_token_meta("t-off").get("status") == "scheduled"
    finally:
        Runner._enqueue_fifo = qcp._originals.pop("_enqueue_fifo")


def test_guide_queue_submit_failed_returns_failure_card_not_queued():
    adapter = MagicMock()
    adapter._app_id = "cli_x"
    adapter._app_secret = "sec"
    adapter._guide_card_state = {
        "gid": {"source": SimpleNamespace(chat_id="oc_chat")}
    }
    adapter._loop = MagicMock()
    adapter._submit_on_loop = MagicMock(return_value=False)

    event = SimpleNamespace(
        operator=SimpleNamespace(open_id="ou_1"),
        context=SimpleNamespace(open_message_id="om_card", open_chat_id="oc_chat"),
    )
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(sc, "operator_display_name", lambda *_a, **_k: "shu")
        mp.setattr(qc, "is_queue_card_enabled", lambda: True)
        resp = sc.handle_guide_card_action(
            adapter=adapter,
            action_value={
                "hermes_feishu_guide": "submit",
                "guide_id": "gid",
                "action_key": "queue",
                "form_value": {"guide_input": "不该显示已排队"},
            },
            event=event,
        )
    assert resp is not None
    card = getattr(resp, "card", None)
    assert card is not None and getattr(card, "data", None)
    title = card.data["header"]["title"]["content"]
    assert "失败" in title
    assert not any(v.get("hermes_queue_card") for v in _action_buttons(card.data))
    assert qcp._token_state == {}
    adapter._submit_on_loop.assert_called_once()


def test_is_queue_card_enabled_reads_overlay(monkeypatch):
    monkeypatch.setattr(
        "owner.patch_config.load_patch_config",
        lambda: {"feishu": {"queue_card": {"enabled": False}}},
    )
    assert qc.is_queue_card_enabled() is False
    monkeypatch.setattr(
        "owner.patch_config.load_patch_config",
        lambda: {"feishu": {"queue_card": {"enabled": True}}},
    )
    assert qc.is_queue_card_enabled() is True
    monkeypatch.setattr("owner.patch_config.load_patch_config", dict)
    assert qc.is_queue_card_enabled() is True
