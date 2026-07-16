"""Unit tests for owner.sync.health.HealthChecker."""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from owner.sync.config import SyncConfig
from owner.sync.health import HealthChecker
from tests.owner.test_upstream_sync.conftest import build_raw_config


def _make_checker(tmp_path: Path) -> HealthChecker:
    cfg = SyncConfig(build_raw_config(tmp_path))
    return HealthChecker(cfg)


def _mkcompleted(returncode=0, stdout="", stderr="") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr,
    )


# ── run_health_check (D6) ──────────────────────────────────────────────────


def test_run_health_check_pass(tmp_path: Path):
    checker = _make_checker(tmp_path)
    with patch("owner.sync.health.subprocess.run") as mock_run:
        mock_run.return_value = _mkcompleted(stdout="all checks passed\n")
        result = checker.run_health_check()
        assert result.passed is True
        assert result.exit_code == 0
        # Command should use venv python and health check script.
        cmd = mock_run.call_args.args[0]
        assert "owner/validation/merge_health_check.py" in str(cmd[1]) or cmd[1].endswith("merge_health_check.py")


def test_run_health_check_fail(tmp_path: Path):
    checker = _make_checker(tmp_path)
    with patch("owner.sync.health.subprocess.run") as mock_run:
        mock_run.return_value = _mkcompleted(returncode=1, stdout="FAIL: anchor missing\n")
        result = checker.run_health_check()
        assert result.passed is False
        assert result.exit_code == 1
        assert "FAIL" in result.output


def test_run_health_check_uses_repo_root_cwd(tmp_path: Path):
    checker = _make_checker(tmp_path)
    with patch("owner.sync.health.subprocess.run") as mock_run:
        mock_run.return_value = _mkcompleted(stdout="ok\n")
        checker.run_health_check()
        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs["cwd"] == str(checker.config.repo_root)


def test_run_health_check_sets_git_terminal_prompt(tmp_path: Path):
    checker = _make_checker(tmp_path)
    with patch("owner.sync.health.subprocess.run") as mock_run:
        mock_run.return_value = _mkcompleted(stdout="ok\n")
        checker.run_health_check()
        env = mock_run.call_args.kwargs["env"]
        assert env["GIT_TERMINAL_PROMPT"] == "0"


# ── run_tests (D7) ─────────────────────────────────────────────────────────


def test_run_tests_pass(tmp_path: Path):
    checker = _make_checker(tmp_path)
    with patch("owner.sync.health.subprocess.run") as mock_run:
        mock_run.return_value = _mkcompleted(stdout="5 passed in 2.3s\n")
        result = checker.run_tests()
        assert result.passed is True
        assert result.exit_code == 0
        # Command should come from config.test_command, split on whitespace.
        cmd = mock_run.call_args.args[0]
        assert ".venv/bin/python" in cmd
        assert "pytest" in cmd


def test_run_tests_fail(tmp_path: Path):
    checker = _make_checker(tmp_path)
    with patch("owner.sync.health.subprocess.run") as mock_run:
        mock_run.return_value = _mkcompleted(returncode=1, stdout="2 failed, 3 passed\n")
        result = checker.run_tests()
        assert result.passed is False
        assert result.exit_code == 1


def test_run_tests_timeout(tmp_path: Path):
    checker = _make_checker(tmp_path)
    with patch("owner.sync.health.subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=[], timeout=600)
        result = checker.run_tests()
        assert result.passed is False
        assert result.exit_code == 124
        assert "timed out" in result.output


def test_run_health_check_timeout(tmp_path: Path):
    checker = _make_checker(tmp_path)
    with patch("owner.sync.health.subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=[], timeout=300)
        result = checker.run_health_check()
        assert result.passed is False
        assert result.exit_code == 124


def test_run_tests_command_not_found(tmp_path: Path):
    checker = _make_checker(tmp_path)
    with patch("owner.sync.health.subprocess.run") as mock_run:
        mock_run.side_effect = FileNotFoundError("no such file")
        result = checker.run_tests()
        assert result.passed is False
        assert result.exit_code == 127
        assert "not found" in result.output.lower()


# ── _extract_summary ───────────────────────────────────────────────────────


def test_extract_summary_last_nonempty_line():
    output = "line1\nline2\n\nlast line\n"
    assert HealthChecker._extract_summary(output) == "last line"


def test_extract_summary_empty_output():
    assert HealthChecker._extract_summary("") == ""


def test_extract_summary_all_empty_lines():
    assert HealthChecker._extract_summary("\n\n\n") == ""


def test_extract_summary_single_line():
    assert HealthChecker._extract_summary("only line\n") == "only line"


def test_summary_in_result(tmp_path: Path):
    checker = _make_checker(tmp_path)
    with patch("owner.sync.health.subprocess.run") as mock_run:
        mock_run.return_value = _mkcompleted(stdout="3 passed in 1.2s\n")
        result = checker.run_tests()
        assert result.summary == "3 passed in 1.2s"


# ── Combined stdout/stderr ─────────────────────────────────────────────────


def test_output_combines_stdout_and_stderr(tmp_path: Path):
    checker = _make_checker(tmp_path)
    with patch("owner.sync.health.subprocess.run") as mock_run:
        mock_run.return_value = _mkcompleted(stdout="stdout line", stderr="stderr line")
        result = checker.run_tests()
        assert "stdout line" in result.output
        assert "stderr line" in result.output
