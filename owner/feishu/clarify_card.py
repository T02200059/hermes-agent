"""Feishu interactive card implementation for the clarify tool.

Core implementation lives here per 二次开发规范:
- P1 import 编排：官方代码只做薄薄的代理 + import + 调用
- 所有真实逻辑放在 owner/ 下，便于独立演进和回滚

This module is private customization for the fork.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from gateway.platforms.feishu import FeishuAdapter

from gateway.platforms.base import SendResult
from owner.clarify.gateway_helpers import get_choice_display, get_choice_key

logger = logging.getLogger(__name__)

# Text tokens for the clarify interactive card UI (future i18n: move to locales/).
_TEXT = {
    "card.options_header": "可选：",
    "card.prompt_choose": "请选择：",
    "card.selected_prefix": "已选择：",
    "card.expired_title": "⏱ 已超时",
    "card.expired_body": "已超时（{timeout_minutes} 分钟无响应），请重新发消息。",
    "card.expired_body_short": "已超时（{timeout_minutes} 分钟），请重新发消息。",
    "btn.other_full": "✏️ 其他（输入答案）",
    "btn.other_short": "✏️ 其他",
}

# Feishu interactive card limits.
_MAX_CLARIFY_CHOICES = 4


def build_clarify_card(
    question: str,
    choices: List[Any],
    clarify_id: str,
) -> Dict[str, Any]:
    """Build a Schema 2.0 interactive card for a clarify prompt.

    The card lists all options in a markdown block first (so users see the
    full text even if button labels are truncated), then renders one button
    per choice plus an "Other (type answer)" button. Button values carry the
    stable choice key (falling back to display when no key is present).
    """
    option_lines = "\n".join(
        f"{i + 1}. {get_choice_display(c)}"
        for i, c in enumerate(choices)
    )
    options_md = f"**{_TEXT['card.options_header']}**\n{option_lines}\n\n{_TEXT['card.prompt_choose']}"

    elements: List[Dict[str, Any]] = [
        {"tag": "markdown", "content": options_md},
        *[
            {
                "tag": "button",
                "text": {
                    "tag": "plain_text",
                    "content": f"{i + 1}. {get_choice_display(c)}",
                },
                "type": "primary" if i == 0 else "default",
                "value": {
                    "clarify_id": clarify_id,
                    "choice": get_choice_key(c),
                },
            }
            for i, c in enumerate(choices)
        ],
        {
            "tag": "button",
            "text": {"tag": "plain_text", "content": _TEXT["btn.other_full"]},
            "type": "default",
            "value": {"clarify_id": clarify_id, "choice": "__other__"},
        },
    ]

    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": f"❓ {question}", "tag": "plain_text"},
            "template": "purple",
        },
        "body": {"elements": elements},
    }


def build_frozen_clarify_card(
    question: str,
    choices: List[Any],
    selected_label: str,
) -> Dict[str, Any]:
    """Build a frozen card after the user clicked a choice.

    All buttons are disabled, the selected option is prefixed with ✅, and
    the header turns green. The original question and option list are
    repeated in a markdown block so context is not lost.
    """
    all_labels = [get_choice_display(c) for c in choices] + [_TEXT["btn.other_short"]]

    if question:
        option_lines = "\n".join(
            f"{i + 1}. {get_choice_display(c)}"
            for i, c in enumerate(choices)
        )
        context_md = f"**{question}**\n\n{option_lines}"
    else:
        context_md = f"{_TEXT['card.selected_prefix']}**{selected_label}**"

    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": f"✅ {selected_label}", "tag": "plain_text"},
            "template": "green",
        },
        "body": {
            "elements": [
                {"tag": "markdown", "content": context_md},
                *(
                    {
                        "tag": "button",
                        "text": {
                            "tag": "plain_text",
                            "content": ("✅ " if lbl == selected_label else "　") + lbl,
                        },
                        "type": "primary" if lbl == selected_label else "default",
                        "disabled": True,
                    }
                    for lbl in all_labels
                ),
            ],
        },
    }


def build_expired_clarify_card(
    question: str,
    choices: List[Any],
    timeout_minutes: int = 10,
) -> Dict[str, Any]:
    """Build a grey disabled card when the clarify prompt times out."""
    option_lines = "\n".join(
        f"{i + 1}. {get_choice_display(c)}"
        for i, c in enumerate(choices)
    )
    if question:
        body_md = (
            f"**{question}**\n\n{option_lines}\n\n"
            f"⏱ {_TEXT['card.expired_body'].format(timeout_minutes=timeout_minutes)}"
        )
    else:
        body_md = f"⏱ {_TEXT['card.expired_body_short'].format(timeout_minutes=timeout_minutes)}"

    disabled_buttons: List[Dict[str, Any]] = [
        {
            "tag": "button",
            "text": {"tag": "plain_text", "content": f"{i + 1}. {get_choice_display(c)}"},
            "type": "default",
            "disabled": True,
        }
        for i, c in enumerate(choices)
    ]
    if choices:
        disabled_buttons.append({
            "tag": "button",
            "text": {"tag": "plain_text", "content": _TEXT["btn.other_full"]},
            "type": "default",
            "disabled": True,
        })

    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": _TEXT["card.expired_title"], "tag": "plain_text"},
            "template": "grey",
        },
        "body": {
            "elements": [
                {"tag": "markdown", "content": body_md},
                *disabled_buttons,
            ],
        },
    }


async def patch_message_via_rest(
    app_id: str,
    app_secret: str,
    message_id: str,
    card: Dict[str, Any],
) -> bool:
    """Update an existing interactive card message via Feishu REST API.

    Uses a freshly acquired tenant_access_token and ``requests`` (not the
    lark_oapi SDK) to avoid WebSocket token refresh that can disconnect the
    long-running event stream.
    """
    try:
        import requests as _requests
    except ImportError:
        logger.debug("[Feishu] patch_message_via_rest: requests library not available")
        return False

    base_url = "https://open.feishu.cn/open-apis"

    try:
        token_resp = _requests.post(
            f"{base_url}/auth/v3/tenant_access_token/internal",
            json={"app_id": app_id, "app_secret": app_secret},
            timeout=10,
        )
        access_token = token_resp.json().get("tenant_access_token", "")
        if not access_token:
            return False

        patch_resp = _requests.patch(
            f"{base_url}/im/v1/messages/{message_id}?msg_type=interactive",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={"content": json.dumps(card, ensure_ascii=False)},
            timeout=10,
        )
        patch_data = patch_resp.json()
        if patch_data.get("code", -1) != 0:
            logger.debug(
                "[Feishu] patch_message_via_rest failed (code %d): %s",
                patch_data.get("code"), patch_data.get("msg"),
            )
            return False
    except Exception as exc:
        logger.debug("[Feishu] patch_message_via_rest failed (non-fatal): %s", exc)
        return False

    return True


async def send_clarify(
    adapter: "FeishuAdapter",
    chat_id: str,
    question: str,
    choices: Optional[list],
    clarify_id: str,
    session_key: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> SendResult:
    """Send a clarify prompt as a Feishu interactive card.

    Open-ended prompts (no choices) fall back to a plain text message so
    the gateway's text-intercept can capture the next user message.
    """
    if not adapter._client:
        return SendResult(success=False, error="Not connected")

    # Open-ended: use text-intercept fallback.
    if not choices:
        from tools.clarify_gateway import mark_awaiting_text
        mark_awaiting_text(clarify_id)
        return await adapter.send(chat_id=chat_id, content=f"❓ {question}", metadata=metadata)

    card = build_clarify_card(question, choices, clarify_id)
    result = await adapter.send_card(chat_id=chat_id, card=card, metadata=metadata)

    # Cache state for later freeze / expire updates.
    adapter._clarify_state[clarify_id] = {
        "session_key": session_key,
        "choices": choices,
        "question": question,
        "message_id": result.message_id,
    }
    return result


async def expire_clarify(
    adapter: "FeishuAdapter",
    clarify_id: str,
    chat_id: str,
    timeout_minutes: int = 10,
) -> bool:
    """Update the clarify card to a grey disabled state on timeout.

    Returns True so the caller interrupts the agent turn instead of
    returning the sentinel string to the LLM. Falls back silently to
    False on any error so the caller can decide how to proceed.
    """
    cached = adapter._clarify_state.pop(clarify_id, {})
    message_id = cached.get("message_id", "")
    question = cached.get("question", "")
    choices = cached.get("choices") or []

    if not message_id:
        return False

    card = build_expired_clarify_card(question, choices, timeout_minutes)
    return await patch_message_via_rest(
        app_id=adapter._app_id,
        app_secret=adapter._app_secret,
        message_id=message_id,
        card=card,
    )


def handle_clarify_card_action(
    adapter: "FeishuAdapter",
    *,
    event: Any,
    action_value: Dict[str, Any],
    loop: Any,
) -> Any:
    """Handle clarify button click: resolve or switch to text-capture.

    Returns a P2CardActionTriggerResponse whose ``card`` field replaces the
    original card with a frozen, disabled version showing the selected
    option.
    """
    try:
        from lark_oapi.event.callback.model.p2_card_action_trigger import (
            CallBackCard,
            P2CardActionTriggerResponse,
        )
    except ImportError:
        CallBackCard = None  # type: ignore[assignment]
        P2CardActionTriggerResponse = None  # type: ignore[assignment]

    if P2CardActionTriggerResponse is None:
        return None

    clarify_id = action_value.get("clarify_id")
    choice = action_value.get("choice", "")

    if not clarify_id:
        return P2CardActionTriggerResponse()

    # Read cached data BEFORE popping — needed to build the frozen card.
    cached = adapter._clarify_state.get(clarify_id, {})
    stored_choices: list = cached.get("choices") or []

    if choice == "__other__":
        # Switch to text-capture mode.
        from tools.clarify_gateway import mark_awaiting_text
        mark_awaiting_text(clarify_id)
        adapter._clarify_state.pop(clarify_id, None)
    else:
        from tools.clarify_gateway import resolve_gateway_clarify
        adapter._clarify_state.pop(clarify_id, None)
        try:
            resolve_gateway_clarify(clarify_id, choice)
        except Exception as exc:
            logger.error("[Feishu] resolve_gateway_clarify failed: %s", exc)

    # Map __other__ / choice-key back to user-facing display label.
    all_labels = [get_choice_display(c) for c in stored_choices] + [_TEXT["btn.other_short"]]
    if choice == "__other__":
        selected_label = _TEXT["btn.other_short"]
    else:
        selected_label = choice  # fallback if no match
        for c in stored_choices:
            if get_choice_key(c) == choice:
                selected_label = get_choice_display(c)
                break

    question = cached.get("question", "")
    frozen_card = build_frozen_clarify_card(question, stored_choices, selected_label)

    response = P2CardActionTriggerResponse()
    if CallBackCard is not None:
        card = CallBackCard()
        card.type = "raw"
        card.data = frozen_card
        response.card = card
    return response
