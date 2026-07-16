"""Unit tests for owner.sync.models dataclasses."""
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


# ── UpstreamCommit ──────────────────────────────────────────────────────────


def test_upstream_commit_instantiation():
    c = UpstreamCommit(
        hash="abc123def456",
        short_hash="abc123d",
        message="fix: crash on startup",
        files=["a.py", "b.py"],
        author="dev",
        date="2025-01-01T00:00:00Z",
    )
    assert c.hash == "abc123def456"
    assert c.short_hash == "abc123d"
    assert c.files == ["a.py", "b.py"]


def test_upstream_commit_empty_files():
    c = UpstreamCommit(hash="h", short_hash="s", message="m", files=[], author="a", date="d")
    assert c.files == []


# ── DimensionResult ─────────────────────────────────────────────────────────


def test_dimension_result_default_triggered_red_line():
    d = DimensionResult(dimension="D1", name="scale", passed=True, details="ok")
    assert d.triggered_red_line is False


def test_dimension_result_triggered_red_line_explicit():
    d = DimensionResult(
        dimension="D1", name="scale", passed=False, details="too many",
        triggered_red_line=True,
    )
    assert d.triggered_red_line is True


# ── FingerprintMatch ────────────────────────────────────────────────────────


def test_fingerprint_match_fields():
    m = FingerprintMatch(
        fingerprint_id="fp-1",
        fingerprint_title="bug fix",
        owner_commit="2.2.1",
        upstream_commit_hash="abc",
        upstream_commit_message="fix bug",
        file_intersection_rate=0.9,
        keyword_hit_rate=0.5,
        combined_similarity=0.74,
        confidence="medium",
    )
    assert m.fingerprint_id == "fp-1"
    assert m.confidence == "medium"


# ── ChangeClassification ────────────────────────────────────────────────────


def test_change_classification_defaults():
    c = ChangeClassification(
        decision="AUTO_MERGE",
        dimensions=[],
        upstream_commits=[],
        total_files_changed=5,
        total_commits=2,
    )
    assert c.reasons == []
    assert c.fingerprint_matches == []


def test_change_classification_with_data():
    dims = [DimensionResult(dimension="D1", name="x", passed=True, details="ok")]
    c = ChangeClassification(
        decision="MANUAL_REVIEW",
        dimensions=dims,
        upstream_commits=[],
        total_files_changed=30,
        total_commits=3,
        reasons=["too many files"],
    )
    assert c.decision == "MANUAL_REVIEW"
    assert len(c.dimensions) == 1


# ── MergeResult ─────────────────────────────────────────────────────────────


def test_merge_result_default_conflict_files():
    m = MergeResult(success=True, output="merged")
    assert m.conflict_files == []


def test_merge_result_with_conflicts():
    m = MergeResult(success=False, output="conflict", conflict_files=["a.py", "b.py"])
    assert m.conflict_files == ["a.py", "b.py"]


# ── HealthCheckResult / TestResult ──────────────────────────────────────────


def test_health_check_result():
    h = HealthCheckResult(exit_code=0, passed=True, output="ok", summary="all good")
    assert h.passed is True
    assert h.exit_code == 0


def test_test_result():
    t = TestResult(exit_code=1, passed=False, output="fail", summary="2 failed")
    assert t.passed is False


# ── SyncReport ──────────────────────────────────────────────────────────────


def test_sync_report_defaults():
    r = SyncReport(
        timestamp="2025-01-01T00:00:00Z",
        pre_merge_head="head123",
        upstream_head="up456",
        merge_base="base789",
        total_commits=3,
    )
    assert r.decision == "SKIPPED"
    assert r.classification is None
    assert r.merge_result is None
    assert r.health_check is None
    assert r.test_result is None
    assert r.rolled_back is False
    assert r.log_file == ""
    assert r.error is None


def test_sync_report_full():
    r = SyncReport(
        timestamp="2025-01-01T00:00:00Z",
        pre_merge_head="h",
        upstream_head="u",
        merge_base="b",
        total_commits=1,
        decision="AUTO_MERGE",
        rolled_back=False,
    )
    assert r.decision == "AUTO_MERGE"
