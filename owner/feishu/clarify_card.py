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
    from plugins.platforms.feishu.adapter import FeishuAdapter

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
    "card.other_prompt": "*请在下方输入你的答案*",
    "card.input_placeholder": "请输入你的答案",
    "card.input_label": "答案：",
    "card.submit_btn": "提交",
    "btn.back": "返回",
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
    custom_answer: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a frozen card after the user clicked a choice.

    All buttons are disabled, the selected option is prefixed with ✅, and
    the header turns green. The original question and option list are
    repeated in a markdown block so context is not lost.

    When custom_answer is provided (user chose "其他" and submitted text),
    the title becomes "✅ 其他: <用户输入>", and the answer is also
    supplemented in the body markdown (卡片上方的文案).
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

    if custom_answer:
        # "其他" 已提交：title 用 "✅ 其他: 用户输入"，同时在 body 文案中补充完整输入
        header_title = f"✅ 其他: {custom_answer}"
        context_md += f"\n\n{_TEXT['card.input_label']}{custom_answer}"
    else:
        header_title = f"✅ {selected_label}"
        # Add prompt for "Other" selection (legacy path where selected_label is the short text)
        if selected_label == _TEXT["btn.other_short"]:
            context_md += f"\n\n{_TEXT['card.other_prompt']}"

    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": header_title, "tag": "plain_text"},
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
                            "content": (
                                "✅ " if (custom_answer is not None and lbl == _TEXT["btn.other_short"]) or (lbl == selected_label and custom_answer is None) else "　"
                            ) + lbl,
                        },
                        "type": "primary" if (custom_answer is not None and lbl == _TEXT["btn.other_short"]) or (lbl == selected_label and custom_answer is None) else "default",
                        "disabled": True,
                    }
                    for lbl in all_labels
                ),
            ],
        },
    }


def build_input_clarify_card(
    question: str,
    choices: List[Any],
    clarify_id: str,
) -> Dict[str, Any]:
    """Build a card with input form for 'Other' selection.

    When user clicks the 'Other' button, this card replaces the original
    clarify card with an input form. User can type their answer and submit.
    """
    # Build context markdown showing the original question and options
    if question:
        option_lines = "\n".join(
            f"{i + 1}. {get_choice_display(c)}"
            for i, c in enumerate(choices)
        )
        context_md = f"**{question}**\n\n{option_lines}"
    else:
        context_md = ""

    # Add prompt for input
    if context_md:
        context_md += f"\n\n{_TEXT['card.other_prompt']}"
    else:
        context_md = _TEXT['card.other_prompt']

    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": _TEXT['btn.other_short'], "tag": "plain_text"},
            "template": "purple",
        },
        "body": {
            "elements": [
                {"tag": "markdown", "content": context_md},
                {
                    "tag": "form",
                    "name": f"clarify_form_{clarify_id}",
                    "elements": [
                        {
                            "tag": "input",
                            "name": "clarify_answer",
                            "placeholder": {
                                "tag": "plain_text",
                                "content": _TEXT["card.input_placeholder"],
                            },
                            "label": {
                                "tag": "plain_text",
                                "content": _TEXT["card.input_label"],
                            },
                            "label_position": "left",
                            "required": True,
                            "max_length": 1000,
                            "input_type": "multiline_text",
                            "rows": 3,
                            "auto_resize": True,
                        },
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": _TEXT["card.submit_btn"]},
                            "type": "primary",
                            "action_type": "form_submit",
                            "name": "submit_clarify",
                            "value": {"clarify_id": clarify_id},
                        },
                    ],
                },
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": _TEXT["btn.back"]},
                    "type": "default",
                    "value": {"clarify_id": clarify_id, "back": True},
                },
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
            logger.warning(
                "[Feishu card] patch_message failed message_id=%s code=%s msg=%s",
                message_id,
                patch_data.get("code"),
                patch_data.get("msg"),
            )
            return False
    except Exception as exc:
        logger.warning(
            "[Feishu card] patch_message failed message_id=%s: %s",
            message_id,
            exc,
        )
        return False

    logger.info(
        "[Feishu card] patch_message OK message_id=%s",
        message_id,
    )
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
    if getattr(result, "success", False):
        logger.info(
            "[Feishu card] clarify sent OK clarify_id=%s chat_id=%s message_id=%s choices=%d",
            clarify_id,
            chat_id,
            result.message_id or "(none)",
            len(choices or []),
        )
    else:
        logger.warning(
            "[Feishu card] clarify send failed clarify_id=%s chat_id=%s error=%s",
            clarify_id,
            chat_id,
            getattr(result, "error", None),
        )
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
    ok = await patch_message_via_rest(
        app_id=adapter._app_id,
        app_secret=adapter._app_secret,
        message_id=message_id,
        card=card,
    )
    logger.info(
        "[Feishu card] clarify expired clarify_id=%s message_id=%s ok=%s",
        clarify_id,
        message_id,
        ok,
    )
    return ok


