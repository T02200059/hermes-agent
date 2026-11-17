"""[owner] C13 recap auto — turn-duration / long-end-message gate (no post-end idle wait)."""

from __future__ import annotations

from unittest.mock import patch


def test_recap_gate_turn_duration_or_long_reply():
    from owner.explainers.recap.gate import (
        MIN_ASSISTANT_CHARS_FOR_AUTO_RECAP,
        RECAP_MIN_IDLE_SECONDS,
        RECAP_MIN_TURN_SECONDS,
        REASON_BELOW_THRESHOLDS,
        REASON_NO_NEW_TURN,
        REASON_NO_TURNS,
        recap_gate,
    )

    assert RECAP_MIN_TURN_SECONDS == 180
    assert RECAP_MIN_IDLE_SECONDS == 180
    assert MIN_ASSISTANT_CHARS_FOR_AUTO_RECAP == 800
    assert recap_gate(0, 0, auto=False) == REASON_NO_TURNS
    # User-turn count alone is not enough (even 3 short turns).
    assert recap_gate(3, 0, auto=True, turn_seconds=10, assistant_chars=20) == REASON_BELOW_THRESHOLDS
    # Duration path: >= 180s triggers immediately, regardless of turn count (>=1) or short reply.
    assert recap_gate(1, 0, auto=True, turn_seconds=180, assistant_chars=20) is None
    assert recap_gate(1, 0, auto=True, turn_seconds=179.9, assistant_chars=20) == REASON_BELOW_THRESHOLDS
    # No reliable start → skip duration path; only the char OR remains.
    assert recap_gate(3, 0, auto=True, turn_seconds=None, assistant_chars=20) == REASON_BELOW_THRESHOLDS
    # min_turn_seconds=0 disables duration path.
    assert recap_gate(1, 0, auto=True, turn_seconds=999, min_turn_seconds=0, assistant_chars=20) == REASON_BELOW_THRESHOLDS
    assert recap_gate(3, 3, auto=True, turn_seconds=200) == REASON_NO_NEW_TURN
    assert recap_gate(3, 2, auto=True, turn_seconds=200) is None
    # Manual exempt from both automatic thresholds.
    assert recap_gate(1, 0, auto=False, turn_seconds=None, assistant_chars=0) is None
    # Char OR: long latest assistant reply can pass with a short turn.
    assert recap_gate(1, 0, auto=True, turn_seconds=5, assistant_chars=2582) is None
    assert recap_gate(1, 0, auto=True, turn_seconds=5, assistant_chars=799) == REASON_BELOW_THRESHOLDS
    assert (
        recap_gate(
            1, 0, auto=True, turn_seconds=5, assistant_chars=2582, min_assistant_chars=0
        )
        == REASON_BELOW_THRESHOLDS
    )


def test_watermark_roundtrip(tmp_path, monkeypatch):
    from owner.explainers.recap import watermark as wm

    monkeypatch.setattr(wm, "_root", lambda: tmp_path)
    assert wm.load_recap_watermark("s1") == 0
    wm.save_recap_watermark("s1", 7)
    assert wm.load_recap_watermark("s1") == 7
    wm.save_recap_watermark("s1", 3)
    assert wm.load_recap_watermark("s1") == 3


def test_count_user_turns_skips_synthetic():
    from owner.explainers.recap.auto import count_user_turns

    msgs = [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "嗯"},
        {"role": "user", "content": "[ASYNC DELEGATION] done"},
        {"role": "user", "content": "继续"},
        {"role": "system", "content": "x"},
        {"role": "user", "content": "第三问"},
    ]
    assert count_user_turns(msgs) == 3


def test_latest_assistant_chars():
    from owner.explainers.recap.auto import latest_assistant_chars

    msgs = [
        {"role": "assistant", "content": ""},
        {"role": "assistant", "content": "short"},
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "x" * 2582},
    ]
    assert latest_assistant_chars(msgs) == 2582
    assert latest_assistant_chars([]) == 0


