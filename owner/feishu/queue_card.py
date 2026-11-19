"""Feishu-only interactive card for /queue lifecycle (status + 3 buttons).

飞书专属：其它平台仍走核心纯文本 ack，不进本模块。

状态卡展示「已排队」原文，三按钮：
  - 引导对话 → 将该排队消息按 ``/steer`` 注入当前 turn（不中断、不新开一轮）
  - 立即处理 → FIFO 插队到头 + soft 中断当前 turn
  - 取消     → 从 FIFO 移除，不再执行

与对话引导卡兼容：引导卡选 queue 提交后，**同一消息变身**为本状态卡
（不再在引导 done 卡上放撤销按钮）。

操作者鉴权（C35 越权修复，语义对齐 resume 卡 ``26d3f202cc``）：三个按钮仅
**排队归属者**可操作——比对 ``event.operator.open_id == token meta
source.user_id``。两条注册路径（busy ``/queue`` 与引导卡 queue 提交）都在
token meta 里存了发起者 ``source``，其 ``user_id`` 即发起者 open_id（见
adapter ``_resolve_sender_profile``：``user_id or open_id``）。鉴权信息缺失
（回调无 open_id / token 未知或未携带归属者身份）一律 **fail-closed** 拒绝。
拒绝回 toast 提示且**不**更新卡片：状态卡是群内共享消息，终态卡替换会让
任何群成员一次点击即销毁归属者的操作按钮（变相 DoS），故只提示不冻结。

开关：``feishu.queue_card.enabled``（overlay，默认 true）；关闭则旁路回官方
纯文本 ack，不发本状态卡。

可移除性：删除本文件后，adapter 路由 no-op，/queue 回退纯文本。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from agent.i18n import t
from owner.feishu.sender_name_helpers import operator_display_name

logger = logging.getLogger(__name__)

_PREVIEW_LIMIT = 500


def is_queue_card_enabled() -> bool:
    """``feishu.queue_card.enabled`` from overlay.yaml; default True (fail-open)."""
    try:
        from owner.patch_config import load_patch_config

        section = (load_patch_config() or {}).get("feishu", {}).get("queue_card") or {}
        if not isinstance(section, dict):
            return True
        if "enabled" not in section:
            return True
        return bool(section.get("enabled"))
    except Exception:
        return True



def _preview_text(user_input: str, limit: int = _PREVIEW_LIMIT) -> str:
    text = (user_input or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def _button_row(buttons: list) -> dict[str, Any]:
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
) -> dict[str, Any]:
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


def build_queue_cancelled_card(user_input: str, user_name: str) -> dict[str, Any]:
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


def build_queue_cancel_failed_card(user_input: str, user_name: str) -> dict[str, Any]:
    """取消失败（已开始执行 / 已消费）终态卡。"""
    preview = _preview_text(user_input)
    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": "💡 无法取消", "tag": "plain_text"},
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


def build_queue_submit_failed_card(user_input: str, user_name: str) -> dict[str, Any]:
    """引导卡/状态卡提交调度失败终态卡（对齐 C04 submit_failed）。

    ``_submit_on_loop`` 返回 False 时必须回此卡，禁止仍显示「已排队」。
    """
    preview = _preview_text(user_input)
    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": "💡 排队提交失败", "tag": "plain_text"},
            "template": "orange",
        },
        "body": {
            "elements": [
                {
                    "tag": "markdown",
                    "content": (
                        "未能把该条排入处理队列（事件循环不可用或调度失败）。\n"
                        "请重试，或直接发送 `/queue …`。\n\n"
                        f"**原文：**\n{preview}\n\n"
                        f"由 {user_name or '用户'} 尝试提交。"
                    ),
                },
            ],
        },
    }


def build_queue_executed_card(user_input: str, user_name: str) -> dict[str, Any]:
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


_NOTIFY_PREVIEW_LIMIT = 200
_REMAINING_PREVIEW_LIMIT = 60
_REMAINING_SHOWN_MAX = 3


def build_queue_started_notify_card(
    user_input: str,
    user_name: str,
    *,
    remaining: Optional[list[str]] = None,
) -> dict[str, Any]:
    """精简「已开始执行」通知卡（无按钮），补发到消息流底部。

    原状态卡被 REST patch 原地冻结，但通常已被流式输出顶上去看不见；
    本卡在用户当前视野补发一条，并列出仍在等待的后续队列。
    ``remaining`` 为截断后的原文预览列表。
    """
    preview = _preview_text(user_input, limit=_NOTIFY_PREVIEW_LIMIT)
    content = f"排队项已开始执行。\n\n**原文：**\n{preview}"

    remaining_clean = [r for r in (remaining or []) if r]
    if remaining_clean:
        shown = remaining_clean[:_REMAINING_SHOWN_MAX]
        content += f"\n\n⏳ 队列中还有 **{len(remaining_clean)}** 条等待："
        for idx, item in enumerate(shown, 1):
            content += f"\n{idx}. {item}"
        if len(remaining_clean) > len(shown):
            content += f"\n…及其他 {len(remaining_clean) - len(shown)} 条。"

    content += f"\n\n由 {user_name or '用户'} 发起。"

    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": "▶️ 已开始执行", "tag": "plain_text"},
            "template": "blue",
        },
        "body": {
            "elements": [{"tag": "markdown", "content": content}],
        },
    }


def queue_item_preview(text: str, limit: int = _REMAINING_PREVIEW_LIMIT) -> str:
    """Short single-line preview for queue-list rendering (newlines flattened)."""
    flat = " ".join((text or "").split())
    if len(flat) <= limit:
        return flat
    return flat[:limit] + "..."


def build_queue_process_now_card(user_input: str, user_name: str) -> dict[str, Any]:
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


def build_queue_process_now_failed_card(user_input: str, user_name: str) -> dict[str, Any]:
    """立即处理失败。"""
    preview = _preview_text(user_input)
    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": "💡 无法立即处理", "tag": "plain_text"},
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


def build_queue_steered_card(user_input: str, user_name: str) -> dict[str, Any]:
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
) -> dict[str, Any]:
    """引导(/steer) 失败。"""
    preview = _preview_text(user_input)
    reason_line = f"\n原因：{reason}\n" if reason else "\n"
    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": "💡 无法引导注入", "tag": "plain_text"},
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
    def __init__(self, data: Optional[dict[str, Any]]):
        self.type = "raw"
        self.data = data


class _RawCardResponse:
    """Duck-typed stand-in for ``P2CardActionTriggerResponse``.

    ``handle_card_action_request`` reads ``response.card.data``; the main
    gateway then wraps that dict in the real SDK type it owns.
    """

    def __init__(self, card_data: Optional[dict[str, Any]] = None):
        self.card = _RawCard(card_data) if card_data is not None else None


# ── 操作者鉴权（C35；语义复刻 resume 卡 26d3f202cc）─────────────────────────
#
# 比对字段：点击者 ``event.operator.open_id`` vs 排队归属者
# ``get_token_meta(token)["source"].user_id``。与 resume 卡的
# ``operator.open_id != source.user_id`` 完全同款（open_id 层比对；不比较
# union_id / user_id_alt）。差异点：resume 在回调缺 open_id 时放行，本卡按
# 安全审查要求 **fail-closed**——点击者或归属者任一身份缺失即拒绝。
#
# 拒绝反馈：toast-only（不携带 card）。状态卡是群内共享消息，回调返回 card
# 会原地替换全员可见的卡片——若用终态卡回拒绝，任何群成员点一下就能销毁
# 归属者的三个按钮（变相 DoS）。toast 只给点击者看，卡片保持可操作。

_DENIED_TOAST_KEY = "gateway.queue_card.action_denied"
_DENIED_TOAST_FALLBACK = (
    "只有发起该排队的用户可以操作（引导 / 立即处理 / 取消）。\n"
    "如需排队，请自己发送 `/queue …`。"
)


def queue_denied_toast_text() -> str:
    """拒绝提示文案：i18n 覆盖键优先，缺键回退内置中文（绝不裸显 dotted key）。"""
    try:
        rendered = t(_DENIED_TOAST_KEY)
    except Exception:  # pragma: no cover - t() 不抛；防御性兜底
        rendered = ""
    if rendered and rendered != _DENIED_TOAST_KEY:
        return rendered
    return _DENIED_TOAST_FALLBACK


def queue_operator_open_id(event: Any) -> str:
    """点击该按钮的飞书用户 open_id（缺失返回空串）。"""
    operator = getattr(event, "operator", None)
    return str(getattr(operator, "open_id", "") or "").strip()


def queue_owner_open_id(token: str) -> str:
    """排队归属者身份：token meta 里注册时的 ``source.user_id``（缺失返回空串）。"""
    if not token:
        return ""
    try:
        from owner.patches.queue_cancel_patch import get_token_meta
    except Exception:  # pragma: no cover - owner 包内部互引，仅防御
        return ""
    meta = get_token_meta(token)
    source = meta.get("source")
    return str(getattr(source, "user_id", "") or "").strip()


def is_queue_operator_authorized(token: str, event: Any) -> bool:
    """True 仅当点击者是排队归属者；身份信息缺失时 fail-closed 返回 False。"""
    operator_id = queue_operator_open_id(event)
    if not operator_id:
        return False
    owner_id = queue_owner_open_id(token)
    if not owner_id:
        return False
    return operator_id == owner_id


def queue_denied_response(resp_cls: Any) -> Any:
    """Toast-only 拒绝响应：不携带 card，共享状态卡保持原样。"""
    if resp_cls is None:
        # lark SDK 缺失（profile 容器经 HTTP 转发）：无 toast 通道，动作已
        # 被阻断（fail-closed 生效），仅缺可见反馈。
        return _RawCardResponse(None)
    try:
        from lark_oapi.event.callback.model.p2_card_action_trigger import CallBackToast
    except ImportError:  # pragma: no cover - resp_cls 在则 toast 类必在
        return _RawCardResponse(None)
    response = resp_cls()
    toast = CallBackToast()
    toast.type = "info"
    toast.content = queue_denied_toast_text()
    response.toast = toast
    return response


def handle_queue_card_action(
    *,
    adapter: Any,
    action_value: dict[str, Any],
    event: Any,
) -> Any:
    """Process queue status card button clicks (Feishu only).

    [owner] C35 操作者鉴权：仅排队归属者（``event.operator.open_id`` ==
    token meta ``source.user_id``）可操作；点击者或归属者身份缺失时
    fail-closed 拒绝（toast 提示、不更新共享卡片）。详见模块头「操作者鉴权」。
    """
    P2CardActionTriggerResponse, CallBackCard = _lark_card_types()

    step = str(action_value.get("hermes_queue_card") or "").strip()
    token = str(action_value.get("queue_token") or "").strip()
    _alog = logging.getLogger(adapter.__class__.__module__)
    _alog.info("[Feishu card] queue action step=%s token=%s", step, token[:8] if token else "-")

    # [owner] C35: fail-closed 操作者鉴权——非归属者 / 身份缺失一律拒绝。
    if not is_queue_operator_authorized(token, event):
        _alog.warning(
            "[Feishu card] queue action DENIED step=%s token=%s operator=%s owner=%s",
            step,
            token[:8] if token else "-",
            queue_operator_open_id(event) or "<missing>",
            queue_owner_open_id(token) or "<missing>",
        )
        return queue_denied_response(P2CardActionTriggerResponse)

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
    action_value: dict[str, Any],
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
    action_value: dict[str, Any],
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
    action_value: dict[str, Any],
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


# =============================================================================
# Moved out of plugins/platforms/feishu/adapter.py (T2-14)
#
# Send-side glue (build + send + trace) and action-side trace used to sit inline
# in the upstream class body. Pure local code, no upstream counterpart deleted —
# see the same note in owner/feishu/model_picker.py.
# =============================================================================


async def send_queue_status_card(
    adapter: Any,
    *,
    chat_id: str,
    user_input: str,
    user_name: str,
    queue_token: str,
    depth: int = 0,
    source: Any = None,
    metadata: Optional[dict[str, Any]] = None,
) -> Any:
    """Send the Feishu-only queue status card (queued text + 3 action buttons).

    Returns the ``SendResult`` from the send so callers (e.g.
    ``owner/patches/queue_cancel_patch.py``) can react to a failed post.
    When ``feishu.queue_card.enabled`` is false, returns a stub with
    ``success=False`` so callers keep the stock text ack.
    """
    if not is_queue_card_enabled():
        logger.info("[Feishu card] queue status skipped (queue_card.enabled=false)")
        from types import SimpleNamespace

        return SimpleNamespace(success=False, message_id=None)
    card = build_queue_status_card(
        user_input,
        user_name,
        queue_token=queue_token,
        depth=depth or None,
    )
    result = await adapter.send_card(
        chat_id=chat_id, card=card, metadata=metadata,
    )
    logger.info(
        "[Feishu card] queue status sent token=%s chat_id=%s success=%s message_id=%s",
        (queue_token or "")[:8],
        chat_id,
        bool(getattr(result, "success", False)),
        getattr(result, "message_id", None) or "(none)",
    )
    return result


def dispatch_queue_card_action(
    adapter: Any, *, event: Any, action_value: dict[str, Any], loop: Any
) -> Any:
    """Trace then delegate a queue-card callback to ``handle_queue_card_action``.

    Named ``dispatch_*`` rather than ``handle_*`` to avoid shadowing the handler
    itself in this module. ``loop`` is accepted (and unused) so the adapter shell
    keeps the exact signature of the other card-action handlers.
    """
    step = action_value.get("hermes_queue_card", "?") if isinstance(action_value, dict) else "?"
    logger.info("[Feishu card] queue action step=%s", step)
    result = handle_queue_card_action(
        adapter=adapter,
        action_value=action_value,
        event=event,
    )
    logger.info(
        "[Feishu card] queue action result step=%s type=%s",
        step,
        type(result).__name__,
    )
    return result
