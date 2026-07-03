"""[owner] Hermes plugin entry: registers owner-specific runtime patches.

All owner monkey-patches are applied at plugin register() time, which
runs during discover_plugins() -- guaranteed before any agent turn or
MemoryManager call (see gateway/run.py and model_tools.py).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _wrap_providers_command(handler):
    async def _providers_command(_raw_args: str, *, hermes_ctx):
        return await handler(
            adapters=getattr(hermes_ctx, "adapters", {}) or {},
            event=getattr(hermes_ctx, "event", None),
        )

    return _providers_command


def register(ctx) -> None:
    """Apply all owner runtime patches. Idempotent per-patch."""
    # §2.5 /providers plugin slash command
    # Uses PluginCommandContext (hermes_ctx) so Feishu can keep its interactive
    # provider picker card via gateway adapters/event, while CLI falls back to text.
    try:
        from owner.commands.providers import handle_providers_command
        ctx.register_command(
            "providers",
            _wrap_providers_command(handle_providers_command),
            description="List configured providers",
        )
        logger.debug("owner: /providers registered via plugin command")
    except Exception:
        logger.warning("owner: /providers registration failed", exc_info=True)

    # §9.3 memory synthetic guard
    # Skip MemoryManager prefetch/sync/on_turn_start for synthetic system
    # messages (async delegation, bg process, watch match, CLI handoff).
    # See owner/patches/memory_synthetic_guard_patch.py
    try:
        from owner.patches.memory_synthetic_guard_patch import apply_patch
        apply_patch()
        logger.debug("owner: memory_synthetic_guard_patch applied via plugin register")
    except Exception:
        logger.warning("owner: memory_synthetic_guard_patch failed", exc_info=True)

    # §2.3 runtime schema patches
    # Mutate built-in tool schema dicts after tool registration so owner-only
    # parameters (image_generate.model, legacy send_message.card) are visible
    # without editing upstream tool modules.
    try:
        import owner.tools.schema_patches  # noqa: F401
        logger.debug("owner: schema_patches applied via plugin register")
    except Exception:
        logger.warning("owner: schema_patches failed", exc_info=True)

    # §7.3 OpenViking recall owner extensions
    # Advisory wording, peer-mirror dedup, recall card (Feishu/QQ).
    # See owner/patches/openviking_owner_recall_patch.py
    try:
        from owner.patches.openviking_owner_recall_patch import apply_patch
        apply_patch()
        logger.debug("owner: openviking_owner_recall_patch applied via plugin register")
    except Exception:
        logger.warning("owner: openviking_owner_recall_patch failed", exc_info=True)

    # §7.4 Feishu memory write-approval interactive card
    # Auto-popup approval card when memory tool stages a write on Feishu.
    # Uses pre_gateway_dispatch + post_tool_call hooks (zero upstream surface).
    # See owner/feishu/memory_approval.py for card construction + click routing.
    try:
        ctx.register_hook("pre_gateway_dispatch", _on_pre_gateway_dispatch)
        ctx.register_hook("post_tool_call", _on_post_tool_call)
        logger.debug("owner: memory-feishu-bridge hooks registered via owner-extensions")
    except Exception:
        logger.warning("owner: memory-feishu-bridge hooks registration failed", exc_info=True)


# ---------------------------------------------------------------------------
# §7.4 Feishu memory write-approval card helpers
# (merged from plugins/owner-memory-feishu-bridge)
# ---------------------------------------------------------------------------
import json
import threading
from typing import Any

_GATEWAY_REF: Any = None
_FEISHU_ADAPTER: Any = None
_REF_LOCK = threading.Lock()


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
        logger.debug("[owner-ext] pre_gateway_dispatch cache failed: %s", exc)


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
        logger.debug("[owner-ext] owner.feishu.memory_approval unavailable: %s", exc)
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
            logger.warning("[owner-ext] no live loop; skipping card for pending %s", pending_id)
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
            logger.warning("[owner-ext] schedule send failed for pending %s: %s", pending_id, exc)
    except Exception as exc:
        logger.warning("[owner-ext] post_tool_call send failed for pending %s: %s", pending_id, exc)
