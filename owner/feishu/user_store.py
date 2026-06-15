"""Unified Feishu per-user store (Phase A facade).

Single entry for open_id-scoped state:
- display names (memory TTL via FeishuSenderNameCache)
- p2p chat_id mappings (disk-backed via user_cache)

gateway/platforms/feishu.py holds one ``FeishuUserStore`` instance; legacy
``_name_cache`` / ``_feishu_user_cache`` / ``_sender_name_cache`` adapter
attrs remain as thin deprecated forwards for tests and gradual migration.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from owner.feishu.sender_name_cache import FeishuSenderNameCache
from owner.feishu.user_cache import (
    ChatIdCacheDebouncer,
    FeishuUserEntry,
    cache_p2p_chat_id,
    get_cached_chat_id,
    load_chat_id_cache,
    save_chat_id_cache,
)

logger = logging.getLogger(__name__)


class FeishuUserStore:
    """Per-adapter store for Feishu user-scoped cache + persistence."""

    def __init__(
        self,
        *,
        chat_id_cache_path: Any,
        legacy_name_dict: Optional[Dict[str, Tuple[str, float]]] = None,
    ) -> None:
        self._client: Any = None
        self._name_cache: Optional[FeishuSenderNameCache] = None
        self._legacy_name_dict: Dict[str, Tuple[str, float]] = (
            legacy_name_dict if legacy_name_dict is not None else {}
        )
        self._users: Dict[str, FeishuUserEntry] = {}
        self._chat_id_cache_path = Path(chat_id_cache_path)
        self._debouncer = ChatIdCacheDebouncer(
            save_fn=lambda: save_chat_id_cache(self._chat_id_cache_path, self._users)
        )
        load_chat_id_cache(self._chat_id_cache_path, self._users)

    @property
    def users(self) -> Dict[str, FeishuUserEntry]:
        return self._users

    @property
    def legacy_name_dict(self) -> Dict[str, Tuple[str, float]]:
        return self._legacy_name_dict

    def replace_legacy_name_dict(
        self, new_dict: Dict[str, Tuple[str, float]]
    ) -> None:
        """Test compat: rebind the legacy name dict (e.g. adapter._sender_name_cache = {})."""
        self._legacy_name_dict = new_dict
        if self._name_cache is not None:
            self._name_cache._cache = new_dict

    @property
    def name_cache(self) -> Optional[FeishuSenderNameCache]:
        return self._name_cache

    @name_cache.setter
    def name_cache(self, value: Optional[FeishuSenderNameCache]) -> None:
        self._name_cache = value
        if value is not None:
            self._legacy_name_dict = value._cache

    def bind_client(self, client: Any) -> None:
        self._client = client
        if self._name_cache is not None:
            self._name_cache.bind_client(client)

    def _read_legacy_name(self, sender_id: Optional[str]) -> Optional[str]:
        if not sender_id or sender_id not in self._legacy_name_dict:
            return None
        name, expire_at = self._legacy_name_dict[sender_id]
        if time.time() < expire_at:
            return name
        self._legacy_name_dict.pop(sender_id, None)
        return None

    def ensure_name_cache(self) -> Optional[FeishuSenderNameCache]:
        if self._name_cache is not None:
            return self._name_cache
        if not self._client:
            return None
        cache = FeishuSenderNameCache(self._client)
        if self._legacy_name_dict:
            cache._cache.update(self._legacy_name_dict)
        self._name_cache = cache
        self._legacy_name_dict = cache._cache
        return cache

    def get_cached_name(self, sender_id: Optional[str]) -> Optional[str]:
        if not sender_id:
            return None
        legacy_hit = self._read_legacy_name(sender_id)
        if legacy_hit is not None:
            return legacy_hit
        if self._name_cache is None:
            return None
        return self._name_cache.get(sender_id)

    def operator_display_name(self, open_id: str) -> str:
        if not open_id:
            return ""
        return self.get_cached_name(open_id) or open_id

    async def resolve_name(
        self,
        sender_id: Optional[str],
        *,
        is_bot: bool = False,
    ) -> Optional[str]:
        if not sender_id:
            return None
        cached_name = self.get_cached_name(sender_id)
        if cached_name is not None:
            return cached_name or None
        cache = self.ensure_name_cache()
        if cache is None:
            return None
        return await cache.resolve(sender_id, is_bot=is_bot)

    def pre_warm_name(
        self,
        sender_id: str,
        *,
        is_bot: bool = False,
    ) -> None:
        if not sender_id or self.get_cached_name(sender_id) is not None:
            return
        cache = self.ensure_name_cache()
        if cache is not None:
            cache.pre_warm(sender_id, is_bot=is_bot)

    def get_p2p_chat_id(self, open_id: str) -> Optional[str]:
        return get_cached_chat_id(self._users, open_id)

    def cache_p2p_chat_id(self, open_id: str, chat_id: str) -> bool:
        return cache_p2p_chat_id(
            self._users,
            open_id,
            chat_id,
            debouncer=self._debouncer,
        )


def get_user_store(adapter: Any) -> Optional[FeishuUserStore]:
    store = getattr(adapter, "_user_store", None)
    return store if isinstance(store, FeishuUserStore) else None