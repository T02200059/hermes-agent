"""Feishu diff/recall card cache with TTL.

可移除性：删除此文件后，卡片缓存变为无 TTL 的普通 dict 存储，
功能不受影响但缓存可能过时。
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

CARD_CACHE_TTL_SEC = 10800  # 3 hours


def cache_put(cache: Dict[str, Any], key: str, value: Dict[str, Any]) -> None:
    """Store in cache with timestamp; evict expired entries."""
    now = time.time()
    expired = [
        k for k, v in cache.items()
        if now - v.get("_ts", 0) > CARD_CACHE_TTL_SEC
    ]
    for k in expired:
        del cache[k]
    value["_ts"] = now
    cache[key] = value


def cache_get(cache: Dict[str, Any], key: str) -> Optional[Dict[str, Any]]:
    """Retrieve from cache; return None if expired or missing."""
    entry = cache.get(key)
    if entry is None:
        return None
    if time.time() - entry.get("_ts", 0) > CARD_CACHE_TTL_SEC:
        del cache[key]
        return None
    return entry
