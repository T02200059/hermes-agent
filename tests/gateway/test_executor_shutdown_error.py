"""Tests for the gateway restart-race classifier.

When a SIGTERM/restart drain tears down asyncio's default ThreadPoolExecutor
while the loop is briefly still serving inbound events, any in-flight
``run_in_executor(None, ...)`` / ``asyncio.to_thread(...)`` raises a RuntimeError
like ``Executor shutdown has been called``. The gateway must recognise this as a
transient restart condition (→ "please resend") rather than a generic agent
error. See the 2026-06-22 restart-race investigation.
"""

from __future__ import annotations

from types import SimpleNamespace

from gateway.run import (
    _GatewayExecutorUnavailable,
    _is_executor_shutdown_error,
    _loop_executor_unavailable,
)


class TestIsExecutorShutdownError:
    def test_executor_shutdown_message(self):
        assert _is_executor_shutdown_error(
            RuntimeError("Executor shutdown has been called")
        )

    def test_cannot_schedule_new_futures_message(self):
        assert _is_executor_shutdown_error(
            RuntimeError("cannot schedule new futures after shutdown")
        )

    def test_event_loop_closed_message(self):
        assert _is_executor_shutdown_error(RuntimeError("Event loop is closed"))

    def test_case_insensitive(self):
        assert _is_executor_shutdown_error(
            RuntimeError("EXECUTOR SHUTDOWN HAS BEEN CALLED")
        )

    def test_unrelated_runtime_error_is_not_shutdown(self):
        assert not _is_executor_shutdown_error(RuntimeError("Agent process disconnected"))

    def test_non_runtime_error_is_not_shutdown(self):
        # Same text but wrong type → not classified (avoids over-matching).
        assert not _is_executor_shutdown_error(ValueError("Executor shutdown has been called"))

    def test_empty_runtime_error(self):
        assert not _is_executor_shutdown_error(RuntimeError())

    def test_gateway_executor_unavailable_is_matched(self):
        # Our own proactive sentinel must classify even though its message
        # doesn't contain the asyncio substrings.
        assert _is_executor_shutdown_error(
            _GatewayExecutorUnavailable("Gateway is restarting (default executor shut down)")
        )


class TestLoopExecutorUnavailable:
    """Cross-platform fast-fail predicate for _run_in_executor_with_context."""

    def test_healthy_loop_is_available(self):
        loop = SimpleNamespace(is_closed=lambda: False)  # no _executor_shutdown_called
        assert _loop_executor_unavailable(loop) is False

    def test_closed_loop_is_unavailable(self):
        loop = SimpleNamespace(is_closed=lambda: True)
        assert _loop_executor_unavailable(loop) is True

    def test_default_executor_shutdown_flag_is_unavailable(self):
        # The actual macOS race window: loop not yet closed, but the default
        # executor was already torn down by asyncio's teardown.
        loop = SimpleNamespace(is_closed=lambda: False, _executor_shutdown_called=True)
        assert _loop_executor_unavailable(loop) is True

    def test_missing_flag_is_treated_as_available(self):
        # Loops without the CPython private flag (e.g. uvloop) must behave as
        # before — no fast-fail.
        loop = SimpleNamespace(is_closed=lambda: False)
        assert _loop_executor_unavailable(loop) is False

    def test_is_closed_raising_is_unavailable(self):
        def _boom():
            raise RuntimeError("loop state unknown")

        loop = SimpleNamespace(is_closed=_boom)
        assert _loop_executor_unavailable(loop) is True
