"""Tests for cron job ``args`` parameter support.

Covers:
- ``args`` field in job creation / storage / update
- ``args`` to CLI flag mapping in ``_run_job_script()``
- ``args`` passed through ``run_job()`` no_agent path and wake-gate path
- Tool-level validation and injection scanning
- Tool list/update formatting
"""

import json
import os
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


@pytest.fixture
def cron_env(tmp_path, monkeypatch):
    """Isolated cron environment with temp HERMES_HOME."""
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir()
    (hermes_home / "cron").mkdir()
    (hermes_home / "cron" / "output").mkdir()
    (hermes_home / "scripts").mkdir()
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))

    import cron.jobs as jobs_mod
    import cron.scheduler as sched_mod

    monkeypatch.setattr(jobs_mod, "HERMES_DIR", hermes_home)
    monkeypatch.setattr(jobs_mod, "CRON_DIR", hermes_home / "cron")
    monkeypatch.setattr(jobs_mod, "JOBS_FILE", hermes_home / "cron" / "jobs.json")
    monkeypatch.setattr(jobs_mod, "OUTPUT_DIR", hermes_home / "cron" / "output")

    monkeypatch.setattr(sched_mod, "_get_hermes_home", lambda: hermes_home)

    return hermes_home


class TestJobArgsField:
    """Test that the args field is stored and retrieved correctly."""

    def test_create_job_with_args(self, cron_env):
        from cron.jobs import create_job, get_job

        job = create_job(
            prompt="Analyze the data",
            schedule="every 30m",
            script="monitor.py",
            args={"days": 7, "verbose": True, "limit": 100},
        )
        assert job["args"] == {"days": 7, "verbose": True, "limit": 100}

        loaded = get_job(job["id"])
        assert loaded["args"] == {"days": 7, "verbose": True, "limit": 100}

    def test_create_job_without_args(self, cron_env):
        from cron.jobs import create_job

        job = create_job(prompt="Hello", schedule="every 1h")
        assert job.get("args") is None

    def test_create_job_empty_args_normalized_to_none(self, cron_env):
        from cron.jobs import create_job

        job = create_job(prompt="Hello", schedule="every 1h", args={})
        assert job.get("args") is None

    def test_create_job_none_values_filtered(self, cron_env):
        from cron.jobs import create_job

        job = create_job(
            prompt="Hello",
            schedule="every 1h",
            script="x.py",
            args={"days": None, "verbose": False, "limit": 10},
        )
        # create_job filters None; False is kept (scheduler skips it later)
        assert "days" not in job["args"]
        assert job["args"]["verbose"] is False
        assert job["args"]["limit"] == 10

    def test_update_job_add_args(self, cron_env):
        from cron.jobs import create_job, update_job

        job = create_job(prompt="Hello", schedule="every 1h")
        assert job.get("args") is None

        updated = update_job(job["id"], {"args": {"threshold": 1000}})
        assert updated["args"] == {"threshold": 1000}

    def test_update_job_clear_args(self, cron_env):
        from cron.jobs import create_job, update_job

        job = create_job(
            prompt="Hello",
            schedule="every 1h",
            script="x.py",
            args={"days": 7},
        )
        assert job["args"] == {"days": 7}

        updated = update_job(job["id"], {"args": None})
        assert updated.get("args") is None


class TestRunJobScriptArgs:
    """Test args to CLI flag mapping."""

    def test_args_mapped_to_cli_flags(self, cron_env):
        from cron.scheduler import _run_job_script

        script = cron_env / "scripts" / "flags.py"
        script.write_text(textwrap.dedent("""\
            import argparse, json, sys
            parser = argparse.ArgumentParser()
            parser.add_argument("--days", type=int)
            parser.add_argument("--verbose", action="store_true")
            parser.add_argument("--message")
            ns = parser.parse_args()
            print(json.dumps({"days": ns.days, "verbose": ns.verbose, "message": ns.message}))
        """))

        success, output = _run_job_script(
            "flags.py",
            args={"days": 7, "verbose": True, "message": "hello world"},
        )
        assert success is True
        parsed = json.loads(output)
        assert parsed == {"days": 7, "verbose": True, "message": "hello world"}

    def test_boolean_false_skipped(self, cron_env):
        from cron.scheduler import _run_job_script

        script = cron_env / "scripts" / "bool.py"
        script.write_text(textwrap.dedent("""\
            import argparse, json
            parser = argparse.ArgumentParser()
            parser.add_argument("--verbose", action="store_true")
            ns = parser.parse_args()
            print(json.dumps({"verbose": ns.verbose}))
        """))

        success, output = _run_job_script("bool.py", args={"verbose": False})
        assert success is True
        assert json.loads(output) == {"verbose": False}

    def test_empty_string_value_skipped(self, cron_env):
        from cron.scheduler import _run_job_script

        script = cron_env / "scripts" / "empty.py"
        script.write_text(textwrap.dedent("""\
            import argparse, json
            parser = argparse.ArgumentParser()
            parser.add_argument("--name", default="default")
            ns = parser.parse_args()
            print(json.dumps({"name": ns.name}))
        """))

        success, output = _run_job_script("empty.py", args={"name": "  "})
        assert success is True
        assert json.loads(output) == {"name": "default"}

    def test_empty_key_skipped(self, cron_env):
        from cron.scheduler import _run_job_script

        script = cron_env / "scripts" / "emptykey.py"
        script.write_text('print("ok")\n')

        success, output = _run_job_script("emptykey.py", args={"": "ignored"})
        assert success is True
        assert output == "ok"


