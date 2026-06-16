"""API Server message:receive hook glue.

Thin owner-side helper so ``gateway/platforms/api_server.py`` only needs a
single ``await _owner_apply_message_receive_hooks(...)`` call.  All hook
orchestration, source construction, and adapter discovery lives here.

可移除性：删除此文件后，api_server.py 的 ``_owner_apply_message_receive_hooks``
会优雅降级为原样返回 ``message_text``，不会崩溃。
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _api_server_hooks(adapter: Any) -> Optional[Any]:
    """Return a hook registry for the API Server adapter.

    Reuses ``GatewayRunner.hooks`` when the adapter is connected through the
    gateway (the common case).  Falls back to a standalone ``HookRegistry`` only
    when the API Server is run directly without a gateway runner.
    """
    gateway_ref = getattr(adapter, "_gateway_ref", None)
    hooks = getattr(gateway_ref, "hooks", None) if gateway_ref is not None else None
    if hooks is not None:
        return hooks

    # Standalone API Server fallback: create and cache a private registry.
    fallback = getattr(adapter, "_owner_fallback_hooks", None)
    if fallback is not None:
        return fallback
    try:
        from gateway.hooks import HookRegistry

        fallback = HookRegistry()
        fallback.discover_and_load()
        adapter._owner_fallback_hooks = fallback
        return fallback
    except Exception as exc:
        logger.debug("API Server fallback hook registry creation failed: %s", exc)
        return None


def _build_source(
    *,
    reply_receive_id: str,
    reply_receive_id_type: str,
    user_id: str,
) -> SimpleNamespace:
    """Build a lightweight source object for message:receive hooks."""
    from gateway.platforms.base import Platform

    chat_id = reply_receive_id or ""
    if chat_id:
        if reply_receive_id_type == "open_id" or chat_id.startswith("ou_"):
            chat_type = "p2p"
            open_id = user_id or chat_id
        else:
            chat_type = "group"
            open_id = ""
    else:
        chat_type = ""
        open_id = ""

    return SimpleNamespace(
        platform=Platform.API_SERVER,
        chat_id=chat_id,
        chat_type=chat_type,
        user_id=user_id,
        open_id=open_id,
    )


def _build_adapters(adapter: Any) -> Dict[Any, Any]:
    """Expose the API Server adapter and, when available, the Feishu adapter."""
    from gateway.platforms.base import Platform

    adapters: Dict[Any, Any] = {Platform.API_SERVER: adapter}
    gateway_ref = getattr(adapter, "_gateway_ref", None)
    if gateway_ref is not None:
        try:
            feishu_adapter = gateway_ref.adapters.get(Platform.FEISHU)
            if feishu_adapter is not None:
                adapters[Platform.FEISHU] = feishu_adapter
        except Exception:
            pass
    return adapters


async def apply_api_server_message_receive_hooks(
    adapter: Any,
    message_text: str,
    *,
    session_id: str,
    reply_receive_id: str = "",
    reply_receive_id_type: str = "",
    user_id: str = "",
) -> str:
    """Trigger message:receive hooks for an API Server request.

    Returns the (possibly augmented) message text.  On any failure the original
    text is returned so the request can continue unimpeded.
    """
    hooks = _api_server_hooks(adapter)
    if hooks is None or not message_text:
        return message_text

    try:
        from owner.hooks.message_receive import apply_message_receive_hooks

        source = _build_source(
            reply_receive_id=reply_receive_id or "",
            reply_receive_id_type=reply_receive_id_type or "",
            user_id=user_id or "",
        )
        return await apply_message_receive_hooks(
            hooks=hooks,
            adapters=_build_adapters(adapter),
            source=source,
            session_id=session_id,
            message_text=message_text,
        )
    except Exception as exc:
        logger.debug("API Server message:receive hook failed: %s", exc)
        return message_text
