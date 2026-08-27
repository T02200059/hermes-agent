"""Feishu approval cards (exec approval with interactive buttons + CallBackCard resolved updates).

Core logic extracted from gateway/platforms/feishu.py per 二次开发规范:
- FeishuApprovalContext encapsulates approval_id state (DiffCardContext pattern)
- 所有卡片构建、i18n label、allow_permanent 配置读取、resolved body 逻辑放在 owner/
- 与 sender_name_cache 配合实现 P45 预热：send 前异步确保回调零延迟拿到真实中文名
- gateway/platforms/feishu.py 只保留 ctx 实例 + 极薄 send/handler 委托
"""

from __future__ import annotations

import itertools
import logging
from types import SimpleNamespace
from typing import Any, Dict, Optional

from agent.i18n import t
from owner.feishu.sender_name_helpers import get_cached_sender_name, operator_display_name
from owner.patch_config import _load_patch_owner_config

logger = logging.getLogger(__name__)


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
    *,
    command: str,
    description: str,
    approval_id: int,
    allow_permanent: Optional[bool] = None,
    smart_denied: bool = False,
) -> Dict[str, Any]:
    """Build the interactive approval card JSON (header + markdown preview + action buttons).

    Truncates long commands.  Conditionally includes "Always" button + hint text
    based on get_allow_permanent().  All user-visible strings via i18n.
    """
    configured_permanent = get_allow_permanent()
    allow_permanent = configured_permanent and allow_permanent is not False

    cmd_preview = command[:3000] + "..." if len(command) > 3000 else command

    def _btn(label: str, action_name: str, btn_type: str = "default") -> dict:
        return {
            "tag": "button",
            "text": {"tag": "plain_text", "content": label},
            "type": btn_type,
            "value": {"hermes_action": action_name, "approval_id": approval_id},
        }

    buttons = [_btn(t("approval.feishu_btn_once"), "approve_once", "primary")]
    if not smart_denied:
        buttons.append(_btn(t("approval.feishu_btn_session"), "approve_session"))
        if allow_permanent:
            buttons.append(_btn(t("approval.feishu_btn_always"), "approve_always"))
    buttons.append(_btn(t("approval.feishu_btn_deny"), "deny", "danger"))

    md_content = f"```\n{cmd_preview}\n```\n" + t(
        "approval.feishu_reason_label", description=description
    )
    if smart_denied:
        # Upstream design (d48bf743f): Smart DENY owner override is one-shot only.
        # Session / Always are hidden so a single override cannot re-open a
        # whole class of commands for the rest of the conversation.
        md_content += "\n\n" + t("approval.feishu_smart_deny_note")
    elif not allow_permanent:
        md_content += "\n\n" + t("approval.feishu_permanent_disabled")

    title_key = (
        "approval.feishu_card_title_smart_deny"
        if smart_denied
        else "approval.feishu_card_title"
    )
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": t(title_key), "tag": "plain_text"},
            # Red template for Smart DENY so it is visually distinct from a
            # normal escalate-style orange approval card.
            "template": "red" if smart_denied else "orange",
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


class FeishuApprovalContext:
    """Encapsulates exec-approval button correlation state for Feishu cards.

    Mirrors DiffCardContext: official gateway code only holds one ctx instance
    and delegates send / callback / resolve to owner helpers.
    """

    def __init__(self) -> None:
        self._state: Dict[int, Dict[str, str]] = {}
        self._counter = itertools.count(1)

    @property
    def state(self) -> Dict[int, Dict[str, str]]:
        """Expose state dict for test compat (adapter._approval_state)."""
        return self._state

    def next_id(self) -> int:
        return next(self._counter)

    def register(
        self,
        approval_id: int,
        *,
        session_key: str,
        message_id: str,
        chat_id: str,
        command: str,
    ) -> None:
        self._state[approval_id] = {
            "session_key": session_key,
            "message_id": message_id,
            "chat_id": chat_id,
            "command": command,
        }

    def get(self, approval_id: Any) -> Optional[Dict[str, str]]:
        return self._state.get(approval_id)

    def pop(self, approval_id: Any) -> Optional[Dict[str, str]]:
        return self._state.pop(approval_id, None)

    @staticmethod
    def choice_from_action(hermes_action: Any) -> str:
        return _APPROVAL_CHOICE_MAP.get(hermes_action, "deny")


