"""Feishu memory write-approval card bridge.

Auto-popup approval card when memory tool stages a write on Feishu.
Uses pre_gateway_dispatch + post_tool_call hooks (zero upstream surface).
See owner/feishu/memory_approval.py for card construction + click routing.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)

# Process-global weak references to the gateway runner + Feishu adapter,
# populated lazily by the ``pre_gateway_dispatch`` hook.
_GATEWAY_REF: Any = None
_FEISHU_ADAPTER: Any = None
_REF_LOCK = threading.Lock()


def register_hooks(ctx: Any) -> None:
    """Register the two hooks needed for memory approval cards."""
    ctx.register_hook("pre_gateway_dispatch", _on_pre_gateway_dispatch)
    ctx.register_hook("post_tool_call", _on_post_tool_call)


def _on_pre_gateway_dispatch(**kwargs: Any) -> None:
    """Cache the gateway reference + Feishu adapter on each inbound message."""
    global _GATEWAY_REF, _FEISHU_ADAPTER
    gateway = kwargs.get("gateway")
    if gateway is None:
        return
    try:
        adapters = getattr(gateway, "adapters", {}) or {}
        try:
            from gateway.config import Platform
            adapter = adapters.get(Platform.FEISHU)
        except Exception:
            adapter = adapters.get("feishu") if "feishu" in adapters else None
        if adapter is None:
            return
        with _REF_LOCK:
            _GATEWAY_REF = gateway
            _FEISHU_ADAPTER = adapter
    except Exception as exc:
        logger.debug("[memory-feishu-bridge] pre_gateway_dispatch cache failed: %s", exc)


def _on_post_tool_call(**kwargs: Any) -> None:
    """Detect staged memory writes on Feishu and send an approval card."""
    tool_name = kwargs.get("tool_name") or ""
    if tool_name != "memory":
        return

    result_raw = kwargs.get("result")
    if not isinstance(result_raw, str):
        return

    try:
        parsed = json.loads(result_raw) if result_raw else {}
    except Exception:
        return
    if not isinstance(parsed, dict):
        return

    if not parsed.get("staged"):
        return
    pending_id = parsed.get("pending_id")
    if not pending_id:
        return

    session_id = str(kwargs.get("session_id") or "")
    args = kwargs.get("args") or {}

    with _REF_LOCK:
        adapter = _FEISHU_ADAPTER
    if adapter is None:
        return

    try:
        from owner.feishu.memory_approval import (
            build_preview, extract_feishu_chat_id, send_approval_card,
        )
    except Exception as exc:
        logger.debug("[memory-feishu-bridge] owner.feishu.memory_approval unavailable: %s", exc)
        return

    chat_id = extract_feishu_chat_id(session_id)
    if not chat_id:
        return

    summary, content_preview = build_preview(args)
    if not summary:
        return

    try:
        loop = getattr(adapter, "_loop", None)
        if loop is None:
            gw = _GATEWAY_REF
            loop = getattr(gw, "_loop", None) if gw is not None else None
        if loop is None or getattr(loop, "is_closed", lambda: False)():
            logger.warning("[memory-feishu-bridge] no live loop; skipping card for pending %s", pending_id)
            return

        import asyncio

        async def _send() -> None:
            await send_approval_card(
                adapter,
                chat_id=chat_id,
                pending_id=str(pending_id),
                summary=summary,
                content_preview=content_preview,
                session_id=session_id,
            )

        try:
            submit = getattr(adapter, "_submit_on_loop", None)
            if callable(submit):
                submit(loop, _send())
            else:
                asyncio.run_coroutine_threadsafe(_send(), loop)
        except Exception as exc:
            logger.warning("[memory-feishu-bridge] schedule send failed for pending %s: %s", pending_id, exc)
    except Exception as exc:
        logger.warning("[memory-feishu-bridge] post_tool_call send failed for pending %s: %s", pending_id, exc)
