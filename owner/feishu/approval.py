# [owner] C04 — Feishu exec-approval cards + click handler helpers.
"""Owner-owned Feishu approval card payloads and failure-path CallBack cards.

Send path stays on the official ``ExecApprovalPrompt`` / ``_send_exec_approval_prompt``
(C01 already gates the Always button via ``allow_permanent``). This module owns:

- resolved / failed frozen CallBack cards (so unauthorized clicks never leave
  live buttons or a silent loading spinner)
- ``handle_approval_card_action`` (authorize → schedule resolve → freeze card)
- sender-name pre-warm helpers used by thin adapter glue before send

Permanent-approval policy is NOT re-read here — callers pass the already-gated
flag into the official send path.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from agent.i18n import t

logger = logging.getLogger(__name__)

_APPROVAL_CHOICE_MAP = {
    "approve_once": "once",
    "approve_session": "session",
    "approve_always": "always",
    "deny": "deny",
}


@dataclass
class FeishuApprovalContext:
    """Lightweight view used by send-path pre-warm glue.

    ``state`` mirrors ``adapter._approval_state``. Prefer packing
    ``sender_open_id`` / ``sender_is_bot`` into send metadata rather than
    widening the official ``send_exec_approval`` signature.
    """

    adapter: Any
    state: dict
    user_store: Any = None
    sender_open_id: Optional[str] = None
    sender_is_bot: bool = False


def build_resolved_card(*, decision: str, user_name: str) -> dict:
    """Frozen card after a successful approve/deny click."""
    labels = {
        "once": ("✅", t("platform.feishu.approval.resolved_once")),
        "session": ("🔓", t("platform.feishu.approval.resolved_session")),
        "always": ("♾️", t("platform.feishu.approval.resolved_always")),
        "deny": ("❌", t("platform.feishu.approval.resolved_deny")),
    }
    icon, label = labels.get(
        decision, ("✓", t("platform.feishu.approval.resolved_fallback"))
    )
    display = (user_name or "").strip() or t(
        "platform.feishu.approval.operator_fallback"
    )
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"{icon} {label}"},
            "template": "green" if decision != "deny" else "red",
        },
        "elements": [
            {
                "tag": "markdown",
                "content": t(
                    "platform.feishu.approval.resolved_by_user",
                    icon=icon,
                    label=label,
                    user=display,
                ),
            }
        ],
    }


# Alias matching older call sites / adapter staticmethod name.
build_resolved_approval_card = build_resolved_card


def build_failed_card(*, reason: str, detail: str = "") -> dict:
    """Frozen CallBack card for unauthorized / expired / already-handled / …"""
    titles = {
        "unauthorized": (
            "🚫",
            t("platform.feishu.approval.fail_unauthorized_title"),
            "red",
        ),
        "expired": (
            "⌛",
            t("platform.feishu.approval.fail_expired_title"),
            "grey",
        ),
        "already_handled": (
            "ℹ️",
            t("platform.feishu.approval.fail_already_handled_title"),
            "grey",
        ),
        "already_resolved": (
            "ℹ️",
            t("platform.feishu.approval.fail_already_handled_title"),
            "grey",
        ),
        "chat_mismatch": (
            "💡",
            t("platform.feishu.approval.fail_chat_mismatch_title"),
            "orange",
        ),
        "missing_id": (
            "💡",
            t("platform.feishu.approval.fail_missing_id_title"),
            "orange",
        ),
        "submit_failed": (
            "💡",
            t("platform.feishu.approval.fail_submit_failed_title"),
            "orange",
        ),
    }
    icon, title, template = titles.get(
        reason,
        ("💡", t("platform.feishu.approval.fail_generic_title"), "orange"),
    )
    bodies = {
        "unauthorized": t("platform.feishu.approval.fail_unauthorized_body"),
        "expired": t("platform.feishu.approval.fail_expired_body"),
        "already_handled": t("platform.feishu.approval.fail_already_handled_body"),
        "already_resolved": t("platform.feishu.approval.fail_already_handled_body"),
        "chat_mismatch": t("platform.feishu.approval.fail_chat_mismatch_body"),
        "missing_id": t("platform.feishu.approval.fail_missing_id_body"),
        "submit_failed": t("platform.feishu.approval.fail_submit_failed_body"),
    }
    body = detail.strip() if detail and detail.strip() else bodies.get(
        reason, t("platform.feishu.approval.fail_generic_body")
    )
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"{icon} {title}"},
            "template": template,
        },
        "elements": [{"tag": "markdown", "content": body}],
    }


build_failed_approval_card = build_failed_card


def handle_approval_card_action(
    *,
    adapter: Any,
    event: Any,
    action_value: dict[str, Any],
    loop: Any,
) -> Any:
    """Authorize → schedule resolve → return frozen CallBack card.

    Failure paths return a frozen error card (never ``card=None``) so Feishu
    does not leave the original buttons clickable or spin forever. Only a
    successful schedule + resolve unblocks the agent.
    """
    approval_id = action_value.get("approval_id")
    if approval_id is None:
        logger.warning("[Feishu] Card action missing approval_id")
        return adapter._card_response(build_failed_card(reason="missing_id"))

    state = adapter._approval_state.get(approval_id)
    if not state:
        logger.info(
            "[Feishu] Approval %s already resolved or unknown (click feedback card)",
            approval_id,
        )
        return adapter._card_response(build_failed_card(reason="already_handled"))

    choice = _APPROVAL_CHOICE_MAP.get(action_value.get("hermes_action"), "deny")

    operator = getattr(event, "operator", None)
    open_id = str(getattr(operator, "open_id", "") or "")
    if not adapter._is_interactive_operator_authorized(open_id):
        logger.warning(
            "[Feishu] Unauthorized approval click by %s for approval %s",
            open_id or "<unknown>",
            approval_id,
        )
        return adapter._card_response(build_failed_card(reason="unauthorized"))

    callback_chat_id = str(
        getattr(getattr(event, "context", None), "open_chat_id", "") or ""
    )
    expected_chat_id = str(state.get("chat_id", "") or "")
    if callback_chat_id and expected_chat_id and callback_chat_id != expected_chat_id:
        logger.warning(
            "[Feishu] Approval callback chat mismatch for %s (expected=%s, got=%s)",
            approval_id,
            expected_chat_id,
            callback_chat_id,
        )
        return adapter._card_response(build_failed_card(reason="chat_mismatch"))

    from owner.feishu.sender_name_helpers import operator_display_name

    user_name = operator_display_name(adapter, open_id)

    coro = adapter._resolve_approval(
        approval_id=approval_id,
        choice=choice,
        user_name=user_name,
        open_id=open_id,
        chat_id=callback_chat_id,
    )
    if not adapter._submit_on_loop(loop, coro):
        logger.warning(
            "[Feishu] Failed to schedule approval resolve for %s", approval_id
        )
        return adapter._card_response(build_failed_card(reason="submit_failed"))

    return adapter._card_response(
        build_resolved_card(decision=choice, user_name=user_name)
    )


async def ensure_sender_name_cached(
    adapter: Any,
    sender_open_id: Optional[str],
    *,
    sender_is_bot: bool = False,
) -> None:
    """Best-effort awaitable pre-warm before the approval card is sent."""
    open_id = (sender_open_id or "").strip()
    if not open_id or sender_is_bot:
        return
    try:
        from owner.feishu.sender_name_helpers import resolve_sender_name

        await resolve_sender_name(adapter, open_id, is_bot=False)
    except Exception:
        logger.debug("[Feishu] approval name pre-warm failed", exc_info=True)


def pre_warm_sender_from_metadata(adapter: Any, metadata: Optional[dict]) -> None:
    """Fire-and-forget pre-warm using send-path metadata (non-blocking)."""
    if not isinstance(metadata, dict):
        return
    open_id = str(metadata.get("sender_open_id") or "").strip()
    if not open_id:
        return
    is_bot = bool(metadata.get("sender_is_bot", False))
    try:
        from owner.feishu.sender_name_helpers import pre_warm_sender_name

        pre_warm_sender_name(adapter, open_id, is_bot=is_bot, fire_delegate=True)
    except Exception:
        logger.debug("[Feishu] approval metadata pre-warm failed", exc_info=True)
