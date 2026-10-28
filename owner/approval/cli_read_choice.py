"""H02: CLI approval stdin read that does not leave a zombie reader after timeout.

Official ``tools.approval_prompt._read_choice`` used a daemon thread blocked on
``input()`` / ``read(0)``. After ``join(timeout)`` the main thread returned
``timeout``, but the daemon kept owning stdin and could swallow the next
approval's keystrokes. Gateway / Feishu / QQ / WeChat / normal TUI never hit
this path (callback or prompt_toolkit fail-closed).

Strategy:
- Interactive POSIX TTY + stock ``builtins.input`` → ``select`` + ``os.read`` so
  a deadline never leaves a blocked reader (avoids TextIO ``readline`` hanging
  past the deadline after select reports partial readiness).
- Otherwise (tests that mock ``input``, non-TTY, Windows) → legacy ``input()`` on
  a daemon thread (same semantics as upstream; zombie risk only on that fallback).
"""

from __future__ import annotations

import builtins
import logging
import os
import select
import sys
import threading
import time
from types import BuiltinFunctionType

logger = logging.getLogger(__name__)


def _use_interruptible_stdin() -> bool:
    """True when we can wait on stdin without a blocking ``input()`` thread."""
    if sys.platform == "win32":
        return False
    if not isinstance(builtins.input, BuiltinFunctionType):
        # Tests (and rare wrappers) replace input(); honor that path.
        return False
    try:
        if not sys.stdin.isatty():
            return False
        sys.stdin.fileno()
    except Exception:
        return False
    return True


def _read_interruptible(prompt: str, timeout_seconds: float) -> str | None:
    """Print *prompt* and read one line; ``None`` on deadline, ``""`` on EOF.

    Choices are ASCII aliases (o/s/a/once/…); bytes are decoded per-byte with
    replacement so a timeout mid-line never blocks and never keeps a reader.
    """
    sys.stdout.write(prompt)
    sys.stdout.flush()
    try:
        fd = sys.stdin.fileno()
    except Exception as exc:
        logger.debug("H02 stdin fileno failed: %s", exc)
        return ""

    encoding = getattr(sys.stdin, "encoding", None) or "utf-8"
    deadline = time.monotonic() + max(0.0, float(timeout_seconds))
    parts: list[str] = []
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        try:
            ready, _, _ = select.select([fd], [], [], remaining)
        except (ValueError, OSError) as exc:
            logger.debug("H02 select on stdin failed: %s", exc)
            return "".join(parts).strip().lower()
        if not ready:
            return None
        try:
            data = os.read(fd, 1)
        except OSError:
            return "".join(parts).strip().lower()
        if not data:
            return "".join(parts).strip().lower()
        ch = data.decode(encoding, errors="replace")
        if ch in ("\n", "\r"):
            return "".join(parts).strip().lower()
        parts.append(ch)


def _read_via_input_thread(prompt: str, timeout_seconds: float) -> str | None:
    """Upstream-compatible daemon ``input()``; may zombie on timeout (fallback only)."""
    result = {"choice": ""}

    def get_input() -> None:
        try:
            result["choice"] = input(prompt).strip().lower()
        except (EOFError, OSError):
            result["choice"] = ""

    thread = threading.Thread(target=get_input, daemon=True)
    thread.start()
    thread.join(timeout=timeout_seconds)
    return None if thread.is_alive() else result["choice"]


def read_choice(prompt: str, timeout_seconds: float) -> str | None:
    """Read one approval answer; ``None`` when the user never answered in time."""
    timeout = float(timeout_seconds)
    if _use_interruptible_stdin():
        return _read_interruptible(prompt, timeout)
    return _read_via_input_thread(prompt, timeout)
