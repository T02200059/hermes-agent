"""Feishu per-message inbound context block (append to user turn).

Replaces system-prompt ``Current user:`` for Feishu only. Exposes open_id,
chat_id, and display name so the model can address the user and target the
correct Feishu receive_id without conflating ou_ vs oc_ identifiers.
"""

from __future__ import annotations

from typing import Any, Optional

_INBOUND_CONTEXT_HEADER = "[Inbound context]"


def build_feishu_inbound_context_block(source: Any) -> Optional[str]:
    """Return an append-only context block for a Feishu ``SessionSource``, or None."""
    open_id = str(getattr(source, "user_id", "") or "").strip()
    chat_id = str(getattr(source, "chat_id", "") or "").strip()
    user_name = str(getattr(source, "user_name", "") or "").strip()
    chat_type = str(getattr(source, "chat_type", "") or "").strip()

    if not open_id and not chat_id and not user_name:
        return None

    lines = [
        "---",
        _INBOUND_CONTEXT_HEADER,
        "platform: feishu",
    ]
    if user_name:
        lines.append(f"user_name: {user_name}")
    if open_id:
        lines.append(f"open_id: {open_id}")
    if chat_id:
        lines.append(f"chat_id: {chat_id}")
    if chat_type:
        lines.append(f"chat_type: {chat_type}")
    lines.append("---")
    return "\n".join(lines)