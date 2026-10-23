"""Guard: the gateway death-cause diagnostic writes somewhere that exists.

New-baseline owner test (2026-10-23). Pins a contract this fork supplies itself
(the wrapper is owner-only; upstream has no equivalent).

Why the fork owns it: `start_gateway_diag_wrap` exists because a dying main task
was swallowed by the async log twice — the `send_path_degraded` AttributeError
took two days to locate. A synchronous file write survives the event-loop
teardown that loses tail log records, so it is the only record of *why* a
gateway died.

It pointed at a hardcoded `/tmp/t220/gw_diag.log`. That is a one-off debug
directory from an earlier session: on this machine it does not exist, on Windows
there is no `/tmp` at all, and the write failure was swallowed by
`except Exception: pass` — so the hook that exists to make silent failures
visible was itself silently recording nothing. The repo-wide Windows-footgun scan
(`tests/scripts/test_windows_footguns_full_repo_scan.py`) is what caught it.

These tests pin the three properties that made it useless rather than merely
inconvenient: destination under HERMES_HOME, explicit UTF-8, and a bound on size.
"""

from __future__ import annotations

import asyncio

import pytest

import gateway.run as gateway_run


def _run_wrap(monkeypatch, tmp_path, *, outcome="return"):
    """Drive start_gateway_diag_wrap with a stubbed start_gateway."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    async def _start_gateway(config=None, *, replace=False, verbosity=0):
        if outcome == "raise":
            raise RuntimeError("gateway exploded")
        return True

    monkeypatch.setattr(gateway_run, "start_gateway", _start_gateway)
    return asyncio.run(gateway_run.start_gateway_diag_wrap())


def _diag_log(tmp_path):
    return tmp_path / "logs" / "gateway_diag.log"


def test_diag_writes_under_hermes_home_not_a_hardcoded_tmp_path(monkeypatch, tmp_path):
    """The log must live under HERMES_HOME — a per-release /tmp dir is gone later."""
    assert _run_wrap(monkeypatch, tmp_path) is True

    log = _diag_log(tmp_path)
    assert log.exists(), f"no diagnostic log under HERMES_HOME: wrote somewhere else"
    text = log.read_text(encoding="utf-8")
    assert "main task alive" in text
    assert "start_gateway returned True" in text


def test_diag_records_the_death_cause(monkeypatch, tmp_path):
    """A raise must leave the exception type/message behind, then propagate."""
    with pytest.raises(RuntimeError, match="gateway exploded"):
        _run_wrap(monkeypatch, tmp_path, outcome="raise")

    text = _diag_log(tmp_path).read_text(encoding="utf-8")
    assert "start_gateway DIED: RuntimeError" in text
    assert "gateway exploded" in text


def test_diag_rotates_instead_of_growing_without_bound(monkeypatch, tmp_path):
    """A diagnostic that grows forever is its own outage; it rotates at the cap."""
    log = _diag_log(tmp_path)
    log.parent.mkdir(parents=True)
    log.write_text("x" * (gateway_run._GATEWAY_DIAG_MAX_BYTES + 1), encoding="utf-8")

    _run_wrap(monkeypatch, tmp_path)

    assert log.stat().st_size < gateway_run._GATEWAY_DIAG_MAX_BYTES


def test_diag_failure_never_breaks_the_gateway(monkeypatch, tmp_path):
    """Diagnostics are best-effort: an unwritable destination must not raise."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    async def _start_gateway(config=None, *, replace=False, verbosity=0):
        return True

    monkeypatch.setattr(gateway_run, "start_gateway", _start_gateway)

    # A FILE where the logs directory should be makes mkdir fail.
    (tmp_path / "logs").write_text("not a directory", encoding="utf-8")

    assert asyncio.run(gateway_run.start_gateway_diag_wrap()) is True
