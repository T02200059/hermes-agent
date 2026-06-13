"""Feishu approval cards (exec approval with interactive buttons + CallBackCard resolved updates).

Core logic extracted from gateway/platforms/feishu.py per 二次开发规范:
- P1 import 编排 + 运行时薄胶水：官方只保留极少量状态（_approval_state 用于 button correlation）+ import + 委托
- 所有卡片构建、i18n label、allow_permanent 配置读取、resolved body 逻辑放在 owner/
- 与 sender_name_cache 配合实现 P45 预热：send 前异步确保回调零延迟拿到真实中文名
- 仅实现 open_id -> 中文名 缓存相关（chat_id/p2p 映射等按补充说明放后面）

Usage in feishu.py:
    from owner.feishu.approval import (
        get_allow_permanent,
        build_approval_card,
        build_resolved_approval_card,
    )
    ...
    allow_permanent = get_allow_permanent()
    card = build_approval_card(command=command, description=description, approval_id=approval_id)
    ...
    # in resolved handler (after auth + _resolve_approval submit)
    command = state.get("command", "") if isinstance(state, dict) else ""
    data = build_resolved_approval_card(choice=choice, user_name=user_name, command=command)
    if CallBackCard is not None:
        card = CallBackCard()
        card.type = "raw"
        card.data = data
        response.card = card
    return response
"""

from __future__ import annotations

from typing import Any, Dict

from agent.i18n import t
from owner.patch_config import _load_patch_owner_config


_APPROVAL_CHOICE_MAP: Dict[str, str] = {
    "approve_once": "once",
    "approve_session": "session",
    "approve_always": "always",
    "deny": "deny",
}


def get_allow_permanent() -> bool:
    """Return whether the 'Always' (permanent) approval button should be shown.

    Reads ``owner.approvals.allow_permanent`` from patch.yaml (owner/config/patch.yaml).
    Defaults to False so users must explicitly choose Once or Session (safer default).
    Fail-open: returns False on any error.
    """
    # [owner] approval: configurable permanent button (see owner/config/patch.yaml + patch_config.py)
    try:
        patch = _load_patch_owner_config()
        return bool(patch.get("approvals", {}).get("allow_permanent", False))
    except Exception:
        return False


def _get_resolved_label(choice: str) -> str:
    """i18n label for resolved state (used in CallBackCard update title)."""
    key_map = {
        "once": "feishu_resolved_once",
        "session": "feishu_resolved_session",
        "always": "feishu_resolved_always",
        "deny": "feishu_resolved_deny",
    }
    return t(f"approval.{key_map.get(choice, 'feishu_resolved_default')}")


def build_approval_card(
    *, command: str, description: str, approval_id: int
) -> Dict[str, Any]:
    """Build the interactive approval card JSON (header + markdown preview + action buttons).

    Truncates long commands.  Conditionally includes "Always" button + hint text
    based on get_allow_permanent().  All user-visible strings via i18n.
    """
    allow_permanent = get_allow_permanent()

    cmd_preview = command[:3000] + "..." if len(command) > 3000 else command

    def _btn(label: str, action_name: str, btn_type: str = "default") -> dict:
        return {
            "tag": "button",
            "text": {"tag": "plain_text", "content": label},
            "type": btn_type,
            "value": {"hermes_action": action_name, "approval_id": approval_id},
        }

    buttons = [
        _btn(t("approval.feishu_btn_once"), "approve_once", "primary"),
        _btn(t("approval.feishu_btn_session"), "approve_session"),
    ]
    if allow_permanent:
        buttons.append(_btn(t("approval.feishu_btn_always"), "approve_always"))
    buttons.append(_btn(t("approval.feishu_btn_deny"), "deny", "danger"))

    md_content = f"```\n{cmd_preview}\n```\n" + t(
        "approval.feishu_reason_label", description=description
    )
    if not allow_permanent:
        md_content += "\n\n" + t("approval.feishu_permanent_disabled")

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": t("approval.feishu_card_title"), "tag": "plain_text"},
            "template": "orange",
        },
        "elements": [
            {
                "tag": "markdown",
                "content": md_content,
            },
            {
                "tag": "action",
                "actions": buttons,
            },
        ],
    }


def build_resolved_approval_card(
    *, choice: str, user_name: str, command: str = ""
) -> Dict[str, Any]:
    """Build the raw card data for CallBackCard inline update after user clicks approve/deny.

    Shows operator name + the (full) command that was approved/denied.
    Used to give immediate visual feedback in the original chat without new message.
    """
    icon = "❌" if choice == "deny" else "✅"
    label = _get_resolved_label(choice)
    body = t("approval.feishu_resolved_body", user_name=user_name, command=command)

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": f"{icon} {label}", "tag": "plain_text"},
            "template": "red" if choice == "deny" else "green",
        },
        "elements": [
            {
                "tag": "markdown",
                "content": body,
            },
        ],
    }
