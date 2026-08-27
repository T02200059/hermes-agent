"""Unified Feishu per-user store (Phase B/C).

Single entry for open_id-scoped state:
- display names (in-memory TTL + synced ``FeishuUserEntry.display_name``)
- p2p chat_id mappings (disk-backed v2 user records)

Name resolution logic is internalized here (formerly ``FeishuSenderNameCache``).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from owner.feishu.user_cache import (
    ChatIdCacheDebouncer,
    FeishuUserEntry,
    cache_p2p_chat_id,
    get_cached_chat_id,
    get_cached_display_name,
    load_user_cache,
    save_user_cache,
    set_cached_display_name,
)

logger = logging.getLogger(__name__)

_FEISHU_SENDER_NAME_TTL_SECONDS = 24 * 60 * 60  # 24 hours (names rarely change)
# Re-warm a cached name when remaining TTL drops below this threshold so a
# card sent near the end of a TTL window does not expire before the user clicks.
_PRE_WARM_REFRESH_THRESHOLD = 30 * 60  # 30 minutes


class FeishuUserStore:
    """Per-adapter store for Feishu user-scoped cache + persistence."""

    def __init__(
        self,
        *,
        cache_path: Any,
    ) -> None:
        self._client: Any = None
        self._users: Dict[str, FeishuUserEntry] = {}
        # lookup_id → (name, expire_at); "" name = known nameless
        self._name_ttl: Dict[str, Tuple[str, float]] = {}
        self._cache_path = Path(cache_path)
        self._debouncer = ChatIdCacheDebouncer(
            save_fn=lambda: save_user_cache(self._cache_path, self._users)
        )
        load_user_cache(self._cache_path, self._users)
        self._seed_name_ttl_from_users()

    @property
    def users(self) -> Dict[str, FeishuUserEntry]:
        return self._users

    @property
    def name_ttl_cache(self) -> Dict[str, Tuple[str, float]]:
        """TTL name map keyed by lookup id (test introspection)."""
        return self._name_ttl

    def bind_client(self, client: Any) -> None:
        self._client = client

    def _seed_name_ttl_from_users(self) -> None:
        now = time.time()
        for open_id, entry in self._users.items():
            if (
                entry.display_name
                and entry.display_name_expire_at
                and now < entry.display_name_expire_at
            ):
                self._name_ttl[open_id] = (
                    entry.display_name,
                    entry.display_name_expire_at,
                )

    def _read_ttl_name(self, sender_id: Optional[str]) -> Optional[str]:
        """Read a cached name for *sender_id*.

        On TTL miss the entry is popped from the hot ``_name_ttl`` dict (so a
        subsequent ``resolve_name`` re-fetches), but the persisted
        ``_users.display_name`` is **not** destroyed — it survives as a
        stale-but-better-than-raw-id fallback so callers like
        ``operator_display_name`` never degrade to ``ou_xxx``.
        """
        if not sender_id:
            return None
        cached = self._name_ttl.get(sender_id)
        if cached is None:
            if sender_id.startswith("ou_"):
                return get_cached_display_name(self._users, sender_id)
            return None
        name, expire_at = cached
        if time.time() < expire_at:
            return name
        # TTL expired — evict from hot cache so resolve_name re-fetches,
        # but do NOT clear _users.display_name (it's still a usable fallback).
        self._name_ttl.pop(sender_id, None)
        if sender_id.startswith("ou_"):
            entry = self._users.get(sender_id)
            if entry is not None and entry.display_name:
                return entry.display_name  # stale but better than raw ou_xxx
        return None

    def _store_resolved_name(
        self, lookup_id: str, name: str, expire_at: float
    ) -> None:
        self._name_ttl[lookup_id] = (name, expire_at)
        if lookup_id.startswith("ou_"):
            set_cached_display_name(self._users, lookup_id, name, expire_at)
            self._debouncer.mark_dirty()

    def seed_cached_name(
        self, sender_id: str, name: str, expire_at: float
    ) -> None:
        """Test helper: inject a TTL name entry (legacy ``_sender_name_cache`` writes)."""
        self._store_resolved_name(sender_id, name, expire_at)

    def get_cached_name(self, sender_id: Optional[str]) -> Optional[str]:
        if not sender_id:
            return None
        return self._read_ttl_name(sender_id)

    def operator_display_name(self, open_id: str) -> str:
        """Return a display name for *open_id*, never the raw ``ou_xxx``.

        On cache miss returns ``""`` so callers can distinguish "name not
        available" from a real ID and use a fallback label instead of
        leaking the raw open_id to end users.
        """
        if not open_id:
            return ""
        return self.get_cached_name(open_id) or ""

    async def resolve_name(
        self,
        sender_id: Optional[str],
        *,
        is_bot: bool = False,
    ) -> Optional[str]:
        if not sender_id:
            return None
        trimmed = sender_id.strip()
        if not trimmed:
            return None

        cached_name = self.get_cached_name(trimmed)
        if cached_name is not None:
            return cached_name or None

        if not self._client:
            return None

        now = time.time()
        if is_bot:
            names = await self._fetch_bot_names([trimmed])
            if names is None:
                return None
            expire_at = now + _FEISHU_SENDER_NAME_TTL_SECONDS
            for oid, name in names.items():
                self._store_resolved_name(oid, name, expire_at)
            hit = self._name_ttl.get(trimmed)
            return (hit[0] or None) if hit else None

        try:
            from lark_oapi.api.contact.v3 import GetUserRequest  # lazy

            if trimmed.startswith("ou_"):
                id_type = "open_id"
            elif trimmed.startswith("on_"):
                id_type = "union_id"
            else:
                id_type = "user_id"

            request = (
                GetUserRequest.builder()
                .user_id(trimmed)
                .user_id_type(id_type)
                .build()
            )
            response = await asyncio.to_thread(
                self._client.contact.v3.user.get, request
            )
            if not response or not response.success():
                return None

            user = getattr(getattr(response, "data", None), "user", None)
            name = (
                getattr(user, "name", None)
                or getattr(user, "display_name", None)
                or getattr(user, "nickname", None)
                or getattr(user, "en_name", None)
            )
            if name and isinstance(name, str):
                name = name.strip()
                if name:
                    expire_at = now + _FEISHU_SENDER_NAME_TTL_SECONDS
                    self._store_resolved_name(trimmed, name, expire_at)
                    return name
        except Exception:
            logger.debug(
                "[Feishu] Failed to resolve sender name for %s",
                sender_id,
                exc_info=True,
            )
        return None

    def pre_warm_name(
        self,
        sender_id: str,
        *,
        is_bot: bool = False,
    ) -> None:
        """Fire-and-forget name resolve if the cached entry is missing or stale.

        Re-warms when the remaining TTL drops below ``_PRE_WARM_REFRESH_THRESHOLD``
        so a card sent near the end of a TTL window does not expire before the
        user clicks.
        """
        if not sender_id:
            return
        cached = self._name_ttl.get(sender_id)
        if cached is not None:
            name, expire_at = cached
            remaining = expire_at - time.time()
            if remaining > _PRE_WARM_REFRESH_THRESHOLD:
                return  # plenty of life left, no need to re-warm
            # TTL almost expired — fall through and re-warm
        if not self._client:
            return
        try:
            asyncio.create_task(self.resolve_name(sender_id, is_bot=is_bot))
        except RuntimeError:
            pass

    async def _fetch_bot_names(self, bot_ids: List[str]) -> Optional[Dict[str, str]]:
        if not self._client or not bot_ids:
            return None
        try:
            from lark_oapi.core import AccessTokenType, HttpMethod
            from lark_oapi.core.model import BaseRequest  # lazy

            req = (
                BaseRequest.builder()
                .http_method(HttpMethod.GET)
                .uri("/open-apis/bot/v3/bots/basic_batch")
                .queries([("bot_ids", oid) for oid in bot_ids])
                .token_types({AccessTokenType.TENANT})
                .build()
            )
            resp = await asyncio.to_thread(self._client.request, req)
            content = getattr(getattr(resp, "raw", None), "content", None)
            if not content:
                return None
            payload = json.loads(content)
            if payload.get("code") != 0:
                return None
            bots = (payload.get("data") or {}).get("bots") or {}
            return {
                oid: str(info.get("name") or "").strip()
                for oid, info in bots.items()
                if oid
            }
        except Exception:
            logger.debug(
                "[Feishu] Failed to fetch bot names for %s", bot_ids, exc_info=True
            )
            return None

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