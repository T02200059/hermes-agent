"""Feishu interactive cards for memory proposals.

Core logic per 二次开发规范: all card building, button handling, and resolved
CallBackCard logic lives in owner/; gateway/platforms/feishu.py only keeps
thin delegation + the minimal per-session state needed for correlation.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from agent.async_utils import safe_schedule_threadsafe
from agent.i18n import t
from owner.memory.gateway import has_memory_proposal, resolve_memory_approval

logger = logging.getLogger(__name__)

# Text tokens for the memory-proposal card UI.
# TODO(i18n): move these into locales/{lang}.yaml under a memory_proposal.*
# namespace once the feature stabilizes and the i18n catalog footprint is
# justified.  For now they live here so the card-building logic stays
# readable and future extraction is a one-file search-and-replace.
_TEXT = {
    "action.add": "添加",
    "action.replace": "替换",
    "action.remove": "删除",
    "card.title": "💾 Memory 提案确认",
    "card.operation": "操作",
    "card.target": "目标",
    "card.existing": "现有内容",
    "card.new_content": "新内容",
    "card.empty": "(无)",
    "card.empty_content": "(无内容)",
    "btn.approve": "✅ 批准",
    "btn.deny": "🟥 拒绝",
    "resolved.approved": "✅ 内存提案已批准",
    "resolved.denied": "❌ 内存提案已拒绝",
    "confirm.approved": "✅ 内存提案已批准",
    "confirm.denied": "❌ 内存提案已拒绝",
}


def _action_label(action: str) -> str:
    return _TEXT.get(f"action.{action}", action)


def build_memory_proposal_card(
    *,
    action: str,
    target: str,
    old_text: str,
    new_content: str,
    session_key: str,
) -> Dict[str, Any]:
    """Build the interactive memory-proposal card JSON."""
    content_preview = new_content[:1000] if new_content else _TEXT["card.empty_content"]
    old_preview = old_text[:200] if old_text else _TEXT["card.empty"]

    def _btn(label: str, action_name: str, btn_type: str = "default") -> dict:
        return {
            "tag": "button",
            "text": {"tag": "plain_text", "content": label},
            "type": btn_type,
            "value": {"hermes_action": action_name, "session_key": session_key},
        }

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": _TEXT["card.title"], "tag": "plain_text"},
            "template": "purple",
        },
        "elements": [
            {
                "tag": "markdown",
                "content": (
                    f"**{_TEXT['card.operation']}**: {_action_label(action)}\n"
                    f"**{_TEXT['card.target']}**: {target}\n"
                    f"**{_TEXT['card.existing']}**: `...{old_preview}...`\n\n"
                    f"**{_TEXT['card.new_content']}**:\n"
                    f"```\n{content_preview}\n```"
                ),
            },
            {
                "tag": "action",
                "actions": [
                    _btn(_TEXT["btn.approve"], "memory_approve"),
                    _btn(_TEXT["btn.deny"], "memory_deny", "danger"),
                ],
            },
        ],
    }


def build_resolved_memory_proposal_card(*, choice: str) -> Dict[str, Any]:
    """Build the raw card data for CallBackCard inline update after click."""
    if choice == "approve":
        icon, label, template = "✅", _TEXT["resolved.approved"], "green"
    else:
        icon, label, template = "❌", _TEXT["resolved.denied"], "red"

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": f"{icon} {label}", "tag": "plain_text"},
            "template": template,
        },
        "elements": [],
    }


def _session_key_from_action_value(action_value: Dict[str, Any], event: Any) -> str:
    """Extract session_key from button value, with chat_id fallback."""
    session_key = ""
    if isinstance(action_value, dict):
        session_key = str(action_value.get("session_key", ""))
    if not session_key:
        context = getattr(event, "context", None)
        chat_id = str(getattr(context, "open_chat_id", "") or "")
        session_key = f"agent:main:feishu:{chat_id}" if chat_id else ""
    return session_key


def resolve_memory_proposal_button(action_value: Dict[str, Any]) -> Optional[str]:
    """Return 'approve'/'deny' for a memory-proposal button value, or None."""
    if not isinstance(action_value, dict):
        return None
    hermes_action = action_value.get("hermes_action", "")
    if hermes_action == "memory_approve":
        return "approve"
    if hermes_action == "memory_deny":
        return "deny"
    return None


def handle_memory_card_action(
    *,
    adapter: Any,
    event: Any,
    action_value: Dict[str, Any],
    loop: Any,
) -> Any:
    """Resolve a memory-proposal button click and optionally update the card.

    Returns a P2CardActionTriggerResponse (with CallBackCard) when the action
    was handled, or None when it was not a memory-proposal action / no pending
    proposal existed.
    """
    choice = resolve_memory_proposal_button(action_value)
    if choice is None:
        return None

    session_key = _session_key_from_action_value(action_value, event)
    if not session_key or not has_memory_proposal(session_key):
        logger.debug("[Feishu] No pending memory proposal for session %s", session_key)
        return None

    count = 0
    try:
        count = resolve_memory_approval(session_key, choice)
        logger.info(
            "[Feishu] Memory proposal resolved %r for session %s (count=%d)",
            choice, session_key, count,
        )
    except Exception as exc:
        logger.error("[Feishu] resolve_memory_approval failed: %s", exc)

    if count > 0:
        # Send user a confirmation reply.
        confirm_text = _TEXT["confirm.approved"] if choice == "approve" else _TEXT["confirm.denied"]
        try:
            context = getattr(event, "context", None)
            chat_id = str(getattr(context, "open_chat_id", "") or "")
            if chat_id:
                safe_schedule_threadsafe(
                    adapter.send(chat_id=chat_id, content=confirm_text),
                    loop,
                    logger=logger,
                    log_message="memory proposal confirm send failed",
                )
        except Exception as exc:
            logger.warning("[Feishu] failed to send memory proposal confirm: %s", exc)

    # Update the original card inline to show the resolved state.
    try:
        from lark_oapi.event.callback.model.p2_card_action_trigger import (
            CallBackCard,
            P2CardActionTriggerResponse,
        )
        if CallBackCard is not None and P2CardActionTriggerResponse is not None:
            response = P2CardActionTriggerResponse()
            card = CallBackCard()
            card.type = "raw"
            card.data = build_resolved_memory_proposal_card(choice=choice)
            response.card = card
            return response
    except Exception as exc:
        logger.debug("[Feishu] memory proposal CallBackCard build failed: %s", exc)

    return None


def send_memory_proposal_card(
    adapter: Any,
    *,
    chat_id: str,
    entry: Any,
    metadata: Optional[Dict[str, Any]] = None,
) -> Any:
    """Send a Feishu interactive memory-proposal card.

    Returns the SendResult from the adapter. Card sending uses the same
    REST-based ``message.create`` path as exec approvals to avoid WebSocket
    token refresh issues.
    """
    from owner.feishu.card_sender import send_card_via_rest

    session_key = getattr(entry, "session_key", "")
    card = build_memory_proposal_card(
        action=getattr(entry, "action", ""),
        target=getattr(entry, "target", ""),
        old_text=getattr(entry, "old_text", ""),
        new_content=getattr(entry, "new_content", ""),
        session_key=session_key,
    )

    # Inject session_key into metadata so button callbacks can correlate.
    card_metadata = dict(metadata) if metadata else {}
    card_metadata["session_key"] = session_key

    return send_card_via_rest(adapter, chat_id, card, card_metadata)
