"""Background plugin discovery must not deadlock the CLI after join timeout."""

from __future__ import annotations

import hermes_cli.plugins as plugins


class _AliveThread:
    def is_alive(self) -> bool:
        return True


def test_discover_plugins_skips_lock_after_join_timeout(monkeypatch):
    monkeypatch.setattr(plugins, "_background_discovery_thread", _AliveThread())
    monkeypatch.setattr(plugins, "_background_discovery_join_timed_out", True)
    monkeypatch.setattr(plugins, "_join_background_discovery", lambda timeout=30.0: None)

    called = []
    monkeypatch.setattr(
        plugins,
        "get_plugin_manager",
        lambda: called.append("manager") or None,
    )

    plugins.discover_plugins()
    assert called == []


def test_discover_plugins_loads_when_background_finished(monkeypatch):
    class _DeadThread:
        def is_alive(self) -> bool:
            return False

    monkeypatch.setattr(plugins, "_background_discovery_thread", _DeadThread())
    monkeypatch.setattr(plugins, "_background_discovery_join_timed_out", False)
    monkeypatch.setattr(plugins, "_join_background_discovery", lambda timeout=30.0: None)

    class _Mgr:
        def discover_and_load(self, force=False):
            self.force = force
            self.called = True

    mgr = _Mgr()
    monkeypatch.setattr(plugins, "get_plugin_manager", lambda: mgr)

    plugins.discover_plugins()
    assert mgr.called is True