def test_latest_user_turn_started_at_uses_last_real_user():
    from owner.explainers.recap.auto import latest_user_turn_started_at

    msgs = [
        {"role": "user", "content": "第一问", "timestamp": 1000},
        {"role": "assistant", "content": "a"},
        {"role": "user", "content": "[SYSTEM] ignore", "timestamp": 2000},
        {"role": "user", "content": "本轮", "timestamp": 1500},
        {"role": "assistant", "content": "b"},
    ]
    assert latest_user_turn_started_at(msgs) == 1500
    assert latest_user_turn_started_at([{"role": "user", "content": "无时间"}]) is None


def test_resolve_turn_seconds_prefers_current_turn():
    from owner.explainers.recap.auto import resolve_turn_seconds

    msgs = [
        {"role": "user", "content": "旧", "timestamp": 1000},
        {"role": "assistant", "content": "a"},
        {"role": "user", "content": "本轮", "timestamp": 2000},
        {"role": "assistant", "content": "b"},
    ]
    assert resolve_turn_seconds(msgs, ended_at=2180) == 180
    # Inbound clearly later than last transcript user → current user msg not persisted yet.
    assert resolve_turn_seconds(msgs, inbound_started_at=2500, ended_at=2600) == 100
    # No timestamps and no inbound → skip duration path.
    assert resolve_turn_seconds([{"role": "user", "content": "x"}], ended_at=3000) is None


def test_load_auto_config_defaults_and_overlay(monkeypatch):
    from owner.explainers.recap.auto import load_auto_config
    from owner.explainers import config as cfg_mod

    auto = load_auto_config(
        {
            "auto": {
                "enabled": True,
                "min_user_turns": 5,
                "min_turn_seconds": 60,
                "min_assistant_chars": 2000,
            }
        }
    )
    assert auto["min_user_turns"] == 5
    assert auto["min_turn_seconds"] == 60
    assert auto["min_assistant_chars"] == 2000
    assert auto["enabled"] is True

    # Legacy overlay key idle_seconds is the duration floor, not a post-end wait.
    legacy = load_auto_config({"auto": {"idle_seconds": 30}})
    assert legacy["min_turn_seconds"] == 30

    # New key wins over the legacy alias.
    prefer = load_auto_config({"auto": {"min_turn_seconds": 90, "idle_seconds": 30}})
    assert prefer["min_turn_seconds"] == 90

    # No overlay auto block → duration 180 + owner char default
    monkeypatch.setattr(cfg_mod, "_raw_explainers", lambda: {"recap": {"enabled": True}})
    bare = load_auto_config({})
    assert bare["min_turn_seconds"] == 180
    assert bare["min_assistant_chars"] == 800


def _short_three_turn_msgs(*, last_ts=None, last_assistant="c"):
    msgs = [
        {"role": "user", "content": "一", "timestamp": 1000},
        {"role": "assistant", "content": "a"},
        {"role": "user", "content": "二", "timestamp": 1100},
        {"role": "assistant", "content": "b"},
        {"role": "user", "content": "三", "timestamp": last_ts if last_ts is not None else 2000},
        {"role": "assistant", "content": last_assistant},
    ]
    return msgs


def test_run_auto_recap_short_turn_and_short_reply_skips(tmp_path, monkeypatch):
    """3 short turns with a short end message do not auto-recap."""
    from owner.explainers.recap import auto as auto_mod
    from owner.explainers.recap import watermark as wm

    monkeypatch.setattr(wm, "_root", lambda: tmp_path)
    msgs = _short_three_turn_msgs(last_ts=2100)
    with patch("owner.explainers.recap.command._load_messages", return_value=msgs), patch.object(
        auto_mod, "resolve_enabled", return_value=True
    ), patch.object(
        auto_mod,
        "load_auto_config",
        return_value={"enabled": True, "min_turn_seconds": 180, "min_assistant_chars": 800},
    ), patch.object(auto_mod, "_send_notice") as send:
        assert auto_mod.run_auto_recap("s", platform="feishu", chat_id="c", ended_at=2110) is None
        send.assert_not_called()


