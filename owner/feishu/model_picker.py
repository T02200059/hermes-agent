"""Feishu interactive model picker card (provider list → model list → confirmation).

三步交互卡片，供飞书用户点选切换模型，无需记忆命令格式。
Step 1: pick provider → Step 2: pick model → 确认（合成 /model 命令）。

核心逻辑 per 二次开发规范：卡片构建器 + 回调处理在 owner/，
gateway/platforms/feishu.py 只保留状态字典 + 薄胶水委托。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from owner.feishu.sender_name_helpers import operator_display_name

logger = logging.getLogger(__name__)


def build_provider_card(picker_id: str, providers: list) -> Dict[str, Any]:
    """Step 1 card: list providers as buttons (sorted alphabetically)."""
    providers = sorted(providers, key=lambda r: (r.get("slug") or "").lower())
    elements: List[Dict[str, Any]] = [
        {"tag": "markdown", "content": f"选择目标 provider（共 {len(providers)} 个）："},
    ]
    for row in providers:
        slug = row.get("slug", "")
        name = row.get("name", "")
        n_models = len(row.get("models") or [])
        label = f"{slug}（{name}）" if name and name != slug else slug
        elements.append({
            "tag": "button",
            "text": {"tag": "plain_text", "content": f"{label}  ·  {n_models} 个模型"},
            "type": "default",
            "value": {"hermes_model_picker": "provider", "picker_id": picker_id, "provider": slug},
        })
    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {"title": {"content": "🔀 切换模型", "tag": "plain_text"}, "template": "blue"},
        "body": {"elements": elements},
    }


def build_model_card(
    picker_id: str, provider_slug: str, provider_name: str, models: list
) -> Dict[str, Any]:
    """Step 2 card: list models for a chosen provider with a back button."""
    label = (
        f"{provider_slug}（{provider_name}）"
        if provider_name and provider_name != provider_slug
        else provider_slug
    )
    elements: List[Dict[str, Any]] = [
        {"tag": "markdown", "content": f"Provider: **{label}**\n\n选择目标模型（共 {len(models)} 个）："},
    ]
    for model in models:
        elements.append({
            "tag": "button",
            "text": {"tag": "plain_text", "content": model},
            "type": "default",
            "value": {
                "hermes_model_picker": "confirm",
                "picker_id": picker_id,
                "provider": provider_slug,
                "model": model,
            },
        })
    elements.append({
        "tag": "button",
        "text": {"tag": "plain_text", "content": "⬅ 返回"},
        "type": "default",
        "value": {"hermes_model_picker": "back", "picker_id": picker_id},
    })
    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": f"🔀 切换模型 — {provider_slug}", "tag": "plain_text"},
            "template": "blue",
        },
        "body": {"elements": elements},
    }


def build_done_card(provider: str, model: str, user_name: str) -> Dict[str, Any]:
    """Confirmation card shown after a model is selected."""
    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": f"✅ 已切换到 {model}", "tag": "plain_text"},
            "template": "green",
        },
        "body": {
            "elements": [
                {
                    "tag": "markdown",
                    "content": (
                        f"Provider: **{provider}**\n"
                        f"模型: **{model}**\n\n"
                        f"由 {user_name} 发起全局切换。"
                    ),
                },
            ],
        },
    }


def handle_picker_action(
    *,
    adapter: Any,
    action_value: Dict[str, Any],
    event: Any,
) -> Any:  # returns P2CardActionTriggerResponse | None
    """Process a model picker card callback.

    Dispatches on the ``hermes_model_picker`` step value:
    - ``provider`` → build model list card
    - ``back`` → rebuild provider list card
    - ``confirm`` → route /model command + build done card

    Returns a ``P2CardActionTriggerResponse`` with ``CallBackCard`` when the
    card should be updated inline, or a toast-only response when state has
    been lost (gateway restart, etc.) so the user sees a hint instead of a
    stuck loading state.

    **Never returns an empty response** (``P2CardActionTriggerResponse()``
    with no card or toast) — that causes the Feishu client to keep the
    loading spinner indefinitely.
    """
    # Lazy import to keep removability (delete owner/feishu/ → no crash).
    try:
        from lark_oapi.event.callback.model.p2_card_action_trigger import (
            CallBackCard,
            CallBackToast,
            P2CardActionTriggerResponse,
        )
    except ImportError:
        return None

    # Normalise: accept dict or JSON-string action_value (SDK version skew).
    if isinstance(action_value, str) and action_value.strip():
        import json as _json
        try:
            parsed = _json.loads(action_value)
            if isinstance(parsed, dict):
                action_value = parsed
        except Exception:
            pass

    if not isinstance(action_value, dict):
        return _toast_response(P2CardActionTriggerResponse, CallBackToast,
                               "卡片数据异常，请重新执行 /providers")

    picker_id = action_value.get("picker_id", "")
    step = action_value.get("hermes_model_picker", "")

    try:
        if step == "provider":
            provider_slug = action_value.get("provider", "")
            state = getattr(adapter, "_model_picker_state", {}).get(picker_id)
            if not state or not provider_slug:
                return _toast_response(P2CardActionTriggerResponse, CallBackToast,
                                       "会话已过期，请重新执行 /providers")
            rows = state.get("providers", [])
            provider_row = next((r for r in rows if r.get("slug") == provider_slug), None)
            if not provider_row:
                return _toast_response(P2CardActionTriggerResponse, CallBackToast,
                                       f"未找到 provider「{provider_slug}」，请重新执行 /providers")
            models = provider_row.get("models") or []
            name = provider_row.get("name", provider_slug)
            logger.info(
                "[Feishu card] model_picker step=provider picker_id=%s provider=%s models=%d",
                picker_id,
                provider_slug,
                len(models),
            )
            return _card_response(
                P2CardActionTriggerResponse, CallBackCard,
                build_model_card(picker_id, provider_slug, name, models),
            )

        if step == "back":
            state = getattr(adapter, "_model_picker_state", {}).get(picker_id)
            if not state:
                return _toast_response(P2CardActionTriggerResponse, CallBackToast,
                                       "会话已过期，请重新执行 /providers")
            rows = state.get("providers", [])
            logger.info(
                "[Feishu card] model_picker step=back picker_id=%s providers=%d",
                picker_id,
                len(rows),
            )
            return _card_response(
                P2CardActionTriggerResponse, CallBackCard,
                build_provider_card(picker_id, rows),
            )

        if step == "confirm":
            provider = action_value.get("provider", "")
            model = action_value.get("model", "")
            state = getattr(adapter, "_model_picker_state", {}).pop(picker_id, {})
            if not state:
                return _toast_response(P2CardActionTriggerResponse, CallBackToast,
                                       "会话已过期，模型未切换。请重新执行 /providers")
            operator = getattr(event, "operator", None)
            open_id = str(getattr(operator, "open_id", "") or "")
            user_name = operator_display_name(adapter, open_id)
            command = f"/model {model} --provider {provider} --global"

            # Route the synthetic command through the adapter.
            _route_picker_command(adapter, command, open_id, state)
            logger.info(
                "[Feishu card] model_picker step=confirm picker_id=%s command=%s user=%s",
                picker_id,
                command,
                user_name,
            )

            return _card_response(
                P2CardActionTriggerResponse, CallBackCard,
                build_done_card(provider, model, user_name),
            )

        return _toast_response(P2CardActionTriggerResponse, CallBackToast,
                               f"未知操作「{step}」，请重新执行 /providers")

    except Exception as exc:
        logger.warning("[Feishu] model picker action failed (step=%s): %s", step, exc, exc_info=True)
        return _toast_response(P2CardActionTriggerResponse, CallBackToast,
                               "操作失败，请重试")


def _route_picker_command(
    adapter: Any, command: str, open_id: str, state: dict
) -> None:
    """Route a model picker confirm as a synthetic /model command.

    Submits the command through the adapter's event loop as a
    ``MessageType.COMMAND`` event so it follows the same processing
    path as a manually typed ``/model ...`` command (including
    --global persistence).
    """
    import uuid as _uuid
    from datetime import datetime

    source = state.get("source") if isinstance(state, dict) else None
    if source is None:
        return
    chat_id = getattr(source, "chat_id", "") or ""
    if not chat_id:
        return

    loop = getattr(adapter, "_loop", None)
    if loop is None:
        return

    async def _dispatch():
        try:
            from gateway.platforms.base import MessageEvent, MessageType

            synthetic_event = MessageEvent(
                text=command,
                message_type=MessageType.COMMAND,
                source=source,
                raw_message=None,
                message_id="",  # no reply_to — synthetic, not a real Feishu message
                timestamp=datetime.now(),
            )
            await adapter._handle_message_with_guards(synthetic_event)
            logger.info(
                "[Feishu card] model_picker command routed OK command=%s chat_id=%s",
                command,
                chat_id,
            )
        except Exception as exc:
            logger.warning("[Feishu] model picker route failed: %s", exc)

    adapter._submit_on_loop(loop, _dispatch())


def _empty_response(resp_cls: Any) -> Any:
    """Return a bare P2CardActionTriggerResponse or None.

    DEPRECATED for model_picker: prefer ``_toast_response`` so the Feishu
    client shows a hint instead of a stuck loading spinner.  Kept for
    external callers that may still import this symbol.
    """
    return resp_cls() if resp_cls else None


def _toast_response(resp_cls: Any, toast_cls: Any, text: str) -> Any:
    """Return a P2CardActionTriggerResponse that shows a toast.

    Unlike an empty response (which leaves the card stuck in a loading
    state), a toast-only response dismisses the spinner and shows the
    user a short message — they can then manually re-run the command.
    """
    if resp_cls is None or toast_cls is None:
        return None
    response = resp_cls()
    toast = toast_cls()
    toast.type = "info"
    toast.content = text
    response.toast = toast
    return response


def _card_response(resp_cls: Any, card_cls: Any, card_data: dict) -> Any:
    """Return a P2CardActionTriggerResponse with a CallBackCard."""
    if resp_cls is None or card_cls is None:
        return None
    response = resp_cls()
    card = card_cls()
    card.type = "raw"
    card.data = card_data
    response.card = card
    return response
