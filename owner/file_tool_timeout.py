"""Single-execution timeout protection for read_file / search_files.

Prevents these heavy I/O tools from hanging the entire turn on slow
filesystems (NFS, large directories).  The budget is inherited from
the active terminal environment timeout (which already implements
deadline + killpg + rc=124), adding a Python-side wall-clock guard
for the wrapper code (dedup, result assembly, etc.).

All logic lives in owner/; core files only contain thin [owner] glue
that calls :func:`resolve_file_tool_timeout`, :func:`is_guard_active`,
:func:`set_guard_active`, and :func:`guard_file_tool_call`.
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import threading
from typing import Any, Callable

logger = logging.getLogger(__name__)

#: Tools that receive the single-execution timeout guard.
GUARDED_TOOLS = frozenset({"read_file", "search_files"})

#: Thread-local flag for de-duplicating timeout guards when ``_run_tool``
#: (outer) and ``invoke_tool`` (inner) both want to protect the same
#: read_file/search_files call.  Prevents nested ThreadPoolExecutor wrappers
#: with identical budgets.
_file_tool_timeout_guard = threading.local()


def is_guard_active() -> bool:
    """Return ``True`` if an outer timeout guard is already in effect."""
    return getattr(_file_tool_timeout_guard, "active", False)


def set_guard_active(value: bool) -> bool:
    """Set the guard flag and return the *previous* value."""
    prev = getattr(_file_tool_timeout_guard, "active", False)
    _file_tool_timeout_guard.active = value
    return prev


def resolve_file_tool_timeout(task_id: str) -> float:
    """Resolve per-execution timeout budget for file tools.

    Priority:
      1. Active terminal environment's ``timeout`` (already implements
         deadline + kill + partial-output + rc=124).
      2. ``config["terminal"]["timeout"]`` (default 180).

    The Python-side wall-clock guard is a safety net for wrapper code;
    the terminal env handles the actual subprocess kill.
    """
    try:
        from tools.terminal_tool import get_active_env
        env = get_active_env(task_id or "default")
        if env is not None:
            t = getattr(env, "timeout", None)
            if isinstance(t, (int, float)) and t > 0:
                return float(t)
    except Exception:
        pass
    try:
        from hermes_cli.config import load_config
        cfg = load_config() or {}
        t = cfg.get("terminal", {}).get("timeout", 180)
        return float(t) if t and t > 0 else 180.0
    except Exception:
        return 180.0


def guard_file_tool_call(
    fn: Callable[[], Any],
    *,
    function_name: str,
    budget: float,
    task_id: str = "",
) -> Any:
    """Run *fn* in a single-thread pool with a wall-clock *budget*.

    Returns ``fn()``'s result on success, or a JSON error-string on
    timeout so the agent loop can surface it to the model gracefully.

    The caller is responsible for setting/clearing the guard flag
    via :func:`set_guard_active` around this call.
    """
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        fut = executor.submit(fn)
        return fut.result(timeout=budget)
    except concurrent.futures.TimeoutError:
        logger.warning(
            "%s timeout after %.0fs (task=%s, budget inherited from terminal env)",
            function_name, budget, task_id,
        )
        return json.dumps({
            "error": (
                f"{function_name} 执行超时（上限 {int(budget)}s，"
                f"继承自 terminal 环境超时）。"
                f"请使用 offset/limit 缩小范围，或检查文件系统/NFS/大目录。"
            ),
            "status": "timeout",
            "tool": function_name,
            "inherited_timeout": budget,
            "task_id": task_id or "",
        }, ensure_ascii=False)
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


__all__ = [
    "GUARDED_TOOLS",
    "is_guard_active",
    "set_guard_active",
    "resolve_file_tool_timeout",
    "guard_file_tool_call",
]