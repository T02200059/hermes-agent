"""Feishu memory write-approval card bridge.

Auto-popup approval card when memory tool stages a write on Feishu.
Uses pre_gateway_dispatch + post_tool_call hooks (zero upstream surface).
See owner/feishu/memory_approval.py for card construction + click routing.

Also transforms the memory tool result message on Feishu to indicate the
approval card is being sent (via transform_tool_result hook). On non-Feishu
platforms the original upstream message is preserved unchanged.

The transform does NOT gate on ``_SENT_CARD_IDS``: the card is dispatched
asynchronously from ``_on_post_tool_call`` and may fail in flight (network
error, API rejection). Marking ``_SENT_CARD_IDS`` immediately after scheduling
would let the transform report a completed send that never landed. Instead
the transform keys on "is this a Feishu session with a staged memory write?"
and uses progressive tense ("being sent"), which stays accurate whether or
not the in-flight card ultimately delivers.

Hardening notes (2026-07-28 regression):
  Silent early-returns (adapter missing / chat_id unparseable / empty
  summary / submit returning False without checking) left staged writes
  with no card and zero log lines. Every skip path now logs at WARNING,
  adapter is re-resolved from the gateway at send time, chat_id falls
  back to agent-level chat_id when the session key is unparseable, empty
  summary no longer aborts, and ``_submit_on_loop`` False is treated as
  a failed schedule (no false SENT mark).
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any, Optional, Set

logger = logging.getLogger(__name__)

# Process-global weak references to the gateway runner + Feishu adapter,
# populated lazily by the ``pre_gateway_dispatch`` hook.
_GATEWAY_REF: Any = None
_FEISHU_ADAPTER: Any = None
_REF_LOCK = threading.Lock()

# Pending IDs for which an approval card dispatch was *submitted* to the Feishu
# event loop on Feishu. Observational only — does NOT prove delivery (the async
# task may still fail). transform_tool_result deliberately ignores this set (see
# module docstring) and keys on "Feishu session + staged write" instead.
_SENT_CARD_IDS: Set[str] = set()
_SENT_CARD_LOCK = threading.Lock()


def register_hooks(ctx: Any) -> None:
    """Register hooks for memory approval cards + result message transform."""
    ctx.register_hook("pre_gateway_dispatch", _on_pre_gateway_dispatch)
    ctx.register_hook("post_tool_call", _on_post_tool_call)
    ctx.register_hook("transform_tool_result", _on_transform_tool_result)


def _resolve_feishu_adapter(gateway: Any = None) -> Any:
    """Best-effort resolve the live Feishu adapter.

    Prefers the cached ``_FEISHU_ADAPTER``. When cache is empty (or the
    gateway was restarted without a subsequent inbound message), re-looks
    up from ``gateway.adapters`` using both the Platform enum and the
    plain ``"feishu"`` string key so multi-import / enum-identity quirks
    cannot leave the cache stuck on None forever.
    """
    global _FEISHU_ADAPTER, _GATEWAY_REF
    with _REF_LOCK:
        cached = _FEISHU_ADAPTER
        gw = gateway if gateway is not None else _GATEWAY_REF
    if cached is not None:
        return cached
    if gw is None:
        return None
    adapters = getattr(gw, "adapters", {}) or {}
    adapter = None
    try:
        from gateway.config import Platform
        adapter = adapters.get(Platform.FEISHU)
    except Exception:
        adapter = None
    if adapter is None:
        adapter = adapters.get("feishu")
    if adapter is not None:
        with _REF_LOCK:
            # Only write if still empty — avoid stomping a fresher cache.
            if _FEISHU_ADAPTER is None:
                _FEISHU_ADAPTER = adapter
            if _GATEWAY_REF is None:
                _GATEWAY_REF = gw
    return adapter


def _resolve_live_loop(adapter: Any) -> Any:
    """Pick a live event loop for card dispatch.

    Prefer ``adapter._loop`` (gateway main loop). Fall back to
    ``adapter._ws_thread_loop`` (Feishu WS thread) then
    ``gateway._loop``. Reject closed loops.
    """
    candidates = []
    if adapter is not None:
        candidates.append(getattr(adapter, "_loop", None))
        candidates.append(getattr(adapter, "_ws_thread_loop", None))
    with _REF_LOCK:
        gw = _GATEWAY_REF
    if gw is not None:
        candidates.append(getattr(gw, "_loop", None))
    for loop in candidates:
        if loop is None:
            continue
        try:
            if getattr(loop, "is_closed", lambda: False)():
                continue
        except Exception:
            continue
        return loop
    return None


def _resolve_chat_id(
    gateway_session_key: str,
    session_id: str,
    *,
    platform: str = "",
    chat_id_hint: str = "",
) -> str:
    """Derive Feishu chat_id from session keys, with agent-level fallback.

    Order:
      1. ``gateway_session_key`` (agent:main:feishu:dm:<chat_id>)
      2. ``session_id`` (legacy gateway-shaped ids)
      3. explicit ``chat_id_hint`` when platform is feishu (agent._chat_id)
    """
    try:
        from owner.feishu.memory_approval import extract_feishu_chat_id
    except Exception as exc:
        logger.warning(
            "[memory-feishu-bridge] extract_feishu_chat_id unavailable: %s", exc,
        )
        return ""

    chat_id = extract_feishu_chat_id(gateway_session_key)
    if chat_id:
        return chat_id
    chat_id = extract_feishu_chat_id(session_id)
    if chat_id:
        return chat_id

    # Agent-level fallback: gateway always sets agent._chat_id for Feishu
    # sessions. When the session key is a bare timestamp id (or missing)
    # we still can address the card if the platform is feishu.
    platform_l = (platform or "").strip().lower()
    hint = (chat_id_hint or "").strip()
    if hint and platform_l in {"feishu", "lark", ""}:
        # Empty platform: still accept a well-formed Feishu chat_id hint
        # (oc_*) so a partially-populated agent object works.
        if platform_l in {"feishu", "lark"} or hint.startswith("oc_"):
            return hint
    return ""


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
            adapter = None
        if adapter is None:
            adapter = adapters.get("feishu")
        if adapter is None:
            # Don't clobber a previously-good cache when this particular
            # inbound event has no Feishu adapter (e.g. a QQ-only path).
            with _REF_LOCK:
                if _GATEWAY_REF is None:
                    _GATEWAY_REF = gateway
            return
        with _REF_LOCK:
            _GATEWAY_REF = gateway
            _FEISHU_ADAPTER = adapter
    except Exception as exc:
        logger.warning(
            "[memory-feishu-bridge] pre_gateway_dispatch cache failed: %s", exc,
        )


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
        logger.warning(
            "[memory-feishu-bridge] staged memory result missing pending_id; skip card",
        )
        return

    session_id = str(kwargs.get("session_id") or "")
    gateway_session_key = str(kwargs.get("gateway_session_key") or "")
    # [owner] agent-level fallbacks for when session keys are unparseable
    platform = str(kwargs.get("platform") or "")
    chat_id_hint = str(kwargs.get("chat_id") or "")
    args = kwargs.get("args") or {}
    if not isinstance(args, dict):
        args = {}

    adapter = _resolve_feishu_adapter()
    if adapter is None:
        logger.warning(
            "[memory-feishu-bridge] no Feishu adapter cached; skip card for pending %s "
            "(gateway_session_key=%r session_id=%r)",
            pending_id, gateway_session_key, session_id,
        )
        return

    try:
        from owner.feishu.memory_approval import (
            build_preview, send_approval_card,
        )
    except Exception as exc:
        logger.warning(
            "[memory-feishu-bridge] owner.feishu.memory_approval unavailable: %s", exc,
        )
        return

    chat_id = _resolve_chat_id(
        gateway_session_key,
        session_id,
        platform=platform,
        chat_id_hint=chat_id_hint,
    )
    if not chat_id:
        logger.warning(
            "[memory-feishu-bridge] cannot derive Feishu chat_id; skip card for pending %s "
            "(gateway_session_key=%r session_id=%r platform=%r chat_id_hint=%r)",
            pending_id, gateway_session_key, session_id, platform, chat_id_hint,
        )
        return

    summary, content_preview = build_preview(args)
    if not summary:
        # Do NOT abort: staged writes with empty/unknown args (or i18n
        # failure) must still produce a card. Fall back to a generic
        # summary so the user can still approve/deny via pending_id.
        summary = f"memory write staged (pending_id={pending_id})"
        if not content_preview:
            content_preview = str(args)[:400] if args else "(no preview)"
        logger.warning(
            "[memory-feishu-bridge] empty preview for pending %s; using fallback summary "
            "(args_keys=%s)",
            pending_id, sorted(args.keys()) if isinstance(args, dict) else type(args),
        )

    try:
        loop = _resolve_live_loop(adapter)
        if loop is None:
            logger.warning(
                "[memory-feishu-bridge] no live loop; skipping card for pending %s",
                pending_id,
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
                # Prefer gateway_session_key: agent:main:feishu:dm:<chat_id>.
                session_id=gateway_session_key or session_id,
            )

        scheduled = False
        try:
            submit = getattr(adapter, "_submit_on_loop", None)
            if callable(submit):
                # _submit_on_loop returns False when safe_schedule_threadsafe
                # fails (closed loop, shutdown race). Treat False as failure
                # — previously the return was ignored, so cards silently
                # vanished while _SENT_CARD_IDS still got the mark.
                result = submit(loop, _send())
                if result is False:
                    logger.warning(
                        "[memory-feishu-bridge] _submit_on_loop returned False for pending %s; "
                        "trying run_coroutine_threadsafe fallback",
                        pending_id,
                    )
                    try:
                        asyncio.run_coroutine_threadsafe(_send(), loop)
                        scheduled = True
                    except Exception as fallback_exc:
                        logger.warning(
                            "[memory-feishu-bridge] fallback schedule failed for pending %s: %s",
                            pending_id, fallback_exc,
                        )
                        return
                else:
                    # True, or a Future, or None-from-legacy-stubs that still
                    # scheduled — any non-False means "handed to the loop".
                    scheduled = True
            else:
                asyncio.run_coroutine_threadsafe(_send(), loop)
                scheduled = True
        except Exception as exc:
            logger.warning(
                "[memory-feishu-bridge] schedule send failed for pending %s: %s",
                pending_id, exc,
            )
            return  # card not sent — don't mark

        if not scheduled:
            return

        # Record that a dispatch was *submitted* for this pending_id.
        # Observational only — transform_tool_result ignores this set and
        # keys on "Feishu session + staged write" instead, because this mark
        # proves the coroutine was handed to the loop, not that it delivered.
        with _SENT_CARD_LOCK:
            _SENT_CARD_IDS.add(str(pending_id))
        logger.info(
            "[memory-feishu-bridge] card dispatch submitted pending_id=%s chat_id=%s",
            pending_id, chat_id,
        )
    except Exception as exc:
        logger.warning(
            "[memory-feishu-bridge] post_tool_call send failed for pending %s: %s",
            pending_id, exc,
        )


def _on_transform_tool_result(**kwargs: Any) -> Optional[str]:
    """On Feishu, rewrite a staged memory result to mention the approval card.

    The upstream message says "Not yet saved - review with /memory pending",
    which is a CLI-only affordance. On Feishu an interactive card is being
    dispatched (by ``_on_post_tool_call``), so the agent is told about the
    in-flight card instead of the CLI-only ``/memory pending`` affordance.

    Detection keys on "is this a Feishu session with a staged memory write?"
    — NOT on ``_SENT_CARD_IDS``. The card is dispatched asynchronously and may
    fail in flight; progressive tense ("being sent") stays accurate whether or
    not the card ultimately lands. Relying on a post-dispatch mark would make
    the message claim a completed send the agent cannot verify.

    Returns ``None`` (no transformation) for:
      * non-memory tools
      * non-staged results
      * non-Feishu sessions (no Feishu chat id derivable from the session key
        or agent-level chat_id hint)
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

    gateway_session_key = str(kwargs.get("gateway_session_key") or "")
    session_id = str(kwargs.get("session_id") or "")
    platform = str(kwargs.get("platform") or "")
    chat_id_hint = str(kwargs.get("chat_id") or "")
    chat_id = _resolve_chat_id(
        gateway_session_key,
        session_id,
        platform=platform,
        chat_id_hint=chat_id_hint,
    )
    if not chat_id:
        return None

    parsed["message"] = (
        "Staged for approval (memory.write_approval is on). "
        "Approval card being sent — click ✅ to save or 🟥 to discard."
    )
    return json.dumps(parsed, ensure_ascii=False)
