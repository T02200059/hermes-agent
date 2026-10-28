"""Feishu interactive card-action branch table + action-value normalisation.

``plugins/platforms/feishu/adapter.py`` 的 ``_dispatch_card_action`` 是薄胶水；
分派表正文在本模块（规范：官方文件只留薄胶水）。

返回 ``UNHANDLED`` 时由适配器跑兜底（submit-as-command + 空响应）。
处理器可以合法返回 ``None``，故不能用 ``None`` 当哨兵。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


class _Unhandled:
    """Sentinel: no branch matched, the adapter must run its own fallback tail."""

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "UNHANDLED"


UNHANDLED = _Unhandled()


def normalise_card_action_value(raw: Any) -> Any:
    """Accept ``action.value`` as either a dict or a JSON string."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    return {}


def dispatch_card_action(
    adapter: Any,
    *,
    event: Any,
    action_value: dict[str, Any],
    loop: Any,
    data: Any = None,
    allow_profile_routing: bool = True,
) -> Any:
    """Dispatch a parsed card action to the right per-type handler.

    Shared by:
      * WebSocket SDK callback (``allow_profile_routing=True``);
      * sub-profile ``/v1/feishu/card-actions`` HTTP replay
        (``allow_profile_routing=False``).
    """
    hermes_action = (
        action_value.get("hermes_action") if isinstance(action_value, dict) else None
    )
    update_prompt_action = (
        action_value.get("hermes_update_prompt_action")
        if isinstance(action_value, dict)
        else None
    )

    # [owner] C05: forward to the sub-profile that sent the card
    if allow_profile_routing:
        try:
            from owner.feishu.profile_routing import try_route_card_action
        except Exception:  # pragma: no cover - fail-open when owner/ is absent
            try_route_card_action = None
        if try_route_card_action is not None:
            route_response = try_route_card_action(event, action_value)
            if route_response is not None:
                return route_response

    model_picker = (
        action_value.get("hermes_model_picker") if isinstance(action_value, dict) else None
    )
    if model_picker:
        return adapter._handle_model_picker_action(
            event=event, action_value=action_value, loop=loop
        )

    clarify_id = action_value.get("clarify_id") if isinstance(action_value, dict) else None
    form_value = (
        action_value.get("form_value") if isinstance(action_value, dict) else None
    )
    if not clarify_id and isinstance(form_value, dict):
        clarify_id = form_value.get("clarify_id")
    if clarify_id:
        return adapter._handle_clarify_card_action(
            event=event, action_value=action_value, loop=loop
        )

    feishu_guide = (
        action_value.get("hermes_feishu_guide") if isinstance(action_value, dict) else None
    )
    if feishu_guide:
        logger.info("[Feishu] Dispatching guide card action: %s", action_value)
        return adapter._handle_guide_card_action(
            event=event, action_value=action_value, loop=loop
        )

    feishu_queue = (
        action_value.get("hermes_queue_card") if isinstance(action_value, dict) else None
    )
    if feishu_queue:
        logger.info("[Feishu] Dispatching queue card action: %s", action_value)
        return adapter._handle_queue_card_action(
            event=event, action_value=action_value, loop=loop
        )

    diff_action = (
        (isinstance(action_value, dict) and action_value.get("expand_diff"))
        or (isinstance(action_value, dict) and action_value.get("collapse_diff"))
        or (isinstance(action_value, dict) and action_value.get("show_full_diff"))
    )
    if diff_action:
        try:
            from owner.diff_card.feishu import handle_feishu_diff_action
        except Exception:
            handle_feishu_diff_action = None
        if handle_feishu_diff_action is not None:
            return handle_feishu_diff_action(adapter, event, action_value)

    if hermes_action == "resume_select":
        from owner.feishu.resume_card import handle_resume_card_action

        return handle_resume_card_action(
            adapter=adapter,
            event=event,
            action_value=action_value,
            loop=loop,
        )

    if hermes_action == "skill_approval_gate":
        from owner.feishu.skill_approval_card import handle_card_click

        return handle_card_click(
            adapter=adapter, event=event, action_value=action_value, loop=loop,
        )

    if hermes_action:
        return adapter._handle_approval_card_action(
            event=event, action_value=action_value, loop=loop
        )
    if update_prompt_action:
        return adapter._handle_update_prompt_card_action(
            event=event,
            action_value=action_value,
            loop=loop,
        )

    return UNHANDLED
