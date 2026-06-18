"""Default send target for sub-profile (send_only) feishu containers.

When the LLM calls send_message without a target on a sub-profile container,
there is no FEISHU_HOME_CHANNEL to fall back to (only the main gateway has one).
But the routed conversation carries full session context, so we default to the
current session's chat — DMs via open_id, groups via chat_id — exactly like the
native reply path.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

_CHAT_TYPE_TOKENS = frozenset({"dm", "group", "thread", "p2p"})


def _parse_chat_type(session_key: str) -> str:
    """Extract the chat-type token from a session key, defaulting to 'group'.

    Keys look like ``agent:<scope>:feishu:<dm|group|thread>:<chat_id>[:<thread_id>]``.
    Scan segments for a known token (fixed index breaks when thread keys carry an
    extra segment). Unknown -> 'group' + warning: 'group' uses the real chat_id and
    never mis-delivers, whereas 'dm' on a group would silently DM the sender.
    """
    for seg in session_key.split(":"):
        if seg in _CHAT_TYPE_TOKENS:
            return seg
    logger.warning(
        "[Feishu] Could not parse chat_type from session_key %r; defaulting to 'group'",
        session_key,
    )
    return "group"


def resolve_default_send_target(
    platform_name: str, pconfig: Any
) -> Optional[Tuple[str, Dict[str, str]]]:
    """Resolve the current-session feishu target when send_message omits one.

    Returns ``(chat_id, metadata)`` to use, or ``None`` to leave the tool's
    existing behaviour unchanged (main gateway / non-feishu / no session).

    ``metadata`` carries ``chat_type`` + ``open_id`` (+ ``thread_id`` if any) so
    the downstream ``_resolve_receive_target`` picks open_id for DMs, chat_id for
    groups.
    """
    if platform_name != "feishu":
        return None
    extra = getattr(pconfig, "extra", None) or {}
    if extra.get("connection_mode") != "send_only":
        return None

    from gateway.session_context import get_session_env

    if get_session_env("HERMES_SESSION_PLATFORM") != "feishu":
        return None
    chat_id = get_session_env("HERMES_SESSION_CHAT_ID")
    if not chat_id:
        return None

    metadata: Dict[str, str] = {
        "chat_type": _parse_chat_type(get_session_env("HERMES_SESSION_KEY")),
    }
    open_id = get_session_env("HERMES_SESSION_USER_ID")
    if open_id:
        metadata["open_id"] = open_id
    thread_id = get_session_env("HERMES_SESSION_THREAD_ID")
    if thread_id:
        metadata["thread_id"] = thread_id
    logger.info(
        "[Feishu] send_message no target on sub-profile; defaulting to session "
        "chat (chat_type=%s, chat_id=%s)", metadata["chat_type"], chat_id,
    )
    return chat_id, metadata
