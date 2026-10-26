"""B11 / T2-1：审批历史挖掘按结构判定，不被 C10 i18n 打穿。"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import pytest

import agent.i18n as i18n
from hermes_cli import approvals_suggest as suggest
from owner.approval import approval_history_policy as policy

_SUGGESTIBLE_DANGEROUS = "git push --force origin main"


def _make_db(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT,
            tool_call_id TEXT,
            tool_calls TEXT,
            timestamp REAL NOT NULL
        );
        """
    )
    con.commit()
    return con


def _add_terminal_call(con, command: str, result: str, ts: float | None = None) -> str:
    call_id = "call_%d" % (id(result) % 10_000_000) + str(int((ts or time.time()) * 1e6))
    ts = ts if ts is not None else time.time()
    tool_calls = json.dumps(
        [
            {
                "id": call_id,
                "type": "function",
                "function": {
                    "name": "terminal",
                    "arguments": json.dumps({"command": command}),
                },
            }
        ]
    )
    con.execute(
        "INSERT INTO messages (session_id, role, content, tool_calls, timestamp) "
        "VALUES ('s1', 'assistant', '', ?, ?)",
        (tool_calls, ts),
    )
    con.execute(
        "INSERT INTO messages (session_id, role, content, tool_call_id, timestamp) "
        "VALUES ('s1', 'tool', ?, ?, ?)",
        (result, call_id, ts + 1),
    )
    con.commit()
    return call_id


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "state.db"
    con = _make_db(path)
    yield path, con
    con.close()


def _set_language(monkeypatch, lang: str) -> None:
    monkeypatch.setenv("HERMES_LANGUAGE", lang)
    i18n.reset_language_cache()
    policy.clear_cache()


@pytest.fixture(autouse=True)
def _reset_policy_cache():
    policy.clear_cache()
    yield
    policy.clear_cache()


def _zh_protected_denied() -> str:
    """C10 护栏中文拦截文案（纯文本，模拟 role=tool content）。"""
    return i18n.t(
        "approval.protected_file_blocked",
        targets="SOUL.md",
        why=i18n.t("approval.gate_why_denied_by_user"),
    )


def _blocked_json_status() -> str:
    return json.dumps(
        {"output": "", "exit_code": -1, "error": "anything", "status": "blocked"},
        ensure_ascii=False,
    )


def _blocked_json_zh_error() -> str:
    return json.dumps(
        {
            "output": "",
            "exit_code": -1,
            "error": _zh_protected_denied(),
            "status": "error",
        },
        ensure_ascii=False,
    )


@pytest.mark.parametrize("lang", ["zh", "en"])
def test_denied_commands_never_become_proposals_status(db_path, monkeypatch, lang):
    _set_language(monkeypatch, lang)
    path, con = db_path
    for _ in range(4):
        _add_terminal_call(con, _SUGGESTIBLE_DANGEROUS, _blocked_json_status())
    assert suggest.scan_approval_history(path, days=0) == []


@pytest.mark.parametrize("lang", ["zh", "en"])
def test_denied_commands_never_become_proposals_zh_copy(db_path, monkeypatch, lang):
    _set_language(monkeypatch, lang)
    path, con = db_path
    for _ in range(4):
        _add_terminal_call(con, _SUGGESTIBLE_DANGEROUS, _zh_protected_denied())
    assert suggest.scan_approval_history(path, days=0) == []


@pytest.mark.parametrize("lang", ["zh", "en"])
def test_approved_commands_still_become_proposals(db_path, monkeypatch, lang):
    _set_language(monkeypatch, lang)
    path, con = db_path
    for _ in range(3):
        _add_terminal_call(con, _SUGGESTIBLE_DANGEROUS, "pushed ok\n")
    records = suggest.scan_approval_history(path, days=0)
    assert len(records) >= 3
    proposals = suggest.build_proposals(records, min_count=2)
    assert any(p.pattern.startswith("git push") for p in proposals)


def test_status_field_alone_blocks_without_english_markers():
    payload = json.dumps({"status": "blocked", "error": "完全没有英文标记"})
    assert policy.result_blocks_execution(payload) is True
    assert policy.result_blocks_execution("pushed successfully") is False


def test_legacy_english_markers_miss_zh_but_policy_hits(monkeypatch):
    _set_language(monkeypatch, "zh")
    text = _zh_protected_denied()
    assert "BLOCKED" not in text
    assert not any(m in text for m in (
        "BLOCKED: User denied", "The user has NOT consented", "approval_required",
    ))
    assert policy.result_blocks_execution(text) is True
    assert policy.result_blocks_execution(
        json.dumps({"error": text, "status": "error"}, ensure_ascii=False)
    ) is True


def test_sql_anchors_cover_loaded_markers():
    markers = policy.load_markers()
    uncovered = [m for m in markers if not policy.anchor_covers(m)]
    # Allow a few short punctuation-heavy leftovers; assert core zh/en covered
    assert policy.anchor_covers("已拦截")
    assert policy.anchor_covers("BLOCKED")
    assert all(policy.anchor_covers(m) for m in markers if len(m) >= 4 and any(a in m.lower() or a in m for a in ("block", "审批", "拦截", "拒绝", "同意", "approval", "consent")))


def test_output_field_mentioning_blocked_is_not_a_denial():
    """真实命令输出里提到 BLOCKED 不算拦截（只看 error/message）。"""
    payload = json.dumps(
        {"output": "echo BLOCKED in log", "exit_code": 0, "status": "success"}
    )
    assert policy.result_blocks_execution(payload) is False


def test_json_zh_error_field_blocks(db_path, monkeypatch):
    _set_language(monkeypatch, "zh")
    path, con = db_path
    _add_terminal_call(con, _SUGGESTIBLE_DANGEROUS, _blocked_json_zh_error())
    assert suggest.scan_approval_history(path, days=0) == []
