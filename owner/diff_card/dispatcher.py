"""Diff card dispatch from the Gateway step_callback.

Captures before-state snapshots at tool-start time and, after the tool batch
completes, sends platform-specific diff cards for file-mutating tools.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any, Callable, Dict, Optional, Set

from agent.async_utils import safe_schedule_threadsafe
from agent.display import capture_local_edit_snapshot, extract_edit_diff, LocalEditSnapshot
from gateway.config import Platform

from owner.diff_card.common import (
    DIFF_CARD_TOOLS,
    basename_for_display,
    diff_card_max_lines,
    display_file_path,
)
from owner.diff_card.feishu import send_feishu_diff_card
from owner.diff_card.qqbot import send_qqbot_diff_markdown

logger = logging.getLogger(__name__)


_ToolStartCallback = Callable[[str, str, Dict[str, Any]], None]


def make_tool_start_snapshot_callback(
    original_cb: Optional[_ToolStartCallback],
    snapshots: Dict[str, Optional[LocalEditSnapshot]],
    lock: threading.Lock,
) -> _ToolStartCallback:
    """Return a tool_start_callback that captures edit snapshots.

    The returned callback first forwards to ``original_cb`` (preserving
    existing behaviour such as Discord voice ack), then captures a
    LocalEditSnapshot for write_file / patch / skill_manage and stores it
    keyed by tool_call_id.
    """

    def _callback(tool_call_id: str, name: str, args: Dict[str, Any]) -> None:
        if original_cb is not None:
            try:
                original_cb(tool_call_id, name, args)
            except Exception:
                logger.debug("diff-card original tool_start_callback error", exc_info=True)

        if name not in DIFF_CARD_TOOLS:
            return

        try:
            snapshot = capture_local_edit_snapshot(name, args)
        except Exception:
            logger.debug("diff-card snapshot capture failed for %s", name, exc_info=True)
            return

        if snapshot is None:
            return

        with lock:
            snapshots[tool_call_id] = snapshot

    return _callback


def _parse_args(raw: Any) -> Dict[str, Any]:
    """Normalize tool arguments from OpenAI message format to a dict."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _parse_result_data(result: Optional[str]) -> Optional[Dict[str, Any]]:
    """Best-effort parse tool result JSON."""
    if not isinstance(result, str) or not result.strip():
        return None
    try:
        data = json.loads(result)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def maybe_send_diff_cards(
    runner: Any,
    source: Any,
    prev_tools: Optional[list],
    snapshots: Dict[str, Optional[LocalEditSnapshot]],
    snapshots_lock: threading.Lock,
    loop: Any,
    sent_ids: Optional[Set[str]] = None,
) -> Set[str]:
    """Send diff cards for the previous tool batch, if any.

    Returns the updated ``sent_ids`` set (created if None).
    """
    if sent_ids is None:
        sent_ids: Set[str] = set()

    if not prev_tools:
        return sent_ids

    adapter = runner.adapters.get(source.platform) if runner is not None else None
    if adapter is None:
        return sent_ids

    if source.platform not in (Platform.FEISHU, Platform.QQBOT):
        return sent_ids

    chat_id = getattr(source, "chat_id", None) or ""
    if not chat_id:
        return sent_ids

    for tool in prev_tools:
        if not isinstance(tool, dict):
            continue

        tool_name = tool.get("name", "")
        if tool_name not in DIFF_CARD_TOOLS:
            continue

        tool_call_id = tool.get("tool_call_id", "")
        if tool_call_id and tool_call_id in sent_ids:
            continue

        try:
            args = _parse_args(tool.get("arguments"))
            result = tool.get("result")
            result_data = _parse_result_data(result)

            with snapshots_lock:
                snapshot = snapshots.pop(tool_call_id, None) if tool_call_id else None

            diff = extract_edit_diff(
                tool_name,
                result,
                function_args=args,
                snapshot=snapshot,
            )
            if not diff:
                continue

            file_path = display_file_path(tool_name, args, snapshot, result_data)
            max_lines = diff_card_max_lines(tool_name)

            if source.platform == Platform.FEISHU:
                safe_schedule_threadsafe(
                    send_feishu_diff_card(
                        adapter, chat_id, diff, tool_name, file_path, max_lines
                    ),
                    loop,
                    logger=logger,
                    log_message="feishu diff card scheduling error",
                )
            elif source.platform == Platform.QQBOT:
                safe_schedule_threadsafe(
                    send_qqbot_diff_markdown(
                        adapter, chat_id, diff, tool_name, file_path, max_lines
                    ),
                    loop,
                    logger=logger,
                    log_message="qqbot diff markdown scheduling error",
                )

            if tool_call_id:
                sent_ids.add(tool_call_id)

        except Exception:
            logger.debug("diff card dispatch error for %s", tool_name, exc_info=True)

    return sent_ids
