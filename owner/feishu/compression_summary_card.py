"""Feishu interactive card for context compression summary feedback.

Mirrors the clarify/approval card pattern: builder lives in owner/ and the
adapter delegates through a thin glue method. This version is intentionally
plain (no fold/expand buttons) because the fallback text is already concise.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def build_compression_summary_card(summary_text: str) -> Dict[str, Any]:
    """Build a Schema 2.0 interactive card for a compression summary.

    The first line of ``summary_text`` is used as the card header title;
    the remaining lines are rendered as markdown body.  If there is no body,
    the card only shows the header.

    Formatting rules:
    * Blank lines in the source are preserved as ``\\n\\n`` paragraph breaks
      so Feishu markdown renders each section on its own line.

    The body is passed through verbatim (lines are only stripped). The builder
    deliberately does NOT split on any inline separator: ``summarize_compression_feedback``
    already emits one item per line, so splitting would only risk mangling
    content that legitimately contains the separator string (e.g. a task or
    file note that itself reads ``a · b``).
    """
    lines: list[str] = summary_text.splitlines()
    title = lines[0].strip() if lines else "🗜️ 上下文压缩完成"

    # Preserve each line as-is; blank lines stay as paragraph breaks.
    processed: list[str] = [raw.strip() for raw in lines[1:]]
    body = "\n".join(processed).strip()

    elements: list[Dict[str, Any]] = []
    if body:
        elements.append({"tag": "markdown", "content": body})

    card: Dict[str, Any] = {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": title, "tag": "plain_text"},
            "template": "blue",
        },
    }
    if elements:
        card["body"] = {"elements": elements}
    return card


async def try_send_compression_summary(
    adapter,
    chat_id: str,
    content: str,
    metadata: Optional[Dict[str, Any]] = None,
):
    """Send compression feedback as a dedicated Feishu card if content matches.

    Returns a ``SendResult`` when the card path is taken, or ``None`` when the
    content is not a compression summary (caller should fall through).
    """
    if not content:
        return None
    # Match both Chinese (current default) and English fallback strings so
    # a future locale change does not silently break the card path.
    if not (
        content.startswith("🗜️ 上下文已压缩")
        or content.startswith("🗜️ Context compressed")
    ):
        return None
    try:
        return await adapter.send_card(
            chat_id=chat_id,
            card=build_compression_summary_card(content),
            metadata=metadata,
        )
    except Exception as exc:
        logger.debug("[Feishu] compression summary card failed: %s", exc)
        return None
