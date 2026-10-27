"""[owner] C13 — /recap slash command (plugin-registered).

Loads the current session transcript, runs the recap explainer, returns a
notice-prefixed body for gateway delivery (Feishu auto_card notice rule).
Does **not** append into the agent model transcript.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, List, Optional

from owner.explainers.common import normalize_platform
from owner.explainers.config import load_kind_config, resolve_enabled
from owner.explainers.recap.explain import explain_from_messages
from owner.explainers.recap.prompt import format_delivery

logger = logging.getLogger("hermes.owner.explainers.recap")

_EMPTY = "📋 系统提示：当前会话还没有可回顾的对话。"
_DISABLED = "📋 系统提示：recap 未启用（见 overlay.yaml explainers.recap）。"
_NO_SESSION = "📋 系统提示：找不到当前会话，无法生成回顾。"
_FAILED = "📋 系统提示：回顾生成失败，请稍后再试。"


def _load_messages(session_id: str) -> list[dict]:
    if not session_id:
        return []
    from hermes_state import SessionDB

    db = SessionDB(read_only=True)
    try:
        resolved = db.resolve_session_id(session_id) or session_id
        tip = None
        try:
            tip = db.get_compression_tip(resolved) or resolved
        except Exception:
            tip = resolved
        return list(db.get_messages_as_conversation(tip, repair_alternation=True) or [])
    finally:
        try:
            db.close()
        except Exception:
            pass


async def handle_recap_command(
    raw_args: str = "",
    *,
    source: Any = None,
    session_id: str = "",
    session_key: str = "",
    platform: str = "",
    event: Any = None,
    **_kwargs: Any,
) -> Optional[str]:
    """Handle /recap → notice-prefixed recap text (or short status)."""
    if source is None and event is not None:
        source = getattr(event, "source", None)

    plat = normalize_platform(platform) or normalize_platform(
        getattr(source, "platform", "") if source is not None else ""
    )
    chat_id = ""
    if source is not None:
        chat_id = str(getattr(source, "chat_id", "") or "")

    if not resolve_enabled("recap", plat, chat_id or None):
        return _DISABLED

    sid = str(session_id or "").strip()
    if not sid and source is not None:
        # Best-effort: env bound by gateway plugin dispatch
        try:
            from gateway.session_context import get_session_env

            sid = get_session_env("HERMES_SESSION_ID", "") or sid
        except Exception:
            pass
    if not sid:
        return _NO_SESSION

    try:
        messages = await asyncio.to_thread(_load_messages, sid)
    except Exception as exc:
        logger.warning("/recap load transcript failed: %s", exc)
        return _FAILED

    if not messages:
        return _EMPTY

    cfg = load_kind_config("recap")
    try:
        text = await asyncio.to_thread(explain_from_messages, messages, cfg=cfg)
    except Exception as exc:
        logger.warning("/recap explain failed: %s", exc)
        return _FAILED

    body = format_delivery(text or "")
    if not body:
        return _FAILED
    # Manual success bumps watermark so idle auto won't re-fire until a new user turn.
    try:
        from owner.explainers.recap.auto import note_manual_recap

        note_manual_recap(sid, messages)
    except Exception:
        logger.debug("/recap watermark note failed", exc_info=True)
    return body
