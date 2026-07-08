"""/feishu_guide command handler for gateway - interactive card on Feishu, plain text elsewhere.

Thin-glue caller pattern, same as owner/commands/providers.py:
  ``from owner.commands.feishu_guide import handle_feishu_guide_command``
  Registered via owner/owner-extensions/__init__.py as plugin slash command.

可移除性：删除此文件后 /feishu_guide 命令不可用，gateway ImportError fallback
返回提示字符串，不会崩溃。
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


async def handle_feishu_guide_command(
    *,
    adapters: Any,
    event: Any,
) -> Optional[str]:
    """Handle /feishu_guide command.

    On Feishu: sends an interactive guide card (queue/steer/goal/subgoal/background).
    On other platforms: returns plain text listing the available commands.

    Returns:
        str for plain-text response; None when a Feishu card was sent
        (suppresses default text reply from gateway runner).
    """
    from gateway.config import Platform

    source = getattr(event, "source", None)
    chat_id = getattr(source, "chat_id", "") or ""

    # Feishu: interactive card
    if source and source.platform == Platform.FEISHU:
        adapter = adapters.get(Platform.FEISHU)
        if adapter and hasattr(adapter, "send_guide_card") and chat_id:
            try:
                await adapter.send_guide_card(
                    chat_id=chat_id, source=source,
                )
                return None
            except Exception as exc:
                logger.warning(
                    "[/feishu_guide] Feishu card failed, falling back to text: %s", exc
                )

    # Fallback: plain text
    return _TEXT["fallback"]


_TEXT = {
    "fallback": (
        "🎛 对话引导命令：\n\n"
        "• /queue <prompt> - 排队到下一轮（不中断）\n"
        "• /steer <prompt> - 注入到下次工具调用后（不中断）\n"
        "• /goal <text> - 设定跨轮常驻目标\n"
        "• /subgoal <text> - 给当前目标加附加条件\n"
        "• /background <prompt> - 后台异步执行\n\n"
        "💡 在飞书上使用 /feishu_guide 可弹出交互式卡片。"
    ),
}