async def resolve_approval(
    ctx: FeishuApprovalContext,
    adapter: Any,
    approval_id: Any,
    choice: str,
    user_name: str,
    *,
    open_id: str = "",
    chat_id: str = "",
) -> None:
    """Pop approval state and unblock the waiting agent thread."""
    state = ctx.get(approval_id)
    if not state:
        logger.debug("[Feishu] Approval %s already resolved or unknown", approval_id)
        return
    if not adapter._is_interactive_operator_authorized(open_id):
        logger.warning(
            "[Feishu] Unauthorized approval click by %s for approval %s",
            open_id or "<unknown>",
            approval_id,
        )
        return
    expected_chat_id = str(state.get("chat_id", "") or "")
    if expected_chat_id and chat_id and expected_chat_id != chat_id:
        logger.warning(
            "[Feishu] Approval %s chat mismatch (expected=%s, got=%s)",
            approval_id,
            expected_chat_id,
            chat_id,
        )
        return
    state = ctx.pop(approval_id)
    if not state:
        logger.debug(
            "[Feishu] Approval %s already resolved while validating callback",
            approval_id,
        )
        return
    try:
        from tools.approval import resolve_gateway_approval

        count = resolve_gateway_approval(state["session_key"], choice)
        logger.info(
            "Feishu button resolved %d approval(s) for session %s (choice=%s, user=%s)",
            count,
            state["session_key"],
            choice,
            user_name,
        )
    except Exception as exc:
        logger.error("Failed to resolve gateway approval from Feishu button: %s", exc)


def handle_approval_card_action(
    *,
    adapter: Any,
    ctx: FeishuApprovalContext,
    event: Any,
    action_value: Dict[str, Any],
    loop: Any,
) -> Any:
    """Schedule approval resolution and build the synchronous callback response.

    Failure paths return a frozen error CallBackCard (not an empty response) so
    the click is never silent. Unauthorized / mismatch must **not** unblock the
    agent — only a successful resolve path does.
    """
    try:
        from lark_oapi.event.callback.model.p2_card_action_trigger import (
            CallBackCard,
            P2CardActionTriggerResponse,
        )
    except ImportError:
        CallBackCard = None  # type: ignore[misc, assignment]
        P2CardActionTriggerResponse = None  # type: ignore[misc, assignment]

    def _fail(reason: str, command: str = "") -> Any:
        return _callback_response_with_card(
            CallBackCard,
            P2CardActionTriggerResponse,
            build_failed_approval_card(reason=reason, command=command),
        )

    approval_id = action_value.get("approval_id")
    if approval_id is None:
        logger.warning("[Feishu] Card action missing approval_id")
        return _fail("missing_id")

    state = ctx.get(approval_id)
    if not state:
        logger.info(
            "[Feishu] Approval %s already resolved or unknown (click feedback card)",
            approval_id,
        )
        return _fail("already_resolved")

    command = str(state.get("command", "") or "")
    choice = ctx.choice_from_action(action_value.get("hermes_action"))

    operator = getattr(event, "operator", None)
    open_id = str(getattr(operator, "open_id", "") or "")
    sender_id = SimpleNamespace(
        open_id=open_id,
        user_id=str(getattr(operator, "user_id", "") or ""),
    )
    if not adapter._allow_group_message(sender_id, state.get("chat_id", ""), is_bot=False):
        logger.warning(
            "[Feishu] Unauthorized approval click by %s (group policy)",
            open_id or "<unknown>",
        )
        return _fail("unauthorized", command)

    if not adapter._is_interactive_operator_authorized(open_id):
        logger.warning(
            "[Feishu] Unauthorized approval click by %s for approval %s "
            "(interactive operator allowlist)",
            open_id or "<unknown>",
            approval_id,
        )
        return _fail("unauthorized", command)

    callback_chat_id = str(getattr(getattr(event, "context", None), "open_chat_id", "") or "")
    expected_chat_id = str(state.get("chat_id", "") or "")
    if callback_chat_id and expected_chat_id and callback_chat_id != expected_chat_id:
        logger.warning(
            "[Feishu] Approval callback chat mismatch for %s (expected=%s, got=%s)",
            approval_id,
            expected_chat_id,
            callback_chat_id,
        )
        return _fail("chat_mismatch", command)

    logger.info(
        "[Feishu card] approval action approval_id=%s choice=%s open_id=%r",
        approval_id,
        choice,
        open_id,
    )
    logger.info(
        "[Feishu] approval callback: operator open_id=%r cached=%r",
        open_id,
        get_cached_sender_name(adapter, open_id),
    )
    user_name = operator_display_name(adapter, open_id)

    chat_context = getattr(event, "context", None)
    chat_id = str(getattr(chat_context, "open_chat_id", "") or "")
    if not adapter._submit_on_loop(
        loop,
        resolve_approval(
            ctx,
            adapter,
            approval_id=approval_id,
            choice=choice,
            user_name=user_name,
            open_id=open_id,
            chat_id=chat_id,
        ),
    ):
        logger.warning(
            "[Feishu] Failed to schedule approval resolve for %s", approval_id,
        )
        return _fail("submit_failed", command)

    return _callback_response_with_card(
        CallBackCard,
        P2CardActionTriggerResponse,
        build_resolved_approval_card(
            choice=choice, user_name=user_name, command=command
        ),
    )


