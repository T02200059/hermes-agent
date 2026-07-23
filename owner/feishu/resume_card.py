"""Feishu interactive card implementation for the /resume command.

Core implementation lives here per 二次开发规范:
- P1 import 编排: 官方代码只做薄薄的代理 + import + 调用
- 所有真实逻辑放在 owner/ 下, 便于独立演进和回滚

设计要点:
- 列表展示: gateway 飞书分支调 ``adapter.send_resume_card`` 委托到这里
  构建 v2 schema 卡片(跟 model_picker 一致), 数字按钮 1~10 三个一行
- 按钮回调: 从 button.value 取 ``source_dict`` 还原 SessionSource,
  合成 ``MessageType.COMMAND`` 的 ``/resume N`` 文本事件,
  通过 ``adapter._submit_on_loop`` + ``_handle_message_with_guards``
  走与 model_picker confirm 完全一致的合成消息流水线
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from gateway.platforms.feishu import FeishuAdapter

from agent.i18n import t
from gateway.platforms.base import SendResult

logger = logging.getLogger(__name__)


def build_resume_card(
    header_text: str,
    sessions: List[Dict[str, Any]],
    session_key: str,
    source_dict: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the interactive card for /resume.

    Args:
        header_text: Translated header text from gateway i18n
        sessions: 1-10 titled sessions to list (each: id/title/preview)
        session_key: Current session key for correlation/debugging
        source_dict: Serialized SessionSource for button callback to reuse
            (avoids reconstruction errors in card-action context)

    Returns:
        Feishu v2-schema card dict ready to send via send_card_via_rest.
    """
    # Markdown content keeps the full session list visible on mobile
    # (button labels are just digits, list text holds the full preview).
    content_lines = [header_text]
    for idx, s in enumerate(sessions, start=1):
        title = s["title"]
        preview = s.get("preview", "")[:40]
        preview_part = (
            t("gateway.resume.list_preview_suffix", preview=preview)
            if preview else ""
        )
        content_lines.append(t(
            "gateway.resume.list_item_numbered",
            index=idx,
            title=title,
            preview_part=preview_part,
        ))
    content_lines.append(t("gateway.resume.list_footer_numbered"))
    content_md = "\n".join(content_lines)

    elements: List[Dict[str, Any]] = [
        {"tag": "markdown", "content": content_md},
    ]

    # Number buttons 3 per row using v2 schema column_set.
    # NOTE: feishu v2 schema **dropped the legacy `tag:action` container** —
    # using it returns API error 230099 / "cards of schema V2 no longer support
    # this capability". `column_set` is the supported way to lay out multiple
    # buttons in one row in v2.
    def _btn(idx: int) -> Dict[str, Any]:
        return {
            "tag": "button",
            "text": {"tag": "plain_text", "content": str(idx)},
            "type": "primary" if idx == 1 else "default",
            "value": {
                "hermes_action": "resume_select",
                "resume_index": idx,
                "session_key": session_key,
                # Stash source_dict so button callback can reconstruct
                # SessionSource without guessing chat_type / user_id.
                "source_dict": source_dict or {},
            },
        }

    total = len(sessions)
    current_row: List[Dict[str, Any]] = []
    for idx in range(1, total + 1):
        current_row.append(_btn(idx))
        if len(current_row) == 3:
            elements.append(_make_button_row(current_row))
            current_row = []
    if current_row:
        elements.append(_make_button_row(current_row))

    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {
                "content": "📋 " + t("gateway.resume.card_title"),
                "tag": "plain_text",
            },
            "template": "blue",
        },
        "body": {"elements": elements},
    }


