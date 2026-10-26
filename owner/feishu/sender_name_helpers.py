# [owner] C04 — Feishu open_id → display-name helpers (user_store primary).
"""Shared helpers for Feishu open_id → display name cache access.

Prefer ``adapter._user_store`` (see ``owner/feishu/user_store.py``).
The legacy ``adapter._sender_name_cache`` dict remains as a fallback for
tests and adapters that have not bound a store yet.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

from owner.feishu.user_store import get_user_store


def ensure_name_cache(adapter: Any) -> Optional[Any]:
    store = get_user_store(adapter)
    if store is not None:
        return store if getattr(store, "_client", None) else None
    # Legacy: dict cache alone is enough for get; resolve needs API client.
    return None


def get_cached_sender_name(adapter: Any, sender_id: Optional[str]) -> Optional[str]:
    store = get_user_store(adapter)
    if store is not None:
        name = store.get_cached_name(sender_id)
        if name is not None:
            return name
    return _legacy_get_cached_sender_name(adapter, sender_id)


def operator_display_name(adapter: Any, open_id: str) -> str:
    """Return a display name for *open_id*, never the raw ``ou_xxx``.

    On cache miss returns ``""`` so callers can use a fallback label
    instead of leaking the raw open_id.
    """
    if not open_id:
        return ""
    store = get_user_store(adapter)
    if store is not None:
        name = store.operator_display_name(open_id)
        if name:
            return name
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


async def ensure_sender_name_cached(
    adapter: Any,
    sender_id: Optional[str],
    *,
    is_bot: bool = False,
) -> None:
    """Best-effort awaitable pre-warm used by approval send glue."""
    if not sender_id or is_bot:
        return
    try:
        await resolve_sender_name(adapter, sender_id, is_bot=is_bot)
    except Exception:
        pass


# --- legacy fallback (no _user_store on adapter) ---


def _legacy_cache_dict(adapter: Any) -> Optional[dict]:
    legacy = getattr(adapter, "_sender_name_cache", None)
    return legacy if isinstance(legacy, dict) else None


def _legacy_get_cached_sender_name(
    adapter: Any, sender_id: Optional[str]
) -> Optional[str]:
    if not sender_id:
        return None
    legacy = _legacy_cache_dict(adapter)
    if not legacy or sender_id not in legacy:
        return None
    entry = legacy[sender_id]
    if isinstance(entry, (tuple, list)) and len(entry) >= 2:
        name, expire_at = entry[0], entry[1]
        if time.time() < float(expire_at):
            return name
        # Soft TTL: keep the name string as stale fallback (do not pop).
        return name or None
    if isinstance(entry, str):
        return entry or None
    return None


async def _legacy_resolve_sender_name(
    adapter: Any,
    sender_id: Optional[str],
    *,
    is_bot: bool = False,
) -> Optional[str]:
    if not sender_id:
        return None
    cached = _legacy_get_cached_sender_name(adapter, sender_id)
    if cached is not None:
        return cached or None
    # No user_store and no live API client binding — cannot resolve.
    resolve = getattr(adapter, "_resolve_sender_name_from_api", None)
    if resolve is None:
        return None
    try:
        return await resolve(sender_id, is_bot=is_bot)
    except Exception:
        return None


def _legacy_pre_warm_sender_name(
    adapter: Any,
    sender_id: str,
    *,
    is_bot: bool = False,
) -> None:
    if not sender_id or _legacy_get_cached_sender_name(adapter, sender_id) is not None:
        return
    resolve = getattr(adapter, "_resolve_sender_name_from_api", None)
    if resolve is None:
        return
    try:
        asyncio.create_task(resolve(sender_id, is_bot=is_bot))
    except RuntimeError:
        pass
