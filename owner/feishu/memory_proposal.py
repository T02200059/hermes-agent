"""Feishu interactive cards for memory proposals.

Core logic per 二次开发规范: all card building, button handling, and resolved
CallBackCard logic lives in owner/; gateway/platforms/feishu.py only keeps
thin delegation + the minimal per-session state needed for correlation.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from agent.async_utils import safe_schedule_threadsafe
from agent.i18n import t
from owner.memory.gateway import has_memory_proposal, resolve_memory_approval

logger = logging.getLogger(__name__)

_ACTION_KEYS = {
    "add": "memory_proposal.action_add",
    "replace": "memory_proposal.action_replace",
    "remove": "memory_proposal.action_remove",
}

# Batch rendering thresholds.
_OP_CONTENT_PREVIEW_LEN = 60    # truncate each op's content preview
_OP_OLDTEXT_PREVIEW_LEN = 40    # truncate each op's old_text preview
_BATCH_COLLAPSE_THRESHOLD = 5   # show at most this many op lines before "还有 N 条"
_BATCH_COLLAPSE_KEEP = 3        # leading ops kept when collapsing


def _action_label(action: str) -> str:
    key = _ACTION_KEYS.get(action)
    if not key:
        return action
    label = t(key)
    return action if label == key else label


def _truncate(text: str, limit: int) -> str:
    """Truncate ``text`` to ``limit`` chars, appending ``…`` when truncated."""
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def _build_batch_proposal_md(
    operations: List[Dict[str, Any]],
    target: str,
    char_budget: Optional[Dict[str, int]] = None,
) -> str:
    """Render the markdown body for a batch proposal card.

    Shows one line per op: ``({idx}/{total}) · {action}  {preview}`` where
    preview is content (add/replace) or old_text (remove/replace). When N >
    ``_BATCH_COLLAPSE_THRESHOLD``, only the first ``_BATCH_COLLAPSE_KEEP`` lines
    are shown plus a "还有 N-M 条" footer.
    """
    total = len(operations)
    lines = [
        f"**{t('memory_proposal.card_target')}**: {target}",
        f"**{t('memory_proposal.card_summary_label')}**:",
    ]

    # Collapse past the threshold: keep the first _BATCH_COLLAPSE_KEEP ops and
    # summarize the rest with a "... 还有 N 条" footer.
    collapse = total > _BATCH_COLLAPSE_THRESHOLD
    if collapse:
        shown = operations[:_BATCH_COLLAPSE_KEEP]
        collapsed = total - _BATCH_COLLAPSE_KEEP
    else:
        shown = operations
        collapsed = 0

    for i, op in enumerate(shown, start=1):
        act = str(op.get("action", "") or "")
        act_label = _action_label(act) if act in _ACTION_KEYS else act
        idx_prefix = t("memory_proposal.card_op_index", idx=i, total=total)

        content = str(op.get("content", "") or "")
        old_text = str(op.get("old_text", "") or "")

        if act == "add":
            preview = _truncate(content, _OP_CONTENT_PREVIEW_LEN)
            lines.append(f"{idx_prefix}· {act_label}  `{preview}`")
        elif act == "replace":
            old_prev = _truncate(old_text, _OP_OLDTEXT_PREVIEW_LEN)
            new_prev = _truncate(content, _OP_CONTENT_PREVIEW_LEN)
            lines.append(f"{idx_prefix}· {act_label}  `{old_prev}` → `{new_prev}`")
        elif act == "remove":
            old_prev = _truncate(old_text, _OP_OLDTEXT_PREVIEW_LEN)
            lines.append(f"{idx_prefix}· {act_label}  `{old_prev}`")
        else:
            lines.append(f"{idx_prefix}· {act}")

    if collapsed > 0:
        lines.append(t("memory_proposal.card_more_ops", count=collapsed))

    if char_budget:
        final = int(char_budget.get("final", 0))
        limit = int(char_budget.get("limit", 0))
        if limit > 0:
            lines.append(t("memory_proposal.card_char_budget", final=final, limit=limit))

    return "\n".join(lines)


def build_memory_proposal_card(
    *,
    action: str = "",
    target: str = "",
    old_text: str = "",
    new_content: str = "",
    session_key: str = "",
    operations: Optional[List[Dict[str, Any]]] = None,
    char_budget: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """Build the interactive memory-proposal card JSON.

    Two shapes (mirrors the dual tool shape):

    - **Batch** (``operations`` non-empty): renders a title showing the op
      count, followed by one preview line per op (collapsed past
      ``_BATCH_COLLAPSE_THRESHOLD``) and an optional char budget line.
    - **Single-op** (legacy, ``operations`` empty/None): renders the original
      operation/target/existing/new-content card unchanged.

    ``char_budget`` is optional — pass ``{"final": <int>, "limit": <int>}`` if
    the caller has the live usage; when None the budget line is omitted (the
    card builder has no store access of its own).
    """
    is_batch = bool(operations)

    if is_batch:
        title = t("memory_proposal.card_title_batch", count=len(operations))
        proposal_md = _build_batch_proposal_md(operations, target, char_budget=char_budget)
    else:
        content_preview = new_content[:1000] if new_content else t("memory_proposal.card_empty_content")
        old_preview = old_text[:200] if old_text else t("memory_proposal.card_empty")
        title = t("memory_proposal.card_title")
        # WR-10: pre-build proposal markdown so button callback can preserve content
        proposal_md = (
            f"**{t('memory_proposal.card_operation')}**: {_action_label(action)}\n"
            f"**{t('memory_proposal.card_target')}**: {target}\n"
            f"**{t('memory_proposal.card_existing')}**: `...{old_preview}...`\n\n"
            f"**{t('memory_proposal.card_new_content')}**:\n"
            f"```\n{content_preview}\n```"
        )

    def _btn(label: str, action_name: str, btn_type: str = "default") -> dict:
        return {
            "tag": "button",
            "text": {"tag": "plain_text", "content": label},
            "type": btn_type,
            "value": {
                "hermes_action": action_name,
                "session_key": session_key,
                "proposal_md": proposal_md,
            },
        }

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": title, "tag": "plain_text"},
            "template": "purple",
        },
        "elements": [
            {
                "tag": "markdown",
                "content": proposal_md,
            },
            {
                "tag": "action",
                "actions": [
                    _btn(t("memory_proposal.btn_approve"), "memory_approve"),
                    _btn(t("memory_proposal.btn_deny"), "memory_deny", "danger"),
                ],
            },
        ],
    }


def build_resolved_memory_proposal_card(
    *, choice: str, proposal_md: str = ""
) -> Dict[str, Any]:
    """Build the raw card data for CallBackCard inline update after click.

    When ``proposal_md`` is provided (WR-10), the original proposal content is
    preserved in the card so the user can still see what was proposed after
    clicking approve/deny.
    """
    if choice == "approve":
        icon, label, template = "✅", t("memory_proposal.resolved_approved"), "green"
    else:
        icon, label, template = "🟥", t("memory_proposal.resolved_denied"), "red"

    elements: list[dict] = []
    if proposal_md:
        elements.append({"tag": "markdown", "content": proposal_md})
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": f"{icon} {label}", "tag": "plain_text"},
            "template": template,
        },
        "elements": elements,
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
        confirm_text = (
            t("memory_proposal.confirm_approved")
            if choice == "approve"
            else t("memory_proposal.confirm_denied")
        )
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
    # WR-10: read proposal_md from button value to preserve original content.
    proposal_md = str(action_value.get("proposal_md", "")) if isinstance(action_value, dict) else ""
    try:
        from lark_oapi.event.callback.model.p2_card_action_trigger import (
            CallBackCard,
            P2CardActionTriggerResponse,
        )
        if CallBackCard is not None and P2CardActionTriggerResponse is not None:
            response = P2CardActionTriggerResponse()
            card = CallBackCard()
            card.type = "raw"
            card.data = build_resolved_memory_proposal_card(choice=choice, proposal_md=proposal_md)
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
        operations=getattr(entry, "operations", None),
    )

    # Inject session_key into metadata so button callbacks can correlate.
    card_metadata = dict(metadata) if metadata else {}
    card_metadata["session_key"] = session_key

    return send_card_via_rest(adapter, chat_id, card, card_metadata)
