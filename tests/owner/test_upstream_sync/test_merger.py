"""Unit tests for owner.sync.merger.Merger."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from owner.sync.gitops import GitError
from owner.sync.merger import Merger
from owner.sync.models import MergeResult


def _make_merger() -> tuple[Merger, MagicMock, MagicMock]:
    gitops = MagicMock()
    state = MagicMock()
    config = MagicMock()
    merger = Merger(config, gitops, state)
    return merger, gitops, state


# ── try_merge ──────────────────────────────────────────────────────────────


def test_try_merge_delegates_to_gitops():
    merger, gitops, _ = _make_merger()
    gitops.try_merge_no_commit.return_value = (True, "output", [])
    result = merger.try_merge()
    assert isinstance(result, MergeResult)
    assert result.success is True
    assert result.output == "output"
    assert result.conflict_files == []


def test_try_merge_with_conflicts():
    merger, gitops, _ = _make_merger()
    gitops.try_merge_no_commit.return_value = (False, "conflict", ["a.py", "b.py"])
    result = merger.try_merge()
    assert result.success is False
    assert result.conflict_files == ["a.py", "b.py"]


# ── complete ───────────────────────────────────────────────────────────────


def test_complete_delegates_to_gitops():
    merger, gitops, _ = _make_merger()
    merger.complete()
    gitops.complete_merge.assert_called_once()


# ── rollback ───────────────────────────────────────────────────────────────


def test_rollback_abort_success_no_reset():
    """When abort succeeds, reset_hard must NOT be called."""
    merger, gitops, state = _make_merger()
    gitops.is_merge_in_progress.return_value = True
    gitops.abort_merge.return_value = None  # no exception

    merger.rollback()

    gitops.is_merge_in_progress.assert_called_once()
    gitops.abort_merge.assert_called_once()
    gitops.reset_hard.assert_not_called()


def test_rollback_abort_failure_falls_back_to_reset_hard():
    """When abort fails, fall back to reset_hard with pre_merge_head."""
    merger, gitops, state = _make_merger()
    gitops.is_merge_in_progress.return_value = True
    gitops.abort_merge.side_effect = GitError("abort failed")
    state.get_pre_merge_head.return_value = "pre_merge_head_123"

    merger.rollback()

    gitops.abort_merge.assert_called_once()
    gitops.reset_hard.assert_called_once_with("pre_merge_head_123")


def test_rollback_no_merge_in_progress_uses_reset_hard():
    """When no merge is in progress, go straight to reset_hard."""
    merger, gitops, state = _make_merger()
    gitops.is_merge_in_progress.return_value = False
    state.get_pre_merge_head.return_value = "head456"

    merger.rollback()

    gitops.abort_merge.assert_not_called()
    gitops.reset_hard.assert_called_once_with("head456")


def test_rollback_no_merge_no_head_raises_giterror():
    """No merge in progress AND no pre_merge_head → GitError."""
    merger, gitops, state = _make_merger()
    gitops.is_merge_in_progress.return_value = False
    state.get_pre_merge_head.return_value = None

    with pytest.raises(GitError, match="rollback failed"):
        merger.rollback()

    gitops.reset_hard.assert_not_called()


def test_rollback_is_merge_in_progress_raises_falls_back():
    """If is_merge_in_progress itself raises GitError, fall through to reset."""
    merger, gitops, state = _make_merger()
    gitops.is_merge_in_progress.side_effect = GitError("rev-parse failed")
    state.get_pre_merge_head.return_value = "head789"

    merger.rollback()

    gitops.reset_hard.assert_called_once_with("head789")
