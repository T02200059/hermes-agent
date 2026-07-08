"""Feishu interactive guide card for /queue, /steer, /goal, /subgoal, /background.

两步交互卡片，供飞书用户点选对话引导操作并输入 prompt：
Step 1: 选择操作类型（5 按钮）-> Step 2: 输入框 + 提交/返回

参考:
- owner/feishu/model_picker.py  (多步卡片 + 合成命令)
- owner/feishu/clarify_card.py  (form + input 输入框)

可移除性：删除此文件后，/feishu_guide 命令回退到纯文本提示。
"""

from __future__ import annotations

import logging
import uuid as _uuid
from typing import Any, Dict, List, Optional

from owner.feishu.sender_name_helpers import operator_display_name

logger = logging.getLogger(__name__)

# ── 5 种对话引导操作 ──────────────────────────────────────────────────────────

_GUIDE_ACTIONS: List[Dict[str, str]] = [
    {
        "key": "queue",
        "label": "📥 排队执行",
        "desc": "排队到下一轮（不中断当前）",
        "cmd": "/queue",
        "placeholder": "输入要排队的 prompt",
    },
    {
        "key": "steer",
        "label": "🧭 注入引导",
        "desc": "注入到下次工具调用后（不中断）",
        "cmd": "/steer",
        "placeholder": "输入要注入的 prompt",
    },
    {
        "key": "goal",
        "label": "🎯 设定目标",
        "desc": "设定跨轮常驻目标",
        "cmd": "/goal",
        "placeholder": "输入目标描述",
    },
    {
        "key": "subgoal",
        "label": "➕ 添加子目标",
        "desc": "给当前目标加附加条件",
        "cmd": "/subgoal",
        "placeholder": "输入子目标描述",
    },
    {
        "key": "background",
        "label": "🔀 后台执行",
        "desc": "后台异步执行，不占当前会话",
        "cmd": "/background",
        "placeholder": "输入后台 prompt",
    },
]


# ── 卡片构建器 ─────────────────────────────────────────────────────────────────

def build_guide_card(guide_id: str) -> Dict[str, Any]:
    """Step 1: 操作选择卡片 - 5 个按钮。"""
    elements: List[Dict[str, Any]] = [
        {"tag": "markdown", "content": "选择对话引导操作："},
    ]
    for action in _GUIDE_ACTIONS:
        elements.append({
            "tag": "button",
            "text": {"tag": "plain_text", "content": f"{action['label']}  ·  {action['desc']}"},
            "type": "default",
            "value": {
                "hermes_feishu_guide": "select",
                "guide_id": guide_id,
                "action_key": action["key"],
            },
        })
    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": "🎛 对话引导", "tag": "plain_text"},
            "template": "blue",
        },
        "body": {"elements": elements},
    }


def build_input_card(guide_id: str, action_key: str) -> Dict[str, Any]:
    """Step 2: 输入框卡片 - form + input + 提交/返回。"""
    action = next((a for a in _GUIDE_ACTIONS if a["key"] == action_key), None)
    if not action:
        return build_guide_card(guide_id)

    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": f"{action['label']}", "tag": "plain_text"},
            "template": "blue",
        },
        "body": {
            "elements": [
                {"tag": "markdown", "content": f"**{action['desc']}**\n\n命令: `{action['cmd']} <prompt>`"},
                {
                    "tag": "form",
                    "name": f"guide_form_{guide_id}",
                    "elements": [
                        {
                            "tag": "input",
                            "name": "guide_input",
                            "placeholder": {
                                "tag": "plain_text",
                                "content": action["placeholder"],
                            },
                            "label": {
                                "tag": "plain_text",
                                "content": "输入：",
                            },
                            "label_position": "left",
                            "required": True,
                            "max_length": 1000,
                            "input_type": "multiline_text",
                            "rows": 4,
                            "auto_resize": True,
                        },
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "提交"},
                            "type": "primary",
                            "action_type": "form_submit",
                            "name": "submit_guide",
                            "value": {
                                "hermes_feishu_guide": "submit",
                                "guide_id": guide_id,
                                "action_key": action_key,
                            },
                        },
                    ],
                },
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "⬅ 返回"},
                    "type": "default",
                    "value": {
                        "hermes_feishu_guide": "back",
                        "guide_id": guide_id,
                    },
                },
            ],
        },
    }