def build_resolved_approval_card(
    *, choice: str, user_name: str, command: str = ""
) -> Dict[str, Any]:
    """Build the raw card data for CallBackCard inline update after user clicks approve/deny.

    Shows operator name + the (full) command that was approved/denied.
    Used to give immediate visual feedback in the original chat without new message.
    """
    icon = "❌" if choice == "deny" else "✅"
    label = _get_resolved_label(choice)
    if user_name:
        body = t("approval.feishu_resolved_body", user_name=user_name, command=command)
    else:
        body = t("approval.feishu_resolved_body_no_name", command=command)

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


# Failure reasons for CallBackCard error states (not silent empty responses).
# Keys map to approval.feishu_fail_<reason>_title / _body i18n entries.
_FAIL_REASON_KEYS = frozenset({
    "unauthorized",
    "already_resolved",
    "chat_mismatch",
    "missing_id",
    "submit_failed",
})


def build_failed_approval_card(
    *,
    reason: str,
    command: str = "",
) -> Dict[str, Any]:
    """Build a frozen failure-state card when a click cannot resolve the approval.

    Does **not** unblock the agent (unauthorized / mismatch must not act as
    deny). Removes action buttons so the user sees an explicit outcome instead
    of a silent no-op.
    """
    key = reason if reason in _FAIL_REASON_KEYS else "default"
    title = t(f"approval.feishu_fail_{key}_title")
    body = t(f"approval.feishu_fail_{key}_body")
    cmd = (command or "").strip()
    if cmd:
        preview = cmd[:500] + ("..." if len(cmd) > 500 else "")
        body = f"{body}\n\n```\n{preview}\n```"

    # Orange for "already done" (informational); red for hard failures.
    template = "orange" if key == "already_resolved" else "red"
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": title, "tag": "plain_text"},
            "template": template,
        },
        "elements": [
            {
                "tag": "markdown",
                "content": body,
            },
        ],
    }


def _callback_response_with_card(
    CallBackCard: Any,
    P2CardActionTriggerResponse: Any,
    card_data: Dict[str, Any],
) -> Any:
    """Wrap raw card dict in Feishu SDK CallBackCard response, or empty if SDK missing."""
    if P2CardActionTriggerResponse is None:
        return None
    response = P2CardActionTriggerResponse()
    if CallBackCard is not None and card_data:
        card = CallBackCard()
        card.type = "raw"
        card.data = card_data
        response.card = card
    return response
