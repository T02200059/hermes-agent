"""Feishu interactive update-prompt cards (Yes/No buttons + CallBackCard resolved updates).

Mirrors FeishuApprovalContext pattern: state + card builders + callback handlers
live in owner/; gateway/platforms/feishu.py keeps thin delegation only.
"""

from __future__ import annotations

import itertools
import logging
from types import SimpleNamespace
from typing import Any, Dict, Optional

from agent.i18n import t
from hermes_constants import get_hermes_home

logger = logging.getLogger(__name__)


class FeishuUpdatePromptContext:
    """Encapsulates update-prompt button correlation state."""

    def __init__(self) -> None:
        self._state: Dict[int, Dict[str, str]] = {}
        self._counter = itertools.count(1)

    @property
    def state(self) -> Dict[int, Dict[str, str]]:
        return self._state

    def next_id(self) -> int:
        return next(self._counter)

    def register(
        self,
        prompt_id: int,
        *,
        session_key: str,
        message_id: str,
        chat_id: str,
    ) -> None:
        self._state[prompt_id] = {
            "session_key": session_key,
            "message_id": message_id,
            "chat_id": chat_id,
        }

    def get(self, prompt_id: Any) -> Optional[Dict[str, str]]:
        return self._state.get(prompt_id)

    def pop(self, prompt_id: Any) -> Optional[Dict[str, str]]:
        return self._state.pop(prompt_id, None)


def build_update_prompt_card(*, prompt: str, default: str, prompt_id: int) -> Dict[str, Any]:
    default_hint = (
        f"\n\n{t('approval.feishu_update_default_hint', default=default)}"
        if default
        else ""
    )

    def _btn(label: str, answer: str, btn_type: str) -> dict:
        return {
            "tag": "button",
            "text": {"tag": "plain_text", "content": label},
            "type": btn_type,
            "value": {
                "hermes_update_prompt_action": answer,
                "update_prompt_id": prompt_id,
            },
        }

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {
                "content": t("approval.feishu_update_card_title"),
                "tag": "plain_text",
            },
            "template": "orange",
        },
        "elements": [
            {"tag": "markdown", "content": f"{prompt}{default_hint}"},
            {
                "tag": "action",
                "actions": [
                    _btn(t("approval.feishu_update_yes"), "y", "primary"),
                    _btn(t("approval.feishu_update_no"), "n", "danger"),
                ],
            },
        ],
    }


def build_resolved_update_prompt_card(*, answer: str, user_name: str) -> Dict[str, Any]:
    yes = answer == "y"
    label = t("approval.feishu_update_yes") if yes else t("approval.feishu_update_no")
    icon = "✅" if yes else "❌"
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {
                "content": f"{icon} {t('approval.feishu_update_title', label=label)}",
                "tag": "plain_text",
            },
            "template": "green" if yes else "red",
        },
        "elements": [
            {
                "tag": "markdown",
                "content": t("approval.feishu_update_body", user_name=user_name),
            },
        ],
    }


def write_update_prompt_response(answer: str) -> None:
    response_path = get_hermes_home() / ".update_response"
    tmp_path = response_path.with_suffix(".tmp")
    tmp_path.write_text(answer)
    tmp_path.replace(response_path)


