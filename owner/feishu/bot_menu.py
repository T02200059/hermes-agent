"""Feishu bot menu event handling.

处理 application.bot.menu_v6 事件：三层去重 → 命令解析 → ack → 生成 synthetic event.

去重设计（针对网络卡死/DNS 抽风恢复后连续触发的问题）：

- 第 1 层 ``event_id`` 精确去重 —— 飞书服务器对未 ACK 事件的重投递携带
  相同 event_id，确定性重复，直接丢弃（误杀率为零）。
- 第 2 层 in-flight 合并 —— 同一 (open_id, event_key) 的上一次点击尚未
  生效期间（ack 网络挂起、排队等 per-chat 锁、DNS 卡死等），后续同类点击
  合并丢弃；超过 PENDING_MAX_AGE 判定 pipeline 疑似卡死，强制放行并记
  ERROR 日志（兼作卡死探测器）。
- 第 3 层到达间隔 TTL —— 防手抖双击。

可移除性：删除此文件后，bot menu 事件无响应（不崩溃）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# ---- 三层去重配置 ----
# 第 1 层：event_id 精确去重 TTL（防飞书重投递，可放宽，无误杀风险）
_BOT_MENU_EVENT_ID_TTL_SECONDS = 600.0
# 第 2 层：in-flight 合并窗口上限。超过该时长仍 PENDING → pipeline 疑似
# 卡死（如 DNS 抽风挂起网络 I/O）：放行新点击并记 ERROR 日志定位卡死起点
_BOT_MENU_PENDING_MAX_AGE_SECONDS = 120.0
# 第 3 层：到达间隔 TTL（防手抖双击）
_BOT_MENU_DEDUP_TTL_SECONDS = 3.0
_BOT_MENU_DEDUP_MAX_SIZE = 512
_BOT_MENU_DEDUP_EVICT_FLOOR = 400
_BOT_MENU_DEDUP_PRUNE_AGE = 60.0
# ack/直发消息的网络超时：DNS 抽风时 _send_raw_message 可能长时间挂起，
# 超时后放弃该条消息但继续路由命令（命令处理在本地，不依赖网络）
_BOT_MENU_SEND_TIMEOUT_SECONDS = 15.0

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


@dataclass
class _BotMenuEntry:
    """(open_id, event_key) 维度的去重状态机.

    IDLE (in_flight_since=None) --点击--> PENDING --处理完成--> IDLE.
    PENDING 期间同 key 再点击 → coalesced 计数合并、丢弃。
    """

    last_arrival: float = 0.0
    in_flight_since: Optional[float] = None
    coalesced: int = 0


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


def _cleanup_dedup_cache(
    dedup_cache: Dict[Tuple[str, str], _BotMenuEntry],
    event_ids: Dict[str, float],
) -> None:
    """Lazy cleanup: prune old entries and cap the cache sizes.

    注意：PENDING 中的条目（in_flight_since 非 None）不参与过期清理和
    容量驱逐 —— 否则 pipeline 卡死超过 prune age 后条目被清掉，第 2 层
    去重失效，恢复后又回到连发。
    """
    now = time.time()
    expired = [
        k
        for k, e in dedup_cache.items()
        if e.in_flight_since is None
        and now - e.last_arrival > _BOT_MENU_DEDUP_PRUNE_AGE
    ]
    for k in expired:
        dedup_cache.pop(k, None)
    if len(dedup_cache) > _BOT_MENU_DEDUP_MAX_SIZE:
        # 仅驱逐 IDLE 且最旧的条目
        idle_items = [
            (k, e.last_arrival)
            for k, e in dedup_cache.items()
            if e.in_flight_since is None
        ]
        idle_items.sort(key=lambda x: x[1])
        evict_count = len(dedup_cache) - _BOT_MENU_DEDUP_EVICT_FLOOR
        for k, _ in idle_items[:evict_count]:
            dedup_cache.pop(k, None)

    expired_ids = [
        eid for eid, ts in event_ids.items()
        if now - ts > _BOT_MENU_EVENT_ID_TTL_SECONDS
    ]
    for eid in expired_ids:
        event_ids.pop(eid, None)
    if len(event_ids) > _BOT_MENU_DEDUP_MAX_SIZE:
        sorted_ids = sorted(event_ids.items(), key=lambda x: x[1])
        evict_count = len(sorted_ids) - _BOT_MENU_DEDUP_EVICT_FLOOR
        for eid, _ in sorted_ids[:evict_count]:
            event_ids.pop(eid, None)


def admit_bot_menu_event(
    dedup_cache: Dict[Tuple[str, str], _BotMenuEntry],
    event_ids: Dict[str, float],
    lock: threading.Lock,
    open_id: str,
    event_key: str,
    event_id: str,
) -> Tuple[str, Optional[float]]:
    """三层去重准入判定.

    Returns:
        (verdict, admit_ts): verdict 为
        ``ADMIT`` | ``DUPLICATE_EVENT_ID`` | ``IN_FLIGHT`` | ``TTL`` 之一；
        admit_ts 仅在 ADMIT 时非 None，是该次点击占据 PENDING 的时间戳，
        需原样传给 :func:`release_bot_menu_event` 做属主校验。
    """
    now = time.time()
    with lock:
        # 第 1 层：event_id 精确去重 —— 飞书服务器对未 ACK 事件的
        # 重投递携带相同 event_id，确定性重复，直接丢弃
        if event_id:
            if event_id in event_ids:
                return "DUPLICATE_EVENT_ID", None
            event_ids[event_id] = now

        entry = dedup_cache.get((open_id, event_key))
        if entry is None:
            entry = _BotMenuEntry()
            dedup_cache[(open_id, event_key)] = entry

        # 第 2 层：in-flight 合并 —— 上一次同 key 点击尚未生效期间
        # （ack 网络挂起 / 排队等 per-chat 锁 / DNS 卡死），后续点击合并
        if entry.in_flight_since is not None:
            age = now - entry.in_flight_since
            if age < _BOT_MENU_PENDING_MAX_AGE_SECONDS:
                entry.coalesced += 1
                return "IN_FLIGHT", None
            # 超龄：pipeline 疑似卡死 → 强制放行并留证据
            logger.error(
                "[Feishu] bot_menu key=%s open_id=%s PENDING %.0fs (>%.0fs), "
                "coalesced=%d — pipeline/network stall suspected, forcing admit",
                event_key,
                open_id,
                age,
                _BOT_MENU_PENDING_MAX_AGE_SECONDS,
                entry.coalesced,
            )
            entry.in_flight_since = None
            entry.coalesced = 0

        # 第 3 层：到达间隔 TTL —— 防手抖双击
        if now - entry.last_arrival < _BOT_MENU_DEDUP_TTL_SECONDS:
            return "TTL", None

        entry.last_arrival = now
        entry.in_flight_since = now
        entry.coalesced = 0
        _cleanup_dedup_cache(dedup_cache, event_ids)
        return "ADMIT", now


def release_bot_menu_event(
    dedup_cache: Dict[Tuple[str, str], _BotMenuEntry],
    lock: threading.Lock,
    open_id: str,
    event_key: str,
    admit_ts: Optional[float],
) -> None:
    """处理结束（含异常 / early-return）后释放 in-flight 状态.

    属主校验：仅当条目当前 PENDING 时间戳等于本次 admit_ts 时才释放，
    避免超龄强制放行后，旧协程的 finally 误释放新点击占据的 PENDING。
    """
    with lock:
        entry = dedup_cache.get((open_id, event_key))
        if entry is None or entry.in_flight_since != admit_ts:
            return
        coalesced = entry.coalesced
        entry.in_flight_since = None
        entry.coalesced = 0
    if coalesced:
        logger.info(
            "[Feishu] bot_menu key=%s open_id=%s 合并了 %d 次排队期间的重复点击",
            event_key,
            open_id,
            coalesced,
        )


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


async def _send_with_timeout(
    adapter: Any,
    *,
    label: str,
    chat_id: str,
    msg_type: str,
    payload: str,
) -> None:
    """带超时的直发（不抛异常）：DNS 抽风时 _send_raw_message 可能长时间
    挂起，超时或失败仅记日志，不阻塞后续命令路由（命令处理在本地）。"""
    try:
        await asyncio.wait_for(
            adapter._send_raw_message(
                chat_id=chat_id,
                msg_type=msg_type,
                payload=payload,
                reply_to=None,
                metadata=None,
            ),
            timeout=_BOT_MENU_SEND_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "[Feishu] bot menu %s to %s timed out after %.0fs (network/DNS stall?)",
            label,
            chat_id,
            _BOT_MENU_SEND_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        logger.warning(
            "[Feishu] bot menu %s to %s failed: %s", label, chat_id, exc
        )


async def handle_bot_menu_event(adapter: Any, data: Any) -> None:
    """Route a bot menu click as a synthetic COMMAND or fallback TEXT event."""
    from owner.feishu.user_store import get_user_store

    event = getattr(data, "event", None)
    operator = getattr(event, "operator", None)
    operator_id_obj = getattr(operator, "operator_id", None)
    open_id = str(getattr(operator_id_obj, "open_id", "") or "")
    event_key = str(getattr(event, "event_key", "") or "")
    if not open_id or not event_key:
        logger.warning("[Feishu] Bot menu event missing open_id or event_key")
        return

    header = getattr(data, "header", None)
    event_id = str(getattr(header, "event_id", "") or "")

    verdict, admit_ts = admit_bot_menu_event(
        adapter._bot_menu_dedup,
        adapter._bot_menu_event_ids,
        adapter._bot_menu_dedup_lock,
        open_id,
        event_key,
        event_id,
    )
    if verdict != "ADMIT":
        logger.info(
            "[Feishu] Dropping bot menu event for %s key=%s reason=%s event_id=%s",
            open_id,
            event_key,
            verdict,
            event_id or "-",
        )
        return

    try:
        await _process_bot_menu_click(adapter, data, open_id, event_key)
    finally:
        # 覆盖所有 early-return / 异常路径，防止 PENDING 永久占位
        release_bot_menu_event(
            adapter._bot_menu_dedup,
            adapter._bot_menu_dedup_lock,
            open_id,
            event_key,
            admit_ts,
        )


async def _process_bot_menu_click(
    adapter: Any, data: Any, open_id: str, event_key: str
) -> None:
    """bot menu 点击的实际处理（在 in-flight PENDING 保护下执行）."""
    from owner.feishu.user_store import get_user_store
    from gateway.platforms.base import MessageEvent, MessageType

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
        await _send_with_timeout(
            adapter, label="fallback", chat_id=open_id, msg_type="text", payload=payload
        )
        return

    ack_text = resolve_bot_menu_ack(event_key)
    if ack_text:
        await _send_with_timeout(
            adapter,
            label="ack",
            chat_id=chat_id,
            msg_type="text",
            payload=json.dumps({"text": ack_text}, ensure_ascii=False),
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
            await asyncio.wait_for(
                adapter.send_guide_card(chat_id=chat_id, source=_source),
                timeout=_BOT_MENU_SEND_TIMEOUT_SECONDS,
            )
            logger.info("[Feishu] Guide card sent directly for %s", open_id)
        except asyncio.TimeoutError:
            logger.warning(
                "[Feishu] Guide card to %s timed out after %.0fs (network/DNS stall?)",
                chat_id,
                _BOT_MENU_SEND_TIMEOUT_SECONDS,
            )
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