def build_done_card(action_key: str, user_input: str, user_name: str) -> Dict[str, Any]:
    """提交后的确认卡片。"""
    action = next((a for a in _GUIDE_ACTIONS if a["key"] == action_key), None)
    if not action:
        return {
            "schema": "2.0",
            "config": {"wide_screen_mode": True},
            "header": {"title": {"content": "✅ 已提交", "tag": "plain_text"}, "template": "green"},
            "body": {"elements": [{"tag": "markdown", "content": f"已提交"}]},
        }

    preview = user_input[:80] + ("..." if len(user_input) > 80 else "")
    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": f"✅ {action['label']}", "tag": "plain_text"},
            "template": "green",
        },
        "body": {
            "elements": [
                {
                    "tag": "markdown",
                    "content": (
                        f"命令: `{action['cmd']}`\n\n"
                        f"内容: {preview}\n\n"
                        f"由 {user_name} 发起。"
                    ),
                },
            ],
        },
    }


# ── 回调处理 ───────────────────────────────────────────────────────────────────

def handle_guide_card_action(
    *,
    adapter: Any,
    action_value: Dict[str, Any],
    event: Any,
) -> Any:
    """Process a guide card callback.

    Dispatches on the ``hermes_feishu_guide`` step value:
    - ``select`` -> build input form card
    - ``back`` -> rebuild selection card
    - ``submit`` -> route slash command + build done card
    """
    try:
        from lark_oapi.event.callback.model.p2_card_action_trigger import (
            CallBackCard,
            P2CardActionTriggerResponse,
        )
    except ImportError:
        return None

    step = action_value.get("hermes_feishu_guide", "")
    guide_id = action_value.get("guide_id", "")

    logger.info("[Feishu Guide] card action: step=%s guide_id=%s action_value=%s", step, guide_id, action_value)

    # Step 1 -> Step 2: 用户选了某个操作，弹出输入框
    if step == "select":
        action_key = action_value.get("action_key", "")
        return _card_response(
            P2CardActionTriggerResponse, CallBackCard,
            build_input_card(guide_id, action_key),
        )

    # Step 2 -> Step 1: 返回
    if step == "back":
        return _card_response(
            P2CardActionTriggerResponse, CallBackCard,
            build_guide_card(guide_id),
        )

    # Step 2 -> 提交
    if step == "submit":
        action_key = action_value.get("action_key", "")
        form_value = action_value.get("form_value", {})
        user_input = ""
        if isinstance(form_value, dict):
            user_input = (form_value.get("guide_input") or "").strip()
        if not user_input:
            return _empty_response(P2CardActionTriggerResponse)

        # 查操作定义
        action = next((a for a in _GUIDE_ACTIONS if a["key"] == action_key), None)
        if not action:
            return _empty_response(P2CardActionTriggerResponse)

        # 弹出状态
        state = getattr(adapter, "_guide_card_state", {}).pop(guide_id, {})
        operator = getattr(event, "operator", None)
        open_id = str(getattr(operator, "open_id", "") or "")
        user_name = operator_display_name(adapter, open_id)

        # 合成 /<cmd> <input> 命令
        command = f"{action['cmd']} {user_input}"
        _route_guide_command(adapter, command, open_id, state)

        return _card_response(
            P2CardActionTriggerResponse, CallBackCard,
            build_done_card(action_key, user_input, user_name),
        )

    return _empty_response(P2CardActionTriggerResponse)


def _route_guide_command(
    adapter: Any, command: str, open_id: str, state: dict
) -> None:
    """Route a guide card submission as a synthetic slash command.

    Submits the command through the adapter's event loop as a
    ``MessageType.COMMAND`` event so it follows the same processing
    path as a manually typed command.
    """
    from datetime import datetime

    source = state.get("source") if isinstance(state, dict) else None
    if source is None:
        return
    chat_id = getattr(source, "chat_id", "") or ""
    if not chat_id:
        return

    loop = getattr(adapter, "_loop", None)
    if loop is None:
        return

    async def _dispatch():
        try:
            from gateway.platforms.base import MessageEvent, MessageType

            synthetic_event = MessageEvent(
                text=command,
                message_type=MessageType.COMMAND,
                source=source,
                raw_message=None,
                message_id="",
                timestamp=datetime.now(),
            )
            await adapter._handle_message_with_guards(synthetic_event)
        except Exception as exc:
            logger.warning("[Feishu] guide card route failed: %s", exc)

    adapter._submit_on_loop(loop, _dispatch())


# ── helpers ────────────────────────────────────────────────────────────────────

def _empty_response(resp_cls: Any) -> Any:
    return resp_cls() if resp_cls else None


def _card_response(resp_cls: Any, card_cls: Any, card_data: dict) -> Any:
    if resp_cls is None or card_cls is None:
        return None
    response = resp_cls()
    card = card_cls()
    card.type = "raw"
    card.data = card_data
    response.card = card
    return response
