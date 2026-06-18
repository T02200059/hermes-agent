"""Hygiene compression user-facing notice.

Extracted from gateway/run.py per the 二次开发规范 so the official file keeps
only a thin # [owner] delegate call.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


async def send_hygiene_compression_notice(
    adapter: Any,
    source: Any,
    *,
    msg_count: int,
    new_count: int,
    approx_tokens: int,
    new_tokens: int,
    hard_msg_limit: int,
    hyg_threshold_pct: float,
    hyg_context_length: int,
    metadata: Optional[dict] = None,
) -> None:
    """Notify the user that a hygiene compression happened.

    Without this, the footer's context-percentage silently drops from e.g.
    20% to 5% with no visible signal.
    """
    if not adapter or not getattr(source, "chat_id", None):
        return

    turns_before = max(1, msg_count // 3)
    turns_after = max(1, new_count // 3)
    notice = (
        f"🗜️ 对话上下文自动压缩（消息数 {msg_count} 达到配置上限 {hard_msg_limit}）\n"
        f"压缩前：~{turns_before} 轮 / {approx_tokens // 1000}K tokens\n"
        f"压缩后：~{turns_after} 轮 / {new_tokens // 1000}K tokens\n"
        f"压缩阈值：消息数 ≥ {hard_msg_limit} 或 tokens ≥ {int(hyg_threshold_pct * 100)}% of {hyg_context_length // 1000}K"
    )
    try:
        await adapter.send(source.chat_id, notice, metadata=metadata)
    except Exception as err:
        logger.debug("Failed to deliver hygiene compression notice: %s", err)
