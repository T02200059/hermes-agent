"""/yolo command logic — shared between CLI and gateway.

Parses /yolo on|off|status arguments and applies session-level
YOLO state changes. Display (colored terminal vs locale-aware reply)
is handled by each caller.

可移除性：删除此文件后 cli.py 和 gateway/slash_commands.py 回退到
ImportError fallback（简单 toggle，无 arg 解析）。
"""

from __future__ import annotations

from typing import Tuple

__all__ = [
    "ON_ARGS",
    "OFF_ARGS",
    "parse_yolo_arg",
    "apply_yolo_action",
]

ON_ARGS = frozenset({"on", "enable", "true", "1"})
OFF_ARGS = frozenset({"off", "disable", "false", "0"})


def parse_yolo_arg(raw: str) -> str:
    """Parse raw /yolo argument into an action.

    Returns one of: ``"on"``, ``"off"``, ``"status"``, ``"toggle"``.
    """
    arg = (raw or "").strip().lower()
    if arg in ("status", "?"):
        return "status"
    if arg in ON_ARGS:
        return "on"
    if arg in OFF_ARGS:
        return "off"
    return "toggle"


def apply_yolo_action(session_key: str, action: str) -> Tuple[bool, bool]:
    """Execute yolo action; returns ``(was_enabled, is_enabled_now)``.

    ``action`` must be one of the strings returned by :func:`parse_yolo_arg`.
    """
    from tools.approval import (
        disable_session_yolo,
        enable_session_yolo,
        is_session_yolo_enabled,
    )

    current = is_session_yolo_enabled(session_key)

    if action == "status":
        return (current, current)
    if action == "on":
        if not current:
            enable_session_yolo(session_key)
        return (current, True)
    if action == "off":
        if current:
            disable_session_yolo(session_key)
        return (current, False)
    # toggle
    if current:
        disable_session_yolo(session_key)
        return (current, False)
    enable_session_yolo(session_key)
    return (current, True)
