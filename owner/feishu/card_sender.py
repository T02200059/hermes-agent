"""Feishu interactive card send helpers (C11 base).

Core lives here per 二次开发规范: adapter only does thin import + call.
Profile tagging (C05) is fail-open and only active in send_only mode.
REST bypass path is deferred — base uses the official SDK send path.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from plugins.platforms.feishu.adapter import FeishuAdapter

from gateway.platforms.base import SendResult

logger = logging.getLogger(__name__)


def _inject_profile_tag(node: Any, profile_tag: str) -> None:
    """Recursively set ``hermes_profile`` on interactive button values (C05 prep)."""
    if isinstance(node, dict):
        if node.get("tag") == "button":
            value = node.get("value")
            if isinstance(value, dict):
                value.setdefault("hermes_profile", profile_tag)
        for child in node.values():
            _inject_profile_tag(child, profile_tag)
    elif isinstance(node, list):
        for item in node:
            _inject_profile_tag(item, profile_tag)


def _maybe_tag_card_profile(adapter: "FeishuAdapter", card: Dict[str, Any]) -> None:
    """Tag buttons with active sub-profile name when connection_mode is send_only.

    Fail-open: any error leaves the card untagged. Main gateway (non-send_only)
    is a no-op. Full multi-profile routing lands with C05.
    """
    try:
        if getattr(adapter, "_connection_mode", "") != "send_only":
            return
        from hermes_cli.profiles import get_active_profile_name

        profile_tag = get_active_profile_name()
        if profile_tag and profile_tag not in ("default", "custom"):
            _inject_profile_tag(card, profile_tag)
    except Exception:
        logger.debug("[Feishu] hermes_profile tag injection skipped", exc_info=True)


def get_card_send_lock(adapter: "FeishuAdapter", chat_id: str) -> "asyncio.Lock":
    """Per-chat lock serializing multi-chunk auto-card dispatch.

    Separate from ``_get_chat_lock`` (inbound). Bounded LRU like chat locks.
    Callers use ``FeishuAdapter._get_card_send_lock``; missing method degrades
    to nullcontext in auto_card.
    """
    lock = adapter._card_send_locks.get(chat_id)
    if lock is not None:
        adapter._card_send_locks.move_to_end(chat_id)
        return lock
    if len(adapter._card_send_locks) >= adapter.CHAT_LOCK_MAX_SIZE:
        evicted = False
        for key in list(adapter._card_send_locks):
            if not adapter._card_send_locks[key].locked():
                adapter._card_send_locks.pop(key)
                evicted = True
                break
        if not evicted:
            adapter._card_send_locks.pop(next(iter(adapter._card_send_locks)))
    lock = asyncio.Lock()
    adapter._card_send_locks[chat_id] = lock
    return lock


async def send_card(
    adapter: "FeishuAdapter",
    *,
    chat_id: str,
    card: Dict[str, Any],
    metadata: Optional[Dict[str, Any]] = None,
) -> SendResult:
    """Send a Feishu interactive card via official ``_feishu_send_with_retry``.

    Uses ``_finalize_send_result`` so API-level errors (9499 / 1120004 / …)
    surface as failure and auto-card can retry / fall through to plain text.
    """
    try:
        _maybe_tag_card_profile(adapter, card)
        payload = json.dumps(card, ensure_ascii=False)
        response = await adapter._feishu_send_with_retry(
            chat_id=chat_id,
            msg_type="interactive",
            payload=payload,
            reply_to=None,
            metadata=metadata,
        )
        result = adapter._finalize_send_result(response, "card send failed")
        if result.success:
            logger.info(
                "[Feishu card] send_card OK chat_id=%s message_id=%s",
                chat_id,
                result.message_id or "(none)",
            )
        else:
            logger.warning(
                "[Feishu card] send_card failed chat_id=%s error=%s",
                chat_id,
                result.error,
            )
        return result
    except Exception as exc:
        logger.warning("[Feishu] send_card failed: %s", exc)
        return SendResult(success=False, error=str(exc))
