"""Gateway inbound message context — platform-specific append blocks.

Feishu gets open_id + chat_id + user_name appended to each user turn.
Other platforms are unchanged (no append here; non-Feishu may still use the
legacy system-prompt ``Current user:`` path in agent/system_prompt.py).
"""

from __future__ import annotations

from typing import Any, Optional


def _platform_name(source: Any) -> str:
    platform = getattr(source, "platform", None)
    return str(getattr(platform, "value", platform) or "").lower().strip()


def build_inbound_context_block(
    source: Any, session_id: Optional[str] = None
) -> Optional[str]:
    """Build a platform-specific inbound context block, or None when not applicable."""
    if _platform_name(source) != "feishu":
        return None
    from owner.feishu.inbound_context import build_feishu_inbound_context_block

    return build_feishu_inbound_context_block(source, session_id=session_id)


def append_inbound_context(
    message_text: str, source: Any, session_id: Optional[str] = None
) -> str:
    """Append inbound context to the prepared user message when the platform supports it."""
    block = build_inbound_context_block(source, session_id=session_id)
    if not block:
        return message_text
    text = (message_text or "").rstrip()
    if not text:
        return block
    return f"{text}\n\n{block}"