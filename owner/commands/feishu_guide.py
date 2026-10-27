"""/feishu-guide command handler — interactive card on Feishu, plain text elsewhere.

Thin-glue caller pattern, same as owner/commands/providers.py:
  Registered via owner/owner-extensions/__init__.py as plugin slash command.

Gateway plugin dispatch passes ``source`` (not ``adapters``), so we resolve
the live Feishu adapter via ``gateway.run._gateway_runner_ref`` when needed.

可移除性：删除此文件后 /feishu-guide 命令不可用，gateway ImportError fallback
返回提示字符串，不会崩溃。
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _resolve_adapters(adapters: Any) -> Any:
    """Use an explicit adapters map, else the in-process GatewayRunner's."""
    if adapters:
        return adapters
    try:
        from gateway.run import _gateway_runner_ref

        runner = _gateway_runner_ref()
    except Exception:
        return None
    if runner is None:
        return None
    return getattr(runner, "adapters", None) or None


async def handle_feishu_guide_command(
    raw_args: str = "",
    *,
    source: Any = None,
    adapters: Any = None,
    event: Any = None,
    **_kwargs: Any,
) -> Optional[str]:
    """Handle /feishu-guide.

    On Feishu: sends an interactive guide card (queue/steer/goal/subgoal/background).
    On other platforms: returns plain text listing the available commands.

    Returns:
        str for plain-text response; None when a Feishu card was sent
        (suppresses default text reply from gateway runner).
    """
    del raw_args  # unused; slash args not required
    if source is None and event is not None:
        source = getattr(event, "source", None)

    from gateway.config import Platform

    chat_id = getattr(source, "chat_id", "") or ""

    # Feishu: interactive card
    if source and getattr(source, "platform", None) == Platform.FEISHU:
        adapters = _resolve_adapters(adapters)
        adapter = None
        if adapters is not None and hasattr(adapters, "get"):
            adapter = adapters.get(Platform.FEISHU)
        if adapter and hasattr(adapter, "send_guide_card") and chat_id:
            try:
                await adapter.send_guide_card(
                    chat_id=chat_id, source=source,
                )
                return None
            except Exception as exc:
                logger.warning(
                    "[/feishu-guide] Feishu card failed, falling back to text: %s", exc
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
        "💡 在飞书上使用 /feishu-guide 可弹出交互式卡片。"
    ),
}
