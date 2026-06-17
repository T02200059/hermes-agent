"""Feishu interactive card for context compression summary feedback.

Mirrors the clarify/approval card pattern: builder lives in owner/ and the
adapter delegates through a thin glue method. This version is intentionally
plain (no fold/expand buttons) because the fallback text is already concise.
"""

from __future__ import annotations

from typing import Any, Dict


def build_compression_summary_card(summary_text: str) -> Dict[str, Any]:
    """Build a Schema 2.0 interactive card for a compression summary.

    The first line of ``summary_text`` is used as the card header title;
    the remaining lines are rendered as markdown body. If there is no body,
    the card only shows the header.
    """
    lines = summary_text.splitlines()
    title = lines[0].strip() if lines else "🗜️ 上下文压缩完成"
    body = "\n".join(line.strip() for line in lines[1:] if line.strip()).strip()

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
