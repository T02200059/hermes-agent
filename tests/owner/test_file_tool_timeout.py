"""Tests for owner.file_tool_timeout single-execution timeout guard."""

from __future__ import annotations

import json
import time
import threading

import pytest

from owner.file_tool_timeout import (
    GUARDED_TOOLS,
    is_guard_active,
    set_guard_active,
    resolve_file_tool_timeout,
    guard_file_tool_call,
    _file_tool_timeout_guard,
)


class TestGuardFlag:
    """Thread-local flag get/set/restore semantics."""

    def test_default_inactive(self):
        # In a fresh thread, flag should be falsy.
        assert not is_guard_active()

    def test_set_returns_previous(self):
        prev = set_guard_active(True)
        assert prev is False
        assert is_guard_active()
        prev2 = set_guard_active(False)
        assert prev2 is True
        assert not is_guard_active()

    def test_restore_previous(self):
        set_guard_active(True)
        prev = set_guard_active(True)  # already True
        assert prev is True
        set_guard_active(False)
        assert not is_guard_active()


class TestGuardFileToolCall:
    """guard_file_tool_call happy path and timeout."""

    def test_returns_fn_result(self):
        result = guard_file_tool_call(
            lambda: "hello",
            function_name="read_file",
            budget=5.0,
            task_id="t1",
        )
        assert result == "hello"

    def test_timeout_returns_json_error(self):
        def slow():
            time.sleep(10)

        result = guard_file_tool_call(
            slow,
            function_name="read_file",
            budget=0.1,
            task_id="t-slow",
        )
        assert isinstance(result, str)
        data = json.loads(result)
        assert data["status"] == "timeout"
        assert data["tool"] == "read_file"
        assert data["task_id"] == "t-slow"
        assert int(data["inherited_timeout"]) == 0  # budget was 0.1 → int=0
        assert "offset/limit" in data["error"]

    def test_timeout_with_real_budget(self):
        """With budget=1.0 the json should show inherited_timeout=1."""
        result = guard_file_tool_call(
            lambda: time.sleep(5),
            function_name="search_files",
            budget=1.0,
            task_id="t2",
        )
        data = json.loads(result)
        assert data["status"] == "timeout"
        assert int(data["inherited_timeout"]) == 1

    def test_fn_exception_propagates(self):
        def boom():
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            guard_file_tool_call(
                boom,
                function_name="read_file",
                budget=5.0,
                task_id="t3",
            )

    def test_fn_returns_none(self):
        result = guard_file_tool_call(
            lambda: None,
            function_name="read_file",
            budget=5.0,
            task_id="t4",
        )
        assert result is None


class TestResolveFileToolTimeout:
    """Budget resolution fallback chain."""

    def test_fallback_default_180(self, monkeypatch):
        """With no active env and no config, falls back to 180."""
        monkeypatch.setattr(
            "tools.terminal_tool.get_active_env",
            lambda task_id: None,
        )
        monkeypatch.setattr(
            "hermes_cli.config.load_config",
            lambda: {},
        )
        budget = resolve_file_tool_timeout("nonexistent")
        assert budget == 180.0

    def test_inherits_from_terminal_env(self, monkeypatch):
        class FakeEnv:
            timeout = 60
        monkeypatch.setattr(
            "tools.terminal_tool.get_active_env",
            lambda task_id: FakeEnv(),
        )
        budget = resolve_file_tool_timeout("t1")
        assert budget == 60.0

    def test_env_timeout_zero_falls_back(self, monkeypatch):
        class FakeEnv:
            timeout = 0
        monkeypatch.setattr(
            "tools.terminal_tool.get_active_env",
            lambda task_id: FakeEnv(),
        )
        monkeypatch.setattr(
            "hermes_cli.config.load_config",
            lambda: {},
        )
        budget = resolve_file_tool_timeout("t1")
        assert budget == 180.0

    def test_config_terminal_timeout(self, monkeypatch):
        monkeypatch.setattr(
            "tools.terminal_tool.get_active_env",
            lambda task_id: None,
        )
        monkeypatch.setattr(
            "hermes_cli.config.load_config",
            lambda: {"terminal": {"timeout": 300}},
        )
        budget = resolve_file_tool_timeout("t1")
        assert budget == 300.0

    def test_env_exception_falls_back(self, monkeypatch):
        def boom(task_id):
            raise RuntimeError("no env")
        monkeypatch.setattr(
            "tools.terminal_tool.get_active_env",
            boom,
        )
        monkeypatch.setattr(
            "hermes_cli.config.load_config",
            lambda: {},
        )
        budget = resolve_file_tool_timeout("t1")
        assert budget == 180.0


class TestGuardedTools:
    """Guaranteed tools set contents."""

    def test_contains_read_file(self):
        assert "read_file" in GUARDED_TOOLS

    def test_contains_search_files(self):
        assert "search_files" in GUARDED_TOOLS

    def test_does_not_contain_terminal(self):
        assert "terminal" not in GUARDED_TOOLS

    def test_is_frozen(self):
        with pytest.raises(AttributeError):
            GUARDED_TOOLS.add("foo")  # type: ignore[attr-defined]


class TestThreadLocal:
    """Flag should be thread-local, not global."""

    def test_flag_does_not_leak_across_threads(self):
        set_guard_active(True)
        assert is_guard_active()

        results = {}

        def worker():
            results["before"] = is_guard_active()
            set_guard_active(True)
            results["after_set"] = is_guard_active()
            set_guard_active(False)

        t = threading.Thread(target=worker)
        t.start()
        t.join()

        # Worker thread should have started fresh
        assert results["before"] is False
        # And the main thread should still see active=True
        assert is_guard_active()
        # Clean up
        set_guard_active(False)