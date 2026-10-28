"""Feishu interactive card for the /resume command (C27-resume-card).

Core lives here per 二次开发规范:
- Official code is thin glue (import + call) only
- Real logic stays under owner/ for independent evolution / rollback

Design:
- List: gateway Feishu branch calls ``adapter.send_resume_card`` → here
  builds a v2-schema card (same family as model_picker), number buttons 1–10
  three per row
- Click: read ``source_dict`` / ``session_title`` from button.value, rebuild
  SessionSource, synthesize ``MessageType.COMMAND`` ``/resume N``, submit via
  ``adapter._submit_on_loop`` + ``_handle_message_with_guards``
  (same pipeline as model_picker confirm). Success -> frozen done card;
  submit failure -> failed card (no empty ack that leaves buttons clickable)

Operator auth: keep clicker == card owner. Unlike approval cards (where the
frozen card already shows "approved by X"), a resume click switches session
state — group members must not impersonate the card owner (IDOR).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from plugins.platforms.feishu.adapter import FeishuAdapter

from agent.i18n import t
from gateway.platforms.base import SendResult

logger = logging.getLogger(__name__)


def build_resume_card(
    header_text: str,
    sessions: list[dict[str, Any]],
    session_key: str,
    source_dict: dict[str, Any] | None = None,
) -> dict[str, Any]:
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

    elements: list[dict[str, Any]] = [
        {"tag": "markdown", "content": content_md},
    ]

    # Number buttons 3 per row using v2 schema column_set.
    # NOTE: feishu v2 schema **dropped the legacy `tag:action` container** —
    # using it returns API error 230099 / "cards of schema V2 no longer support
    # this capability". `column_set` is the supported way to lay out multiple
    # buttons in one row in v2.
    def _btn(idx: int) -> dict[str, Any]:
        # Click callback has no session list — stash title for the frozen card.
        title = ""
        if 1 <= idx <= len(sessions):
            title = str(sessions[idx - 1].get("title") or "")
        return {
            "tag": "button",
            "text": {"tag": "plain_text", "content": str(idx)},
            "type": "primary" if idx == 1 else "default",
            "value": {
                "hermes_action": "resume_select",
                "resume_index": idx,
                "session_key": session_key,
                "session_title": title,
                # Stash source_dict so button callback can reconstruct
                # SessionSource without guessing chat_type / user_id.
                "source_dict": source_dict or {},
            },
        }

    total = len(sessions)
    current_row: list[dict[str, Any]] = []
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


def _make_button_row(buttons: list[dict[str, Any]]) -> dict[str, Any]:
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
    titled_sessions: list[Any],
    session_key: str,
    header_text: str,
) -> str:
    """Feishu-specific path for /resume list: send an interactive number card.

    Returns an empty string when the card path delivered (or gracefully fell
    back to plain text inside the helper), indicating the caller should stop
    rendering the list. Raises on unexpected failure so the caller can fall
    back to the normal plain-text list.

    Keeps gateway/slash_commands_session.py free of Feishu-specific card
    building, metadata injection and fallback logic per 二次开发规范.
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
    adapter: FeishuAdapter,
    *,
    chat_id: str,
    header_text: str,
    sessions: list[dict[str, Any]],
    session_key: str,
    source_dict: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
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


def _build_plain_text(header_text: str, sessions: list[dict[str, Any]]) -> str:
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


def build_done_card(
    resume_index: int,
    session_title: str,
    user_name: str,
) -> dict[str, Any]:
    """Frozen confirmation card after a resume number button is clicked.

    No buttons — mirrors model_picker ``build_done_card`` so a second click
    cannot re-dispatch ``/resume N``. Actual resume reply still arrives via
    the synthetic command path.
    """
    title = (session_title or "").strip() or f"#{resume_index}"
    display = (user_name or "").strip() or "用户"
    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {
                "content": f"🔄 已选择恢复 {title}",
                "tag": "plain_text",
            },
            "template": "green",
        },
        "body": {
            "elements": [
                {
                    "tag": "markdown",
                    "content": (
                        f"编号: **{resume_index}**\n"
                        f"会话: **{title}**\n\n"
                        f"由 {display} 发起恢复。正在切换会话…"
                    ),
                },
            ],
        },
    }


def build_failed_card(
    *,
    reason: str = "submit_failed",
    resume_index: int | None = None,
    session_title: str = "",
    detail: str = "",
) -> dict[str, Any]:
    """Frozen error card when resume click cannot be scheduled.

    Aligns with C12 queue / C04 approval ``submit_failed``: never leave the
    interactive number buttons clickable after a failed schedule.
    """
    title_map = {
        "submit_failed": "💡 恢复提交失败",
        "loop_closed": "💡 恢复提交失败",
        "missing_source": "💡 恢复失败",
        "unauthorized": "💡 无权重启该会话",
    }
    body_map = {
        "submit_failed": (
            "未能把恢复请求排入处理队列（事件循环不可用或调度失败）。\n"
            "请重试，或直接发送 `/resume <编号>`。"
        ),
        "loop_closed": (
            "当前事件循环已关闭，无法调度恢复。\n"
            "请稍后重试，或直接发送 `/resume <编号>`。"
        ),
        "missing_source": (
            "卡片回调缺少会话来源信息，已忽略本次点击。\n"
            "请重新发送 `/resume` 获取新列表。"
        ),
        "unauthorized": (
            "只有发起该恢复列表的用户可以点选编号。\n"
            "如需恢复，请自己发送 `/resume`。"
        ),
    }
    header = title_map.get(reason, "💡 恢复失败")
    body = detail.strip() if detail and detail.strip() else body_map.get(
        reason,
        "操作失败，请重试或直接发送 `/resume <编号>`。",
    )
    bits: list[str] = [body]
    if resume_index is not None:
        bits.append(f"\n\n编号: **{resume_index}**")
        title = (session_title or "").strip()
        if title:
            bits.append(f"\n会话: **{title}**")
    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": header, "tag": "plain_text"},
            "template": "orange",
        },
        "body": {
            "elements": [
                {"tag": "markdown", "content": "".join(bits)},
            ],
        },
    }


