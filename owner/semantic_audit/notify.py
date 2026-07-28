"""HALT / BLOCK 通知文案生成。"""

from __future__ import annotations

from typing import Optional


def block_message(
    tool_name: str,
    reason: str,
    *,
    strikes: int = 1,
    max_strikes: int = 2,
) -> str:
    warn = (
        f" Strike {strikes}/{max_strikes}."
        if strikes < max_strikes
        else f" Strike {strikes}/{max_strikes} — next violation will HALT the turn."
    )
    return (
        f"[semantic_audit] BLOCKED tool `{tool_name}`: {reason}.{warn} "
        "Do not retry the same action with a different phrasing. "
        "Stay within the user's explicit instructions. "
        "If the user only asked to inspect/status, use read-only commands."
    )


def halt_message(
    tool_name: str,
    reason: str,
    *,
    strikes: Optional[int] = None,
    hardline: bool = False,
) -> str:
    prefix = "[semantic_audit] HALTED"
    if hardline:
        detail = f" hardline irreversible action blocked for `{tool_name}`: {reason}."
    elif strikes is not None:
        detail = (
            f" conversation interrupted after repeated scope violations "
            f"(strike {strikes}) on `{tool_name}`: {reason}."
        )
    else:
        detail = f" tool `{tool_name}` out of scope: {reason}."
    return (
        f"{prefix}:{detail} "
        "The agent loop has been interrupted. Do not continue executing "
        "further tools in this batch. Wait for the next user message."
    )


def skipped_sibling_message(tool_name: str) -> str:
    return (
        f"[semantic_audit] Tool `{tool_name}` was not started because "
        "the batch was halted by the semantic audit gate."
    )
