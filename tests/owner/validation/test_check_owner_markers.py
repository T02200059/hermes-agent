"""Guard tests for owner/validation/check_owner_markers.py (Check 8, v2 port).

Each test builds a throwaway git repository: a baseline commit on ``main``,
then a ``dev`` branch carrying the divergence under test. The checker is
invoked as a subprocess with ``cwd`` set to that repo, so the exit code and
the actionable output text are exercised exactly as pre-commit / CI see them.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CHECKER = PROJECT_ROOT / "owner" / "validation" / "check_owner_markers.py"

BASELINE_FILES = {
    "app/code.py": "def f():\n    return 1\n",
    "app/staged_ok.py": "a = 1\n",
    "app/unstaged.py": "b = 2\n",
    "app/bundle.min.js": "// bundled\n",
    "uv.lock": "# lock v1\n",
    "README.md": "# readme\n",
    "owner/keep.py": "x = 1\n",
}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _write(repo: Path, rel_path: str, content: str) -> None:
    path = repo / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _commit_all(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A git repo with a baseline commit on ``main`` and HEAD on ``dev``."""
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    for rel_path, content in BASELINE_FILES.items():
        _write(tmp_path, rel_path, content)
    _commit_all(tmp_path, "baseline")
    _git(tmp_path, "checkout", "-b", "dev")
    return tmp_path


def _check(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CHECKER), *args],
        check=False,
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _register_debt(repo: Path, entry: str) -> None:
    _write(repo, "owner/validation/marker_debt.txt", f"{entry}\n")


def test_modified_file_with_marker_passes(repo: Path) -> None:
    _write(repo, "app/code.py", "def f():\n    # [owner] 演示:改返回值\n    return 2\n")
    _commit_all(repo, "diverge")

    result = _check(repo, "--all")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout


def test_modified_official_file_without_marker_fails_and_names_it(repo: Path) -> None:
    # owner/, *.md and newly added official files are all out of scope; only
    # the modified official file without a marker must be named.
    _write(repo, "app/code.py", "def f():\n    return 2\n")
    _write(repo, "owner/keep.py", "x = 2\n")
    _write(repo, "README.md", "# changed\n")
    _write(repo, "app/added.py", "new = True\n")
    _commit_all(repo, "diverge")

    result = _check(repo, "--all")

    assert result.returncode == 1
    assert "app/code.py" in result.stdout
    assert "marker_debt.txt" in result.stdout  # the register way out is offered
    assert "app/added.py" not in result.stdout
    assert "owner/keep.py" not in result.stdout
    assert "README.md" not in result.stdout


def test_generated_artifacts_are_exempt(repo: Path) -> None:
    _write(repo, "uv.lock", "# lock v2\n")
    _write(repo, "app/bundle.min.js", "// bundled v2\n")
    _commit_all(repo, "diverge")

    result = _check(repo, "--all")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 generated-exempt" in result.stdout


def test_registered_debt_passes(repo: Path) -> None:
    _write(repo, "app/code.py", "def f():\n    return 2\n")
    _commit_all(repo, "diverge")
    _register_debt(repo, "app/code.py # 生成物之外的豁免演示")

    result = _check(repo, "--all")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "app/code.py" in result.stdout
    assert "acknowledged debt" in result.stdout


def test_stale_entry_when_file_gains_marker(repo: Path) -> None:
    _write(repo, "app/code.py", "def f():\n    # [owner] 演示:改返回值\n    return 2\n")
    _commit_all(repo, "diverge")
    _register_debt(repo, "app/code.py # 曾登记的债务")

    result = _check(repo, "--all")

    assert result.returncode == 1
    assert "carries an [owner] marker" in result.stdout


def test_stale_entry_when_file_no_longer_diverges(repo: Path) -> None:
    _register_debt(repo, "app/code.py # 曾登记的债务")
    _git(repo, "commit", "--allow-empty", "-m", "placeholder")

    result = _check(repo, "--all")

    assert result.returncode == 1
    assert "no longer a modified official file" in result.stdout


def test_stale_entry_for_missing_path(repo: Path) -> None:
    _register_debt(repo, "app/gone.py # 路径已消失的登记")
    _git(repo, "commit", "--allow-empty", "-m", "placeholder")

    result = _check(repo, "--all")

    assert result.returncode == 1
    assert "app/gone.py" in result.stdout
    assert "path no longer exists" in result.stdout


def test_malformed_register_line_fails(repo: Path) -> None:
    _register_debt(repo, "app/code.py reason-without-the-hash-separator")

    result = _check(repo, "--all")

    assert result.returncode == 1
    assert "malformed" in result.stdout


def test_staged_mode_checks_only_staged_files(repo: Path) -> None:
    _write(repo, "app/staged_ok.py", "a = 1  # [owner] 演示:已暂存且有标记\n")
    _write(repo, "app/unstaged.py", "b = 3\n")
    _git(repo, "add", "app/staged_ok.py")

    staged = _check(repo, "--staged")
    assert staged.returncode == 0, staged.stdout + staged.stderr

    # The unstaged divergence is invisible to --staged but red under --all.
    full = _check(repo, "--all")
    assert full.returncode == 1
    assert "app/unstaged.py" in full.stdout

    # Staging the marker-less file turns --staged red too.
    _git(repo, "add", "app/unstaged.py")
    staged_now = _check(repo, "--staged")
    assert staged_now.returncode == 1
    assert "app/unstaged.py" in staged_now.stdout


def test_missing_main_fails_open(repo: Path) -> None:
    _git(repo, "branch", "-D", "main")

    result = _check(repo, "--all")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "fail-open" in result.stdout
