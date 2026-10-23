"""Guard: the merge-residue gate can reach the failures it is meant to catch.

New-baseline owner test (2026-10-23). Pins the coverage of this fork's own sync
gate, not a product behaviour.

Why the gate needed a second mode: its dynamic targets are "test files changed in
this range". A merge that only touches PRODUCT code therefore selects nothing, and
the gate reports PASS without ever running the tests that cover the change — which
is exactly the shape of "conflict resolved by taking upstream's caller but not its
callee". Closing T2-21 turned up 12 real product bugs whose failing tests all lived
in ``tests/gateway``, ``tests/tools``, ``tests/plugins`` and ``tests/monitoring``
while the gate's fixed target was only ``tests/owner``.

``--full`` routes through ``scripts/run_tests.sh`` (per-file subprocess isolation,
``env -i``, deterministic TZ/LANG/hashseed). Using bare ``pytest`` there would make
the gate disagree with the authoritative baseline it exists to enforce.

These cases drive the script as a subprocess with a stubbed git scope, so they
assert the wiring (which runner, which targets, how the summary is read) rather
than re-running the suite.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "owner" / "scripts" / "check-merge-residue.sh"


@pytest.fixture(scope="module")
def script_text() -> str:
    assert SCRIPT.is_file(), f"missing gate script: {SCRIPT}"
    return SCRIPT.read_text(encoding="utf-8")


def test_script_parses():
    """`bash -n` — a syntax error here silently disables the whole gate."""
    proc = subprocess.run(
        ["bash", "-n", str(SCRIPT)], capture_output=True, text=True, timeout=30
    )
    assert proc.returncode == 0, proc.stderr


def test_help_lists_the_full_mode(script_text):
    """--full must be discoverable, or the next person keeps using the leaky mode."""
    proc = subprocess.run(
        ["bash", str(SCRIPT), "--help"], capture_output=True, text=True, timeout=30
    )
    assert proc.returncode == 0
    assert "--full" in proc.stdout


def test_full_mode_delegates_to_the_standard_runner(script_text):
    """--full must use scripts/run_tests.sh, not bare pytest.

    The authoritative baseline is per-file isolated. A gate that runs pytest
    in-process can disagree with it in both directions, so its verdict would not
    mean what the commit message claims.
    """
    assert "run_tests.sh" in script_text, (
        "--full must delegate to scripts/run_tests.sh (per-file isolation); "
        "bare pytest yields a different verdict than the authoritative baseline"
    )
    # The full branch is the one that invokes the runner over all of tests/.
    assert '"$RUNNER" tests/' in script_text


def test_full_mode_refuses_to_run_without_the_runner(tmp_path):
    """A missing runner is an environment error (rc=2), never a silent pass."""
    # Point the script at an empty repo so its runner probe must fail.
    fake_root = tmp_path / "repo"
    (fake_root / "scripts").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(fake_root)], check=True, timeout=60)
    git_env = {
        "PATH": "/usr/bin:/bin", "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    # Two commits: the script derives base from TARGET^1, which a root commit lacks
    # (it would exit 2 on base derivation and never reach the runner probe).
    for msg in ("init", "second"):
        subprocess.run(
            ["git", "-C", str(fake_root), "commit", "-q", "--allow-empty", "-m", msg],
            check=True, timeout=60, env=git_env,
        )
    proc = subprocess.run(
        ["bash", str(SCRIPT), "--full"],
        capture_output=True, text=True, timeout=120,
        env={"HERMES_REPO_ROOT": str(fake_root), "PATH": "/usr/bin:/bin",
             "HOME": str(tmp_path)},
    )
    assert proc.returncode == 2, (
        f"missing runner must exit 2 (environment error), got {proc.returncode}: "
        f"{proc.stdout[-400:]}"
    )
    assert "标准入口" in proc.stderr


def test_summary_parser_accepts_both_output_shapes(script_text):
    """targeted prints pytest's own summary; --full prints "=== Summary: ...".

    Both feed the pasteable commit-message record, so both must be recognised.
    """
    assert "=== Summary:" in script_text, "full-mode summary shape is not parsed"
    assert "^[0-9]+ (passed|failed)" in script_text, "targeted summary shape is not parsed"


def test_flaky_rows_are_reported_separately_from_the_real_count(script_text):
    """The runner retries a failing FILE once and leaves ``FAILED`` rows behind.

    Reporting the raw ``FAILED`` line count as the failure count overstates the
    result (an operator then chases tests that passed on retry). The record must
    keep the Summary number authoritative and label the extra rows.
    """
    assert "FLAKY" in script_text
    assert "failed-rows" in script_text
