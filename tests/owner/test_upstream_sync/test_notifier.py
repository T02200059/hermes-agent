"""Unit tests for owner.sync.notifier."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from owner.sync.config import SyncConfig
from owner.sync.models import (
    ChangeClassification,
    SyncReport,
)
from owner.sync.notifier import FeishuNotifier, LogNotifier, Notifier, build_notifiers
from tests.owner.test_upstream_sync.conftest import build_raw_config, write_config_yaml


def _report(**kw) -> SyncReport:
    defaults = dict(
        timestamp="2025-01-01T00:00:00Z",
        pre_merge_head="pre", upstream_head="up",
        merge_base="base", total_commits=2,
    )
    defaults.update(kw)
    return SyncReport(**defaults)


# ── LogNotifier ────────────────────────────────────────────────────────────


def test_log_notifier_creates_log_dir(tmp_path: Path):
    cfg = SyncConfig(build_raw_config(tmp_path))
    notifier = LogNotifier(cfg)
    assert cfg.log_dir.exists()


def test_log_notifier_notify_success_writes_md_and_jsonl(tmp_path: Path):
    cfg = SyncConfig(build_raw_config(tmp_path))
    notifier = LogNotifier(cfg)
    report = _report(decision="AUTO_MERGE")
    notifier.notify_success(report)

    md_file = cfg.log_dir / "2025-01-01-auto.md"
    jsonl_file = cfg.log_dir / "2025-01-01.jsonl"
    assert md_file.exists()
    assert jsonl_file.exists()

    md_content = md_file.read_text(encoding="utf-8")
    assert "上游同步完成" in md_content

    jsonl_line = jsonl_file.read_text(encoding="utf-8").strip()
    record = json.loads(jsonl_line)
    assert record["decision"] == "AUTO_MERGE"
    assert record["total_commits"] == 2


def test_log_notifier_notify_manual_review(tmp_path: Path):
    cfg = SyncConfig(build_raw_config(tmp_path))
    notifier = LogNotifier(cfg)
    cls = ChangeClassification(
        decision="MANUAL_REVIEW", dimensions=[],
        upstream_commits=[], total_files_changed=0, total_commits=1,
        reasons=["D4 conflict"],
    )
    report = _report(decision="MANUAL_REVIEW", classification=cls)
    notifier.notify_manual_review(report)

    md_file = cfg.log_dir / "2025-01-01-manual-review.md"
    assert md_file.exists()
    content = md_file.read_text(encoding="utf-8")
    assert "人工确认" in content
    # log_file should be set on the report.
    assert report.log_file != ""


def test_log_notifier_notify_error(tmp_path: Path):
    cfg = SyncConfig(build_raw_config(tmp_path))
    notifier = LogNotifier(cfg)
    report = _report(decision="ERROR", error="something broke")
    notifier.notify_error(report)

    md_file = cfg.log_dir / "2025-01-01-error.md"
    assert md_file.exists()
    content = md_file.read_text(encoding="utf-8")
    assert "something broke" in content


def test_log_notifier_jsonl_appends_multiple_runs(tmp_path: Path):
    cfg = SyncConfig(build_raw_config(tmp_path))
    notifier = LogNotifier(cfg)
    notifier.notify_success(_report(decision="AUTO_MERGE"))
    notifier.notify_error(_report(decision="ERROR", error="oops"))

    jsonl_file = cfg.log_dir / "2025-01-01.jsonl"
    lines = [l for l in jsonl_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 2
    records = [json.loads(l) for l in lines]
    assert records[0]["decision"] == "AUTO_MERGE"
    assert records[1]["decision"] == "ERROR"


def test_log_notifier_jsonl_includes_classification_fields(tmp_path: Path):
    from owner.sync.models import (
        DimensionResult, FingerprintMatch, HealthCheckResult, TestResult,
    )
    cfg = SyncConfig(build_raw_config(tmp_path))
    notifier = LogNotifier(cfg)
    fp = FingerprintMatch(
        fingerprint_id="fp-1", fingerprint_title="bug", owner_commit="2.2.1",
        upstream_commit_hash="abc", upstream_commit_message="fix",
        file_intersection_rate=1.0, keyword_hit_rate=1.0,
        combined_similarity=0.95, confidence="high",
    )
    cls = ChangeClassification(
        decision="MANUAL_REVIEW",
        dimensions=[DimensionResult("D4", "试合并", False, "conflict", True)],
        upstream_commits=[], total_files_changed=5, total_commits=3,
        fingerprint_matches=[fp],
    )
    report = _report(decision="MANUAL_REVIEW", classification=cls,
                     health_check=HealthCheckResult(1, False, "fail", "check failed"),
                     test_result=TestResult(0, True, "ok", "all passed"))
    notifier.notify_manual_review(report)

    jsonl_file = cfg.log_dir / "2025-01-01.jsonl"
    record = json.loads(jsonl_file.read_text(encoding="utf-8").strip())
    assert record["classification_decision"] == "MANUAL_REVIEW"
    assert record["fingerprint_matches"] == 1
    assert record["health_check_passed"] is False
    assert record["test_passed"] is True


# ── FeishuNotifier ─────────────────────────────────────────────────────────


def test_feishu_notifier_methods_are_noop(tmp_path: Path):
    raw = build_raw_config(tmp_path)
    raw["notification"]["feishu_webhook"] = "https://example.com/hook"
    cfg = SyncConfig(raw)
    notifier = FeishuNotifier(cfg)
    assert notifier.webhook_url == "https://example.com/hook"
    # All methods should be no-ops (no exception, no side effect).
    notifier.notify_success(_report())
    notifier.notify_manual_review(_report())
    notifier.notify_error(_report())


# ── build_notifiers ────────────────────────────────────────────────────────


def test_build_notifiers_log_only_when_no_webhook(tmp_path: Path):
    cfg = SyncConfig(build_raw_config(tmp_path))
    notifiers = build_notifiers(cfg)
    assert len(notifiers) == 1
    assert isinstance(notifiers[0], LogNotifier)


def test_build_notifiers_includes_feishu_when_webhook_set(tmp_path: Path):
    raw = build_raw_config(tmp_path)
    raw["notification"]["feishu_webhook"] = "https://example.com/hook"
    cfg = SyncConfig(raw)
    notifiers = build_notifiers(cfg)
    assert len(notifiers) == 2
    assert isinstance(notifiers[0], LogNotifier)
    assert isinstance(notifiers[1], FeishuNotifier)


# ── Notifier ABC ───────────────────────────────────────────────────────────


def test_notifier_abc_cannot_instantiate():
    with pytest.raises(TypeError):
        Notifier()  # type: ignore[abstract]


# ── _date_str fallback ─────────────────────────────────────────────────────


def test_date_str_fallback_on_empty_timestamp(tmp_path: Path):
    cfg = SyncConfig(build_raw_config(tmp_path))
    notifier = LogNotifier(cfg)
    report = _report(timestamp="")
    notifier.notify_success(report)
    # Should still produce a jsonl file with today's date.
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert (cfg.log_dir / f"{today}.jsonl").exists()
