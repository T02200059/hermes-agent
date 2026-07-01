"""QQ Bot plain-markdown diff display.

QQ does not support interactive callback cards, so we send a single markdown
message with a ```diff code block.
"""

from __future__ import annotations

import logging
from typing import Any, Optional, TYPE_CHECKING

from owner.diff_card.common import basename_for_display, count_diff_changes, diff_card_emoji

if TYPE_CHECKING:
    from gateway.platforms.qqbot.adapter import QQBotAdapter

logger = logging.getLogger(__name__)

_QQ_DIFF_MAX_CHARS = 3800  # headroom under QQ's 4000 char limit


def diff_to_qq_markdown(
    diff: str,
    tool_name: str,
    *,
    file_path: str = "",
    max_lines: int = 60,
) -> Optional[str]:
    """Convert a unified diff to a QQ Bot markdown message.

    Returns None if the diff is empty after processing.
    """
    if not diff or not diff.strip():
        return None

    fname = basename_for_display(file_path)
    emoji = diff_card_emoji(tool_name)
    added, removed = count_diff_changes(diff)
    stats = f"+{added} -{removed}" if added or removed else ""
    header = f"**{emoji} {tool_name}: {fname}**"
    if stats:
        header += f"  `{stats}`"

    lines = diff.splitlines()
    skipped = 0
    if len(lines) > max_lines:
        skipped = len(lines) - max_lines
        lines = lines[:max_lines]

    diff_body = "\n".join(lines)
    if skipped:
        diff_body += f"\n… {skipped} more line(s)"

    code_block = f"```diff\n{diff_body}\n```"
    full = f"{header}\n{code_block}"

    if len(full) > _QQ_DIFF_MAX_CHARS:
        suffix = "\n… (truncated)"
        overhead = len(header) + len("```diff\n\n```") + len(suffix) + 1
        budget = _QQ_DIFF_MAX_CHARS - overhead
        if budget > 100:
            diff_body = diff_body[:budget] + suffix
            full = f"{header}\n```diff\n{diff_body}\n```"
        else:
            full = header[:_QQ_DIFF_MAX_CHARS]

    return full


async def send_qqbot_diff_markdown(
    adapter: "QQBotAdapter",
    chat_id: str,
    diff: str,
    tool_name: str,
    file_path: str,
    max_lines: int,
) -> Any:
    """Send a markdown diff message to QQ Bot."""
    markdown = diff_to_qq_markdown(diff, tool_name, file_path=file_path, max_lines=max_lines)
    if not markdown:
        logger.debug("qqbot diff markdown skipped: empty markdown")
        return None
    return await adapter.send(chat_id, markdown)
