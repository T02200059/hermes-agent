"""Plugin: owner-memory-feishu-bridge.

Auto-popup Feishu interactive approval card when
``tools/memory_tool.py:_apply_write_gate`` *stages* a memory write on a Feishu
gateway session. The card mirrors the established owner Feishu card pattern
(``owner/feishu/model_picker.py`` / ``clarify_card.py``) — purple header, two
buttons (✅ Approve / 🟥 Deny), and an inline card update after click (green /
red header, buttons removed, title renamed, original proposal markdown
preserved).

How it works
-------------

1. **Capture the gateway reference** (``pre_gateway_dispatch`` hook): every
   inbound user message fires this hook with ``gateway=<GatewayRunner>``
   (see ``gateway/run.py``). The plugin caches a weak reference to the Feishu
   adapter so subsequent ``post_tool_call`` fires don't have to re-resolve.

2. **Detect staged memory writes** (``post_tool_call`` hook): every tool
   completion fires this hook with ``tool_name``, ``args``, ``result``, and
   ``session_id``. The plugin:

     * Skips immediately when ``tool_name != "memory"``.
     * Parses ``result`` as JSON and skips when ``staged`` is not truthy / no
       ``pending_id`` is present (non-staged writes flow through unchanged).
     * Extracts the Feishu ``chat_id`` from ``session_id`` (the gateway
       encodes the platform in the colon-delimited session key — see
       ``owner/feishu/memory_approval.py:extract_feishu_chat_id``).
     * Builds a small summary + content preview from the original ``args``
       the agent passed to memory tool (``action`` / ``target`` / ``content``
       / ``old_text`` / ``operations``) and calls
       ``owner.feishu.memory_approval.send_approval_card``.

3. **Click handling** is performed by
   ``owner.feishu.memory_approval.handle_card_click``, which is dispatched by
   the 4-line ``adapter._dispatch_card_action`` branch added to
   ``plugins/platforms/feishu/adapter.py`` — that branch is the only upstream
   surface this plugin needs (the lark_oapi WebSocket callback path lands
   directly in the adapter; there is no plugin hook for raw card-action
   triggers).

Design constraints
-------------------

* **Zero upstream surface on the send side.** This plugin uses two generic
  hooks (``pre_gateway_dispatch`` + ``post_tool_call``) that already exist.
  No upstream code is touched to send the card — only the 4-line dispatch
  branch in ``adapter.py`` for click handling (matches the established
  pattern used by ``claify`` / ``model_picker`` / ``resume`` cards).

* **Fail-open.** Every path is best-effort: card-sending failure, gateway
  adapter missing, chat_id not parseable, etc., all log a warning and skip.
  The staged write is still on disk under
  ``<HERMES_HOME>/pending/memory/<pending_id>.json`` and can be reviewed
  manually via ``/memory pending``.

* **Observer semantics preserved.** The ``post_tool_call`` hook contract is
  documented as observer-only (``docs/observability/README.md``). We do
  NOT transform the tool result or block the agent — we just emit a
  side-effect card and return ``None``.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# Process-global weak references to the gateway runner + Feishu adapter,
# populated lazily by the ``pre_gateway_dispatch`` hook. Guards make this
# safe under multi-threaded tool dispatch and the multi-profile container
# gateway (which has several Feishu adapters under
# ``gateway._profile_containers``; we re-pick on every dispatch so a
# sub-profile adapter overrides the default).
_GATEWAY_REF: Any = None
_FEISHU_ADAPTER: Any = None
_REF_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Hook registrations
# ---------------------------------------------------------------------------

def register(ctx):  # type: ignore[no-untyped-def]
    """Plugin entry point — wire the two hooks we need."""
    ctx.register_hook("pre_gateway_dispatch", _on_pre_gateway_dispatch)
    ctx.register_hook("post_tool_call", _on_post_tool_call)


def _on_pre_gateway_dispatch(**kwargs: Any) -> None:
    """Cache the gateway reference + Feishu adapter on each inbound message.

    The hook fires on every user-originated ``MessageEvent``; the cache
    refresh is cheap and survives a sub-profile adapter hot-swap. We don't
    block or rewrite the message — return ``None`` (= "allow").
    """
    global _GATEWAY_REF, _FEISHU_ADAPTER
    gateway = kwargs.get("gateway")
    if gateway is None:
        return
    try:
        adapters = getattr(gateway, "adapters", {}) or {}
        # Lazy import so the plugin can be loaded before the gateway module
        # finishes initialising (pathological timing).
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
        logger.debug(
            "[owner-memory-feishu-bridge] pre_gateway_dispatch cache failed: %s",
            exc,
        )


def _on_post_tool_call(**kwargs: Any) -> None:
    """Detect staged memory writes on Feishu and send an approval card.

    Observer semantics: returns ``None`` (does not transform the tool result).
    Card send failures are logged and swallowed — the staged write is on disk
    and can still be reviewed via ``/memory pending``.
    """
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

    # Bail out unless this is a *staged* result (write_approval gate engaged).
    if not parsed.get("staged"):
        return
    pending_id = parsed.get("pending_id")
    if not pending_id:
        return

    session_id = str(kwargs.get("session_id") or "")
    args = kwargs.get("args") or {}

    # Fast adapter check (avoid parsing session_id if no adapter yet).
    with _REF_LOCK:
        adapter = _FEISHU_ADAPTER
    if adapter is None:
        # No Feishu adapter in this gateway yet — give up silently.
        return

    # Extract chat_id from session_id (only proceeds when platform=feishu).
    try:
        from owner.feishu.memory_approval import (
            build_preview, extract_feishu_chat_id, send_approval_card,
        )
    except Exception as exc:
        logger.debug(
            "[owner-memory-feishu-bridge] owner.feishu.memory_approval unavailable: %s",
            exc,
        )
        return

    chat_id = extract_feishu_chat_id(session_id)
    if not chat_id:
        return

    summary, content_preview = build_preview(args)
    if not summary:
        # Don't pop a card for an entry we can't describe — the user can still
        # see it in /memory pending.
        return

    # Schedule the async send on the adapter's event loop (same pattern as
    # the model_picker's _route_picker_command). Failures are swallowed
    # inside send_approval_card.
    try:
        loop = getattr(adapter, "_loop", None)
        if loop is None:
            # Fallback to the gateway's loop if the adapter doesn't expose one.
            gw = _GATEWAY_REF
            loop = getattr(gw, "_loop", None) if gw is not None else None
        if loop is None or getattr(loop, "is_closed", lambda: False)():
            logger.warning(
                "[owner-memory-feishu-bridge] no live loop; skipping card for "
                "pending %s", pending_id,
            )
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

        # Use the adapter's own thread-safe scheduler so we don't need to
        # roll call_soon_threadsafe ourselves. Falls back to asyncio.run_coroutine_threadsafe
        # which is the standard pattern.
        try:
            submit = getattr(adapter, "_submit_on_loop", None)
            if callable(submit):
                submit(loop, _send())
            else:
                asyncio.run_coroutine_threadsafe(_send(), loop)
        except Exception as exc:
            logger.warning(
                "[owner-memory-feishu-bridge] schedule send failed for "
                "pending %s: %s", pending_id, exc,
            )
    except Exception as exc:
        logger.warning(
            "[owner-memory-feishu-bridge] post_tool_call send failed for "
            "pending %s: %s", pending_id, exc,
        )
# Preview extraction lives in owner.feishu.memory_approval.build_preview()
# so tests can import it without needing the plugin on PYTHONPATH.