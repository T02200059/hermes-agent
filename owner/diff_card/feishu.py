"""Feishu interactive diff cards.

Builds the initial compact card and handles expand / collapse / full-diff
callback actions via CallBackCard inline replacement.
"""

from __future__ import annotations

import logging
import secrets
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from owner.diff_card.common import (
    DIFF_CACHE_TTL_SECONDS,
    basename_for_display,
    cache_get,
    cache_put,
    count_diff_changes,
    diff_card_emoji,
)

if TYPE_CHECKING:
    from gateway.platforms.feishu import FeishuAdapter

try:
    from lark_oapi.event.callback.model.p2_card_action_trigger import (
        CallBackCard,
        P2CardActionTriggerResponse,
    )
except Exception:  # pragma: no cover - lark_oapi is optional
    CallBackCard = None  # type: ignore[misc,assignment]
    P2CardActionTriggerResponse = None  # type: ignore[misc,assignment]

logger = logging.getLogger(__name__)

_FEISHU_DIFF_RED = "red"
_FEISHU_DIFF_GREEN = "green"
_FEISHU_DIFF_GREY = "neutral"
_FEISHU_DIFF_PURPLE = "purple"


def _esc(s: str) -> str:
    """Escape HTML special chars for Feishu markdown/text_tag content."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _render_diff_lines(diff_text: str, max_lines: int, compact: bool) -> tuple[List[str], int]:
    """Render unified diff lines into Feishu <text_tag> strings.

    Returns (lines, skipped_count).  In compact mode only ---/+++/@@ headers
    are rendered.
    """
    lines: List[str] = []
    skipped = 0

    for raw in diff_text.splitlines():
        is_header = raw.startswith("--- ") or raw.startswith("+++ ") or raw.startswith("@@")
        if compact and not is_header:
            continue

        if len(lines) >= max_lines:
            skipped += 1
            continue

        if raw.startswith("--- "):
            path_part = _esc(raw[4:].strip().lstrip("ab/"))
            lines.append(f'<text_tag color="{_FEISHU_DIFF_PURPLE}">--- {path_part}</text_tag>')
        elif raw.startswith("+++ "):
            path_part = _esc(raw[4:].strip().lstrip("ab/"))
            lines.append(f'<text_tag color="{_FEISHU_DIFF_PURPLE}">+++ {path_part}</text_tag>')
        elif raw.startswith("@@"):
            lines.append(f'<text_tag color="{_FEISHU_DIFF_PURPLE}">{_esc(raw)}</text_tag>')
        elif raw.startswith("-"):
            lines.append(f'<text_tag color="{_FEISHU_DIFF_RED}">-{_esc(raw[1:])}</text_tag>')
        elif raw.startswith("+"):
            lines.append(f'<text_tag color="{_FEISHU_DIFF_GREEN}">+{_esc(raw[1:])}</text_tag>')
        elif raw.startswith(" "):
            lines.append(f'<text_tag color="{_FEISHU_DIFF_GREY}"> {_esc(raw[1:])}</text_tag>')
        elif raw:
            lines.append(_esc(raw))

    if skipped and not compact:
        lines.append(f'<text_tag color="{_FEISHU_DIFF_GREY}">… {skipped} more line(s)</text_tag>')

    return lines, skipped


def diff_to_feishu_card(
    diff_text: str,
    tool_name: str,
    file_path: str = "",
    diff_id: str = "",
    max_lines: int = 60,
    compact: bool = False,
) -> Optional[Dict[str, Any]]:
    """Convert a unified diff to a Feishu interactive card dict.

    Returns None if the diff is empty after processing.
    """
    if not diff_text or not diff_text.strip():
        return None

    lines, _ = _render_diff_lines(diff_text, max_lines, compact)
    if not lines:
        return None

    added, removed = count_diff_changes(diff_text)
    fname = basename_for_display(file_path)
    emoji = diff_card_emoji(tool_name)
    stats = " ".join(part for part in (f"+{added}" if added else "", f"-{removed}" if removed else "") if part)

    elements: List[Dict[str, Any]] = [
        {"tag": "markdown", "content": "\n".join(lines)},
        {"tag": "hr"},
        {
            "tag": "markdown",
            "content": f"🟢 +{added} added  🔴 -{removed} removed" if added or removed else "no changes",
        },
    ]

    if diff_id:
        if compact:
            elements.append({
                "tag": "button",
                "text": {"tag": "plain_text", "content": "🔍 展开 diff"},
                "type": "default",
                "width": "fill",
                "behaviors": [
                    {"type": "callback", "value": {"expand_diff": True, "diff_id": diff_id}}
                ],
            })
        else:
            elements.append({
                "tag": "button",
                "text": {"tag": "plain_text", "content": "⬆️ 折叠"},
                "type": "default",
                "width": "fill",
                "behaviors": [
                    {"type": "callback", "value": {"collapse_diff": True, "diff_id": diff_id}}
                ],
            })
            elements.append({
                "tag": "button",
                "text": {"tag": "plain_text", "content": "📄 查看完整 diff"},
                "type": "default",
                "width": "fill",
                "behaviors": [
                    {"type": "callback", "value": {"show_full_diff": True, "diff_id": diff_id}}
                ],
            })

    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"{emoji} {tool_name}: {fname}  {stats}"},
            "template": "green" if not removed else "orange",
        },
        "body": {"elements": elements},
    }


def _full_diff_card(
    diff_text: str,
    tool_name: str,
    file_path: str,
    diff_id: str,
) -> Optional[Dict[str, Any]]:
    """Build the Stage 2 'full diff' card with a markdown code block."""
    if not diff_text or not diff_text.strip():
        return None

    fname = basename_for_display(file_path)
    emoji = diff_card_emoji(tool_name)

    header_lines: List[str] = []
    for raw in diff_text.splitlines():
        if raw.startswith("--- ") or raw.startswith("+++ "):
            prefix = "--- " if raw.startswith("--- ") else "+++ "
            path_part = _esc(raw[4:].strip().lstrip("ab/"))
            header_lines.append(f'<text_tag color="purple">{prefix}{path_part}</text_tag>')
        elif raw.startswith("@@"):
            header_lines.append(f'<text_tag color="purple">{_esc(raw)}</text_tag>')
        elif raw.startswith("-") or raw.startswith("+") or raw.startswith(" "):
            break

    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"{emoji} {tool_name}: {fname} (full)"},
            "template": "blue",
        },
        "body": {
            "elements": [
                {"tag": "markdown", "content": "\n".join(header_lines)},
                {"tag": "hr"},
                {"tag": "markdown", "content": f"```diff\n{diff_text}\n```"},
                {"tag": "hr"},
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "⬆️ 折叠"},
                    "type": "default",
                    "width": "fill",
                    "behaviors": [
                        {"type": "callback", "value": {"collapse_diff": True, "diff_id": diff_id}}
                    ],
                },
            ],
        },
    }


def _diff_card_cache(adapter: "FeishuAdapter") -> Dict[str, Dict[str, Any]]:
    """Return the adapter's diff-card cache, creating it lazily if needed."""
    cache = getattr(adapter, "_diff_card_cache", None)
    if cache is None:
        cache = {}
        adapter._diff_card_cache = cache
    return cache


