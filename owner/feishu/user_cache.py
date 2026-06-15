"""Feishu user cache — open_id → {name, p2p_chat_id, last_seen_at}.

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


class FeishuUserEntry:
    """Single-user cache keyed by open_id."""

    __slots__ = ("name", "name_expire_at", "p2p_chat_id", "last_seen_at")

    def __init__(self) -> None:
        self.name: str = ""
        self.name_expire_at: float = 0.0
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


def load_chat_id_cache(path: Any, cache: Dict[str, FeishuUserEntry]) -> None:
    """Load persisted open_id → p2p_chat_id mappings from disk into ``cache``."""
    path = Path(path)
    if not path.exists():
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return
        for open_id, chat_id in data.items():
            if isinstance(open_id, str) and isinstance(chat_id, str) and chat_id:
                entry = get_user_entry(cache, open_id)
                entry.p2p_chat_id = chat_id
        logger.info("[Feishu] Loaded %d persisted p2p_chat_id mappings", len(data))
    except Exception as exc:
        logger.warning("[Feishu] Failed to load chat_id cache: %s", exc)


def save_chat_id_cache(path: Any, cache: Dict[str, FeishuUserEntry]) -> None:
    """Persist current open_id → p2p_chat_id mappings from ``cache`` to disk."""
    path = Path(path)
    snapshot = {
        open_id: entry.p2p_chat_id
        for open_id, entry in cache.items()
        if entry.p2p_chat_id
    }
    try:
        from utils import atomic_json_write

        atomic_json_write(path, snapshot)
    except Exception as exc:
        logger.warning("[Feishu] Failed to save chat_id cache: %s", exc)


class ChatIdCacheDebouncer:
    """Debounced persistence for open_id → p2p_chat_id cache.

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
