"""Post-merge verification: D6 health check + D7 test suite.

Both stages run while the merge is staged (``git merge --no-commit`` has
updated the working tree but HEAD is unchanged). The health checker shells
out to the existing ``merge_health_check.py`` (D6) and ``pytest tests/owner/``
(D7), capturing exit codes and stdout for the report.

Exit-code convention:
    0 → passed
    1 → failed (D6/D7 red line → rollback + MANUAL_REVIEW)
"""

from __future__ import annotations

import os
import subprocess
from typing import Optional

from owner.sync.config import SyncConfig
from owner.sync.models import HealthCheckResult, TestResult


class HealthChecker:
    """Run D6 (merge_health_check.py) and D7 (pytest) against the staged merge."""

    # Default timeout for the D6 health-check script (5 min).
    _HEALTH_CHECK_TIMEOUT: int = 300

    def __init__(self, config: SyncConfig) -> None:
        """Initialize the health checker.

        Args:
            config: Loaded :class:`SyncConfig`.
        """
        self.config: SyncConfig = config

    # ------------------------------------------------------------------
    # D6: merge_health_check.py
    # ------------------------------------------------------------------
    def run_health_check(self) -> HealthCheckResult:
        """Run ``merge_health_check.py`` via the venv Python.

        Returns:
            A :class:`HealthCheckResult` with ``passed=(exit_code == 0)``.
        """
        cmd = [
            str(self.config.venv_python),
            str(self.config.health_check_script),
        ]
        exit_code, output = self._run_subprocess(
            cmd, timeout=self._HEALTH_CHECK_TIMEOUT
        )
        summary = self._extract_summary(output)
        return HealthCheckResult(
            exit_code=exit_code,
            passed=(exit_code == 0),
            output=output,
            summary=summary,
        )

    # ------------------------------------------------------------------
    # D7: pytest tests/owner/
    # ------------------------------------------------------------------
    def run_tests(self) -> TestResult:
        """Run the owner test suite via pytest.

        Uses ``config.test_command`` (e.g.
        ``.venv/bin/python -m pytest tests/owner/ -x -q``) with the configured
        timeout.

        Returns:
            A :class:`TestResult` with ``passed=(exit_code == 0)``.
        """
        cmd = self.config.test_command.split()
        exit_code, output = self._run_subprocess(
            cmd, timeout=self.config.testing_timeout
        )
        summary = self._extract_summary(output)
        return TestResult(
            exit_code=exit_code,
            passed=(exit_code == 0),
            output=output,
            summary=summary,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _run_subprocess(
        self, cmd: list[str], timeout: int
    ) -> tuple[int, str]:
        """Run ``cmd`` in ``repo_root`` and capture stdout+stderr.

        Args:
            cmd: Command tokens to execute.
            timeout: Timeout in seconds.

        Returns:
            A ``(exit_code, combined_output)`` tuple. On timeout the exit
            code is ``124`` and the output explains the timeout.
        """
        env = dict(os.environ)
        env["GIT_TERMINAL_PROMPT"] = "0"
        try:
            result = subprocess.run(
                cmd,
                cwd=str(self.config.repo_root),
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except FileNotFoundError as exc:
            return 127, f"command not found: {exc}"
        except subprocess.TimeoutExpired as exc:
            return 124, (
                f"command timed out after {timeout}s: {' '.join(cmd)}\n"
                f"{exc.stdout or ''}{exc.stderr or ''}"
            )

        combined = result.stdout
        if result.stderr:
            if combined:
                combined += "\n"
            combined += result.stderr
        return result.returncode, combined

    @staticmethod
    def _extract_summary(output: str) -> str:
        """Return the last non-empty line of ``output`` as a summary."""
        if not output:
            return ""
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        return lines[-1] if lines else ""
