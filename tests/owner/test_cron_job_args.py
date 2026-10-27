"""§11.2 / C23: stored cron job args → CLI --key value."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from owner.cron.job_args import extend_argv_with_job_args, map_job_args_to_cli


@pytest.mark.parametrize(
    "args, expected",
    [
        ({"mode": "pref-card"}, ["--mode", "pref-card"]),
        (
            {"BACKUP_QUIET": "1", "timeout_seconds": "1800"},
            ["--BACKUP_QUIET", "1", "--timeout_seconds", "1800"],
        ),
        ({"BACKUP_QUIET": "1"}, ["--BACKUP_QUIET", "1"]),
        ({"days": "2"}, ["--days", "2"]),
        ({"verbose": True}, ["--verbose"]),
        ({"quiet": False}, []),
        ({"x": None}, []),
        ({"": "nope", "  ": "no"}, []),
        ({"pad": "  spaced  "}, ["--pad", "spaced"]),
        ({"zero": 0}, ["--zero", "0"]),
        (None, []),
        ("not-a-dict", []),
        ([], []),
        ({}, []),
    ],
)
def test_map_job_args_to_cli(args, expected):
    assert map_job_args_to_cli(args) == expected


def test_mixed_bool_and_values():
    assert map_job_args_to_cli(
        {"verbose": True, "quiet": False, "days": 7, "empty": "", "nil": None}
    ) == ["--verbose", "--days", "7"]


def test_extend_argv_mutates_and_returns():
    argv = ["/bin/bash", "/tmp/s.sh"]
    out = extend_argv_with_job_args(argv, {"mode": "pref-card", "BACKUP_QUIET": "1"})
    assert out is argv
    assert argv == [
        "/bin/bash",
        "/tmp/s.sh",
        "--mode",
        "pref-card",
        "--BACKUP_QUIET",
        "1",
    ]


def test_live_jobs_samples_match_expected():
    """现网 jobs.json 样例（与运行时脱钩后的 scripts 约定一致）。"""
    samples = {
        "hermes-daily-backup": {"BACKUP_QUIET": "1", "timeout_seconds": "1800"},
        "viking-quality-kanban-scan": {"mode": "pref-card"},
        "openviking-daily-backup": {"BACKUP_QUIET": "1"},
        "starryshore-swagger-check": {"days": "2"},
    }
    assert map_job_args_to_cli(samples["viking-quality-kanban-scan"]) == [
        "--mode",
        "pref-card",
    ]
    assert map_job_args_to_cli(samples["hermes-daily-backup"]) == [
        "--BACKUP_QUIET",
        "1",
        "--timeout_seconds",
        "1800",
    ]
    assert map_job_args_to_cli(samples["openviking-daily-backup"]) == [
        "--BACKUP_QUIET",
        "1",
    ]
    assert map_job_args_to_cli(samples["starryshore-swagger-check"]) == [
        "--days",
        "2",
    ]


@pytest.fixture
def cron_env(tmp_path, monkeypatch):
    """Isolated HERMES_HOME/scripts for glue-path checks (Popen mocked)."""
    hermes_home = tmp_path / ".hermes"
    (hermes_home / "scripts").mkdir(parents=True)
    (hermes_home / "cron").mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    # Clear any process-pinned home so resolution sees the fixture.
    try:
        import hermes_constants as _hc

        monkeypatch.setattr(_hc, "_PINNED_PROCESS_HERMES_HOME", None, raising=False)
    except Exception:
        pass
    return hermes_home


def _fake_proc(*, returncode: int = 0, stdout: str = "ok", stderr: str = ""):
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate.return_value = (stdout, stderr)
    return proc


def test_run_job_script_appends_mapped_flags_to_argv(cron_env):
    """Thin glue: ``_run_job_script(..., args=...)`` extends argv before Popen."""
    from cron import scheduler_script as mod

    script = cron_env / "scripts" / "probe.sh"
    script.write_text("#!/bin/bash\necho ok\n")

    captured: dict = {}

    def fake_popen(argv, **kwargs):
        captured["argv"] = list(argv)
        return _fake_proc(stdout="ok")

    with patch.object(mod.subprocess, "Popen", side_effect=fake_popen), patch(
        "tools.environments.local.build_subprocess_env", return_value={}
    ):
        ok, out = mod._run_job_script(
            "probe.sh",
            args={"mode": "pref-card", "BACKUP_QUIET": "1", "quiet": False},
        )

    assert ok is True
    assert out == "ok"
    assert captured["argv"][-4:] == ["--mode", "pref-card", "--BACKUP_QUIET", "1"]
    assert captured["argv"][0].endswith("bash") or captured["argv"][0] == "/bin/bash"
    assert str(script.resolve()) in captured["argv"][1]


def test_claim_heartbeat_forwards_job_args(cron_env):
    """``_run_job_script_with_claim_heartbeat`` passes ``job["args"]`` through."""
    from cron import scheduler_script as mod

    script = cron_env / "scripts" / "probe2.sh"
    script.write_text("#!/bin/bash\necho ok\n")
    captured: dict = {}

    def fake_popen(argv, **kwargs):
        captured["argv"] = list(argv)
        return _fake_proc(stdout="ok")

    job = {
        "id": "j1",
        "schedule": {"kind": "cron", "expression": "0 3 * * *"},
        "args": {"mode": "pref-card"},
        "interpreter": None,
    }
    with patch.object(mod.subprocess, "Popen", side_effect=fake_popen), patch(
        "tools.environments.local.build_subprocess_env", return_value={}
    ):
        ok, _out = mod._run_job_script_with_claim_heartbeat(job, "probe2.sh")

    assert ok is True
    assert captured["argv"][-2:] == ["--mode", "pref-card"]


def test_run_job_script_without_args_unchanged(cron_env):
    """No args → argv ends at the script path (legacy monkeypatch surface)."""
    from cron import scheduler_script as mod

    script = cron_env / "scripts" / "bare.sh"
    script.write_text("#!/bin/bash\necho ok\n")
    captured: dict = {}

    def fake_popen(argv, **kwargs):
        captured["argv"] = list(argv)
        return _fake_proc(stdout="ok")

    with patch.object(mod.subprocess, "Popen", side_effect=fake_popen), patch(
        "tools.environments.local.build_subprocess_env", return_value={}
    ):
        ok, _ = mod._run_job_script("bare.sh")

    assert ok is True
    assert captured["argv"][-1] == str(script.resolve())
    assert not any(a.startswith("--") for a in captured["argv"])
