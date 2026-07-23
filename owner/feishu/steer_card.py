"""Feishu interactive guide card for /queue, /steer, /goal, /subgoal, /background.

两步交互卡片，供飞书用户点选对话引导操作并输入 prompt：
Step 1: 选择操作类型（5 按钮）-> Step 2: 输入框 + 提交/返回

queue 提交后额外展示「撤销队列」按钮（owner 私有 cancel，不引入核心 /unqueue）。
见 owner/patches/queue_cancel_patch.py。

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


def _preview_text(user_input: str, limit: int = 80) -> str:
    return user_input[:limit] + ("..." if len(user_input) > limit else "")


def build_done_card(
    action_key: str,
    user_input: str,
    user_name: str,
    *,
    guide_id: str = "",
    queue_token: Optional[str] = None,
) -> Dict[str, Any]:
    """提交后的确认卡片。

    queue 且带 ``queue_token`` 时附加「撤销队列」按钮；其余操作保持静态终态。
    """
    action = next((a for a in _GUIDE_ACTIONS if a["key"] == action_key), None)
    if not action:
        return {
            "schema": "2.0",
            "config": {"wide_screen_mode": True},
            "header": {"title": {"content": "✅ 已提交", "tag": "plain_text"}, "template": "green"},
            "body": {"elements": [{"tag": "markdown", "content": "已提交"}]},
        }

    preview = _preview_text(user_input)
    elements: List[Dict[str, Any]] = [
        {
            "tag": "markdown",
            "content": (
                f"命令: `{action['cmd']}`\n\n"
                f"内容: {preview}\n\n"
                f"由 {user_name} 发起。"
            ),
        },
    ]

    # queue only: allow abandoning the pending FIFO item before it starts.
    if action_key == "queue" and queue_token:
        elements[0]["content"] += "\n\n⏳ 已排队，等待当前对话结束后执行。"
        elements.append({
            "tag": "button",
            "text": {"tag": "plain_text", "content": "🗑 撤销队列"},
            "type": "danger",
            "value": {
                "hermes_feishu_guide": "cancel_queue",
                "guide_id": guide_id,
                "queue_token": queue_token,
                "user_input": preview,
                "user_name": user_name,
            },
        })

    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": f"✅ {action['label']}", "tag": "plain_text"},
            "template": "green",
        },
        "body": {"elements": elements},
    }


def build_queue_cancelled_card(user_input: str, user_name: str) -> Dict[str, Any]:
    """撤销成功后的终态卡（无按钮）。"""
    preview = _preview_text(user_input)
    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": "🗑 已撤销队列", "tag": "plain_text"},
            "template": "orange",
        },
        "body": {
            "elements": [
                {
                    "tag": "markdown",
                    "content": (
                        f"已从排队中移除，不会再执行。\n\n"
                        f"内容: {preview}\n\n"
                        f"由 {user_name} 撤销。"
                    ),
                },
            ],
        },
    }


def build_queue_cancel_failed_card(user_input: str, user_name: str) -> Dict[str, Any]:
    """撤销失败（已开始执行 / 队列已空）终态卡。"""
    preview = _preview_text(user_input)
    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": "⚠️ 无法撤销", "tag": "plain_text"},
            "template": "grey",
        },
        "body": {
            "elements": [
                {
                    "tag": "markdown",
                    "content": (
                        "该排队项可能已开始执行，或已被消费/清理。\n"
                        "如需中断当前运行，请使用 `/stop`。\n\n"
                        f"内容: {preview}\n\n"
                        f"由 {user_name} 尝试撤销。"
                    ),
                },
            ],
        },
    }


def build_queue_executed_card(user_input: str, user_name: str) -> Dict[str, Any]:
    """队列项已开始执行：冻结终态卡（无按钮）。"""
    preview = _preview_text(user_input)
    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": "▶️ 已开始执行", "tag": "plain_text"},
            "template": "blue",
        },
        "body": {
            "elements": [
                {
                    "tag": "markdown",
                    "content": (
                        "排队项已进入本轮对话，无法再撤销。\n\n"
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
    - ``cancel_queue`` -> drop owner-tagged FIFO item + final card
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

    logger.info(
        "[Feishu card] guide action step=%s guide_id=%s action_key=%s",
        step,
        guide_id,
        action_value.get("action_key", "") if isinstance(action_value, dict) else "",
    )

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

    # queue done card -> 撤销排队
    if step == "cancel_queue":
        return _handle_cancel_queue(
            adapter=adapter,
            action_value=action_value,
            event=event,
            resp_cls=P2CardActionTriggerResponse,
            card_cls=CallBackCard,
        )

    # Step 2 -> 提交
    if step == "submit":
        action_key = action_value.get("action_key", "")
        form_value = action_value.get("form_value", {})
        user_input = ""
        if isinstance(form_value, dict):
            user_input = (form_value.get("guide_input") or "").strip()
        if not user_input:
            # Use adapter's module logger — owner.* loggers aren't wired to gateway log
            _alog = logging.getLogger(adapter.__class__.__module__)
            _alog.warning(
                "[Feishu Guide] submit: empty user_input — form_value type=%s keys=%s action_value_keys=%s",
                type(form_value).__name__,
                list(form_value.keys()) if isinstance(form_value, dict) else "N/A",
                list(action_value.keys()) if isinstance(action_value, dict) else "N/A",
            )
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

        # queue: mint cancel token; associate by prompt text at enqueue time
        # (never put token in message_id — Feishu treats it as reply_to).
        # Bind card open_message_id so we can freeze the card when execution starts.
        queue_token: Optional[str] = None
        if action_key == "queue":
            from owner.patches.queue_cancel_patch import register_scheduled_token

            queue_token = str(_uuid.uuid4())
            context = getattr(event, "context", None)
            card_message_id = str(getattr(context, "open_message_id", "") or "")
            chat_id = str(getattr(context, "open_chat_id", "") or "")
            if not chat_id and isinstance(state, dict):
                stored = state.get("source")
                chat_id = str(getattr(stored, "chat_id", "") or "")
            register_scheduled_token(
                queue_token,
                text=user_input,
                card_message_id=card_message_id,
                chat_id=chat_id,
                user_input=user_input,
                user_name=user_name,
                app_id=str(getattr(adapter, "_app_id", "") or ""),
                app_secret=str(getattr(adapter, "_app_secret", "") or ""),
            )

        command = f"{action['cmd']} {user_input}"
        _route_guide_command(
            adapter, command, open_id, state, queue_token=queue_token,
        )

        return _card_response(
            P2CardActionTriggerResponse, CallBackCard,
            build_done_card(
                action_key,
                user_input,
                user_name,
                guide_id=guide_id,
                queue_token=queue_token,
            ),
        )

    return _empty_response(P2CardActionTriggerResponse)


def _handle_cancel_queue(
    *,
    adapter: Any,
    action_value: Dict[str, Any],
    event: Any,
    resp_cls: Any,
    card_cls: Any,
) -> Any:
    """Process「撤销队列」: drop FIFO item by token and freeze the card."""
    from owner.patches.queue_cancel_patch import cancel_queued_by_token

    token = str(action_value.get("queue_token") or "").strip()
    user_input = str(action_value.get("user_input") or "")
    operator = getattr(event, "operator", None)
    open_id = str(getattr(operator, "open_id", "") or "")
    user_name = (
        str(action_value.get("user_name") or "").strip()
        or operator_display_name(adapter, open_id)
        or "用户"
    )

    _alog = logging.getLogger(adapter.__class__.__module__)
    status = cancel_queued_by_token(adapter, token) if token else "invalid"
    _alog.info(
        "[Feishu Guide] cancel_queue: status=%s token=%s",
        status,
        (token or "")[:8],
    )

    if status == "ok":
        card = build_queue_cancelled_card(user_input, user_name)
    else:
        card = build_queue_cancel_failed_card(user_input, user_name)
    return _card_response(resp_cls, card_cls, card)


def _route_guide_command(
    adapter: Any,
    command: str,
    open_id: str,
    state: dict,
    *,
    queue_token: Optional[str] = None,
) -> None:
    """Route a guide card submission as a synthetic slash command.

    Rebuilds a real inbound ``MessageSource`` and routes the command through
    the adapter's standard inbound pipeline (``_handle_message_with_guards``)
    so it lands in the gateway runner's running-agent fast path — the same
    path a manually typed ``/steer`` (or ``/queue``/``/goal``/``/subgoal``/
    ``/background``) takes.

    The source stored on the guide card (built in the feishu_guide shortcut
    in ``bot_menu.py``) carries ``chat_type="p2p"`` and a bare ``open_id``,
    which produces a *different* session key from the running agent's
    ``chat_type="dm"`` key. Reusing it verbatim made the fast-path guard
    (``_quick_key in self._running_agents``) miss, so ``/steer`` fell through
    to the cold path and was answered by the LLM instead of injected into
    the running turn. We therefore resolve a fresh source the same way
    ``bot_menu.py`` does for ordinary bot-menu commands.

    When ``queue_token`` is set, cancel association is via
    ``register_scheduled_token`` + enqueue-time text match (see
    ``queue_cancel_patch``). ``message_id`` stays empty so Feishu reply_to
    is not polluted with a synthetic id.
    """
    from datetime import datetime
    from types import SimpleNamespace

    # Use adapter's module logger — owner.* loggers aren't wired to gateway log
    _alog = logging.getLogger(adapter.__class__.__module__)

    stored_source = state.get("source") if isinstance(state, dict) else None
    chat_id = getattr(stored_source, "chat_id", "") or ""
    if not chat_id:
        _alog.warning("[Feishu Guide] _route_guide_command: chat_id empty — state was lost or never stored")
        return

    loop = getattr(adapter, "_loop", None)
    if loop is None:
        _alog.warning("[Feishu Guide] _route_guide_command: adapter._loop is None")
        return

    _alog.info(
        "[Feishu Guide] _route_guide_command: scheduling dispatch command=%s chat_id=%s token=%s",
        command, chat_id, (queue_token or "")[:8],
    )

    async def _dispatch():
        try:
            from owner.feishu.sender_name_helpers import pre_warm_sender_name
            from gateway.platforms.base import MessageEvent, MessageType
            from owner.patches.queue_cancel_patch import should_skip_dispatch

            # Cancel won the race before this coroutine ran — drop silently.
            if should_skip_dispatch(queue_token):
                _alog.info(
                    "[Feishu Guide] _dispatch: skip cancelled queue token=%s",
                    (queue_token or "")[:8],
                )
                return

            # Rebuild a source whose session key matches the running agent's,
            # mirroring the ordinary bot-menu command path (bot_menu.py). The
            # feishu_guide shortcut stored a p2p/open-id-only source whose key
            # differs from the live "dm" session, so the running-agent fast
            # path never matched and /steer was processed as a fresh turn.
            pre_warm_sender_name(adapter, open_id)
            sender_id = SimpleNamespace(open_id=open_id, user_id=None, union_id=None)
            sender_profile = await adapter._resolve_sender_profile(sender_id)
            chat_info = await adapter.get_chat_info(chat_id)
            source = adapter.build_source(
                chat_id=chat_id,
                chat_name=chat_info.get("name") or chat_id or "Feishu Chat",
                chat_type=adapter._resolve_source_chat_type(
                    chat_info=chat_info, event_chat_type="p2p"
                ),
                user_id=sender_profile["user_id"],
                user_name=sender_profile["user_name"],
                thread_id=None,
                user_id_alt=sender_profile["user_id_alt"],
            )
            # message_id MUST stay empty/real Feishu ids only. A synthetic
            # owner-q:* id is used as reply_to by gateway and fails Feishu API.
            synthetic_event = MessageEvent(
                text=command,
                message_type=MessageType.COMMAND,
                source=source,
                raw_message=None,
                message_id="",
                timestamp=datetime.now(),
            )
            _alog.info(
                "[Feishu Guide] _dispatch: calling _handle_message_with_guards "
                "for command=%s chat_type=%s chat_id=%s token=%s",
                command, source.chat_type, chat_id, (queue_token or "")[:8] or "-",
            )
            await adapter._handle_message_with_guards(synthetic_event)
            _alog.info("[Feishu Guide] _dispatch: _handle_message_with_guards returned for command=%s", command)
        except Exception as exc:
            _alog.warning("[Feishu Guide] guide card route failed: %s", exc, exc_info=True)

    submitted = adapter._submit_on_loop(loop, _dispatch())
    if not submitted:
        _alog.warning("[Feishu Guide] _route_guide_command: _submit_on_loop returned False")


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
