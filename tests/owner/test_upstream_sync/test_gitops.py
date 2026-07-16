"""Unit tests for owner.sync.gitops.GitOps.

All subprocess calls are mocked — no real git commands are executed.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from owner.sync.config import SyncConfig
from owner.sync.gitops import GitError, GitOps
from owner.sync.models import UpstreamCommit
from tests.owner.test_upstream_sync.conftest import build_raw_config


def _make_gitops(tmp_path: Path) -> tuple[GitOps, SyncConfig]:
    cfg = SyncConfig(build_raw_config(tmp_path))
    return GitOps(cfg.repo_root, cfg), cfg


def _mkcompleted(returncode=0, stdout="", stderr="") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["git"], returncode=returncode, stdout=stdout, stderr=stderr,
    )


# ── Environment ────────────────────────────────────────────────────────────


def test_git_terminal_prompt_disabled(tmp_path: Path):
    gitops, cfg = _make_gitops(tmp_path)
    with patch("owner.sync.gitops.subprocess.run") as mock_run:
        mock_run.return_value = _mkcompleted(stdout="clean\n")
        gitops.is_workdir_clean()
        call_kwargs = mock_run.call_args
        env = call_kwargs.kwargs["env"]
        assert env["GIT_TERMINAL_PROMPT"] == "0"


def test_commands_run_with_cwd_repo_root(tmp_path: Path):
    gitops, cfg = _make_gitops(tmp_path)
    with patch("owner.sync.gitops.subprocess.run") as mock_run:
        mock_run.return_value = _mkcompleted(stdout="clean\n")
        gitops.is_workdir_clean()
        call_kwargs = mock_run.call_args
        assert call_kwargs.kwargs["cwd"] == str(cfg.repo_root)


# ── fetch_upstream ─────────────────────────────────────────────────────────


def test_fetch_upstream_constructs_correct_command(tmp_path: Path):
    gitops, _ = _make_gitops(tmp_path)
    with patch("owner.sync.gitops.subprocess.run") as mock_run:
        mock_run.return_value = _mkcompleted()
        gitops.fetch_upstream()
        cmd = mock_run.call_args.args[0]
        assert cmd == ["git", "fetch", "upstream", "--quiet"]


# ── Read-only queries ──────────────────────────────────────────────────────


def test_get_merge_base(tmp_path: Path):
    gitops, _ = _make_gitops(tmp_path)
    with patch("owner.sync.gitops.subprocess.run") as mock_run:
        mock_run.return_value = _mkcompleted(stdout="abc123\n")
        result = gitops.get_merge_base()
        assert result == "abc123"
        cmd = mock_run.call_args.args[0]
        assert "merge-base" in cmd
        assert "HEAD" in cmd
        assert "upstream/main" in cmd


def test_get_upstream_head(tmp_path: Path):
    gitops, _ = _make_gitops(tmp_path)
    with patch("owner.sync.gitops.subprocess.run") as mock_run:
        mock_run.return_value = _mkcompleted(stdout="def456\n")
        result = gitops.get_upstream_head()
        assert result == "def456"


def test_get_current_head(tmp_path: Path):
    gitops, _ = _make_gitops(tmp_path)
    with patch("owner.sync.gitops.subprocess.run") as mock_run:
        mock_run.return_value = _mkcompleted(stdout="head789\n")
        assert gitops.get_current_head() == "head789"


def test_is_workdir_clean_true(tmp_path: Path):
    gitops, _ = _make_gitops(tmp_path)
    with patch("owner.sync.gitops.subprocess.run") as mock_run:
        mock_run.return_value = _mkcompleted(stdout="")
        assert gitops.is_workdir_clean() is True


def test_is_workdir_clean_false(tmp_path: Path):
    gitops, _ = _make_gitops(tmp_path)
    with patch("owner.sync.gitops.subprocess.run") as mock_run:
        mock_run.return_value = _mkcompleted(stdout=" M file.py\n")
        assert gitops.is_workdir_clean() is False


def test_get_changed_files(tmp_path: Path):
    gitops, _ = _make_gitops(tmp_path)
    with patch("owner.sync.gitops.subprocess.run") as mock_run:
        mock_run.return_value = _mkcompleted(stdout="a.py\nb.py\nc.py\n")
        files = gitops.get_changed_files("base", "head")
        assert files == ["a.py", "b.py", "c.py"]


def test_get_commit_files(tmp_path: Path):
    gitops, _ = _make_gitops(tmp_path)
    with patch("owner.sync.gitops.subprocess.run") as mock_run:
        mock_run.return_value = _mkcompleted(stdout="x.py\ny.py\n")
        files = gitops.get_commit_files("abc123")
        assert files == ["x.py", "y.py"]


# ── Error handling ─────────────────────────────────────────────────────────


def test_git_error_on_nonzero_exit(tmp_path: Path):
    gitops, _ = _make_gitops(tmp_path)
    with patch("owner.sync.gitops.subprocess.run") as mock_run:
        mock_run.return_value = _mkcompleted(returncode=1, stderr="fatal: error")
        with pytest.raises(GitError, match="failed"):
            gitops.fetch_upstream()


def test_git_error_includes_stderr(tmp_path: Path):
    gitops, _ = _make_gitops(tmp_path)
    with patch("owner.sync.gitops.subprocess.run") as mock_run:
        mock_run.return_value = _mkcompleted(returncode=1, stdout="", stderr="boom")
        with pytest.raises(GitError, match="boom"):
            gitops.get_current_head()


def test_git_error_on_timeout(tmp_path: Path):
    gitops, _ = _make_gitops(tmp_path)
    with patch("owner.sync.gitops.subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="git", timeout=30)
        with pytest.raises(GitError, match="timed out"):
            gitops._run(["fetch"], timeout=30)


# ── try_merge_no_commit ────────────────────────────────────────────────────


def test_try_merge_no_commit_success(tmp_path: Path):
    gitops, _ = _make_gitops(tmp_path)
    with patch("owner.sync.gitops.subprocess.run") as mock_run:
        mock_run.return_value = _mkcompleted(stdout="Merge made by recursive")
        success, output, conflicts = gitops.try_merge_no_commit()
        assert success is True
        assert conflicts == []
        cmd = mock_run.call_args.args[0]
        assert "merge" in cmd
        assert "--no-commit" in cmd
        assert "--no-ff" in cmd
        assert "upstream/main" in cmd


def test_try_merge_no_commit_conflict(tmp_path: Path):
    gitops, _ = _make_gitops(tmp_path)
    with patch("owner.sync.gitops.subprocess.run") as mock_run:
        # First call: merge fails. Second call: diff --name-only --diff-filter=U
        mock_run.side_effect = [
            _mkcompleted(returncode=1, stdout="", stderr="CONFLICT"),
            _mkcompleted(stdout="conflict.py\nother.py\n"),
        ]
        success, output, conflicts = gitops.try_merge_no_commit()
        assert success is False
        assert conflicts == ["conflict.py", "other.py"]


# ── complete_merge / abort_merge / reset_hard ──────────────────────────────


def test_complete_merge(tmp_path: Path):
    gitops, _ = _make_gitops(tmp_path)
    with patch("owner.sync.gitops.subprocess.run") as mock_run:
        mock_run.return_value = _mkcompleted()
        gitops.complete_merge()
        cmd = mock_run.call_args.args[0]
        assert cmd == ["git", "commit", "--no-edit"]


def test_abort_merge(tmp_path: Path):
    gitops, _ = _make_gitops(tmp_path)
    with patch("owner.sync.gitops.subprocess.run") as mock_run:
        mock_run.return_value = _mkcompleted()
        gitops.abort_merge()
        cmd = mock_run.call_args.args[0]
        assert cmd == ["git", "merge", "--abort"]


def test_reset_hard(tmp_path: Path):
    gitops, _ = _make_gitops(tmp_path)
    with patch("owner.sync.gitops.subprocess.run") as mock_run:
        mock_run.return_value = _mkcompleted()
        gitops.reset_hard("target_hash")
        cmd = mock_run.call_args.args[0]
        assert cmd == ["git", "reset", "--hard", "target_hash"]


def test_is_merge_in_progress_true(tmp_path: Path):
    gitops, _ = _make_gitops(tmp_path)
    with patch("owner.sync.gitops.subprocess.run") as mock_run:
        mock_run.return_value = _mkcompleted(returncode=0)
        assert gitops.is_merge_in_progress() is True


def test_is_merge_in_progress_false(tmp_path: Path):
    gitops, _ = _make_gitops(tmp_path)
    with patch("owner.sync.gitops.subprocess.run") as mock_run:
        mock_run.return_value = _mkcompleted(returncode=1)
        assert gitops.is_merge_in_progress() is False


# ── get_new_commits parsing ────────────────────────────────────────────────


def test_get_new_commits_parses_log_output(tmp_path: Path):
    gitops, _ = _make_gitops(tmp_path)
    record_sep = "\x1e"
    field_sep = "\x1f"
    log_output = (
        f"{record_sep}fullhash1{field_sep}short1{field_sep}author1"
        f"{field_sep}2025-01-01T00:00:00Z{field_sep}fix: bug 1"
        f"{record_sep}fullhash2{field_sep}short2{field_sep}author2"
        f"{field_sep}2025-01-02T00:00:00Z{field_sep}fix: bug 2"
    )

    def run_side_effect(cmd, **kwargs):
        if "log" in cmd and "--format" in " ".join(cmd):
            return _mkcompleted(stdout=log_output)
        if "show" in cmd:
            return _mkcompleted(stdout="a.py\n")
        return _mkcompleted()

    with patch("owner.sync.gitops.subprocess.run") as mock_run:
        mock_run.side_effect = run_side_effect
        commits = gitops.get_new_commits("base123")

    # git log returns newest-first; code reverses to oldest-first.
    # In the log output, fullhash1 appears first (newest), fullhash2 second (oldest).
    # After reversing: [fullhash2 (oldest), fullhash1 (newest)]
    assert len(commits) == 2
    assert commits[0].hash == "fullhash2"  # oldest first after reverse
    assert commits[1].hash == "fullhash1"  # newest second
    assert commits[0].message == "fix: bug 2"
    assert commits[0].files == ["a.py"]


def test_get_new_commits_empty_output(tmp_path: Path):
    gitops, _ = _make_gitops(tmp_path)
    with patch("owner.sync.gitops.subprocess.run") as mock_run:
        mock_run.return_value = _mkcompleted(stdout="")
        commits = gitops.get_new_commits("base123")
        assert commits == []
