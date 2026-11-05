"""[owner] C13 — explainer notice persist (role=notice) into messages."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def test_notice_kinds_and_role_constants():
    from owner.explainers.persist import NOTICE_KINDS, NOTICE_ROLE

    assert NOTICE_ROLE == "notice"
    assert NOTICE_KINDS == frozenset({"recap", "progress", "english"})


def test_persist_notice_rejects_bad_args(tmp_path, monkeypatch):
    from owner.explainers import persist as persist_mod

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    assert persist_mod.persist_notice("", "recap", "📋 系统提示：x") is None
    assert persist_mod.persist_notice("s1", "approval", "x") is None
    assert persist_mod.persist_notice("s1", "recap", "   ") is None


def test_persist_notice_writes_row_and_provider(tmp_path, monkeypatch):
    from hermes_state import SessionDB
    from owner.explainers.persist import persist_notice

    home = tmp_path / "hermes_home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    db_path = home / "state.db"

    db = SessionDB(db_path=db_path)
    try:
        db.create_session("sess-notice-1", source="test")
        row_id = persist_notice(
            "sess-notice-1",
            "recap",
            "📋 系统提示：做到哪了；下一步接回归。",
            provider="custom:Damodel",
            model="xy-pro",
            task="recap_explainer",
            trigger="manual",
            platform_message_id="om_test_1",
            extra_meta={"user_turns": 4},
            db=db,
        )
        assert isinstance(row_id, int) and row_id > 0

        row = db._read_one(
            "SELECT role, content, display_kind, display_metadata, owner_provider_name, "
            "platform_message_id, active FROM messages WHERE id = ?",
            (row_id,),
        )
        assert row is not None
        assert row["role"] == "notice"
        assert row["display_kind"] == "recap"
        assert row["content"].startswith("📋 系统提示：")
        assert row["owner_provider_name"] == "damodel"
        assert row["platform_message_id"] == "om_test_1"
        assert row["active"] == 1
        meta = json.loads(row["display_metadata"])
        assert meta["explainer_kind"] == "recap"
        assert meta["provider"] == "damodel"
        assert meta["model"] == "xy-pro"
        assert meta["task"] == "recap_explainer"
        assert meta["trigger"] == "manual"
        assert meta["user_turns"] == 4
    finally:
        db.close()


def test_persist_progress_and_english_kinds(tmp_path, monkeypatch):
    from hermes_state import SessionDB
    from owner.explainers.persist import persist_notice

    home = tmp_path / "hermes_home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    db = SessionDB(db_path=home / "state.db")
    try:
        db.create_session("sess-2", source="test")
        pid = persist_notice(
            "sess-2",
            "progress",
            "🧭 系统提示：正在跑契约测试。",
            provider="damodel",
            model="flash",
            trigger="tick",
            db=db,
        )
        eid = persist_notice(
            "sess-2",
            "english",
            "🔤 系统提示：部署已完成。",
            provider="damodel",
            model="flash",
            trigger="reply",
            db=db,
        )
        assert pid and eid
        kinds = {
            r[0]
            for r in db._read_all(
                "SELECT display_kind FROM messages WHERE session_id = ? AND role = 'notice'",
                ("sess-2",),
            )
        }
        assert kinds == {"progress", "english"}
    finally:
        db.close()


def test_notice_excluded_from_model_resume(tmp_path, monkeypatch):
    """get_resume_conversations model_history must drop role=notice.

    Avoid append_message(role=user) here: that path imports conversation_loop /
    hermes_bootstrap and trips the real-home I/O guard in unit tests.
    """
    from hermes_state import SessionDB
    from owner.explainers.persist import persist_notice

    home = tmp_path / "hermes_home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    db = SessionDB(db_path=home / "state.db")
    try:
        db.create_session("sess-3", source="test")
        persist_notice(
            "sess-3",
            "recap",
            "📋 系统提示：回顾正文不应进模型。",
            provider="damodel",
            model="m",
            trigger="manual",
            db=db,
        )
        # Row is durable…
        n = db._read_one(
            "SELECT COUNT(*) AS c FROM messages WHERE session_id = ? AND role = 'notice'",
            ("sess-3",),
        )
        assert int(n["c"]) == 1
        model_hist, _display_hist = db.get_resume_conversations("sess-3")
        assert all(m.get("role") != "notice" for m in model_hist)
    finally:
        db.close()


def test_gateway_history_builder_skips_notice():
    """Sanity: gateway/run.py bookkeeping set includes notice (source contract)."""
    src = Path("gateway/run.py").read_text(encoding="utf-8")
    assert '{"session_meta", "system", "notice"}' in src


def test_tui_history_roles_omit_notice():
    from tui_gateway.session_history import _HISTORY_ROLES

    assert "notice" not in _HISTORY_ROLES
    assert {"user", "assistant", "tool", "system"} <= _HISTORY_ROLES


def test_export_filters_notice():
    src = Path("hermes_cli/session_export.py").read_text(encoding="utf-8")
    assert '"notice"' in src
    html = Path("hermes_cli/session_export_html.py").read_text(encoding="utf-8")
    assert 'role in ("session_meta", "notice")' in html


def test_recap_auto_persists_after_send(tmp_path, monkeypatch):
    from owner.explainers.recap import auto as auto_mod
    from owner.explainers.recap import watermark as wm

    monkeypatch.setattr(wm, "_root", lambda: tmp_path)
    msgs = [
        {"role": "user", "content": "一"},
        {"role": "assistant", "content": "a"},
        {"role": "user", "content": "二"},
        {"role": "assistant", "content": "b"},
        {"role": "user", "content": "三"},
        {"role": "assistant", "content": "c"},
    ]
    persisted = {}

    def fake_persist(sid, kind, body, **kwargs):
        persisted.update({"sid": sid, "kind": kind, "body": body, **kwargs})
        return 99

    with patch("owner.explainers.recap.command._load_messages", return_value=msgs), patch.object(
        auto_mod, "resolve_enabled", return_value=True
    ), patch.object(
        auto_mod,
        "load_auto_config",
        return_value={"enabled": True, "min_user_turns": 3, "idle_seconds": 180},
    ), patch.object(auto_mod, "explain_from_messages", return_value="做到哪了"), patch.object(
        auto_mod, "_send_notice", return_value=True
    ), patch("owner.explainers.persist.persist_notice", side_effect=fake_persist):
        body = auto_mod.run_auto_recap("s-persist", platform="feishu", chat_id="c", idle_ok=True)
        assert body and body.startswith("📋")
        assert persisted.get("kind") == "recap"
        assert persisted.get("sid") == "s-persist"
        assert persisted.get("trigger") == "auto"
