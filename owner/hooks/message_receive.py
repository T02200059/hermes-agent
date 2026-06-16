"""message:receive hook orchestration for gateway/run.py.

Emit → collect hook results → deliver extra_context to chat → inject into
LLM prompt. Supports:

- Plain text delivery (any platform)
- Feishu card delivery (when hook returns ``feishu_card``)
- Card cache warming (when hook returns ``feishu_card_cache``)
- Configurable delivery gating (global / per-platform / per-chat)

Thin glue in gateway/run.py calls ``apply_message_receive_hooks()`` with
the runner's hooks + adapters + config.

可移除性：删除此文件后 gateway/run.py 的 try/except ImportError fallback
会跳过 hook 注入，功能退级但不崩溃。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Sentinel wrappers ───────────────────────────────────────────────────────
# Hook-injected context is wrapped in HTML comments so the LLM sees it
# but history persistence strips it.
_HOOK_CTX_START = "<!-- HERMES_HOOK_CONTEXT_START -->"
_HOOK_CTX_END = "<!-- HERMES_HOOK_CONTEXT_END -->"


async def apply_message_receive_hooks(
    *,
    hooks: Any,
    adapters: Dict[Any, Any],
    source: Any,
    session_id: str,
    message_text: str,
) -> str:
    """Emit message:receive lifecycle hooks and process results.

    Returns:
        Updated message_text (with extra_context appended for LLM injection).

    Side effects (when allowed by config):
        - Echoes extra_context as a chat message via adapter.send()
        - On Feishu: sends feishu_card via adapter.send_card()
        - Warms card cache when hook returns feishu_card_cache
    """
    try:
        from owner.hooks.display_config import should_deliver
        _should_deliver = should_deliver
    except ImportError:
        _should_deliver = None  # fallback: always deliver

    # Determine platform slug
    platform_value = ""
    platform_enum = getattr(source, "platform", None)
    if platform_enum is not None:
        platform_value = str(getattr(platform_enum, "value", "") or "")

    try:
        results = await hooks.emit_collect(
            "message:receive",
            {
                "platform": platform_value,
                "user_id": getattr(source, "user_id", None),
                "session_id": session_id,
                "message": message_text,
            },
        )
    except Exception as exc:
        logger.warning("message:receive hook emit failed: %s", exc)
        return message_text

    if not results:
        return message_text

    # Collect hook results
    extra_parts: List[str] = []
    feishu_card: Any = None
    feishu_card_cache: Any = None
    for result in results:
        if isinstance(result, dict) and "extra_context" in result:
            extra_parts.append(result["extra_context"])
        if isinstance(result, dict) and "feishu_card" in result:
            feishu_card = result["feishu_card"]
        if isinstance(result, dict) and "feishu_card_cache" in result:
            feishu_card_cache = result["feishu_card_cache"]

    if not extra_parts:
        return message_text

    extra_context_raw = "\n\n".join(extra_parts)

    # Deliver to chat if allowed by config
    chat_id = getattr(source, "chat_id", "") or ""
    if _should_deliver is not None and chat_id:
        delivery_allowed, skip_reason = _should_deliver(platform_value, chat_id)
    else:
        delivery_allowed, skip_reason = True, ""

    if delivery_allowed:
        try:
            adapter = adapters.get(platform_enum)
            # [owner] send_only mode: if platform is api_server but feishu adapter is available,
            # use feishu adapter for sending cards
            if platform_value == "api_server" and feishu_card:
                logger.debug("[message_receive] send_only mode: attempting to use feishu adapter for card")
                from gateway.platforms.base import Platform
                feishu_adapter = adapters.get(Platform.FEISHU)
                if feishu_adapter and hasattr(feishu_adapter, "send_card"):
                    adapter = feishu_adapter
                    platform_value = "feishu"  # Override for card sending

            if adapter and chat_id:
                logger.debug(
                    "[message_receive] sending to chat_id=%s, platform=%s, has_feishu_card=%s",
                    chat_id, platform_value, bool(feishu_card),
                )
                if feishu_card and hasattr(adapter, "send_card"):
                    # Feishu card path
                    if feishu_card_cache and hasattr(adapter, "warm_recall_cache"):
                        adapter.warm_recall_cache(
                            feishu_card_cache.get("recall_id", ""),
                            feishu_card_cache,
                        )
                    # DM routing needs explicit chat_type + open_id metadata
                    chat_type = getattr(source, "chat_type", None)
                    card_metadata = {
                        "chat_type": chat_type,
                        "open_id": (
                            getattr(source, "open_id", None)
                            or (
                                getattr(source, "user_id", None)
                                if str(chat_type or "").lower() in {"dm", "p2p"}
                                else None
                            )
                        ),
                    }
                    logger.debug("[message_receive] calling send_card for chat_id=%s", chat_id)
                    await adapter.send_card(chat_id, feishu_card, metadata=card_metadata)
                else:
                    await adapter.send(chat_id, extra_context_raw)
        except Exception as send_err:
            logger.warning(
                "hook recall delivery to %s failed: %s",
                platform_value,
                send_err,
            )
    elif skip_reason:
        logger.debug(
            "hook recall delivery skipped: %s (platform=%s chat_id=%s)",
            skip_reason,
            platform_value,
            chat_id,
        )

    # Append to LLM message (always — delivery gating only affects user-visible echo)
    return message_text + "\n\n" + extra_context_raw