async def send_feishu_diff_card(
    adapter: "FeishuAdapter",
    chat_id: str,
    diff_text: str,
    tool_name: str,
    file_path: str,
    max_lines: int,
) -> Any:
    """Send an initial compact diff card via Feishu REST API."""
    diff_id = secrets.token_hex(6)
    cache_put(
        _diff_card_cache(adapter),
        diff_id,
        {
            "diff": diff_text,
            "tool_name": tool_name,
            "file_path": file_path,
            "max_lines": max_lines,
        },
        ttl=DIFF_CACHE_TTL_SECONDS,
    )

    card = diff_to_feishu_card(
        diff_text,
        tool_name,
        file_path=file_path,
        diff_id=diff_id,
        max_lines=max_lines,
        compact=True,
    )
    if not card:
        logger.debug("feishu diff card skipped: empty card")
        return None

    result = await adapter.send_card(chat_id, card)
    logger.info(
        "[Feishu card] diff sent tool=%s file=%s diff_id=%s success=%s message_id=%s",
        tool_name,
        file_path,
        diff_id,
        bool(getattr(result, "success", False)),
        getattr(result, "message_id", None) or "(none)",
    )
    return result


def handle_feishu_diff_action(
    adapter: "FeishuAdapter",
    event: Any,
    action_value: Dict[str, Any],
) -> Any:
    """Handle expand/collapse/show_full_diff callback actions.

    Returns a P2CardActionTriggerResponse with a CallBackCard inline update.
    """
    diff_id = action_value.get("diff_id", "")
    cached = cache_get(_diff_card_cache(adapter), diff_id, ttl=DIFF_CACHE_TTL_SECONDS)
    if not cached:
        logger.debug("[Feishu] diff action: diff_id %s not found in cache", diff_id)
        return P2CardActionTriggerResponse() if P2CardActionTriggerResponse else None

    diff_text = cached["diff"]
    tool_name = cached["tool_name"]
    file_path = cached.get("file_path", "")
    max_lines = cached.get("max_lines", 60)

    if action_value.get("expand_diff"):
        action = "expand"
        card = diff_to_feishu_card(
            diff_text, tool_name,
            file_path=file_path,
            diff_id=diff_id,
            max_lines=max_lines,
            compact=False,
        )
    elif action_value.get("collapse_diff"):
        action = "collapse"
        card = diff_to_feishu_card(
            diff_text, tool_name,
            file_path=file_path,
            diff_id=diff_id,
            max_lines=max_lines,
            compact=True,
        )
    elif action_value.get("show_full_diff"):
        action = "show_full"
        card = _full_diff_card(diff_text, tool_name, file_path, diff_id)
    else:
        action = "unknown"
        card = None

    if P2CardActionTriggerResponse is None:
        return None

    response = P2CardActionTriggerResponse()
    if CallBackCard is not None and card:
        cb_card = CallBackCard()
        cb_card.type = "raw"
        cb_card.data = card
        response.card = cb_card
    logger.info(
        "[Feishu card] diff action=%s diff_id=%s tool=%s file=%s has_card=%s",
        action,
        diff_id,
        tool_name,
        file_path,
        card is not None,
    )
    return response