def test_run_auto_recap_long_duration_triggers(tmp_path, monkeypatch):
    from owner.explainers.recap import auto as auto_mod
    from owner.explainers.recap import watermark as wm

    monkeypatch.setattr(wm, "_root", lambda: tmp_path)
    msgs = _short_three_turn_msgs(last_ts=2000)
    with patch("owner.explainers.recap.command._load_messages", return_value=msgs), patch.object(
        auto_mod, "resolve_enabled", return_value=True
    ), patch.object(
        auto_mod,
        "load_auto_config",
        return_value={"enabled": True, "min_turn_seconds": 180, "min_assistant_chars": 800},
    ), patch.object(auto_mod, "explain_from_messages", return_value="我们做了三件事"), patch.object(
        auto_mod, "_send_notice", return_value=True
    ) as send:
        body = auto_mod.run_auto_recap("s", platform="feishu", chat_id="c", ended_at=2180)
        assert body and body.startswith("📋 系统提示：")
        assert wm.load_recap_watermark("s") == 3
        send.assert_called_once()

    # watermark blocks repeat without new turn
    with patch("owner.explainers.recap.command._load_messages", return_value=msgs), patch.object(
        auto_mod, "resolve_enabled", return_value=True
    ), patch.object(
        auto_mod,
        "load_auto_config",
        return_value={"enabled": True, "min_turn_seconds": 180, "min_assistant_chars": 800},
    ), patch.object(auto_mod, "_send_notice") as send2:
        assert auto_mod.run_auto_recap("s", platform="feishu", chat_id="c", ended_at=2300) is None
        send2.assert_not_called()


def test_run_auto_recap_char_or_allows_short_duration(tmp_path, monkeypatch):
    """1 user turn + long final assistant reply (≥800) passes auto gate even if turn is short."""
    from owner.explainers.recap import auto as auto_mod
    from owner.explainers.recap import watermark as wm

    monkeypatch.setattr(wm, "_root", lambda: tmp_path)
    long_body = "答" * 1600
    msgs = [
        {"role": "user", "content": "分析一下", "timestamp": 1000},
        {"role": "assistant", "content": long_body},
    ]
    with patch("owner.explainers.recap.command._load_messages", return_value=msgs), patch.object(
        auto_mod, "resolve_enabled", return_value=True
    ), patch.object(
        auto_mod,
        "load_auto_config",
        return_value={"enabled": True, "min_turn_seconds": 180, "min_assistant_chars": 800},
    ), patch.object(auto_mod, "explain_from_messages", return_value="已核对口径，下一步等你确认"), patch.object(
        auto_mod, "_send_notice", return_value=True
    ) as send:
        body = auto_mod.run_auto_recap("s-long", platform="feishu", chat_id="c", ended_at=1010)
        assert body and body.startswith("📋 系统提示：")
        assert wm.load_recap_watermark("s-long") == 1
        send.assert_called_once()


def test_run_auto_recap_missing_start_skips_duration_uses_chars(tmp_path, monkeypatch):
    from owner.explainers.recap import auto as auto_mod
    from owner.explainers.recap import watermark as wm

    monkeypatch.setattr(wm, "_root", lambda: tmp_path)
    short = [{"role": "user", "content": "问"}, {"role": "assistant", "content": "短"}]
    long_msgs = [{"role": "user", "content": "问"}, {"role": "assistant", "content": "答" * 800}]
    cfg = {"enabled": True, "min_turn_seconds": 180, "min_assistant_chars": 800}
    with patch("owner.explainers.recap.command._load_messages", return_value=short), patch.object(
        auto_mod, "resolve_enabled", return_value=True
    ), patch.object(auto_mod, "load_auto_config", return_value=cfg), patch.object(
        auto_mod, "_send_notice"
    ) as send:
        assert auto_mod.run_auto_recap("s-nostart", platform="feishu", chat_id="c") is None
        send.assert_not_called()

    with patch("owner.explainers.recap.command._load_messages", return_value=long_msgs), patch.object(
        auto_mod, "resolve_enabled", return_value=True
    ), patch.object(auto_mod, "load_auto_config", return_value=cfg), patch.object(
        auto_mod, "explain_from_messages", return_value="长答回顾"
    ), patch.object(auto_mod, "_send_notice", return_value=True) as send2:
        body = auto_mod.run_auto_recap("s-nostart-long", platform="feishu", chat_id="c")
        assert body
        send2.assert_called_once()


