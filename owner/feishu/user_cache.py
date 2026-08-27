"""Feishu user cache — open_id → {display_name, p2p_chat_id, last_seen_at}.

Disk format v2 (``feishu_chat_id_cache.json``):
  {"_version": 2, "users": {"ou_x": {"p2p_chat_id": "...", "display_name": "...", ...}}}

v1 flat ``{open_id: chat_id}`` is migrated on load.

可移除性：删除此文件后，缓存功能降级为无缓存运行（不崩溃）。
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

USER_CACHE_VERSION = 2


class FeishuUserEntry:
    """Single-user cache keyed by open_id."""

    __slots__ = ("display_name", "display_name_expire_at", "p2p_chat_id", "last_seen_at")

    def __init__(self) -> None:
        self.display_name: str = ""
        self.display_name_expire_at: float = 0.0
        self.p2p_chat_id: str = ""
        self.last_seen_at: float = 0.0


def get_user_entry(cache: Dict[str, FeishuUserEntry], open_id: str) -> FeishuUserEntry:
    """Get or create a user cache entry and update ``last_seen_at``."""
    entry = cache.get(open_id)
    if entry is None:
        entry = FeishuUserEntry()
        cache[open_id] = entry
    entry.last_seen_at = time.time()
    return entry


def get_cached_chat_id(
    cache: Dict[str, FeishuUserEntry], open_id: str
) -> Optional[str]:
    """Return cached p2p chat_id for an open_id, or ``None``."""
    entry = cache.get(open_id)
    if entry is None:
        return None
    return entry.p2p_chat_id or None


def get_cached_display_name(
    cache: Dict[str, FeishuUserEntry], open_id: str
) -> Optional[str]:
    """Return cached display_name for open_id, including stale entries.

    On TTL expiry the name is still returned as a stale-but-better-than-raw-id
    fallback. The caller (``_read_ttl_name``) handles hot-cache eviction; this
    function does **not** destructively clear ``display_name`` so the name
    survives across multiple reads within the same process lifetime.
    """
    entry = cache.get(open_id)
    if entry is None:
        return None
    if entry.display_name:
        return entry.display_name
    return None


def set_cached_display_name(
    cache: Dict[str, FeishuUserEntry],
    open_id: str,
    name: str,
    expire_at: float,
) -> None:
    """Persist display_name + TTL on the open_id user record."""
    open_id = (open_id or "").strip()
    if not open_id:
        return
    entry = get_user_entry(cache, open_id)
    entry.display_name = name
    entry.display_name_expire_at = expire_at


def cache_p2p_chat_id(
    cache: Dict[str, FeishuUserEntry],
    open_id: str,
    chat_id: str,
    *,
    debouncer: Optional[ChatIdCacheDebouncer] = None,
) -> bool:
    """Persist open_id → p2p chat_id when it changes. Returns True if updated."""
    open_id = (open_id or "").strip()
    chat_id = (chat_id or "").strip()
    if not open_id or not chat_id:
        return False
    entry = get_user_entry(cache, open_id)
    if entry.p2p_chat_id == chat_id:
        return False
    entry.p2p_chat_id = chat_id
    if debouncer is not None:
        debouncer.mark_dirty()
    return True


def _entry_to_dict(entry: FeishuUserEntry) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if entry.p2p_chat_id:
        payload["p2p_chat_id"] = entry.p2p_chat_id
    if entry.display_name and entry.display_name_expire_at:
        payload["display_name"] = entry.display_name
        payload["display_name_expire_at"] = entry.display_name_expire_at
    if entry.last_seen_at:
        payload["last_seen_at"] = entry.last_seen_at
    return payload


def _entry_from_dict(data: Dict[str, Any]) -> FeishuUserEntry:
    entry = FeishuUserEntry()
    if isinstance(data.get("p2p_chat_id"), str):
        entry.p2p_chat_id = data["p2p_chat_id"]
    if isinstance(data.get("display_name"), str):
        entry.display_name = data["display_name"]
    expire = data.get("display_name_expire_at")
    if isinstance(expire, (int, float)):
        entry.display_name_expire_at = float(expire)
    seen = data.get("last_seen_at")
    if isinstance(seen, (int, float)):
        entry.last_seen_at = float(seen)
    return entry


def load_user_cache(path: Any, cache: Dict[str, FeishuUserEntry]) -> None:
    """Load persisted user records from disk into ``cache`` (v1 + v2)."""
    path = Path(path)
    if not path.exists():
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return
        if data.get("_version") == USER_CACHE_VERSION:
            users = data.get("users")
            if not isinstance(users, dict):
                return
            for open_id, record in users.items():
                if isinstance(open_id, str) and isinstance(record, dict):
                    cache[open_id] = _entry_from_dict(record)
            logger.info("[Feishu] Loaded %d persisted user records (v2)", len(users))
            return
        # v1: flat open_id → p2p_chat_id
        count = 0
        for open_id, chat_id in data.items():
            if isinstance(open_id, str) and isinstance(chat_id, str) and chat_id:
                entry = get_user_entry(cache, open_id)
                entry.p2p_chat_id = chat_id
                count += 1
        if count:
            logger.info("[Feishu] Migrated %d v1 p2p_chat_id mappings", count)
    except Exception as exc:
        logger.warning("[Feishu] Failed to load user cache: %s", exc)


def _should_persist_entry(entry: FeishuUserEntry) -> bool:
    return bool(entry.p2p_chat_id) or bool(
        entry.display_name and entry.display_name_expire_at
    )


def save_user_cache(path: Any, cache: Dict[str, FeishuUserEntry]) -> None:
    """Persist user records to disk (always v2)."""
    path = Path(path)
    users = {
        open_id: _entry_to_dict(entry)
        for open_id, entry in cache.items()
        if _should_persist_entry(entry)
    }
    snapshot = {"_version": USER_CACHE_VERSION, "users": users}
    try:
        from utils import atomic_json_write

        atomic_json_write(path, snapshot)
    except Exception as exc:
        logger.warning("[Feishu] Failed to save user cache: %s", exc)


# Deprecated back-compat aliases — use load_user_cache / save_user_cache instead.
# Remove after 2026-07-15 once all Phase A callers are migrated.
load_chat_id_cache = load_user_cache
save_chat_id_cache = save_user_cache


class ChatIdCacheDebouncer:
    """Debounced persistence for Feishu user cache.

    Extracted from gateway/platforms/feishu.py per 二次开发规范.
    """

    def __init__(self, save_fn: Callable[[], None]) -> None:
        self._lock = threading.Lock()
        self._dirty = False
        self._timer: Optional[threading.Timer] = None
        self._save_fn = save_fn

    def mark_dirty(self) -> None:
        with self._lock:
            self._dirty = True
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(5.0, self._flush)
            self._timer.daemon = True
            self._timer.start()

    def _flush(self) -> None:
        with self._lock:
            self._timer = None
            if not self._dirty:
                return
            self._dirty = False
        self._save_fn()