def handle_resume_card_action(
    *,
    adapter: Any,
    event: Any,
    action_value: dict[str, Any],
    loop: Any,
) -> Any:
    """Handle resume number-button click.

    Reconstructs the original SessionSource from ``source_dict`` baked into
    button.value at card-build time, then synthesizes a ``/resume N`` COMMAND
    MessageEvent and submits it on the adapter loop — same pattern model_picker
    confirm uses (see ``owner/feishu/model_picker.py:_route_picker_command``).

    Returns:
        Frozen CallBack card (done / failed). Success freezes buttons so a
        double-click cannot re-dispatch; submit failure surfaces a notice card
        instead of an empty ack. The actual /resume reply still arrives via
        the normal message handling path.
    """
    resume_index = action_value.get("resume_index")
    session_title = str(action_value.get("session_title") or "")
    if resume_index is None:
        return adapter._card_response()

    try:
        idx_int = int(resume_index)
    except (TypeError, ValueError):
        idx_int = None

    source_dict = action_value.get("source_dict") or {}
    if not isinstance(source_dict, dict) or not source_dict.get("chat_id"):
        logger.warning(
            "[Feishu] /resume card callback missing source_dict, dropping (value=%r)",
            action_value,
        )
        return adapter._card_response(
            build_failed_card(
                reason="missing_source",
                resume_index=idx_int,
                session_title=session_title,
            )
        )

    # Reconstruct SessionSource from the stashed dict — this is exactly the
    # source we used at card-build time, so chat_type / user_id are correct.
    try:
        from gateway.session import SessionSource
        source = SessionSource.from_dict(source_dict)
    except Exception as exc:
        logger.warning("[Feishu] /resume failed to rebuild SessionSource: %s", exc)
        return adapter._card_response(
            build_failed_card(
                reason="missing_source",
                resume_index=idx_int,
                session_title=session_title,
                detail=f"无法还原会话来源：{exc}",
            )
        )

    # [owner] Clicker must be the card owner. Resume switches session state
    # (unlike approval cards, where the frozen card already shows who approved).
    operator = getattr(event, "operator", None)
    operator_id = str(getattr(operator, "open_id", "") or "")
    if operator_id and operator_id != source.user_id:
        logger.warning(
            "[owner] resume card action rejected: operator %s != source user %s",
            operator_id, source.user_id,
        )
        return adapter._card_response(
            build_failed_card(
                reason="unauthorized",
                resume_index=idx_int,
                session_title=session_title,
            )
        )

    # Schedule the synthetic /resume N command on the adapter loop.
    if not adapter._loop_accepts_callbacks(loop):
        logger.warning("[Feishu] /resume card callback: loop not accepting work")
        return adapter._card_response(
            build_failed_card(
                reason="loop_closed",
                resume_index=idx_int,
                session_title=session_title,
            )
        )

    try:
        from owner.feishu.sender_name_helpers import operator_display_name
        user_name = operator_display_name(adapter, operator_id)
    except Exception:
        user_name = operator_id or "用户"

    async def _dispatch() -> None:
        try:
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

    coro = _dispatch()
    if not adapter._submit_on_loop(loop, coro):
        logger.warning("[Feishu] /resume card callback: _submit_on_loop failed")
        try:
            coro.close()
        except Exception:
            pass
        return adapter._card_response(
            build_failed_card(
                reason="submit_failed",
                resume_index=idx_int,
                session_title=session_title,
            )
        )

    return adapter._card_response(
        build_done_card(
            idx_int if idx_int is not None else resume_index,
            session_title,
            user_name,
        )
    )

def dispatch_resume_card_action(
    adapter: Any,
    *,
    event: Any,
    action_value: dict[str, Any],
    loop: Any,
) -> Any:
    """Trace then delegate a resume-card callback to ``handle_resume_card_action``.

    Named ``dispatch_*`` rather than ``handle_*`` to match model_picker / queue /
    guide shells used by the Feishu adapter thin glue.
    """
    resume_index = action_value.get("resume_index") if isinstance(action_value, dict) else None
    logger.info(
        "[Feishu card] resume action resume_index=%s",
        resume_index,
    )
    return handle_resume_card_action(
        adapter=adapter,
        event=event,
        action_value=action_value,
        loop=loop,
    )
