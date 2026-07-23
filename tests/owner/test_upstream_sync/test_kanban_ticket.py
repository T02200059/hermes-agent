"""Unit tests for K0 kanban ticket opener."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from owner.sync.config import SyncConfig
from owner.sync.kanban_ticket import (
    KanbanTicketOpener,
    _parse_create_json,
)
from owner.sync.models import (
    ChangeClassification,
    DimensionResult,
    SyncReport,
)
from tests.owner.test_upstream_sync.conftest import build_raw_config


def _manual_report(**kwargs) -> SyncReport:
    cls = ChangeClassification(
        decision="MANUAL_REVIEW",
        dimensions=[
            DimensionResult(
                "D3", "重度侵入文件触及", False,
                "触及 gateway/run.py", True,
            ),
        ],
        upstream_commits=[],
        total_files_changed=1,
        total_commits=3,
        reasons=["触及 gateway/run.py"],
    )
    base = dict(
        timestamp="2026-07-16T11:00:00Z",
        pre_merge_head="aaa111",
        upstream_head="bbb222ccc333ddd",
        merge_base="base00",
        total_commits=3,
        decision="MANUAL_REVIEW",
        classification=cls,
    )
    base.update(kwargs)
    return SyncReport(**base)


def test_parse_create_json_flat_id():
    tid, reused = _parse_create_json('{"id": "t_abc", "status": "blocked"}')
    assert tid == "t_abc"
    assert reused is False


def test_parse_create_json_nested_and_noise():
    out = 'log line\n{"task": {"id": "t_nested"}, "reused": true}\n'
    tid, reused = _parse_create_json(out)
    assert tid == "t_nested"
    assert reused is True


def test_maybe_open_disabled_returns_none(tmp_path: Path):
    raw = build_raw_config(tmp_path)
    raw["kanban"] = {"enabled": False}
    cfg = SyncConfig(raw)
    opener = KanbanTicketOpener(cfg)
    assert opener.maybe_open(_manual_report()) is None


def test_maybe_open_skips_auto_merge(tmp_path: Path):
    raw = build_raw_config(tmp_path)
    raw["kanban"] = {
        "enabled": True,
        "workspace": str(tmp_path / "ws"),
        "create_on": ["MANUAL_REVIEW"],
    }
    cfg = SyncConfig(raw)
    opener = KanbanTicketOpener(cfg)
    report = _manual_report(decision="AUTO_MERGE")
    report.decision = "AUTO_MERGE"
    assert opener.maybe_open(report) is None


def test_open_for_report_writes_workspace_and_parses_id(tmp_path: Path):
    ws = tmp_path / "ws"
    raw = build_raw_config(tmp_path)
    raw["kanban"] = {
        "enabled": True,
        "workspace": str(ws),
        "tenant": "owner-upstream-sync",
        "assignee": "",
        "initial_status": "blocked",
        "hermes_bin": "hermes",
    }
    cfg = SyncConfig(raw)
    opener = KanbanTicketOpener(cfg)

    fake = MagicMock()
    fake.returncode = 0
    fake.stdout = '{"id": "t_k0test01", "status": "blocked"}\n'
    fake.stderr = ""

    with patch("owner.sync.kanban_ticket.shutil.which", return_value="/bin/hermes"), \
         patch("owner.sync.kanban_ticket.subprocess.run", return_value=fake) as run:
        result = opener.open_for_report(_manual_report())

    assert result.task_id == "t_k0test01"
    assert result.created is True
    assert result.error is None
    assert (ws / "latest-task.json").is_file()
    assert list(ws.glob("*-manual-review.md"))
    assert list(ws.glob("*-meta.json"))
    # hermes kanban create ... --initial-status blocked --json
    cmd = run.call_args[0][0]
    assert cmd[0] == "hermes"
    assert "kanban" in cmd and "create" in cmd
    assert "--initial-status" in cmd
    assert "blocked" in cmd
    assert "--idempotency-key" in cmd
    assert any(a.startswith("owner-upstream-") for a in cmd)


def test_open_for_report_hermes_missing(tmp_path: Path):
    raw = build_raw_config(tmp_path)
    raw["kanban"] = {
        "enabled": True,
        "workspace": str(tmp_path / "ws"),
        "hermes_bin": "hermes-not-real-bin",
    }
    cfg = SyncConfig(raw)
    opener = KanbanTicketOpener(cfg)
    with patch("owner.sync.kanban_ticket.shutil.which", return_value=None):
        result = opener.open_for_report(_manual_report())
    assert result.task_id is None
    assert result.error and "not found" in result.error
