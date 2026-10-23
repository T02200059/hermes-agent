"""The discovery lock must never be waited on without a deadline.

A plugin whose import blocks (network filesystem, a subprocess reading stdin) holds
``PluginManager._discovery_lock`` for the whole sweep. With a plain ``with lock`` every later
caller — the CLI's own ``discover_plugins``, hook delivery, dashboard activation — queued behind
it, so the process sat on a blank screen until someone pressed Ctrl+C. Regression cover for the
timed acquire and for the "leave the in-flight sweep alone" branches.
"""

from __future__ import annotations

import threading
import time

import pytest

from hermes_cli import plugins as plugins_mod


def test_timed_lock_returns_false_instead_of_blocking():
    lock = threading.Lock()
    lock.acquire()
    try:
        started = time.monotonic()
        with plugins_mod._TimedLock(lock, timeout=0.05) as got:
            assert got is False
        assert time.monotonic() - started < 5.0
        # Not acquired, so the holder still owns it: no stray release happened on exit.
        assert lock.acquire(blocking=False) is False
    finally:
        lock.release()


def test_timed_lock_releases_when_it_did_acquire():
    lock = threading.Lock()
    with plugins_mod._TimedLock(lock, timeout=1.0) as got:
        assert got is True
        assert lock.locked()
    # A second acquisition only succeeds when the context manager released on exit.
    assert lock.acquire(blocking=False) is True
    lock.release()


def test_timed_lock_reads_the_module_budget_at_call_time(monkeypatch):
    monkeypatch.setattr(plugins_mod, "_DISCOVERY_LOCK_TIMEOUT_S", 0.01)
    lock = threading.Lock()
    lock.acquire()
    try:
        started = time.monotonic()
        assert plugins_mod._TimedLock(lock).__enter__() is False
        assert time.monotonic() - started < 5.0
    finally:
        lock.release()


def test_discover_and_load_skips_a_held_lock_instead_of_hanging(monkeypatch):
    """The whole point: a stuck sweep must not turn startup into an unkillable wait."""
    monkeypatch.setattr(plugins_mod, "_DISCOVERY_LOCK_TIMEOUT_S", 0.05)
    manager = plugins_mod.get_plugin_manager()
    holder_ready = threading.Event()
    release_holder = threading.Event()

    def hold() -> None:
        with manager._discovery_lock:
            holder_ready.set()
            release_holder.wait(10)

    thread = threading.Thread(target=hold, daemon=True)
    thread.start()
    try:
        assert holder_ready.wait(5), "holder thread never took the lock"
        started = time.monotonic()
        manager.discover_and_load()
        assert time.monotonic() - started < 10.0
    finally:
        release_holder.set()
        thread.join(5)


def test_join_background_discovery_reports_a_sweep_that_outlived_it(monkeypatch):
    """False means "still importing": every caller uses it to avoid contending for the lock."""
    started = threading.Event()
    release = threading.Event()

    def stuck() -> None:
        started.set()
        release.wait(10)

    thread = threading.Thread(target=stuck, name="plugin-discovery", daemon=True)
    thread.start()
    try:
        assert started.wait(5)
        monkeypatch.setattr(plugins_mod, "_background_discovery_thread", thread)
        assert plugins_mod._join_background_discovery(timeout=0.05) is False
    finally:
        release.set()
        thread.join(5)

    finished = threading.Thread(target=lambda: None)
    finished.start()
    finished.join()
    monkeypatch.setattr(plugins_mod, "_background_discovery_thread", finished)
    assert plugins_mod._join_background_discovery(timeout=1.0) is True


def test_discover_plugins_does_not_start_a_pass_behind_a_live_sweep(monkeypatch):
    calls: list[bool] = []

    class _Manager:
        def discover_and_load(self, force: bool = False) -> None:
            calls.append(force)

    started = threading.Event()
    release = threading.Event()

    def stuck() -> None:
        started.set()
        release.wait(10)

    thread = threading.Thread(target=stuck, name="plugin-discovery", daemon=True)
    thread.start()
    try:
        assert started.wait(5)
        monkeypatch.setattr(plugins_mod, "_background_discovery_thread", thread)
        monkeypatch.setattr(plugins_mod, "_DISCOVERY_JOIN_TIMEOUT_S", 0.05)
        monkeypatch.setattr(plugins_mod, "get_plugin_manager", lambda: _Manager())

        plugins_mod.discover_plugins()
        assert calls == [], "an incremental pass must wait for the live sweep, not contend for its lock"
    finally:
        release.set()
        thread.join(5)


@pytest.mark.parametrize("force", [True])
def test_discover_plugins_forced_pass_still_goes_through_the_timed_lock(monkeypatch, force):
    """``force`` needs its own pass; it must reach discover_and_load (which times out itself)."""
    calls: list[bool] = []

    class _Manager:
        def discover_and_load(self, force: bool = False) -> None:
            calls.append(force)

    started = threading.Event()
    release = threading.Event()

    def stuck() -> None:
        started.set()
        release.wait(10)

    thread = threading.Thread(target=stuck, name="plugin-discovery", daemon=True)
    thread.start()
    try:
        assert started.wait(5)
        monkeypatch.setattr(plugins_mod, "_background_discovery_thread", thread)
        monkeypatch.setattr(plugins_mod, "_DISCOVERY_JOIN_TIMEOUT_S", 0.05)
        monkeypatch.setattr(plugins_mod, "get_plugin_manager", lambda: _Manager())

        plugins_mod.discover_plugins(force=force)
        assert calls == [True]
    finally:
        release.set()
        thread.join(5)
