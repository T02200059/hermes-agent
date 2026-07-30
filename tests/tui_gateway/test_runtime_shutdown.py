"""Regression coverage for orderly standalone-TUI runtime shutdown."""

import pytest


def test_runtime_shutdown_preserves_session_end_before_mcp_cleanup(monkeypatch):
    from tools import mcp_tool
    from tui_gateway import server

    calls: list[str] = []

    monkeypatch.setattr(
        server, "_shutdown_sessions", lambda: calls.append("session_end")
    )
    monkeypatch.setattr(
        mcp_tool, "shutdown_mcp_servers", lambda: calls.append("mcp_shutdown")
    )

    server._shutdown_runtime()

    assert calls == ["session_end", "mcp_shutdown"]


def test_runtime_shutdown_still_stops_mcp_when_session_cleanup_finds_nothing(
    monkeypatch,
):
    from tools import mcp_tool
    from tui_gateway import server

    stopped = []

    monkeypatch.setattr(server, "_shutdown_sessions", lambda: None)
    monkeypatch.setattr(
        mcp_tool, "shutdown_mcp_servers", lambda: stopped.append(True)
    )

    server._shutdown_runtime()

    assert stopped == [True]


def test_runtime_shutdown_still_stops_mcp_if_session_cleanup_raises(monkeypatch):
    from tools import mcp_tool
    from tui_gateway import server

    stopped = []

    def fail_session_cleanup():
        raise RuntimeError("session cleanup failed")

    monkeypatch.setattr(server, "_shutdown_sessions", fail_session_cleanup)
    monkeypatch.setattr(
        mcp_tool, "shutdown_mcp_servers", lambda: stopped.append(True)
    )

    with pytest.raises(RuntimeError, match="session cleanup failed"):
        server._shutdown_runtime()

    assert stopped == [True]
