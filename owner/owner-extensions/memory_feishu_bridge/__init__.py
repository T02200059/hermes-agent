"""Feishu memory write-approval card bridge.

Auto-popup approval card when memory tool stages a write on Feishu.
Uses pre_gateway_dispatch + post_tool_call hooks (zero upstream surface).
See owner/feishu/memory_approval.py for card construction + click routing.

Also transforms the memory tool result message on Feishu to indicate the
approval card has been sent (via transform_tool_result hook). On non-Feishu
platforms the original upstream message is preserved unchanged.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any, Set

logger = logging.getLogger(__name__)

# Process-global weak references to the gateway runner + Feishu adapter,
# populated lazily by the ``pre_gateway_dispatch`` hook.
_GATEWAY_REF: Any = None
_FEISHU_ADAPTER: Any = None
_REF_LOCK = threading.Lock()

# Pending IDs for which an approval card was successfully sent on Feishu.
# Populated by post_tool_call, consumed by transform_tool_result (runs after).
_SENT_CARD_IDS: Set[str] = set()
_SENT_CARD_LOCK = threading.Lock()


def register_hooks(ctx: Any) -> None:
    """Register hooks for memory approval cards + result message transform."""
    ctx.register_hook("pre_gateway_dispatch", _on_pre_gateway_dispatch)
    ctx.register_hook("post_tool_call", _on_post_tool_call)
    ctx.register_hook("transform_tool_result", _on_transform_tool_result)


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
    gateway_session_key = str(kwargs.get("gateway_session_key") or "")  # [owner] preferred: stable per-chat key
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

    # Prefer gateway_session_key (agent:main:feishu:dm:<chat_id>) — it is the
    # stable per-chat identifier. Fall back to session_id (agent.session_id,
    # a timestamp id) for backward compat with older hook callers.
    chat_id = extract_feishu_chat_id(gateway_session_key)
    if not chat_id:
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
                # [owner] prefer gateway_session_key: it has the stable
                # agent:main:feishu:dm:<chat_id> shape the card expects.
                session_id=gateway_session_key or session_id,
            )

        try:
            submit = getattr(adapter, "_submit_on_loop", None)
            if callable(submit):
                submit(loop, _send())
            else:
                asyncio.run_coroutine_threadsafe(_send(), loop)
        except Exception as exc:
            logger.warning("[memory-feishu-bridge] schedule send failed for pending %s: %s", pending_id, exc)
            return  # card not sent — don't mark

        # Mark that a card was dispatched for this pending_id so
        # transform_tool_result can update the agent-facing message.
        with _SENT_CARD_LOCK:
            _SENT_CARD_IDS.add(str(pending_id))
    except Exception as exc:
        logger.warning("[memory-feishu-bridge] post_tool_call send failed for pending %s: %s", pending_id, exc)


def _on_transform_tool_result(**kwargs: Any) -> str | None:
    """On Feishu, rewrite a staged memory result to mention the approval card.

    The upstream message says "Not yet saved - review with /memory pending",
    which is a CLI-only affordance. On Feishu an interactive card was already
    dispatched, so the agent is told the card has been sent instead.

    Returns ``None`` (no transformation) for:
      * non-memory tools
      * non-staged results
      * results whose pending_id has no matching dispatched card (non-Feishu
        sessions, or card dispatch that failed before marking)
    """
    tool_name = kwargs.get("tool_name") or ""
    if tool_name != "memory":
        return None

    result_raw = kwargs.get("result")
    if not isinstance(result_raw, str):
        return None

    try:
        parsed = json.loads(result_raw) if result_raw else {}
    except Exception:
        return None
    if not isinstance(parsed, dict) or not parsed.get("staged"):
        return None

    pending_id = str(parsed.get("pending_id") or "")
    if not pending_id:
        return None

    # Only transform when a card was actually dispatched on Feishu.
    with _SENT_CARD_LOCK:
        hit = pending_id in _SENT_CARD_IDS
        if hit:
            _SENT_CARD_IDS.discard(pending_id)  # one-shot

    if not hit:
        return None

    parsed["message"] = (
        "Staged for approval (memory.write_approval is on). "
        "Approval card sent to chat — click ✅ to save or 🟥 to discard."
    )
    return json.dumps(parsed, ensure_ascii=False)