async def resolve_update_prompt(
    ctx: FeishuUpdatePromptContext,
    adapter: Any,
    prompt_id: Any,
    answer: str,
    user_name: str,
    *,
    open_id: str = "",
    chat_id: str = "",
) -> None:
    """Persist an update prompt answer for the detached update process."""
    state = ctx.get(prompt_id)
    if not state:
        logger.debug("[Feishu] Update prompt %s already resolved or unknown", prompt_id)
        return
    if open_id:
        sender_id = SimpleNamespace(open_id=open_id, user_id="")
        if not adapter._allow_group_message(sender_id, state.get("chat_id", ""), is_bot=False):
            logger.warning(
                "[Feishu] Unauthorized update prompt click by %s for prompt %s",
                open_id,
                prompt_id,
            )
            return
    expected_chat_id = str(state.get("chat_id", "") or "")
    if expected_chat_id and chat_id and expected_chat_id != chat_id:
        logger.warning(
            "[Feishu] Update prompt %s chat mismatch (expected=%s, got=%s)",
            prompt_id,
            expected_chat_id,
            chat_id,
        )
        return
    state = ctx.pop(prompt_id)
    if not state:
        logger.debug(
            "[Feishu] Update prompt %s already resolved while validating callback",
            prompt_id,
        )
        return
    try:
        write_update_prompt_response(answer)
        logger.info(
            "Feishu update prompt resolved for session %s (answer=%s, user=%s)",
            state["session_key"],
            answer,
            user_name,
        )
    except Exception as exc:
        logger.error("Failed to resolve Feishu update prompt: %s", exc)


def handle_update_prompt_card_action(
    *,
    adapter: Any,
    ctx: FeishuUpdatePromptContext,
    event: Any,
    action_value: Dict[str, Any],
    loop: Any,
) -> Any:
    """Schedule update prompt resolution and build the synchronous callback response."""
    try:
        from lark_oapi.event.callback.model.p2_card_action_trigger import (
            CallBackCard,
            P2CardActionTriggerResponse,
        )
    except ImportError:
        CallBackCard = None  # type: ignore[misc, assignment]
        P2CardActionTriggerResponse = None  # type: ignore[misc, assignment]

    prompt_id = action_value.get("update_prompt_id")
    if prompt_id is None:
        logger.debug("[Feishu] Card action missing update_prompt_id, ignoring")
        return P2CardActionTriggerResponse() if P2CardActionTriggerResponse else None
    state = ctx.get(prompt_id)
    if not state:
        logger.debug("[Feishu] Update prompt %s already resolved or unknown", prompt_id)
        return P2CardActionTriggerResponse() if P2CardActionTriggerResponse else None

    answer = str(action_value.get("hermes_update_prompt_action", "") or "").strip().lower()
    if answer not in {"y", "n"}:
        logger.debug("[Feishu] Card action has invalid update prompt answer=%r", answer)
        return P2CardActionTriggerResponse() if P2CardActionTriggerResponse else None

    operator = getattr(event, "operator", None)
    open_id = str(getattr(operator, "open_id", "") or "")
    sender_id = SimpleNamespace(
        open_id=open_id,
        user_id=str(getattr(operator, "user_id", "") or ""),
    )
    if not adapter._allow_group_message(sender_id, state.get("chat_id", ""), is_bot=False):
        logger.warning("[Feishu] Unauthorized update prompt click by %s", open_id or "<unknown>")
        return P2CardActionTriggerResponse() if P2CardActionTriggerResponse else None

    callback_chat_id = str(getattr(getattr(event, "context", None), "open_chat_id", "") or "")
    expected_chat_id = str(state.get("chat_id", "") or "")
    if callback_chat_id and expected_chat_id and callback_chat_id != expected_chat_id:
        logger.warning(
            "[Feishu] Update prompt callback chat mismatch for %s (expected=%s, got=%s)",
            prompt_id,
            expected_chat_id,
            callback_chat_id,
        )
        return P2CardActionTriggerResponse() if P2CardActionTriggerResponse else None

    user_name = adapter._get_cached_sender_name(open_id) or open_id
    if not adapter._submit_on_loop(
        loop,
        resolve_update_prompt(
            ctx,
            adapter,
            prompt_id,
            answer,
            user_name,
            open_id=open_id,
            chat_id=callback_chat_id,
        ),
    ):
        return P2CardActionTriggerResponse() if P2CardActionTriggerResponse else None

    if P2CardActionTriggerResponse is None:
        return None
    response = P2CardActionTriggerResponse()
    if CallBackCard is not None:
        card = CallBackCard()
        card.type = "raw"
        card.data = build_resolved_update_prompt_card(answer=answer, user_name=user_name)
        response.card = card
    return response