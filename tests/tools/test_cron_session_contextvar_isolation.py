"""ContextVar isolation tests for the HERMES_CRON_SESSION migration.

These tests assert invariants, not fixed values:
- ContextVar values are isolated per thread/context.
- The run_job() try/finally pattern does not leave HERMES_CRON_SESSION in os.environ.
- tools/approval._is_cron_session() prefers ContextVar over os.environ fallback.
- The gateway restart watcher scrubs leaked session/cron env vars.
- Removing owner/cron leaves official modules importable (thin-glue contract).
"""

import os
import sys
import threading
from contextvars import copy_context

import pytest

from gateway.session_context import _UNSET, _VAR_MAP, get_session_env
from owner.cron.approval_helper import owner_cron_is_active
from owner.cron.restart_scrub import owner_cron_scrub_watcher_env
from owner.cron.run_job_hook import owner_cron_session_enter, owner_cron_session_exit
from owner.cron.session_context import _CRON_SESSION


# Invariant: setting HERMES_CRON_SESSION in one thread/context does not
# affect another thread/context. ContextVar is the concurrency primitive
# that replaced the process-global os.environ write.
def test_cron_session_contextvar_isolated_per_thread():
    results = {}
    barrier = threading.Barrier(2)

    def thread_a():
        # Start from a fresh context so the main-thread state does not leak.
        ctx = copy_context()

        def run():
            barrier.wait()
            token = owner_cron_session_enter()
            results["a"] = _CRON_SESSION.get()
            owner_cron_session_exit(token)

        ctx.run(run)

    def thread_b():
        ctx = copy_context()

        def run():
            barrier.wait()
            results["b"] = _CRON_SESSION.get()

        ctx.run(run)

    t1 = threading.Thread(target=thread_a)
    t2 = threading.Thread(target=thread_b)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert results["a"] == "1"
    assert results["b"] is _UNSET


# Invariant: after the run_job() try/finally pattern, the process-global
# os.environ must not retain HERMES_CRON_SESSION. The ContextVar reset makes
# get_session_env() fall back to os.environ, so a clean os.environ means a
# clean view for legacy callers too.
def test_cron_session_does_not_leak_to_os_environ_after_finally():
    # Ensure a clean baseline.
    os.environ.pop("HERMES_CRON_SESSION", None)

    try:
        token = owner_cron_session_enter()
        os.environ["HERMES_CRON_SESSION"] = "1"

        # Simulate the body of run_job() where the cron marker is visible.
        assert get_session_env("HERMES_CRON_SESSION") == "1"
    finally:
        owner_cron_session_exit(token)

    assert os.environ.get("HERMES_CRON_SESSION") is None
    assert get_session_env("HERMES_CRON_SESSION") == ""


# Invariant: _is_cron_session() uses the ContextVar first. When the ContextVar
# is unset it falls back to os.environ, preserving compatibility with tests
# and legacy callers that still set the env var directly.
def test_approval_cron_check_via_contextvar_not_env():
    from tools.approval import _is_cron_session

    # Clean baseline.
    os.environ.pop("HERMES_CRON_SESSION", None)
    assert not _is_cron_session()

    token = owner_cron_session_enter()
    try:
        assert _is_cron_session()
    finally:
        owner_cron_session_exit(token)

    # After reset the ContextVar is unset.
    assert not _is_cron_session()

    # With only os.environ set, the helper falls back to the legacy path.
    os.environ["HERMES_CRON_SESSION"] = "1"
    try:
        assert _is_cron_session()
    finally:
        os.environ.pop("HERMES_CRON_SESSION", None)

    # After removing the env var and with the ContextVar still unset,
    # the helper returns False again.
    assert not _is_cron_session()


# Invariant: the restart watcher copies os.environ and then scrubs session/cron
# markers so the new gateway process starts with a clean environment.
def test_restart_watcher_scrubs_cron_env():
    watcher_env = os.environ.copy()

    # Simulate stale values leaked from a previous gateway lifetime.
    watcher_env["HERMES_CRON_SESSION"] = "1"
    watcher_env["HERMES_SESSION_KEY"] = "stale-session-key"
    watcher_env["HERMES_SESSION_ID"] = "stale-session-id"
    # A non-scrubbed var should survive.
    watcher_env["OTHER_VAR"] = "survive"

    owner_cron_scrub_watcher_env(watcher_env)

    assert "HERMES_CRON_SESSION" not in watcher_env
    assert "HERMES_SESSION_KEY" not in watcher_env
    assert "HERMES_SESSION_ID" not in watcher_env
    assert watcher_env["OTHER_VAR"] == "survive"


# Invariant: when the ContextVar is unset, owner_cron_is_active() still reads
# os.environ. This covers external plugins/hooks that set the env var directly
# outside our ContextVar scope.
def test_cron_session_fallback_to_environ_when_contextvar_unset():
    os.environ.pop("HERMES_CRON_SESSION", None)
    # ContextVar is unset and env var is absent.
    assert not owner_cron_is_active()

    os.environ["HERMES_CRON_SESSION"] = "1"
    try:
        assert owner_cron_is_active()
    finally:
        os.environ.pop("HERMES_CRON_SESSION", None)

    assert not owner_cron_is_active()


# Contract: deleting owner/cron must leave official modules importable. The
# helper functions are imported inline inside official code, so the modules can
# still be parsed/loaded; only the runtime helper calls fail with a clear error.
def test_owner_cron_session_removable():
    # Snapshot owner.cron-related modules and mark them as missing in
    # sys.modules. Setting the entry to None makes subsequent imports of
    # owner.cron raise ModuleNotFoundError, simulating removal of the
    # owner/cron directory while leaving official modules importable.
    owner_modules = {
        name: mod
        for name, mod in sys.modules.items()
        if name == "owner" or name.startswith("owner.")
    }
    for name in owner_modules:
        sys.modules[name] = None

    try:
        # gateway.session_context swallows the owner.cron import failure, so
        # these official modules remain importable without owner/cron.
        import cron.scheduler  # noqa: F401
        import tools.approval  # noqa: F401

        # Calling the thin-glue helpers without owner/cron raises ImportError,
        # which is the clear, actionable failure mode required by the
        # removability contract.
        from tools.approval import _is_cron_session

        with pytest.raises(ImportError):
            _is_cron_session()
    finally:
        # Restore owner modules so subsequent tests are not affected.
        sys.modules.update(owner_modules)
