"""[owner] C13 recap idle-auto — gate, watermark, scheduler (Grok Build aligned)."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def test_recap_gate_mirrors_grok():
    from owner.explainers.recap.gate import (
        MIN_TURNS_FOR_AUTO_RECAP,
        RECAP_MIN_IDLE_SECONDS,
        recap_gate,
    )

    assert MIN_TURNS_FOR_AUTO_RECAP == 3
    assert RECAP_MIN_IDLE_SECONDS == 180
    assert recap_gate(0, 0, auto=False, idle_ok=True) == "no main turns yet"
    assert recap_gate(2, 0, auto=True, idle_ok=True) == "fewer than min turns for auto recap"
    assert recap_gate(3, 0, auto=True, idle_ok=False) == "idle threshold not met"
    assert recap_gate(3, 3, auto=True, idle_ok=True) == "no new main turn since last recap"
    assert recap_gate(3, 2, auto=True, idle_ok=True) is None
    assert recap_gate(1, 0, auto=False, idle_ok=False) is None  # manual exempt


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


def test_load_auto_config_defaults_and_overlay(monkeypatch):
    from owner.explainers.recap.auto import load_auto_config
    from owner.explainers import config as cfg_mod

    auto = load_auto_config({"auto": {"enabled": True, "min_user_turns": 5, "idle_seconds": 30}})
    assert auto["min_user_turns"] == 5
    assert auto["idle_seconds"] == 30
    assert auto["enabled"] is True

    # No overlay auto block → Grok defaults
    monkeypatch.setattr(cfg_mod, "_raw_explainers", lambda: {"recap": {"enabled": True}})
    bare = load_auto_config({})
    assert bare["min_user_turns"] == 3
    assert bare["idle_seconds"] == 180


def test_schedule_cancel_before_fire():
    from owner.explainers.recap import auto as auto_mod

    auto_mod.cancel_pending("sess-a")
    called = {"n": 0}

    def fake_run(*a, **k):
        called["n"] += 1
        return "body"

    with patch.object(auto_mod, "run_auto_recap", side_effect=fake_run):
        auto_mod.schedule_auto_recap(
            "sess-a",
            platform="feishu",
            chat_id="oc_x",
            idle_seconds=0.05,
            min_user_turns=3,
        )
        assert auto_mod.pending_count() == 1
        auto_mod.cancel_pending("sess-a")
        time.sleep(0.12)
        assert called["n"] == 0
        assert auto_mod.pending_count() == 0


def test_schedule_fires_after_idle():
    from owner.explainers.recap import auto as auto_mod

    auto_mod.cancel_pending("sess-b")
    called = {"n": 0, "kwargs": None}

    def fake_run(session_id, **kwargs):
        called["n"] += 1
        called["kwargs"] = {"session_id": session_id, **kwargs}
        return "📋 系统提示：ok"

    with patch.object(auto_mod, "run_auto_recap", side_effect=fake_run):
        auto_mod.schedule_auto_recap(
            "sess-b",
            platform="feishu",
            chat_id="oc_y",
            idle_seconds=0.05,
            min_user_turns=3,
        )
        time.sleep(0.15)
        assert called["n"] == 1
        assert called["kwargs"]["session_id"] == "sess-b"
        assert called["kwargs"]["idle_ok"] is True
        assert auto_mod.pending_count() == 0


def test_run_auto_recap_respects_gate(tmp_path, monkeypatch):
    from owner.explainers.recap import auto as auto_mod
    from owner.explainers.recap import watermark as wm

    monkeypatch.setattr(wm, "_root", lambda: tmp_path)
    msgs = [
        {"role": "user", "content": "一"},
        {"role": "assistant", "content": "a"},
        {"role": "user", "content": "二"},
        {"role": "assistant", "content": "b"},
    ]
    with patch("owner.explainers.recap.command._load_messages", return_value=msgs), patch.object(
        auto_mod, "resolve_enabled", return_value=True
    ), patch.object(auto_mod, "load_auto_config", return_value={"enabled": True, "min_user_turns": 3, "idle_seconds": 180}):
        # only 2 turns → skip
        assert auto_mod.run_auto_recap("s", platform="feishu", chat_id="c", idle_ok=True) is None

    msgs.append({"role": "user", "content": "三"})
    msgs.append({"role": "assistant", "content": "c"})
    with patch("owner.explainers.recap.command._load_messages", return_value=msgs), patch.object(
        auto_mod, "resolve_enabled", return_value=True
    ), patch.object(
        auto_mod, "load_auto_config", return_value={"enabled": True, "min_user_turns": 3, "idle_seconds": 180}
    ), patch.object(auto_mod, "explain_from_messages", return_value="我们做了三件事"), patch.object(
        auto_mod, "_send_notice", return_value=True
    ) as send:
        body = auto_mod.run_auto_recap("s", platform="feishu", chat_id="c", idle_ok=True)
        assert body and body.startswith("📋 系统提示：")
        assert wm.load_recap_watermark("s") == 3
        send.assert_called_once()

    # watermark blocks repeat without new turn
    with patch("owner.explainers.recap.command._load_messages", return_value=msgs), patch.object(
        auto_mod, "resolve_enabled", return_value=True
    ), patch.object(
        auto_mod, "load_auto_config", return_value={"enabled": True, "min_user_turns": 3, "idle_seconds": 180}
    ), patch.object(auto_mod, "_send_notice") as send2:
        assert auto_mod.run_auto_recap("s", platform="feishu", chat_id="c", idle_ok=True) is None
        send2.assert_not_called()


def test_note_manual_recap_bumps_watermark(tmp_path, monkeypatch):
    from owner.explainers.recap import auto as auto_mod
    from owner.explainers.recap import watermark as wm

    monkeypatch.setattr(wm, "_root", lambda: tmp_path)
    msgs = [{"role": "user", "content": "a"}, {"role": "user", "content": "b"}]
    auto_mod.note_manual_recap("m1", msgs)
    assert wm.load_recap_watermark("m1") == 2


def test_on_session_end_schedules_when_routed():
    from owner.explainers.recap import auto as auto_mod

    auto_mod.cancel_pending("sid-1")
    with auto_mod._ROUTE_LOCK:
        auto_mod._SESSION_ROUTES["sid-1"] = ("feishu", "oc_z")
    scheduled = {}

    def fake_sched(sid, **kw):
        scheduled["sid"] = sid
        scheduled.update(kw)

    with patch.object(auto_mod, "resolve_enabled", return_value=True), patch.object(
        auto_mod, "load_auto_config", return_value={"enabled": True, "min_user_turns": 3, "idle_seconds": 1}
    ), patch.object(auto_mod, "schedule_auto_recap", side_effect=fake_sched):
        auto_mod._on_session_end(
            session_id="sid-1",
            completed=True,
            failed=False,
            interrupted=False,
            platform="feishu",
        )
    assert scheduled.get("sid") == "sid-1"
    assert scheduled.get("chat_id") == "oc_z"