class TestCronjobToolArgs:
    """Test the cronjob tool's args parameter."""

    def test_create_with_args(self, cron_env, monkeypatch):
        monkeypatch.setenv("HERMES_INTERACTIVE", "1")
        from tools.cronjob_tools import cronjob

        result = json.loads(cronjob(
            action="create",
            schedule="every 1h",
            prompt="Monitor things",
            script="monitor.py",
            args={"days": 7, "verbose": True},
        ))
        assert result["success"] is True
        assert result["job"]["args"] == {"days": 7, "verbose": True}

    def test_update_args(self, cron_env, monkeypatch):
        monkeypatch.setenv("HERMES_INTERACTIVE", "1")
        from tools.cronjob_tools import cronjob

        create_result = json.loads(cronjob(
            action="create",
            schedule="every 1h",
            prompt="Monitor things",
            script="monitor.py",
        ))
        job_id = create_result["job_id"]

        update_result = json.loads(cronjob(
            action="update",
            job_id=job_id,
            args={"threshold": 1000},
        ))
        assert update_result["success"] is True
        assert update_result["job"]["args"] == {"threshold": 1000}

    def test_update_clear_args(self, cron_env, monkeypatch):
        monkeypatch.setenv("HERMES_INTERACTIVE", "1")
        from tools.cronjob_tools import cronjob

        create_result = json.loads(cronjob(
            action="create",
            schedule="every 1h",
            prompt="Monitor things",
            script="monitor.py",
            args={"days": 7},
        ))
        job_id = create_result["job_id"]

        update_result = json.loads(cronjob(
            action="update",
            job_id=job_id,
            args={},
        ))
        assert update_result["success"] is True
        assert "args" not in update_result["job"]

    def test_list_shows_args(self, cron_env, monkeypatch):
        monkeypatch.setenv("HERMES_INTERACTIVE", "1")
        from tools.cronjob_tools import cronjob

        cronjob(
            action="create",
            schedule="every 1h",
            prompt="Monitor things",
            script="data_collector.py",
            args={"limit": 5},
        )

        list_result = json.loads(cronjob(action="list"))
        assert list_result["success"] is True
        assert len(list_result["jobs"]) == 1
        assert list_result["jobs"][0]["args"] == {"limit": 5}

    def test_args_injection_blocked(self, cron_env, monkeypatch):
        monkeypatch.setenv("HERMES_INTERACTIVE", "1")
        from tools.cronjob_tools import cronjob

        result = json.loads(cronjob(
            action="create",
            schedule="every 1h",
            prompt="Monitor things",
            script="monitor.py",
            args={"malicious": "rm -rf /"},
        ))
        assert result["success"] is False
        assert "args.malicious" in result["error"]

    def test_args_must_be_dict(self, cron_env, monkeypatch):
        monkeypatch.setenv("HERMES_INTERACTIVE", "1")
        from tools.cronjob_tools import cronjob

        result = json.loads(cronjob(
            action="create",
            schedule="every 1h",
            prompt="Monitor things",
            script="monitor.py",
            args=["bad"],
        ))
        assert result["success"] is False
        assert "args must be a dict" in result["error"]


class TestRunJobNoAgentArgs:
    """Test that run_job() passes args to scripts in no_agent mode."""

    def test_no_agent_script_receives_args(self, cron_env):
        from cron.scheduler import run_job

        script = cron_env / "scripts" / "report.py"
        script.write_text(textwrap.dedent("""\
            import argparse
            parser = argparse.ArgumentParser()
            parser.add_argument("--days", type=int)
            args = parser.parse_args()
            print(f"report for last {args.days} days")
        """))

        job = {
            "id": "test-no-agent-args",
            "name": "test",
            "no_agent": True,
            "script": "report.py",
            "args": {"days": 7},
            "schedule_display": "every 1h",
            "deliver": "local",
        }
        success, doc, response, error = run_job(job)
        assert success is True
        assert error is None
        assert response == "report for last 7 days"
