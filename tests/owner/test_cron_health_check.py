"""Tests for owner/scripts/cron-health-check.py restore-log classification."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load():
    path = (
        Path(__file__).resolve().parents[2]
        / "owner"
        / "scripts"
        / "cron-health-check.py"
    )
    spec = importlib.util.spec_from_file_location("owner_cron_health_check", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mod = _load()


def test_dated_completed_today_is_success():
    log = "2026-08-18 restore completed\n2026-08-19 restore completed\n"
    done, fail, _line = mod.interpret_restore_log(log, "20260819")
    assert done is True
    assert fail is False


def test_dated_completed_yesterday_is_not_today():
    log = "2026-08-18 restore completed\n"
    done, fail, _line = mod.interpret_restore_log(log, "20260819")
    assert done is False
    assert fail is False


def test_dateless_completed_is_not_today():
    log = "01:00:00 restore completed\n"
    done, fail, _line = mod.interpret_restore_log(log, "20260819")
    assert done is False
    assert fail is False


def test_later_fail_wins_over_older_completed():
    log = "2026-08-19 restore completed\n2026-08-19 ERROR boom\n"
    done, fail, _line = mod.interpret_restore_log(log, "20260819")
    assert done is False
    assert fail is True


def test_later_completed_wins_over_older_fail():
    log = "2026-08-18 ERROR boom\n2026-08-19 restore completed\n"
    done, fail, _line = mod.interpret_restore_log(log, "20260819")
    assert done is True
    assert fail is False