def handle_clarify_card_action(
    adapter: "FeishuAdapter",
    *,
    event: Any,
    action_value: Dict[str, Any],
    loop: Any,
) -> Any:
    """Handle clarify button click: resolve or switch to input form.

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
    form_value = action_value.get("form_value", {})

    # Also check form_value for clarify_id (form submissions)
    if not clarify_id and isinstance(form_value, dict):
        clarify_id = form_value.get("clarify_id")

    if not clarify_id:
        return P2CardActionTriggerResponse()

    # Read cached data BEFORE popping — needed to build the frozen card.
    cached = adapter._clarify_state.get(clarify_id, {})
    stored_choices: list = cached.get("choices") or []

    # Handle "返回" from the "其他" input form — restore the original button choices card.
    # Do not pop state or resolve; user can pick again.
    if isinstance(action_value, dict) and action_value.get("back"):
        question = cached.get("question", "")
        orig_card = build_clarify_card(question, stored_choices, clarify_id)
        response = P2CardActionTriggerResponse()
        if CallBackCard is not None:
            card = CallBackCard()
            card.type = "raw"
            card.data = orig_card
            response.card = card
        logger.info(
            "[Feishu card] clarify action=back clarify_id=%s",
            clarify_id,
        )
        return response

    # Handle form submission from input card
    if form_value and "clarify_answer" in form_value:
        answer = form_value["clarify_answer"]
        if not answer:
            # Empty answer: keep the input card as-is, do not resolve.
            return P2CardActionTriggerResponse()

        from tools.clarify_gateway import resolve_gateway_clarify
        # 写回最终 answer（按方案：提交后把 resolved_answer 记录到 state 条目中，便于后续一致性/expire 等路径使用）
        if clarify_id in adapter._clarify_state:
            adapter._clarify_state[clarify_id]["resolved_answer"] = answer
        adapter._clarify_state.pop(clarify_id, None)
        try:
            resolve_gateway_clarify(clarify_id, answer)
        except Exception as exc:
            logger.error("[Feishu] resolve_gateway_clarify failed: %s", exc)

        # Return frozen card showing the answer（仅改提交后卡片，input 阶段不改）
        question = cached.get("question", "")
        frozen_card = build_frozen_clarify_card(
            question, stored_choices, _TEXT["btn.other_short"], custom_answer=answer
        )

        response = P2CardActionTriggerResponse()
        if CallBackCard is not None:
            card = CallBackCard()
            card.type = "raw"
            card.data = frozen_card
            response.card = card
        logger.info(
            "[Feishu card] clarify resolved clarify_id=%s via=other answer_len=%d",
            clarify_id,
            len(str(answer)),
        )
        return response

    if choice == "__other__":
        # Return input form card instead of text-capture mode.
        question = cached.get("question", "")
        input_card = build_input_clarify_card(question, stored_choices, clarify_id)

        response = P2CardActionTriggerResponse()
        if CallBackCard is not None:
            card = CallBackCard()
            card.type = "raw"
            card.data = input_card
            response.card = card
        logger.info(
            "[Feishu card] clarify action=other clarify_id=%s",
            clarify_id,
        )
        return response
    else:
        from tools.clarify_gateway import resolve_gateway_clarify
        adapter._clarify_state.pop(clarify_id, None)
        try:
            resolve_gateway_clarify(clarify_id, choice)
        except Exception as exc:
            logger.error("[Feishu] resolve_gateway_clarify failed: %s", exc)

    # Map choice-key back to user-facing display label.
    all_labels = [get_choice_display(c) for c in stored_choices] + [_TEXT["btn.other_short"]]
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
    logger.info(
        "[Feishu card] clarify resolved clarify_id=%s choice=%s label=%s",
        clarify_id,
        choice,
        selected_label,
    )
    return response