def test_note_manual_recap_bumps_watermark(tmp_path, monkeypatch):
    from owner.explainers.recap import auto as auto_mod
    from owner.explainers.recap import watermark as wm

    monkeypatch.setattr(wm, "_root", lambda: tmp_path)
    msgs = [{"role": "user", "content": "a"}, {"role": "user", "content": "b"}]
    auto_mod.note_manual_recap("m1", msgs)
    assert wm.load_recap_watermark("m1") == 2


def test_on_session_end_starts_immediately_when_routed():
    from owner.explainers.recap import auto as auto_mod

    with auto_mod._ROUTE_LOCK:
        auto_mod._SESSION_ROUTES["sid-1"] = ("feishu", "oc_z")
    started = {}

    def fake_start(sid, **kw):
        started["sid"] = sid
        started.update(kw)

    with patch.object(auto_mod, "resolve_enabled", return_value=True), patch.object(
        auto_mod,
        "load_auto_config",
        return_value={"enabled": True, "min_turn_seconds": 180, "min_assistant_chars": 800},
    ), patch.object(auto_mod, "start_auto_recap", side_effect=fake_start):
        auto_mod._on_session_end(
            session_id="sid-1",
            completed=True,
            failed=False,
            interrupted=False,
            platform="feishu",
        )
    assert started.get("sid") == "sid-1"
    assert started.get("chat_id") == "oc_z"
    assert "idle_seconds" not in started
    assert started.get("ended_at")  # immediate, no delay


def test_on_session_end_skips_interrupted_or_failed():
    from owner.explainers.recap import auto as auto_mod

    with auto_mod._ROUTE_LOCK:
        auto_mod._SESSION_ROUTES["sid-int"] = ("feishu", "oc_z")
    with patch.object(auto_mod, "start_auto_recap") as start:
        auto_mod._on_session_end(
            session_id="sid-int",
            completed=False,
            failed=False,
            interrupted=True,
            platform="feishu",
        )
        auto_mod._on_session_end(
            session_id="sid-int",
            completed=False,
            failed=True,
            interrupted=False,
            platform="feishu",
        )
        auto_mod._on_session_end(
            session_id="sid-int",
            completed=False,
            failed=False,
            interrupted=False,
            platform="feishu",
        )
        start.assert_not_called()


def test_agent_loop_stopped_then_ambiguous_session_end_skips():
    from owner.explainers.recap import auto as auto_mod

    with auto_mod._ROUTE_LOCK:
        auto_mod._SESSION_ROUTES["sid-stop"] = ("feishu", "oc_z")
    auto_mod._clear_turn_state("sid-stop")
    with patch.object(auto_mod, "resolve_enabled", return_value=True), patch.object(
        auto_mod,
        "load_auto_config",
        return_value={"enabled": True, "min_turn_seconds": 180, "min_assistant_chars": 800},
    ), patch.object(auto_mod, "start_auto_recap") as start:
        auto_mod._on_agent_loop_stopped(session_id="sid-stop")
        # Official flags omitted / ambiguous, but interrupt mark is set.
        auto_mod._on_session_end(session_id="sid-stop", platform="feishu")
        start.assert_not_called()
        # Mark consumed; a later clearly successful end can still fire.
        auto_mod._on_session_end(
            session_id="sid-stop",
            completed=True,
            failed=False,
            interrupted=False,
            platform="feishu",
        )
        start.assert_called_once()


