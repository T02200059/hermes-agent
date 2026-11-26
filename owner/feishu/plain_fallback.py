"""网关级纯文本兜底（Feishu）。

``gateway/platforms/base.py::_send_plain_fallback`` 的默认实现是再调一次
``self.send(content)``，而 Feishu 的 ``send()`` 第一步就进 ``try_auto_card`` ——
于是所谓「纯文本兜底」会先再打一轮卡片，一条回复被放大成多条消息
（2026-11-26 的重复风暴就是这么来的：卡片×3 → 卡片×3 → post → 卡片×3 → 带
「（响应格式化失败，以下为纯文本：）」前缀的文本）。

这里直接走 ``msg_type=text``：保留同一段兜底前缀，但绕开 auto-card 和 post。
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Optional

from agent.i18n import t
from gateway.platforms.base import SendResult

if TYPE_CHECKING:
    from plugins.platforms.feishu.adapter import FeishuAdapter

logger = logging.getLogger(__name__)

# 与 base 的兜底保持一致：只发前 3500 字符，避免同一条内容二次超长。
_PLAIN_FALLBACK_CHAR_LIMIT = 3500


async def send_plain_fallback(
    adapter: FeishuAdapter,
    chat_id: str,
    content: str,
    *,
    reply_to: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> SendResult:
    """发一条真正的纯文本兜底消息（不经过 auto-card）。"""
    limit = _PLAIN_FALLBACK_CHAR_LIMIT
    text = adapter.warning_text(
        t("gateway.notify.plain_fallback_prefix", content=content[:limit]),
        content[:limit],
        chat_id=chat_id,
        metadata=metadata,
    )
    try:
        response = await adapter._feishu_send_with_retry(
            chat_id=chat_id,
            msg_type="text",
            payload=json.dumps({"text": text}, ensure_ascii=False),
            reply_to=reply_to,
            metadata=metadata,
        )
    except Exception as exc:
        logger.error("[Feishu] Plain-text fallback send error: %s", exc, exc_info=True)
        return SendResult(success=False, error=str(exc))
    return adapter._finalize_send_result(response, "plain fallback failed")
