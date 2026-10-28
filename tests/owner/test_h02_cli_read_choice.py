"""H02: CLI approval stdin read must not leave a zombie reader after timeout."""

from __future__ import annotations

import builtins
import os
import sys
import threading
import time

import pytest

from owner.approval import cli_read_choice as mod


@pytest.fixture()
def restore_stdin():
    original = sys.stdin
    yield
    sys.stdin = original


def test_interruptible_timeout_then_next_read_gets_input(restore_stdin, monkeypatch, capsys):
    """Regression: after a timeout, the next prompt still sees the user's keystrokes.

    Old daemon ``input()`` path left a blocked reader that could swallow ``o\\n``.
    """
    r_fd, w_fd = os.pipe()
    reader = os.fdopen(r_fd, "r", buffering=1)
    writer = os.fdopen(w_fd, "w", buffering=1)
    sys.stdin = reader
    monkeypatch.setattr(reader, "isatty", lambda: True)
    # Force stock-input gate open even if something wrapped builtins.input.
    monkeypatch.setattr(mod, "_use_interruptible_stdin", lambda: True)

    assert mod.read_choice("p1> ", 0.15) is None

    def _late_type() -> None:
        time.sleep(0.05)
        writer.write("o\n")
        writer.flush()

    t = threading.Thread(target=_late_type, daemon=True)
    t.start()
    assert mod.read_choice("p2> ", 1.0) == "o"
    t.join(timeout=1)
    writer.close()
    reader.close()


def test_interruptible_reads_answer_before_deadline(restore_stdin, monkeypatch, capsys):
    r_fd, w_fd = os.pipe()
    reader = os.fdopen(r_fd, "r", buffering=1)
    writer = os.fdopen(w_fd, "w", buffering=1)
    sys.stdin = reader
    monkeypatch.setattr(mod, "_use_interruptible_stdin", lambda: True)

    def _type() -> None:
        time.sleep(0.05)
        writer.write("once\n")
        writer.flush()

    t = threading.Thread(target=_type, daemon=True)
    t.start()
    assert mod.read_choice("p> ", 1.0) == "once"
    t.join(timeout=1)
    writer.close()
    reader.close()


def test_mocked_input_path_preserved(monkeypatch):
    """Official tests patch builtins.input; non-stock input must still win."""
    monkeypatch.setattr(builtins, "input", lambda _prompt="": "s")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    assert mod.read_choice("p> ", 1.0) == "s"


def test_use_interruptible_false_on_non_tty(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert mod._use_interruptible_stdin() is False


def test_prompt_dangerous_approval_timeout_still_timeout(monkeypatch):
    """End-to-end: hang input + short timeout → 'timeout' (official contract)."""
    from tools.approval_prompt import prompt_dangerous_approval

    def _hang(_prompt=""):
        time.sleep(10)
        return ""

    monkeypatch.setattr(builtins, "input", _hang)
    assert prompt_dangerous_approval(
        "rm -rf /var/data", "recursive delete", timeout_seconds=0.05,
    ) == "timeout"
