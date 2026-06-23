"""Tests for the gateway restart-race classifier.

When a SIGTERM/restart drain tears down asyncio's default ThreadPoolExecutor
while the loop is briefly still serving inbound events, any in-flight
``run_in_executor(None, ...)`` / ``asyncio.to_thread(...)`` raises a RuntimeError
like ``Executor shutdown has been called``. The gateway must recognise this as a
transient restart condition (→ "please resend") rather than a generic agent
error. See the 2026-06-22 restart-race investigation.
"""

from __future__ import annotations

from gateway.run import _is_executor_shutdown_error


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