def _make_button_row(buttons: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Wrap up to 3 buttons into a v2-schema column_set row.

    Each button gets its own column with weight=1 so they share the row width
    evenly. Used because v2 schema dropped the legacy `tag:action` container.
    """
    return {
        "tag": "column_set",
        "horizontal_align": "left",
        "columns": [
            {
                "tag": "column",
                "width": "weighted",
                "weight": 1,
                "elements": [btn],
            }
            for btn in buttons
        ],
    }


async def try_send_resume_card_list(
    adapter: Any,
    *,
    source: Any,
    event: Any,
    titled_sessions: List[Any],
    session_key: str,
    header_text: str,
) -> str:
    """Feishu-specific path for /resume list: send an interactive number card.

    Returns an empty string when the card path delivered (or gracefully fell
    back to plain text inside the helper), indicating the caller should stop
    rendering the list. Raises on unexpected failure so the caller can fall
    back to the normal plain-text list.

    This keeps gateway/slash_commands.py free of Feishu-specific card building,
    metadata injection and fallback logic per 二次开发规范.
    """
    if not adapter or not hasattr(adapter, "send_resume_card"):
        raise RuntimeError("Feishu adapter does not support resume card")

    card_sessions = [
        {
            "id": s.get("id"),
            "title": s.get("title"),
            "preview": s.get("preview", ""),
        }
        for s in titled_sessions[:10]
    ]

    # send_card_via_rest needs chat_type + open_id to compute receive_id_type
    event_meta = getattr(event, "metadata", None)
    metadata = dict(event_meta) if event_meta is not None else {}
    metadata["chat_type"] = source.chat_type
    # SessionSource.user_id holds the Feishu open_id (see _resolve_sender_profile)
    if source.user_id:
        metadata["open_id"] = source.user_id
    elif source.user_id_alt:
        metadata["open_id"] = source.user_id_alt

    await adapter.send_resume_card(
        chat_id=source.chat_id,
        header_text=header_text,
        sessions=card_sessions,
        session_key=session_key,
        source_dict=source.to_dict(),
        metadata=metadata,
    )
    # Card path delivered (or already fell back to plain text inside the helper).
    return ""


async def send_resume_card(
    adapter: "FeishuAdapter",
    *,
    chat_id: str,
    header_text: str,
    sessions: List[Dict[str, Any]],
    session_key: str,
    source_dict: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> SendResult:
    """Send the /resume interactive card; fall back to plain text on failure.

    Returns:
        SendResult: success=True if card sent OK,
                    success=False if card failed AND plain-text fallback
                    was successfully sent (caller can treat both as "delivered").
    """
    if not adapter._client:
        return SendResult(success=False, error="Not connected")

    from owner.feishu.card_sender import send_card_via_rest

    try:
        card = build_resume_card(
            header_text=header_text,
            sessions=sessions,
            session_key=session_key,
            source_dict=source_dict,
        )
        result = await send_card_via_rest(adapter, chat_id, card, metadata)
        if result.success:
            logger.info(
                "[Feishu card] resume sent OK chat_id=%s message_id=%s sessions=%d",
                chat_id,
                result.message_id or "(none)",
                len(sessions or []),
            )
            return result
        logger.info(
            "[Feishu card] resume send failed (%s); falling back to plain text",
            result.error,
        )
    except Exception as exc:
        logger.warning(
            "[Feishu] /resume card build failed: %s; falling back to plain text",
            exc,
        )

    # Plain-text fallback path (also reached when card build/send raised).
    plain_text = _build_plain_text(header_text, sessions)
    try:
        await adapter.send(chat_id=chat_id, content=plain_text, metadata=metadata)
        # Card path failed but text fallback succeeded — caller can treat as delivered.
        return SendResult(success=False, error="card failed; plain text fallback sent")
    except Exception as exc:
        logger.warning("[Feishu] /resume plain-text fallback also failed: %s", exc)
        return SendResult(success=False, error=f"both card and fallback failed: {exc}")


def _build_plain_text(header_text: str, sessions: List[Dict[str, Any]]) -> str:
    """Plain-text version of the resume list (used as card fallback)."""
    lines = [header_text]
    for idx, s in enumerate(sessions, start=1):
        title = s["title"]
        preview = s.get("preview", "")[:40]
        preview_part = (
            t("gateway.resume.list_preview_suffix", preview=preview)
            if preview else ""
        )
        lines.append(t(
            "gateway.resume.list_item_numbered",
            index=idx,
            title=title,
            preview_part=preview_part,
        ))
    lines.append(t("gateway.resume.list_footer_numbered"))
    return "\n".join(lines)


def handle_resume_card_action(
    *,
    adapter: Any,
    event: Any,
    action_value: Dict[str, Any],
    loop: Any,
) -> Any:
    """Handle resume number-button click.

    Reconstructs the original SessionSource from ``source_dict`` baked into
    button.value at card-build time, then synthesizes a ``/resume N`` COMMAND
    MessageEvent and submits it on the adapter loop — same pattern model_picker
    confirm uses (see ``owner/feishu/model_picker.py:_route_picker_command``).

    Returns:
        P2CardActionTriggerResponse (empty) so the click is acknowledged
        without rewriting the card. The actual /resume reply comes through
        the normal message handling path.
    """
    # Lazy import: keep removability — deleting owner/feishu/ shouldn't
    # crash the adapter at import time even if SDK is missing.
    try:
        from lark_oapi.event.callback.model.p2_card_action_trigger import (
            P2CardActionTriggerResponse,
        )
    except ImportError:
        P2CardActionTriggerResponse = None  # type: ignore[assignment]

    def _empty_response() -> Any:
        return P2CardActionTriggerResponse() if P2CardActionTriggerResponse else None

    resume_index = action_value.get("resume_index")
    if resume_index is None:
        return _empty_response()

    source_dict = action_value.get("source_dict") or {}
    if not isinstance(source_dict, dict) or not source_dict.get("chat_id"):
        logger.warning(
            "[Feishu] /resume card callback missing source_dict, dropping (value=%r)",
            action_value,
        )
        return _empty_response()

    # Reconstruct SessionSource from the stashed dict — this is exactly the
    # source we used at card-build time, so chat_type / user_id are correct.
    try:
        from gateway.session import SessionSource
        source = SessionSource.from_dict(source_dict)
    except Exception as exc:
        logger.warning("[Feishu] /resume failed to rebuild SessionSource: %s", exc)
        return _empty_response()

    # [owner] Validate that the operator who clicked the button is the same
    # user whose sessions are being listed. Prevents group members from
    # impersonating the card owner and resuming someone else's session.
    operator = getattr(event, "operator", None)
    operator_id = str(getattr(operator, "open_id", "") or "")
    if operator_id and operator_id != source.user_id:
        logger.warning(
            "[owner] resume card action rejected: operator %s != source user %s",
            operator_id, source.user_id,
        )
        return _empty_response()

    # Schedule the synthetic /resume N command on the adapter loop.
    if not adapter._loop_accepts_callbacks(loop):
        logger.warning("[Feishu] /resume card callback: loop not accepting work")
        return _empty_response()

    async def _dispatch() -> None:
        try:
            import uuid as _uuid
            from datetime import datetime
            from gateway.platforms.base import MessageEvent, MessageType

            synthetic_event = MessageEvent(
                text=f"/resume {resume_index}",
                message_type=MessageType.COMMAND,
                source=source,
                raw_message=None,
                message_id="",  # no reply_to — synthetic, not a real Feishu message
                timestamp=datetime.now(),
            )
            await adapter._handle_message_with_guards(synthetic_event)
        except Exception as exc:
            logger.warning("[Feishu] /resume card synthetic dispatch failed: %s", exc)

    adapter._submit_on_loop(loop, _dispatch())
    return _empty_response()