def test_pre_gateway_dispatch_uses_event_source_only():
    """Official hook: event + gateway only; platform/chat_id on event.source."""
    from types import SimpleNamespace
    from owner.explainers.recap import auto as auto_mod

    with auto_mod._ROUTE_LOCK:
        auto_mod._SESSION_ROUTES.clear()
    with auto_mod._REF_LOCK:
        auto_mod._GATEWAY_REF = None
        auto_mod._ADAPTERS.clear()
    auto_mod._clear_turn_state("sid-from-store", "agent:main:feishu:dm:oc_only_source")

    source = SimpleNamespace(platform="feishu", chat_id="oc_only_source")
    # Deliberately NO top-level platform / chat_id / session_key / session_id.
    event = SimpleNamespace(source=source, text="hi")

    class FakeStore:
        def lookup_by_session_key(self, key):
            assert "oc_only_source" in key
            return SimpleNamespace(session_id="sid-from-store", origin=source)

        def lookup_by_session_id(self, sid):
            if sid == "sid-from-store":
                return SimpleNamespace(
                    session_id=sid,
                    session_key="agent:main:feishu:dm:oc_only_source",
                    origin=source,
                    platform="feishu",
                )
            return None

    class FakeGw:
        adapters = {"feishu": object()}
        session_store = FakeStore()

        def _session_key_for_source(self, src):
            return f"agent:main:feishu:dm:{src.chat_id}"

    auto_mod._on_pre_gateway_dispatch(event=event, gateway=FakeGw())
    with auto_mod._ROUTE_LOCK:
        routes = dict(auto_mod._SESSION_ROUTES)
    assert routes.get("sid-from-store") == ("feishu", "oc_only_source", "", "")
    assert routes.get("agent:main:feishu:dm:oc_only_source") == ("feishu", "oc_only_source", "", "")
    # Inbound time recorded against the resolved session id.
    started = auto_mod._pop_turn_start("sid-from-store", "agent:main:feishu:dm:oc_only_source")
    assert started is not None


def test_on_session_end_gateway_routing_fallback():
    """When _SESSION_ROUTES is empty, pull chat_id from session_store.origin."""
    from types import SimpleNamespace
    from owner.explainers.recap import auto as auto_mod

    with auto_mod._ROUTE_LOCK:
        auto_mod._SESSION_ROUTES.clear()

    origin = SimpleNamespace(platform="feishu", chat_id="oc_from_store")

    class FakeStore:
        def lookup_by_session_id(self, sid):
            if sid == "sid-gw":
                return SimpleNamespace(
                    session_id=sid,
                    session_key="agent:main:feishu:dm:oc_from_store",
                    origin=origin,
                    platform="feishu",
                )
            return None

    class FakeGw:
        adapters = {}
        session_store = FakeStore()

    with auto_mod._REF_LOCK:
        auto_mod._GATEWAY_REF = FakeGw()

    started = {}

    def fake_start(sid, **kw):
        started["sid"] = sid
        started.update(kw)

    with patch.object(auto_mod, "resolve_enabled", return_value=True), patch.object(
        auto_mod,
        "load_auto_config",
        return_value={"enabled": True, "min_turn_seconds": 180, "min_assistant_chars": 800},
    ), patch.object(auto_mod, "start_auto_recap", side_effect=fake_start):
        auto_mod._on_session_end(
            session_id="sid-gw",
            completed=True,
            failed=False,
            interrupted=False,
            platform="feishu",
        )
    assert started.get("sid") == "sid-gw"
    assert started.get("chat_id") == "oc_from_store"


def test_manual_recap_stays_immediate(tmp_path, monkeypatch):
    """/recap does not use the auto duration or end-message thresholds."""
    from owner.explainers.recap import auto as auto_mod
    from owner.explainers.recap import command as cmd
    from owner.explainers.recap import watermark as wm

    monkeypatch.setattr(wm, "_root", lambda: tmp_path)
    msgs = [
        {"role": "user", "content": "短问", "timestamp": 1000},
        {"role": "assistant", "content": "短答"},
    ]

    async def _run():
        with patch.object(cmd, "resolve_enabled", return_value=True), patch.object(
            cmd, "_load_messages", return_value=msgs
        ), patch.object(cmd, "explain_from_messages", return_value="手动回顾"), patch(
            "owner.explainers.persist.persist_notice", return_value=1
        ):
            return await cmd.handle_recap_command(session_id="m-now", platform="feishu")

    import asyncio

    body = asyncio.run(_run())
    assert body and body.startswith("📋 系统提示：")
    assert "手动回顾" in body
    assert wm.load_recap_watermark("m-now") == 1
