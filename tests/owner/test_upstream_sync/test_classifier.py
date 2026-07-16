"""Unit tests for owner.sync.classifier.ChangeClassifier."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from owner.sync.classifier import ChangeClassifier
from owner.sync.config import SyncConfig
from owner.sync.gitops import GitError
from owner.sync.models import UpstreamCommit
from tests.owner.test_upstream_sync.conftest import build_raw_config, write_anchors


def _commit(hash_: str, files: list[str], message: str = "normal fix") -> UpstreamCommit:
    return UpstreamCommit(
        hash=hash_, short_hash=hash_[:7], message=message,
        files=files, author="dev", date="2025-01-01T00:00:00Z",
    )


def _make_classifier(tmp_path: Path, anchors: list[dict] | None = None,
                     **config_overrides) -> tuple[ChangeClassifier, MagicMock]:
    """Build a classifier with a mock GitOps."""
    if anchors is not None:
        write_anchors(tmp_path, anchors)
    cfg = SyncConfig(build_raw_config(tmp_path, **config_overrides))
    gitops = MagicMock()
    gitops.get_merge_base.return_value = "base123"
    gitops.get_upstream_head.return_value = "upstream456"
    gitops.get_changed_files.return_value = []
    gitops.try_merge_no_commit.return_value = (True, "merged", [])
    clf = ChangeClassifier(cfg, gitops)
    return clf, gitops


def _set_changed_files(gitops: MagicMock, files: list[str]):
    gitops.get_changed_files.return_value = files


# ── D1: 改动规模 ────────────────────────────────────────────────────────────


def test_d1_pass_when_files_le_threshold(tmp_path: Path):
    clf, gitops = _make_classifier(tmp_path)
    _set_changed_files(gitops, [f"file{i}.py" for i in range(20)])
    result = clf.classify([_commit("h1", [])])
    d1 = next(d for d in result.dimensions if d.dimension == "D1")
    assert d1.passed is True
    assert d1.triggered_red_line is False


def test_d1_fail_when_files_gt_threshold(tmp_path: Path):
    clf, gitops = _make_classifier(tmp_path)
    _set_changed_files(gitops, [f"file{i}.py" for i in range(21)])
    result = clf.classify([_commit("h1", [])])
    d1 = next(d for d in result.dimensions if d.dimension == "D1")
    assert d1.passed is False
    assert d1.triggered_red_line is True
    assert result.decision == "MANUAL_REVIEW"


# ── D2: 锚点文件触及 ────────────────────────────────────────────────────────


def test_d2_pass_when_no_anchor_touched(tmp_path: Path):
    anchors = [{"file": "protected/anchor.py", "reason": "critical"}]
    clf, gitops = _make_classifier(tmp_path, anchors=anchors)
    _set_changed_files(gitops, ["safe/file.py", "other.py"])
    result = clf.classify([_commit("h1", [])])
    d2 = next(d for d in result.dimensions if d.dimension == "D2")
    assert d2.passed is True


def test_d2_fail_when_anchor_touched(tmp_path: Path):
    anchors = [{"file": "protected/anchor.py", "reason": "critical"}]
    clf, gitops = _make_classifier(tmp_path, anchors=anchors)
    _set_changed_files(gitops, ["protected/anchor.py", "safe.py"])
    result = clf.classify([_commit("h1", [])])
    d2 = next(d for d in result.dimensions if d.dimension == "D2")
    assert d2.passed is False
    assert d2.triggered_red_line is True
    assert result.decision == "MANUAL_REVIEW"


def test_d2_pass_when_anchors_file_missing(tmp_path: Path):
    clf, gitops = _make_classifier(tmp_path)  # no anchors file written
    _set_changed_files(gitops, ["any/file.py"])
    result = clf.classify([_commit("h1", [])])
    d2 = next(d for d in result.dimensions if d.dimension == "D2")
    assert d2.passed is True


# ── D3: 重度侵入文件触及 ────────────────────────────────────────────────────


def test_d3_pass_when_no_heavy_file_touched(tmp_path: Path):
    clf, gitops = _make_classifier(tmp_path)
    _set_changed_files(gitops, ["safe/file.py"])
    result = clf.classify([_commit("h1", [])])
    d3 = next(d for d in result.dimensions if d.dimension == "D3")
    assert d3.passed is True


def test_d3_fail_when_heavy_file_touched(tmp_path: Path):
    clf, gitops = _make_classifier(tmp_path)
    # Config has d3_heavily_intruded_files = ["gateway/run.py", "agent/conversation_loop.py"]
    _set_changed_files(gitops, ["gateway/run.py", "safe.py"])
    result = clf.classify([_commit("h1", [])])
    d3 = next(d for d in result.dimensions if d.dimension == "D3")
    assert d3.passed is False
    assert d3.triggered_red_line is True
    assert result.decision == "MANUAL_REVIEW"


# ── D5: commit message 关键词 ───────────────────────────────────────────────


def test_d5_pass_when_no_dangerous_keyword(tmp_path: Path):
    clf, gitops = _make_classifier(tmp_path)
    _set_changed_files(gitops, ["a.py"])
    result = clf.classify([_commit("h1", [], "fix: minor bug in parser")])
    d5 = next(d for d in result.dimensions if d.dimension == "D5")
    assert d5.passed is True


def test_d5_fail_when_dangerous_keyword_present(tmp_path: Path):
    clf, gitops = _make_classifier(tmp_path)
    _set_changed_files(gitops, ["a.py"])
    result = clf.classify([_commit("h1", [], "refactor: rewrite module")])
    d5 = next(d for d in result.dimensions if d.dimension == "D5")
    assert d5.passed is False
    assert d5.triggered_red_line is True
    assert result.decision == "MANUAL_REVIEW"


def test_d5_keyword_case_insensitive(tmp_path: Path):
    clf, gitops = _make_classifier(tmp_path)
    _set_changed_files(gitops, ["a.py"])
    result = clf.classify([_commit("h1", [], "REFACTOR the module")])
    d5 = next(d for d in result.dimensions if d.dimension == "D5")
    assert d5.passed is False


# ── D4: 试合并冲突预检 ──────────────────────────────────────────────────────


def test_d4_pass_when_no_conflict(tmp_path: Path):
    clf, gitops = _make_classifier(tmp_path)
    gitops.try_merge_no_commit.return_value = (True, "merged", [])
    _set_changed_files(gitops, ["a.py"])
    result = clf.classify([_commit("h1", [])])
    d4 = next(d for d in result.dimensions if d.dimension == "D4")
    assert d4.passed is True
    assert d4.triggered_red_line is False


def test_d4_fail_on_conflict_and_abort_called(tmp_path: Path):
    clf, gitops = _make_classifier(tmp_path)
    gitops.try_merge_no_commit.return_value = (
        False, "conflict", ["conflict_file.py"]
    )
    _set_changed_files(gitops, ["a.py"])
    result = clf.classify([_commit("h1", [])])
    d4 = next(d for d in result.dimensions if d.dimension == "D4")
    assert d4.passed is False
    assert d4.triggered_red_line is True
    # abort must be called immediately after a conflict.
    gitops.abort_merge.assert_called_once()
    assert result.decision == "MANUAL_REVIEW"


def test_d4_fail_when_giterror_raised(tmp_path: Path):
    clf, gitops = _make_classifier(tmp_path)
    gitops.try_merge_no_commit.side_effect = GitError("merge exploded")
    _set_changed_files(gitops, ["a.py"])
    result = clf.classify([_commit("h1", [])])
    d4 = next(d for d in result.dimensions if d.dimension == "D4")
    assert d4.passed is False
    assert d4.triggered_red_line is True


def test_d4_abort_failure_does_not_raise(tmp_path: Path):
    clf, gitops = _make_classifier(tmp_path)
    gitops.try_merge_no_commit.return_value = (
        False, "conflict", ["x.py"]
    )
    gitops.abort_merge.side_effect = GitError("no merge to abort")
    _set_changed_files(gitops, ["a.py"])
    # Should not raise — abort failure is swallowed.
    result = clf.classify([_commit("h1", [])])
    d4 = next(d for d in result.dimensions if d.dimension == "D4")
    assert d4.passed is False


# ── D4 is evaluated last ────────────────────────────────────────────────────


def test_d4_evaluated_after_d1_d2_d3_d5(tmp_path: Path):
    """D4 (trial merge) must be the last dimension evaluated."""
    clf, gitops = _make_classifier(tmp_path)
    _set_changed_files(gitops, ["a.py"])

    call_order: list[str] = []

    gitops.try_merge_no_commit.side_effect = lambda: (
        call_order.append("d4_try_merge"),
        (True, "ok", []),
    )[1]

    clf.classify([_commit("h1", [], "safe message")])
    # try_merge_no_commit should have been called exactly once, after all
    # read-only gitops queries (get_merge_base, get_upstream_head, get_changed_files).
    assert call_order == ["d4_try_merge"]


# ── Pre-check: commit count threshold ──────────────────────────────────────


def test_pre_check_gt_threshold_short_circuits_to_manual_review(tmp_path: Path):
    clf, gitops = _make_classifier(tmp_path)
    commits = [_commit(f"h{i}", [], "msg") for i in range(101)]
    result = clf.classify(commits)

    assert result.decision == "MANUAL_REVIEW"
    # D0 dimension should be present.
    d0 = next(d for d in result.dimensions if d.dimension == "D0")
    assert d0.passed is False
    assert d0.triggered_red_line is True
    # D1-D5 should NOT have been evaluated (gitops queries not called).
    gitops.get_changed_files.assert_not_called()
    gitops.try_merge_no_commit.assert_not_called()


def test_pre_check_exactly_threshold_passes(tmp_path: Path):
    """Exactly 100 commits (== threshold) should NOT short-circuit."""
    clf, gitops = _make_classifier(tmp_path)
    _set_changed_files(gitops, ["a.py"])
    commits = [_commit(f"h{i}", [], "msg") for i in range(100)]
    result = clf.classify(commits)
    # Should proceed to D1-D5 evaluation.
    gitops.get_changed_files.assert_called_once()
    # No D0 dimension.
    assert not any(d.dimension == "D0" for d in result.dimensions)


# ── Overall decision ────────────────────────────────────────────────────────


def test_all_dimensions_pass_yields_auto_merge(tmp_path: Path):
    clf, gitops = _make_classifier(tmp_path)
    _set_changed_files(gitops, ["safe.py"])
    gitops.try_merge_no_commit.return_value = (True, "ok", [])
    result = clf.classify([_commit("h1", [], "fix: minor bug")])
    assert result.decision == "AUTO_MERGE"
    assert all(d.passed for d in result.dimensions)
    assert len(result.reasons) == 0


def test_any_failure_yields_manual_review(tmp_path: Path):
    clf, gitops = _make_classifier(tmp_path)
    _set_changed_files(gitops, [f"f{i}.py" for i in range(25)])  # D1 fails
    result = clf.classify([_commit("h1", [], "safe msg")])
    assert result.decision == "MANUAL_REVIEW"
    assert len(result.reasons) > 0


def test_classification_records_total_files_and_commits(tmp_path: Path):
    clf, gitops = _make_classifier(tmp_path)
    changed = ["a.py", "b.py", "c.py"]
    _set_changed_files(gitops, changed)
    commits = [_commit("h1", []), _commit("h2", [])]
    result = clf.classify(commits)
    assert result.total_files_changed == 3
    assert result.total_commits == 2


def test_empty_commits_list_still_runs_dimensions(tmp_path: Path):
    """Even with 0 commits, D1-D5 should still run (files may be non-zero)."""
    clf, gitops = _make_classifier(tmp_path)
    _set_changed_files(gitops, ["a.py"])
    result = clf.classify([])
    assert result.total_commits == 0
    # D5 should trivially pass with no commits.
    d5 = next(d for d in result.dimensions if d.dimension == "D5")
    assert d5.passed is True
