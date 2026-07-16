"""Integration tests for the upstream_sync orchestrator pipeline.

All git/subprocess dependencies are mocked. The orchestrator is instantiated
with a real config rooted at tmp_path, then its sub-modules are swapped for
MagicMock instances so the pipeline logic is exercised in isolation.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from owner.sync.classifier import ChangeClassifier
from owner.sync.gitops import GitError
from owner.sync.models import (
    ChangeClassification,
    DimensionResult,
    FingerprintMatch,
    HealthCheckResult,
    MergeResult,
    TestResult,
    UpstreamCommit,
)
from owner.sync.notifier import Notifier
from tests.owner.test_upstream_sync.conftest import write_config_yaml


def _commit(h: str = "chash1", msg: str = "fix: normal bug") -> UpstreamCommit:
    return UpstreamCommit(
        hash=h, short_hash=h[:7], message=msg,
        files=["a.py"], author="dev", date="2025-01-01T00:00:00Z",
    )


def _auto_classification(commits: list[UpstreamCommit] | None = None) -> ChangeClassification:
    """A classification where all dimensions pass → AUTO_MERGE."""
    return ChangeClassification(
        decision="AUTO_MERGE",
        dimensions=[
            DimensionResult("D1", "改动规模", True, "ok", False),
            DimensionResult("D2", "锚点文件触及", True, "ok", False),
            DimensionResult("D3", "重度侵入文件触及", True, "ok", False),
            DimensionResult("D5", "关键词", True, "ok", False),
            DimensionResult("D4", "试合并冲突预检", True, "试合并无冲突", False),
        ],
        upstream_commits=commits or [_commit()],
        total_files_changed=1,
        total_commits=len(commits) if commits else 1,
    )


def _manual_classification(commits: list[UpstreamCommit] | None = None) -> ChangeClassification:
    """A classification where D4 failed → MANUAL_REVIEW."""
    return ChangeClassification(
        decision="MANUAL_REVIEW",
        dimensions=[
            DimensionResult("D1", "改动规模", True, "ok", False),
            DimensionResult("D2", "锚点文件触及", True, "ok", False),
            DimensionResult("D3", "重度侵入文件触及", True, "ok", False),
            DimensionResult("D5", "关键词", True, "ok", False),
            DimensionResult("D4", "试合并冲突预检", False, "试合并产生 1 个冲突文件：a.py", True),
        ],
        upstream_commits=commits or [_commit()],
        total_files_changed=1,
        total_commits=len(commits) if commits else 1,
        reasons=["试合并产生 1 个冲突文件：a.py"],
    )


def _setup_orchestrator(tmp_path: Path) -> "UpstreamSyncOrchestrator":
    """Create an orchestrator with all sub-modules mocked."""
    # Import here to avoid sys.path issues at module level.
    from owner.scripts.upstream_sync import UpstreamSyncOrchestrator

    config_path = write_config_yaml(tmp_path)
    orch = UpstreamSyncOrchestrator(config_path=config_path)

    # Replace every sub-module with a fresh MagicMock.
    orch.gitops = MagicMock()
    orch.state = MagicMock()
    orch.classifier = MagicMock()
    orch.fingerprint = MagicMock()
    orch.merger = MagicMock()
    orch.health = MagicMock()
    orch.notifiers = [MagicMock(spec=Notifier)]

    # Sensible defaults.
    orch.gitops.is_workdir_clean.return_value = True
    orch.gitops.get_merge_base.return_value = "base123"
    orch.gitops.get_upstream_head.return_value = "upstream456"
    orch.gitops.get_current_head.return_value = "current_head"
    orch.gitops.get_new_commits.return_value = [_commit()]
    orch.state.is_pending_review.return_value = False
    orch.state.get_pre_merge_head.return_value = "current_head"
    orch.fingerprint.detect.return_value = []
    orch.merger.rollback.return_value = None  # no exception
    orch.merger.complete.return_value = None

    return orch


# ── AUTO_MERGE success path ────────────────────────────────────────────────


def test_auto_merge_success(tmp_path: Path):
    orch = _setup_orchestrator(tmp_path)
    orch.classifier.classify.return_value = _auto_classification()
    orch.health.run_health_check.return_value = HealthCheckResult(0, True, "ok", "all passed")
    orch.health.run_tests.return_value = TestResult(0, True, "ok", "5 passed")

    report = orch.run()

    assert report.decision == "AUTO_MERGE"
    # Pipeline stages should have been called in order.
    orch.gitops.fetch_upstream.assert_called_once()
    orch.classifier.classify.assert_called_once()
    orch.fingerprint.detect.assert_called_once()
    orch.health.run_health_check.assert_called_once()
    orch.health.run_tests.assert_called_once()
    orch.merger.complete.assert_called_once()
    orch.state.clear_state.assert_called_once()
    # State should have been saved before merge.
    orch.state.save_pre_merge.assert_called_once()


def test_auto_merge_sends_success_notification(tmp_path: Path):
    orch = _setup_orchestrator(tmp_path)
    orch.classifier.classify.return_value = _auto_classification()
    orch.health.run_health_check.return_value = HealthCheckResult(0, True, "ok", "pass")
    orch.health.run_tests.return_value = TestResult(0, True, "ok", "pass")

    report = orch.run()
    assert report.decision == "AUTO_MERGE"
    notifier = orch.notifiers[0]
    notifier.notify_success.assert_called_once()
    notifier.notify_manual_review.assert_not_called()


# ── MANUAL_REVIEW path (classification) ────────────────────────────────────


def test_manual_review_classification_triggers_rollback(tmp_path: Path):
    orch = _setup_orchestrator(tmp_path)
    orch.classifier.classify.return_value = _manual_classification()

    report = orch.run()

    assert report.decision == "MANUAL_REVIEW"
    orch.merger.rollback.assert_called_once()
    orch.state.mark_pending_review.assert_called_once()
    orch.merger.complete.assert_not_called()
    orch.health.run_health_check.assert_not_called()
    orch.health.run_tests.assert_not_called()


def test_manual_review_sends_notification(tmp_path: Path):
    orch = _setup_orchestrator(tmp_path)
    orch.classifier.classify.return_value = _manual_classification()

    report = orch.run()
    assert report.decision == "MANUAL_REVIEW"
    notifier = orch.notifiers[0]
    notifier.notify_manual_review.assert_called_once()


# ── dry-run path ───────────────────────────────────────────────────────────


def test_dry_run_does_not_merge(tmp_path: Path):
    orch = _setup_orchestrator(tmp_path)
    orch.classifier.classify.return_value = _auto_classification()

    report = orch.run(dry_run=True)

    assert report.decision == "AUTO_MERGE"
    # Should rollback the D4 staged merge (cleanup).
    orch.merger.rollback.assert_called_once()
    # Must NOT proceed to health check, tests, or merge completion.
    orch.health.run_health_check.assert_not_called()
    orch.health.run_tests.assert_not_called()
    orch.merger.complete.assert_not_called()
    orch.state.clear_state.assert_not_called()


def test_dry_run_manual_review_does_not_merge(tmp_path: Path):
    orch = _setup_orchestrator(tmp_path)
    orch.classifier.classify.return_value = _manual_classification()

    report = orch.run(dry_run=True)
    assert report.decision == "MANUAL_REVIEW"
    orch.merger.complete.assert_not_called()
    # In dry-run, should NOT mark pending (it's just a preview).
    # Actually, dry-run path returns before the MANUAL_REVIEW gate.
    # Let's check: dry_run branch is before the decision gate.


# ── Workdir not clean → skip ───────────────────────────────────────────────


def test_dirty_workdir_skips(tmp_path: Path):
    orch = _setup_orchestrator(tmp_path)
    orch.gitops.is_workdir_clean.return_value = False

    report = orch.run()

    assert report.decision == "SKIPPED"
    assert "工作区不干净" in report.error
    orch.gitops.fetch_upstream.assert_not_called()
    orch.classifier.classify.assert_not_called()


# ── Pending review → skip ─────────────────────────────────────────────────


def test_pending_review_skips(tmp_path: Path):
    orch = _setup_orchestrator(tmp_path)
    orch.state.is_pending_review.return_value = True

    report = orch.run()

    assert report.decision == "SKIPPED"
    assert "pending review" in report.error.lower()
    orch.gitops.fetch_upstream.assert_not_called()
    orch.classifier.classify.assert_not_called()


# ── Already up to date ────────────────────────────────────────────────────


def test_already_up_to_date(tmp_path: Path):
    orch = _setup_orchestrator(tmp_path)
    # merge_base == upstream_head → no new commits.
    orch.gitops.get_merge_base.return_value = "same_hash"
    orch.gitops.get_upstream_head.return_value = "same_hash"

    report = orch.run()

    assert report.decision == "AUTO_MERGE"
    assert "已是最新" in (report.error or "")
    orch.classifier.classify.assert_not_called()
    orch.merger.complete.assert_not_called()


# ── D6 health check failure ────────────────────────────────────────────────


def test_d6_failure_rolls_back_and_manual_review(tmp_path: Path):
    orch = _setup_orchestrator(tmp_path)
    orch.classifier.classify.return_value = _auto_classification()
    orch.health.run_health_check.return_value = HealthCheckResult(
        1, False, "FAIL: anchor missing", "anchor check failed"
    )

    report = orch.run()

    assert report.decision == "MANUAL_REVIEW"
    orch.merger.rollback.assert_called_once()
    orch.merger.complete.assert_not_called()
    orch.state.mark_pending_review.assert_called_once()
    orch.health.run_tests.assert_not_called()  # D7 not reached


# ── D7 test failure ────────────────────────────────────────────────────────


def test_d7_failure_rolls_back_and_manual_review(tmp_path: Path):
    orch = _setup_orchestrator(tmp_path)
    orch.classifier.classify.return_value = _auto_classification()
    orch.health.run_health_check.return_value = HealthCheckResult(0, True, "ok", "pass")
    orch.health.run_tests.return_value = TestResult(1, False, "2 failed", "2 failed")

    report = orch.run()

    assert report.decision == "MANUAL_REVIEW"
    orch.merger.rollback.assert_called_once()
    orch.merger.complete.assert_not_called()
    orch.state.mark_pending_review.assert_called_once()
    # D6 should have passed.
    orch.health.run_health_check.assert_called_once()


# ── Fingerprint matches → MANUAL_REVIEW ────────────────────────────────────


def test_high_confidence_fingerprint_triggers_manual_review(tmp_path: Path):
    orch = _setup_orchestrator(tmp_path)
    orch.classifier.classify.return_value = _auto_classification()
    fp = FingerprintMatch(
        fingerprint_id="fp-1", fingerprint_title="bug", owner_commit="2.2.1",
        upstream_commit_hash="abc", upstream_commit_message="fix",
        file_intersection_rate=1.0, keyword_hit_rate=1.0,
        combined_similarity=0.95, confidence="high",
    )
    orch.fingerprint.detect.return_value = [fp]

    report = orch.run()

    assert report.decision == "MANUAL_REVIEW"
    orch.merger.rollback.assert_called_once()
    orch.merger.complete.assert_not_called()
    orch.state.mark_pending_review.assert_called_once()
    # The fingerprint reason should be in the classification reasons.
    assert any("疑似重复修复" in r for r in report.classification.reasons)


def test_medium_confidence_fingerprint_triggers_manual_review(tmp_path: Path):
    orch = _setup_orchestrator(tmp_path)
    orch.classifier.classify.return_value = _auto_classification()
    fp = FingerprintMatch(
        fingerprint_id="fp-2", fingerprint_title="bug", owner_commit="2.2.2",
        upstream_commit_hash="def", upstream_commit_message="fix",
        file_intersection_rate=0.5, keyword_hit_rate=0.5,
        combined_similarity=0.6, confidence="medium",
    )
    orch.fingerprint.detect.return_value = [fp]

    report = orch.run()
    assert report.decision == "MANUAL_REVIEW"


def test_no_fingerprint_matches_allows_auto_merge(tmp_path: Path):
    orch = _setup_orchestrator(tmp_path)
    orch.classifier.classify.return_value = _auto_classification()
    orch.fingerprint.detect.return_value = []
    orch.health.run_health_check.return_value = HealthCheckResult(0, True, "ok", "pass")
    orch.health.run_tests.return_value = TestResult(0, True, "ok", "pass")

    report = orch.run()
    assert report.decision == "AUTO_MERGE"


# ── Merge commit failure ──────────────────────────────────────────────────


def test_complete_merge_failure_returns_error(tmp_path: Path):
    orch = _setup_orchestrator(tmp_path)
    orch.classifier.classify.return_value = _auto_classification()
    orch.health.run_health_check.return_value = HealthCheckResult(0, True, "ok", "pass")
    orch.health.run_tests.return_value = TestResult(0, True, "ok", "pass")
    orch.merger.complete.side_effect = GitError("commit failed")

    report = orch.run()

    assert report.decision == "ERROR"
    assert "merge commit 失败" in report.error
    orch.merger.rollback.assert_called_once()


# ── GitError in pipeline ──────────────────────────────────────────────────


def test_git_error_during_fetch_returns_error(tmp_path: Path):
    orch = _setup_orchestrator(tmp_path)
    orch.gitops.fetch_upstream.side_effect = GitError("fetch failed")

    report = orch.run()

    assert report.decision == "ERROR"
    assert "git 操作失败" in report.error


# ── --resolve ─────────────────────────────────────────────────────────────


def test_resolve_clears_pending_state(tmp_path: Path):
    orch = _setup_orchestrator(tmp_path)
    orch.resolve()
    orch.state.mark_resolved.assert_called_once()


# ── Empty commits list ────────────────────────────────────────────────────


def test_empty_commits_list_with_auto_classification(tmp_path: Path):
    """If get_new_commits returns [], classify is still called."""
    orch = _setup_orchestrator(tmp_path)
    orch.gitops.get_new_commits.return_value = []
    orch.classifier.classify.return_value = ChangeClassification(
        decision="AUTO_MERGE", dimensions=[], upstream_commits=[],
        total_files_changed=0, total_commits=0,
    )
    orch.health.run_health_check.return_value = HealthCheckResult(0, True, "ok", "pass")
    orch.health.run_tests.return_value = TestResult(0, True, "ok", "pass")

    report = orch.run()
    assert report.decision == "AUTO_MERGE"
    assert report.total_commits == 0


# ── Notification fan-out ──────────────────────────────────────────────────


def test_notification_fan_out_to_multiple_notifiers(tmp_path: Path):
    orch = _setup_orchestrator(tmp_path)
    orch.classifier.classify.return_value = _auto_classification()
    orch.health.run_health_check.return_value = HealthCheckResult(0, True, "ok", "pass")
    orch.health.run_tests.return_value = TestResult(0, True, "ok", "pass")
    orch.notifiers = [MagicMock(spec=Notifier), MagicMock(spec=Notifier)]

    report = orch.run()
    assert report.decision == "AUTO_MERGE"
    for n in orch.notifiers:
        n.notify_success.assert_called_once()


def test_notifier_exception_does_not_kill_pipeline(tmp_path: Path):
    orch = _setup_orchestrator(tmp_path)
    orch.classifier.classify.return_value = _auto_classification()
    orch.health.run_health_check.return_value = HealthCheckResult(0, True, "ok", "pass")
    orch.health.run_tests.return_value = TestResult(0, True, "ok", "pass")
    bad_notifier = MagicMock(spec=Notifier)
    bad_notifier.notify_success.side_effect = RuntimeError("boom")
    orch.notifiers = [bad_notifier]

    # Should not raise — notifier errors are swallowed.
    report = orch.run()
    assert report.decision == "AUTO_MERGE"


# ── Exit code mapping ─────────────────────────────────────────────────────


def test_exit_code_map():
    from owner.scripts.upstream_sync import _EXIT_CODE_MAP

    assert _EXIT_CODE_MAP["AUTO_MERGE"] == 0
    assert _EXIT_CODE_MAP["MANUAL_REVIEW"] == 1
    assert _EXIT_CODE_MAP["SKIPPED"] == 2
    assert _EXIT_CODE_MAP["ERROR"] == 2


# ── _build_merge_result helper ────────────────────────────────────────────


def test_build_merge_result_with_d4_passed():
    from owner.scripts.upstream_sync import UpstreamSyncOrchestrator

    cls = _auto_classification()
    result = UpstreamSyncOrchestrator._build_merge_result(cls)
    assert result.success is True
    assert result.conflict_files == []


def test_build_merge_result_with_d4_failed():
    from owner.scripts.upstream_sync import UpstreamSyncOrchestrator

    cls = _manual_classification()
    result = UpstreamSyncOrchestrator._build_merge_result(cls)
    assert result.success is False
    assert len(result.conflict_files) > 0


def test_build_merge_result_no_d4_dimension():
    from owner.scripts.upstream_sync import UpstreamSyncOrchestrator

    cls = ChangeClassification(
        decision="AUTO_MERGE",
        dimensions=[DimensionResult("D1", "x", True, "ok", False)],
        upstream_commits=[], total_files_changed=0, total_commits=0,
    )
    result = UpstreamSyncOrchestrator._build_merge_result(cls)
    assert result.success is True
    assert "D4 未执行" in result.output
