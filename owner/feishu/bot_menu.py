"""Feishu bot menu event handling.

处理 application.bot.menu_v6 事件：去重 → 命令解析 → ack → 生成 synthetic event.

可移除性：删除此文件后，bot menu 事件无响应（不崩溃）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

_BOT_MENU_DEDUP_TTL_SECONDS = 3.0
_BOT_MENU_DEDUP_MAX_SIZE = 512
_BOT_MENU_DEDUP_EVICT_FLOOR = 400
_BOT_MENU_DEDUP_PRUNE_AGE = 60.0

BUILTIN_BOT_MENU: Dict[str, str] = {
    "new": "/new",
    "status": "/status",
    "stop": "/stop",
    "reasoning_off": "/reasoning off --global",
    "reasoning_medium": "/reasoning medium --global",
    "reasoning_high": "/reasoning high --global",
    "model_flash": "/model deepseek-v4-flash --provider damodel",
    "model_pro": "/model deepseek-v4-pro --provider damodel",
    "model_max": "/model qwen3.7-max --provider damodel",
}


def _load_patch_config_safe() -> Dict[str, Any]:
    """Fail-open loader for ``~/.hermes/patch.yaml`` ``owner`` section."""
    try:
        from owner.patch_config import load_patch_config

        return load_patch_config()
    except Exception:
        return {}


def resolve_bot_menu_command(event_key: str) -> Optional[str]:
    """Look up event_key → command string in patch.yaml (owner.feishu.bot_menu).

    Falls back to hardcoded built-in mappings when config is unavailable.

    .. note::
        The returned string is **not** restricted to slash commands.
        It can be an arbitrary prompt (e.g. Chinese text) that is
        injected as a synthetic user message. Slash-command parsing
        happens later in the pipeline; this method only resolves the
        raw text for the menu key.
    """
    if not event_key:
        return None

    patch = _load_patch_config_safe()
    mapping = patch.get("feishu", {}).get("bot_menu", {})
    cmd = mapping.get(event_key)
    if isinstance(cmd, str) and cmd.strip():
        return cmd

    cmd = BUILTIN_BOT_MENU.get(event_key)
    if cmd:
        logger.info(
            "[Feishu] Bot menu event_key=%r resolved via built-in mapping",
            event_key,
        )
    return cmd


def _cleanup_dedup_cache(dedup_cache: Dict[Tuple[str, str], float]) -> None:
    """Lazy cleanup: prune old entries and cap the cache size."""
    now = time.time()
    expired = [
        k for k, ts in dedup_cache.items() if now - ts > _BOT_MENU_DEDUP_PRUNE_AGE
    ]
    for k in expired:
        dedup_cache.pop(k, None)
    if len(dedup_cache) > _BOT_MENU_DEDUP_MAX_SIZE:
        sorted_items = sorted(dedup_cache.items(), key=lambda x: x[1])
        evict_count = len(sorted_items) - _BOT_MENU_DEDUP_EVICT_FLOOR
        for k, _ in sorted_items[:evict_count]:
            dedup_cache.pop(k, None)


def is_bot_menu_duplicate(
    dedup_cache: Dict[Tuple[str, str], float],
    lock: threading.Lock,
    open_id: str,
    event_key: str,
) -> bool:
    """Per-user per-key dedup with a short TTL window."""
    dedup_key = (open_id, event_key)
    now = time.time()
    with lock:
        last_seen = dedup_cache.get(dedup_key)
        if last_seen is not None and now - last_seen < _BOT_MENU_DEDUP_TTL_SECONDS:
            return True
        dedup_cache[dedup_key] = now
        _cleanup_dedup_cache(dedup_cache)
        return False


def resolve_bot_menu_ack(event_key: str) -> Optional[str]:
    """Look up ack text for a bot menu event_key from patch.yaml config.

    Returns ``None`` if ack is disabled for this key or globally.
    """
    patch = _load_patch_config_safe()
    dedup_cfg = patch.get("feishu", {}).get("bot_menu_dedup", {})
    if not dedup_cfg.get("enabled", True):
        return None
    per_key = dedup_cfg.get("per_key", {})
    key_cfg = per_key.get(event_key)
    default_ack = dedup_cfg.get("default_ack", "⏳ 已收到…")
    if key_cfg is None:
        return default_ack
    return key_cfg.get("ack", default_ack)


async def handle_bot_menu_event(adapter: Any, data: Any) -> None:
    """Route a bot menu click as a synthetic COMMAND or fallback TEXT event."""
    from owner.feishu.user_store import get_user_store
    from gateway.platforms.base import MessageEvent, MessageType

    event = getattr(data, "event", None)
    operator = getattr(event, "operator", None)
    operator_id_obj = getattr(operator, "operator_id", None)
    open_id = str(getattr(operator_id_obj, "open_id", "") or "")
    event_key = str(getattr(event, "event_key", "") or "")
    if not open_id or not event_key:
        logger.warning("[Feishu] Bot menu event missing open_id or event_key")
        return

    if is_bot_menu_duplicate(
        adapter._bot_menu_dedup, adapter._bot_menu_dedup_lock, open_id, event_key
    ):
        logger.info(
            "[Feishu] Dropping duplicate bot menu event for %s key=%s",
            open_id,
            event_key,
        )
        return

    store = get_user_store(adapter)
    chat_id = store.get_p2p_chat_id(open_id) if store else None
    if not chat_id:
        logger.warning(
            "[Feishu] Bot menu event: no cached chat_id for %s; "
            "sending direct fallback instead of routing to session",
            open_id,
        )
        fallback_text = (
            f'⚠️ 未配置的菜单事件: event_key="{event_key}"\n'
            f"请在 patch.yaml → owner.feishu.bot_menu 中添加映射，\n"
            f'例如: {event_key}: "/help"'
        )
        payload = json.dumps({"text": fallback_text}, ensure_ascii=False)
        try:
            await adapter._send_raw_message(
                chat_id=open_id,
                msg_type="text",
                payload=payload,
                reply_to=None,
                metadata=None,
            )
        except Exception:
            logger.exception("[Feishu] Failed to send bot menu fallback to %s", open_id)
        return

    ack_text = resolve_bot_menu_ack(event_key)
    if ack_text:
        try:
            await adapter._send_raw_message(
                chat_id=chat_id,
                msg_type="text",
                payload=json.dumps({"text": ack_text}, ensure_ascii=False),
                reply_to=None,
                metadata=None,
            )
        except Exception as exc:
            logger.warning(
                "[Feishu] Failed to send bot menu ack to %s: %s", chat_id, exc
            )

    # [owner] feishu_guide: send the interactive card directly after ack,
    # bypassing the message pipeline.  The card is a read-only UI element
    # (queue/steer/goal/subgoal/background picker) — it does not need agent
    # processing, and routing through _handle_message_with_guards would block
    # behind the per-chat lock until the current turn finishes, causing a
    # multi-second delay between the ack and the card appearing.
    if event_key == "feishu_guide":
        try:
            _source = adapter.build_source(
                chat_id=chat_id,
                user_id=open_id,
                user_name="",
                chat_type="p2p",
            )
            await adapter.send_guide_card(chat_id=chat_id, source=_source)
            logger.info("[Feishu] Guide card sent directly for %s", open_id)
        except Exception as exc:
            logger.warning("[Feishu] Failed to send guide card directly: %s", exc)
        return

    command = resolve_bot_menu_command(event_key)
    if command:
        synthetic_text = command
        msg_type = MessageType.COMMAND
        logger.info(
            "[Feishu] Bot menu event_key=%r mapped to command=%r for %s",
            event_key,
            command,
            open_id,
        )
    else:
        synthetic_text = (
            f'⚠️ 未配置的菜单事件: event_key="{event_key}"\n'
            f"请在 patch.yaml → owner.feishu.bot_menu 中添加映射，\n"
            f'例如: {event_key}: "/help"'
        )
        msg_type = MessageType.TEXT
        logger.warning(
            "[Feishu] Unknown bot menu event_key=%r for %s", event_key, open_id
        )

    # Multi-profile routing: bot_menu events arrive only at the main gateway
    # (single WebSocket), so forward the resolved synthetic command to the
    # routed container. Logic lives in owner/feishu/profile_routing.py.
    try:
        from owner.feishu.profile_routing import try_route_bot_menu_command
    except ImportError:
        try_route_bot_menu_command = None  # type: ignore[assignment]

    if try_route_bot_menu_command is not None:
        _routed = await try_route_bot_menu_command(
            adapter,
            chat_id=chat_id,
            open_id=open_id,
            synthetic_text=synthetic_text,
        )
        if _routed:
            return

    # [owner] bot-menu: pre-warm name cache before profile resolve (see owner/feishu/sender_name_helpers.py)
    from owner.feishu.sender_name_helpers import pre_warm_sender_name

    pre_warm_sender_name(adapter, open_id)
    sender_id = SimpleNamespace(open_id=open_id, user_id=None, union_id=None)
    sender_profile = await adapter._resolve_sender_profile(sender_id)
    chat_info = await adapter.get_chat_info(chat_id)
    source = adapter.build_source(
        chat_id=chat_id,
        chat_name=chat_info.get("name") or chat_id or "Feishu Chat",
        chat_type=adapter._resolve_source_chat_type(
            chat_info=chat_info, event_chat_type="p2p"
        ),
        user_id=sender_profile["user_id"],
        user_name=sender_profile["user_name"],
        thread_id=None,
        user_id_alt=sender_profile["user_id_alt"],
    )
    synthetic_event = MessageEvent(
        text=synthetic_text,
        message_type=msg_type,
        source=source,
        raw_message=data,
        message_id=None,
        timestamp=datetime.now(),
    )
    await adapter._handle_message_with_guards(synthetic_event)
