"""C16 thin gap: inherited cron/session env scrubbed at process + watcher."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from owner.cron.restart_scrub import (
    owner_cron_scrub_process_env,
    owner_cron_scrub_watcher_env,
)

_VARS = ("HERMES_CRON_SESSION", "HERMES_SESSION_KEY", "HERMES_SESSION_ID")
_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def polluted_environ(monkeypatch):
    for var in _VARS:
        monkeypatch.setenv(var, f"leak-{var}")
    yield


def test_owner_cron_scrub_process_env_clears_markers(polluted_environ):
    for var in _VARS:
        assert os.environ.get(var)
    owner_cron_scrub_process_env()
    for var in _VARS:
        assert var not in os.environ


def test_owner_cron_scrub_watcher_env_pops_markers():
    env = {var: f"leak-{var}" for var in _VARS}
    env["PATH"] = "/usr/bin"
    env["_HERMES_GATEWAY"] = "1"
    owner_cron_scrub_watcher_env(env)
    for var in _VARS:
        assert var not in env
    assert env["PATH"] == "/usr/bin"
    assert env["_HERMES_GATEWAY"] == "1"


def test_gateway_glue_calls_owner_cron_scrub():
    """Official glue sites must invoke the owner scrub helpers."""
    run_py = (_ROOT / "gateway" / "run.py").read_text(encoding="utf-8")
    shut_py = (_ROOT / "gateway" / "run_shutdown.py").read_text(encoding="utf-8")
    assert "owner_cron_scrub_process_env" in run_py
    assert "owner_cron_scrub_watcher_env" in shut_py
