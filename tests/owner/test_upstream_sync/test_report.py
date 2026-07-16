"""Unit tests for owner.sync.report.ReportBuilder."""
from __future__ import annotations

from owner.sync.models import (
    ChangeClassification,
    DimensionResult,
    FingerprintMatch,
    HealthCheckResult,
    MergeResult,
    SyncReport,
    TestResult,
    UpstreamCommit,
)
from owner.sync.report import ReportBuilder


def _commit(h: str, msg: str) -> UpstreamCommit:
    return UpstreamCommit(
        hash=h, short_hash=h[:7], message=msg,
        files=["a.py"], author="dev", date="2025-01-01T00:00:00Z",
    )


def _base_report(**kw) -> SyncReport:
    defaults = dict(
        timestamp="2025-01-01T00:00:00Z",
        pre_merge_head="pre123",
        upstream_head="up456",
        merge_base="base789",
        total_commits=3,
    )
    defaults.update(kw)
    return SyncReport(**defaults)


# ── Success report ─────────────────────────────────────────────────────────


def test_success_report_contains_timestamp_and_commit_count():
    report = _base_report(decision="AUTO_MERGE")
    md = ReportBuilder.build_success_report(report)
    assert "2025-01-01T00:00:00Z" in md
    assert "3" in md  # total_commits


def test_success_report_shows_latest_commit():
    cls = ChangeClassification(
        decision="AUTO_MERGE", dimensions=[],
        upstream_commits=[_commit("aaa111", "fix: latest")],
        total_files_changed=1, total_commits=1,
    )
    report = _base_report(decision="AUTO_MERGE", classification=cls)
    md = ReportBuilder.build_success_report(report)
    assert "aaa111" in md
    assert "fix: latest" in md


def test_success_report_includes_health_and_test():
    report = _base_report(
        decision="AUTO_MERGE",
        health_check=HealthCheckResult(0, True, "ok", "all passed"),
        test_result=TestResult(0, True, "ok", "5 passed"),
    )
    md = ReportBuilder.build_success_report(report)
    assert "all passed" in md
    assert "5 passed" in md


def test_success_report_includes_log_file():
    report = _base_report(decision="AUTO_MERGE", log_file="/path/to/log.md")
    md = ReportBuilder.build_success_report(report)
    assert "/path/to/log.md" in md


# ── Manual review report ──────────────────────────────────────────────────


def test_manual_review_report_contains_reasons():
    cls = ChangeClassification(
        decision="MANUAL_REVIEW",
        dimensions=[
            DimensionResult("D1", "scale", False, "too many files", True),
        ],
        upstream_commits=[_commit("h1", "fix something")],
        total_files_changed=25, total_commits=1,
        reasons=["总改动文件数 25 > 20，触发红线"],
    )
    report = _base_report(decision="MANUAL_REVIEW", classification=cls)
    md = ReportBuilder.build_manual_review_report(report)
    assert "总改动文件数 25 > 20" in md
    assert "D1" in md
    assert "h1" in md


def test_manual_review_report_dimension_table():
    cls = ChangeClassification(
        decision="MANUAL_REVIEW",
        dimensions=[
            DimensionResult("D1", "改动规模", True, "ok", False),
            DimensionResult("D4", "试合并冲突预检", False, "conflict", True),
        ],
        upstream_commits=[], total_files_changed=0, total_commits=0,
    )
    report = _base_report(decision="MANUAL_REVIEW", classification=cls)
    md = ReportBuilder.build_manual_review_report(report)
    assert "| 维度 |" in md
    assert "D1" in md
    assert "D4" in md


def test_manual_review_report_includes_fingerprint_matches():
    fp = FingerprintMatch(
        fingerprint_id="fp-1", fingerprint_title="bug",
        owner_commit="2.2.1", upstream_commit_hash="abcdef123456",
        upstream_commit_message="fix bug",
        file_intersection_rate=0.9, keyword_hit_rate=1.0,
        combined_similarity=0.94, confidence="high",
    )
    cls = ChangeClassification(
        decision="MANUAL_REVIEW", dimensions=[],
        upstream_commits=[], total_files_changed=0, total_commits=0,
        fingerprint_matches=[fp],
    )
    report = _base_report(decision="MANUAL_REVIEW", classification=cls)
    md = ReportBuilder.build_manual_review_report(report)
    assert "fp-1" in md
    assert "高置信度" in md


def test_manual_review_report_shows_d6_failure():
    cls = ChangeClassification(
        decision="MANUAL_REVIEW", dimensions=[],
        upstream_commits=[], total_files_changed=0, total_commits=0,
    )
    report = _base_report(
        decision="MANUAL_REVIEW", classification=cls,
        health_check=HealthCheckResult(1, False, "FAIL output", "1 check failed"),
    )
    md = ReportBuilder.build_manual_review_report(report)
    assert "D6" in md
    assert "1 check failed" in md


def test_manual_review_report_shows_d7_failure():
    cls = ChangeClassification(
        decision="MANUAL_REVIEW", dimensions=[],
        upstream_commits=[], total_files_changed=0, total_commits=0,
    )
    report = _base_report(
        decision="MANUAL_REVIEW", classification=cls,
        test_result=TestResult(1, False, "2 failed", "2 failed, 3 passed"),
    )
    md = ReportBuilder.build_manual_review_report(report)
    assert "D7" in md
    assert "2 failed, 3 passed" in md


def test_manual_review_report_includes_resolve_command():
    cls = ChangeClassification(
        decision="MANUAL_REVIEW", dimensions=[],
        upstream_commits=[], total_files_changed=0, total_commits=0,
    )
    report = _base_report(decision="MANUAL_REVIEW", classification=cls)
    md = ReportBuilder.build_manual_review_report(report)
    assert "--resolve" in md


def test_manual_review_report_shows_conflict_files():
    cls = ChangeClassification(
        decision="MANUAL_REVIEW", dimensions=[],
        upstream_commits=[], total_files_changed=0, total_commits=0,
    )
    report = _base_report(
        decision="MANUAL_REVIEW", classification=cls,
        merge_result=MergeResult(False, "conflict", ["a.py", "b.py"]),
    )
    md = ReportBuilder.build_manual_review_report(report)
    assert "a.py" in md
    assert "b.py" in md


# ── Error report ───────────────────────────────────────────────────────────


def test_error_report_contains_decision_and_error():
    report = _base_report(decision="ERROR", error="git fetch failed")
    md = ReportBuilder.build_error_report(report)
    assert "ERROR" in md
    assert "git fetch failed" in md


def test_error_report_skipped_pending_review():
    report = _base_report(
        decision="SKIPPED", error="存在 pending review，请先执行 --resolve 后再运行"
    )
    md = ReportBuilder.build_error_report(report)
    assert "pending review" in md.lower()
    assert "--resolve" in md


def test_error_report_skipped_dirty_workdir():
    report = _base_report(
        decision="SKIPPED", error="工作区不干净（存在未提交改动），跳过本轮同步"
    )
    md = ReportBuilder.build_error_report(report)
    assert "工作区" in md
