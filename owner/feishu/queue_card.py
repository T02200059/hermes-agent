"""Feishu-only interactive card for /queue lifecycle (status + 3 buttons).

飞书专属：其它平台仍走核心纯文本 ack，不进本模块。

状态卡展示「已排队」原文，三按钮：
  - 引导对话 → 将该排队消息按 ``/steer`` 注入当前 turn（不中断、不新开一轮）
  - 立即处理 → FIFO 插队到头 + soft 中断当前 turn
  - 取消     → 从 FIFO 移除，不再执行

与对话引导卡兼容：引导卡选 queue 提交后，**同一消息变身**为本状态卡
（不再在引导 done 卡上放撤销按钮）。

可移除性：删除本文件后，adapter 路由 no-op，/queue 回退纯文本。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from owner.feishu.sender_name_helpers import operator_display_name

logger = logging.getLogger(__name__)

_PREVIEW_LIMIT = 500


def _preview_text(user_input: str, limit: int = _PREVIEW_LIMIT) -> str:
    text = (user_input or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def _button_row(buttons: list) -> Dict[str, Any]:
    """v2 schema: buttons side-by-side via column_set."""
    return {
        "tag": "column_set",
        "flex_mode": "none",
        "background_style": "default",
        "columns": [
            {
                "tag": "column",
                "width": "weighted",
                "weight": 1,
                "vertical_align": "top",
                "elements": [btn],
            }
            for btn in buttons
        ],
    }


def build_queue_status_card(
    user_input: str,
    user_name: str,
    *,
    queue_token: str,
    depth: Optional[int] = None,
) -> Dict[str, Any]:
    """排队中状态卡：原文 + 引导对话(/steer) / 立即处理 / 取消。"""
    preview = _preview_text(user_input)
    depth_line = ""
    if depth is not None and depth > 0:
        depth_line = f"\n\n队列中共 **{depth}** 条（含本条）。"

    elements: list = [
        {
            "tag": "markdown",
            "content": (
                "⏳ 这句话已进入排队，当前任务结束后按先进先出执行。\n\n"
                "• **引导对话**：按 `/steer` 注入当前任务（不中断）\n"
                "• **立即处理**：插队并中断当前任务后立刻执行\n"
                "• **取消**：从队列移除"
                f"{depth_line}\n\n"
                f"**原文：**\n{preview}\n\n"
                f"由 {user_name or '用户'} 发起。"
            ),
        },
    ]

    buttons = [
        {
            "tag": "button",
            "text": {"tag": "plain_text", "content": "🧭 引导对话"},
            "type": "default",
            "value": {
                "hermes_queue_card": "steer",
                "queue_token": queue_token,
                "user_input": preview,
                "user_name": user_name or "",
            },
        },
        {
            "tag": "button",
            "text": {"tag": "plain_text", "content": "▶️ 立即处理"},
            "type": "primary",
            "value": {
                "hermes_queue_card": "process_now",
                "queue_token": queue_token,
                "user_input": preview,
                "user_name": user_name or "",
            },
        },
        {
            "tag": "button",
            "text": {"tag": "plain_text", "content": "🗑 取消"},
            "type": "danger",
            "value": {
                "hermes_queue_card": "cancel",
                "queue_token": queue_token,
                "user_input": preview,
                "user_name": user_name or "",
            },
        },
    ]
    elements.append(_button_row(buttons))

    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": "📥 已排队", "tag": "plain_text"},
            "template": "orange",
        },
        "body": {"elements": elements},
    }


def build_queue_cancelled_card(user_input: str, user_name: str) -> Dict[str, Any]:
    """取消成功终态卡（无按钮）。"""
    preview = _preview_text(user_input)
    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": "🗑 已取消排队", "tag": "plain_text"},
            "template": "orange",
        },
        "body": {
            "elements": [
                {
                    "tag": "markdown",
                    "content": (
                        "已从排队中移除，不会再执行。\n\n"
                        f"**原文：**\n{preview}\n\n"
                        f"由 {user_name or '用户'} 取消。"
                    ),
                },
            ],
        },
    }


def build_queue_cancel_failed_card(user_input: str, user_name: str) -> Dict[str, Any]:
    """取消失败（已开始执行 / 已消费）终态卡。"""
    preview = _preview_text(user_input)
    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": "⚠️ 无法取消", "tag": "plain_text"},
            "template": "grey",
        },
        "body": {
            "elements": [
                {
                    "tag": "markdown",
                    "content": (
                        "该排队项可能已开始执行，或已被消费/清理。\n"
                        "如需中断当前运行，请使用 `/stop`。\n\n"
                        f"**原文：**\n{preview}\n\n"
                        f"由 {user_name or '用户'} 尝试取消。"
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
                        "排队项已进入本轮对话，无法再取消或插队。\n\n"
                        f"**原文：**\n{preview}\n\n"
                        f"由 {user_name or '用户'} 发起。"
                    ),
                },
            ],
        },
    }


def build_queue_process_now_card(user_input: str, user_name: str) -> Dict[str, Any]:
    """立即处理已接受：插队并中断当前任务。"""
    preview = _preview_text(user_input)
    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": "⚡ 立即处理", "tag": "plain_text"},
            "template": "blue",
        },
        "body": {
            "elements": [
                {
                    "tag": "markdown",
                    "content": (
                        "已插队到队首，并请求中断当前任务；"
                        "当前轮结束后将立刻执行本条。\n\n"
                        f"**原文：**\n{preview}\n\n"
                        f"由 {user_name or '用户'} 触发。"
                    ),
                },
            ],
        },
    }


def build_queue_process_now_failed_card(user_input: str, user_name: str) -> Dict[str, Any]:
    """立即处理失败。"""
    preview = _preview_text(user_input)
    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": "⚠️ 无法立即处理", "tag": "plain_text"},
            "template": "grey",
        },
        "body": {
            "elements": [
                {
                    "tag": "markdown",
                    "content": (
                        "该排队项可能已开始执行，或已不在队列中。\n"
                        "如需中断当前运行，请使用 `/stop`。\n\n"
                        f"**原文：**\n{preview}\n\n"
                        f"由 {user_name or '用户'} 尝试。"
                    ),
                },
            ],
        },
    }


def build_queue_steered_card(user_input: str, user_name: str) -> Dict[str, Any]:
    """已按 /steer 注入当前 turn。"""
    preview = _preview_text(user_input)
    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": "🧭 已引导注入", "tag": "plain_text"},
            "template": "blue",
        },
        "body": {
            "elements": [
                {
                    "tag": "markdown",
                    "content": (
                        "已从排队移除，并按 `/steer` 注入当前任务"
                        "（下次工具调用后生效，不中断当前执行）。\n\n"
                        f"**原文：**\n{preview}\n\n"
                        f"由 {user_name or '用户'} 触发。"
                    ),
                },
            ],
        },
    }


def build_queue_steer_failed_card(
    user_input: str,
    user_name: str,
    *,
    reason: str = "",
) -> Dict[str, Any]:
    """引导(/steer) 失败。"""
    preview = _preview_text(user_input)
    reason_line = f"\n原因：{reason}\n" if reason else "\n"
    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": "⚠️ 无法引导注入", "tag": "plain_text"},
            "template": "grey",
        },
        "body": {
            "elements": [
                {
                    "tag": "markdown",
                    "content": (
                        "未能将该排队消息按 `/steer` 注入当前任务。"
                        f"{reason_line}"
                        "若队列中仍有该项，可稍后重试，或改用「立即处理」/「取消」。\n\n"
                        f"**原文：**\n{preview}\n\n"
                        f"由 {user_name or '用户'} 尝试。"
                    ),
                },
            ],
        },
    }


# ── 回调处理 ───────────────────────────────────────────────────────────────────

def _lark_card_types() -> tuple:
    """Return ``(P2CardActionTriggerResponse, CallBackCard)`` or ``(None, None)``.

    Profile containers may not have ``lark_oapi`` installed — the click is
    forwarded over HTTP and the main gateway wraps the returned card JSON.
    Missing SDK must not swallow the action (P2-6).
    """
    try:
        from lark_oapi.event.callback.model.p2_card_action_trigger import (
            CallBackCard,
            P2CardActionTriggerResponse,
        )

        return P2CardActionTriggerResponse, CallBackCard
    except ImportError:
        logger.warning(
            "[owner queue-card] lark SDK missing; relaying raw card JSON"
        )
        return None, None


class _RawCard:
    def __init__(self, data: Optional[Dict[str, Any]]):
        self.type = "raw"
        self.data = data


class _RawCardResponse:
    """Duck-typed stand-in for ``P2CardActionTriggerResponse``.

    ``handle_card_action_request`` reads ``response.card.data``; the main
    gateway then wraps that dict in the real SDK type it owns.
    """

    def __init__(self, card_data: Optional[Dict[str, Any]] = None):
        self.card = _RawCard(card_data) if card_data is not None else None


def handle_queue_card_action(
    *,
    adapter: Any,
    action_value: Dict[str, Any],
    event: Any,
) -> Any:
    """Process queue status card button clicks (Feishu only)."""
    P2CardActionTriggerResponse, CallBackCard = _lark_card_types()

    step = str(action_value.get("hermes_queue_card") or "").strip()
    token = str(action_value.get("queue_token") or "").strip()
    _alog = logging.getLogger(adapter.__class__.__module__)
    _alog.info("[Feishu card] queue action step=%s token=%s", step, token[:8] if token else "-")

    # "guide" kept as alias for older cards already in chat.
    if step in ("steer", "guide"):
        return _handle_steer(
            adapter=adapter,
            action_value=action_value,
            event=event,
            resp_cls=P2CardActionTriggerResponse,
            card_cls=CallBackCard,
        )

    if step == "cancel":
        return _handle_cancel(
            adapter=adapter,
            action_value=action_value,
            event=event,
            resp_cls=P2CardActionTriggerResponse,
            card_cls=CallBackCard,
        )

    if step == "process_now":
        return _handle_process_now(
            adapter=adapter,
            action_value=action_value,
            event=event,
            resp_cls=P2CardActionTriggerResponse,
            card_cls=CallBackCard,
        )

    return _empty_response(P2CardActionTriggerResponse)


def _handle_steer(
    *,
    adapter: Any,
    action_value: Dict[str, Any],
    event: Any,
    resp_cls: Any,
    card_cls: Any,
) -> Any:
    """Treat the queued prompt as ``/steer`` into the running agent."""
    from owner.patches.queue_cancel_patch import get_token_meta, steer_queued_by_token

    token = str(action_value.get("queue_token") or "").strip()
    meta = get_token_meta(token) if token else {}
    user_input = (
        str(action_value.get("user_input") or "").strip()
        or str(meta.get("user_input") or meta.get("text") or "")
    )
    operator = getattr(event, "operator", None)
    open_id = str(getattr(operator, "open_id", "") or "")
    user_name = (
        str(action_value.get("user_name") or "").strip()
        or operator_display_name(adapter, open_id)
        or str(meta.get("user_name") or "")
        or "用户"
    )

    status = steer_queued_by_token(adapter, token) if token else "invalid"
    logging.getLogger(adapter.__class__.__module__).info(
        "[Feishu card] queue steer status=%s token=%s",
        status,
        (token or "")[:8],
    )
    if status == "ok":
        card = build_queue_steered_card(user_input, user_name)
    else:
        reason_map = {
            "not_found": "该项可能已开始执行或已不在队列中。",
            "no_agent": "当前没有可注入的运行中任务。",
            "rejected": "agent 未接受 steer（内容为空或当前不可注入）。",
            "invalid": "无效的排队项。",
        }
        card = build_queue_steer_failed_card(
            user_input,
            user_name,
            reason=reason_map.get(status, status),
        )
    return _card_response(resp_cls, card_cls, card)


def _handle_cancel(
    *,
    adapter: Any,
    action_value: Dict[str, Any],
    event: Any,
    resp_cls: Any,
    card_cls: Any,
) -> Any:
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

    status = cancel_queued_by_token(adapter, token) if token else "invalid"
    logging.getLogger(adapter.__class__.__module__).info(
        "[Feishu card] queue cancel status=%s token=%s",
        status,
        (token or "")[:8],
    )
    if status == "ok":
        card = build_queue_cancelled_card(user_input, user_name)
    else:
        card = build_queue_cancel_failed_card(user_input, user_name)
    return _card_response(resp_cls, card_cls, card)


def _handle_process_now(
    *,
    adapter: Any,
    action_value: Dict[str, Any],
    event: Any,
    resp_cls: Any,
    card_cls: Any,
) -> Any:
    from owner.patches.queue_cancel_patch import process_now_by_token

    token = str(action_value.get("queue_token") or "").strip()
    user_input = str(action_value.get("user_input") or "")
    operator = getattr(event, "operator", None)
    open_id = str(getattr(operator, "open_id", "") or "")
    user_name = (
        str(action_value.get("user_name") or "").strip()
        or operator_display_name(adapter, open_id)
        or "用户"
    )

    status = process_now_by_token(adapter, token) if token else "invalid"
    logging.getLogger(adapter.__class__.__module__).info(
        "[Feishu card] queue process_now status=%s token=%s",
        status,
        (token or "")[:8],
    )
    if status == "ok":
        card = build_queue_process_now_card(user_input, user_name)
    else:
        card = build_queue_process_now_failed_card(user_input, user_name)
    return _card_response(resp_cls, card_cls, card)


def _empty_response(resp_cls: Any) -> Any:
    if resp_cls is None:
        return _RawCardResponse(None)
    return resp_cls()


def _card_response(resp_cls: Any, card_cls: Any, card_data: dict) -> Any:
    if resp_cls is None or card_cls is None:
        return _RawCardResponse(card_data)
    response = resp_cls()
    card = card_cls()
    card.type = "raw"
    card.data = card_data
    response.card = card
    return response
