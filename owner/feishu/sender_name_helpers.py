"""Shared helpers for Feishu open_id -> display name cache access.

Centralizes lazy cache binding, legacy test-compat shims, and pre-warm so
owner modules (approval, update_prompt, model_picker, bot_menu) and the thin
feishu.py glue all share one code path (see owner/feishu/sender_name_cache.py).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

from owner.feishu.sender_name_cache import FeishuSenderNameCache


def _legacy_cache_dict(adapter: Any) -> Optional[dict]:
    legacy = getattr(adapter, "_sender_name_cache", None)
    return legacy if isinstance(legacy, dict) else None


def _read_legacy_cached_name(adapter: Any, sender_id: Optional[str]) -> Optional[str]:
    """Return a valid legacy/test cache hit, or None if miss/expired."""
    legacy = _legacy_cache_dict(adapter)
    if not legacy or not sender_id or sender_id not in legacy:
        return None
    name, expire_at = legacy[sender_id]
    if time.time() < expire_at:
        return name
    legacy.pop(sender_id, None)
    return None


def ensure_name_cache(adapter: Any) -> Optional[FeishuSenderNameCache]:
    """Lazy-bind FeishuSenderNameCache on the adapter; preserve legacy entries."""
    existing = getattr(adapter, "_name_cache", None)
    if existing is not None:
        return existing
    client = getattr(adapter, "_client", None)
    if not client:
        return None
    cache = FeishuSenderNameCache(client)
    legacy = _legacy_cache_dict(adapter)
    if legacy:
        cache._cache.update(legacy)
    adapter._name_cache = cache
    adapter._sender_name_cache = cache._cache  # compat for tests
    return cache


def get_cached_sender_name(adapter: Any, sender_id: Optional[str]) -> Optional[str]:
    """Return cached display name if valid, else None."""
    if not sender_id:
        return None
    legacy_hit = _read_legacy_cached_name(adapter, sender_id)
    if legacy_hit is not None:
        return legacy_hit
    cache = getattr(adapter, "_name_cache", None)
    if cache is None:
        return None
    return cache.get(sender_id)


def operator_display_name(adapter: Any, open_id: str) -> str:
    """Cached display name for card callbacks, or open_id fallback."""
    if not open_id:
        return ""
    return get_cached_sender_name(adapter, open_id) or open_id


async def resolve_sender_name(
    adapter: Any,
    sender_id: Optional[str],
    *,
    is_bot: bool = False,
) -> Optional[str]:
    """Resolve via cache or API; never raises."""
    if not sender_id:
        return None
    cached_name = get_cached_sender_name(adapter, sender_id)
    if cached_name is not None:
        return cached_name or None  # "" means known nameless
    cache = ensure_name_cache(adapter)
    if cache is None:
        return None
    return await cache.resolve(sender_id, is_bot=is_bot)


def pre_warm_sender_name(
    adapter: Any,
    sender_id: str,
    *,
    is_bot: bool = False,
    fire_delegate: bool = False,
) -> None:
    """Fire-and-forget pre-warm when sender_id is not already cached.

    When ``fire_delegate`` is True (feishu.py send_exec_approval test compat),
    also schedules ``adapter._resolve_sender_name_from_api`` so tests that patch
    that method still observe a call.
    """
    if not sender_id:
        return
    if get_cached_sender_name(adapter, sender_id) is not None:
        return
    cache = ensure_name_cache(adapter)
    if cache is not None:
        cache.pre_warm(sender_id, is_bot=is_bot)
    if fire_delegate and hasattr(adapter, "_resolve_sender_name_from_api"):
        try:
            asyncio.create_task(
                adapter._resolve_sender_name_from_api(sender_id, is_bot=is_bot)
            )
        except RuntimeError:
            pass