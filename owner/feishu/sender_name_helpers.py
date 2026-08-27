"""Shared helpers for Feishu open_id -> display name cache access.

Phase A: prefer ``adapter._user_store`` (see owner/feishu/user_store.py).
Legacy adapter attrs remain as fallback for tests and non-Feishu stubs.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple

if TYPE_CHECKING:
    from owner.feishu.sender_name_cache import FeishuSenderNameCache
    from owner.feishu.user_store import FeishuUserStore

from owner.feishu.user_store import FeishuUserStore, get_user_store


def _legacy_adapter_path(adapter: Any) -> bool:
    return get_user_store(adapter) is None


def ensure_name_cache(adapter: Any) -> Optional[Any]:
    store = get_user_store(adapter)
    if store is not None:
        return store if getattr(store, "_client", None) else None
    return _legacy_ensure_name_cache(adapter)


def get_cached_sender_name(adapter: Any, sender_id: Optional[str]) -> Optional[str]:
    store = get_user_store(adapter)
    if store is not None:
        return store.get_cached_name(sender_id)
    return _legacy_get_cached_sender_name(adapter, sender_id)


def operator_display_name(adapter: Any, open_id: str) -> str:
    """Return a display name for *open_id*, never the raw ``ou_xxx``.

    On cache miss returns ``""`` so callers can use a fallback label
    instead of leaking the raw open_id.
    """
    store = get_user_store(adapter)
    if store is not None:
        return store.operator_display_name(open_id)
    if not open_id:
        return ""
    return _legacy_get_cached_sender_name(adapter, open_id) or ""


async def resolve_sender_name(
    adapter: Any,
    sender_id: Optional[str],
    *,
    is_bot: bool = False,
) -> Optional[str]:
    store = get_user_store(adapter)
    if store is not None:
        return await store.resolve_name(sender_id, is_bot=is_bot)
    return await _legacy_resolve_sender_name(adapter, sender_id, is_bot=is_bot)


def pre_warm_sender_name(
    adapter: Any,
    sender_id: str,
    *,
    is_bot: bool = False,
    fire_delegate: bool = False,
) -> None:
    store = get_user_store(adapter)
    if store is not None:
        store.pre_warm_name(sender_id, is_bot=is_bot)
    else:
        _legacy_pre_warm_sender_name(adapter, sender_id, is_bot=is_bot)
    if fire_delegate and hasattr(adapter, "_resolve_sender_name_from_api"):
        try:
            asyncio.create_task(
                adapter._resolve_sender_name_from_api(sender_id, is_bot=is_bot)
            )
        except RuntimeError:
            pass


# --- legacy fallback (no _user_store on adapter) ---


def _legacy_cache_dict(adapter: Any) -> Optional[dict]:
    """Return ``adapter._sender_name_cache`` if it is a dict, else None."""
    legacy = getattr(adapter, "_sender_name_cache", None)
    return legacy if isinstance(legacy, dict) else None


def _legacy_read_cached_name(adapter: Any, sender_id: Optional[str]) -> Optional[str]:
    """Return valid legacy cache hit for *sender_id*, or None on miss/expiry.

    Side effect: expired entries are popped from the cache dict.
    """
    import time

    legacy = _legacy_cache_dict(adapter)
    if not legacy or not sender_id or sender_id not in legacy:
        return None
    name, expire_at = legacy[sender_id]
    if time.time() < expire_at:
        return name
    legacy.pop(sender_id, None)
    return None


def _legacy_ensure_name_cache(adapter: Any) -> Optional[FeishuSenderNameCache]:
    """Lazy-bind ``FeishuSenderNameCache`` on the adapter with legacy entry sync.

    Deprecated: prefer ``FeishuUserStore`` (Phase B/C).  This path exists
    only for legacy test adapters that do not carry ``_user_store``.
    Remove after the last ``SimpleNamespace`` test adapter is migrated
    (target: 2026-07-15).
    """
    from owner.feishu.sender_name_cache import FeishuSenderNameCache as _Cache

    existing = getattr(adapter, "_name_cache", None)
    if existing is not None:
        return existing
    client = getattr(adapter, "_client", None)
    if not client:
        return None
    cache = _Cache(client)
    legacy = _legacy_cache_dict(adapter)
    if legacy:
        cache._cache.update(legacy)
    adapter._name_cache = cache
    adapter._sender_name_cache = cache._cache
    return cache


def _legacy_get_cached_sender_name(
    adapter: Any, sender_id: Optional[str]
) -> Optional[str]:
    if not sender_id:
        return None
    legacy_hit = _legacy_read_cached_name(adapter, sender_id)
    if legacy_hit is not None:
        return legacy_hit
    cache = getattr(adapter, "_name_cache", None)
    if cache is None:
        return None
    return cache.get(sender_id)


async def _legacy_resolve_sender_name(
    adapter: Any,
    sender_id: Optional[str],
    *,
    is_bot: bool = False,
) -> Optional[str]:
    if not sender_id:
        return None
    cached_name = _legacy_get_cached_sender_name(adapter, sender_id)
    if cached_name is not None:
        return cached_name or None
    cache = _legacy_ensure_name_cache(adapter)
    if cache is None:
        return None
    return await cache.resolve(sender_id, is_bot=is_bot)


def _legacy_pre_warm_sender_name(
    adapter: Any,
    sender_id: str,
    *,
    is_bot: bool = False,
) -> None:
    if not sender_id or _legacy_get_cached_sender_name(adapter, sender_id) is not None:
        return
    cache = _legacy_ensure_name_cache(adapter)
    if cache is not None:
        cache.pre_warm(sender_id, is_bot=is_bot)