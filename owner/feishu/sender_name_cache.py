"""Feishu open_id (and user_id/union_id) -> 中文名 cache with TTL and pre-warm.

Core logic extracted from gateway/platforms/feishu.py per 二次开发规范:
- P1 import 编排: 核心实现在 owner/，官方文件只剩薄薄委托 + import + 调用
- Owner 目录: 所有自定义逻辑只放在 owner/ 下，便于独立演进、测试、回滚
- 高内聚低耦合: 仅处理名称缓存（open_id -> display name，10min TTL + 预热），chat_id/p2p 映射等留待后续
- 便于 sync upstream: 官方 feishu.py 字面 diff 极小

主要用途：
- 审批卡片 (P45)：send_exec_approval 前异步 pre-warm，确保 _handle_approval_card_action 回调能零延迟读到真实中文名
- 通用 sender profile：_resolve_sender_profile 中用于填充 user_name（群聊/单聊显示）

Usage in feishu.py (after extraction):
    from owner.feishu.sender_name_cache import FeishuSenderNameCache
    ...
    # in __init__
    self._name_cache: Optional[FeishuSenderNameCache] = None
    ...
    # after client ready or on first use
    if self._name_cache is None:
        self._name_cache = FeishuSenderNameCache(self._client)
    ...
    # delegates
    def _get_cached_sender_name(self, sid):
        # [owner] approval: open_id -> 中文名 cache (see owner/feishu/sender_name_cache.py)
        if self._name_cache is None:
            return None
        return self._name_cache.get(sid)

    async def _resolve_sender_name_from_api(self, sid, *, is_bot=False):
        if self._name_cache is None:
            return None
        return await self._name_cache.resolve(sid, is_bot=is_bot)

    # pre-warm (in send_exec_approval)
    if sender_open_id and self._name_cache:
        self._name_cache.pre_warm(sender_open_id, is_bot=sender_is_bot)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_FEISHU_SENDER_NAME_TTL_SECONDS = 10 * 60  # 10 minutes


class FeishuSenderNameCache:
    """Per-adapter cache for Feishu sender display names.

    Keys are the ID used for lookup (open_id preferred for approval callback alignment).
    Values are (name, expire_at).  "" name means "known but nameless".
    Bot names go through a separate /bot/v3/bots/basic_batch endpoint.
    Failures are silent (never block message/approval flows).
    """

    def __init__(self, client: Any = None) -> None:
        self._client = client
        self._cache: Dict[str, Tuple[str, float]] = {}  # id -> (name, expire_at)

    def get(self, sender_id: Optional[str]) -> Optional[str]:
        """Return cached name if still valid within TTL, else None (and evict)."""
        if not sender_id:
            return None
        cached = self._cache.get(sender_id)
        if cached is None:
            return None
        name, expire_at = cached
        if time.time() < expire_at:
            return name
        self._cache.pop(sender_id, None)
        return None

    async def resolve(
        self, sender_id: Optional[str], *, is_bot: bool = False
    ) -> Optional[str]:
        """Resolve via API (or cache) and populate cache on success.

        Returns the name or None.  Never raises to caller.
        """
        if not sender_id or not self._client:
            return None
        trimmed = sender_id.strip()
        if not trimmed:
            return None

        now = time.time()
        cached_name = self.get(trimmed)
        if cached_name is not None:
            return cached_name or None  # "" means known nameless

        if is_bot:
            names = await self._fetch_bot_names([trimmed])
            if names is None:
                return None
            expire_at = now + _FEISHU_SENDER_NAME_TTL_SECONDS
            for oid, name in names.items():
                self._cache[oid] = (name, expire_at)
            hit = self._cache.get(trimmed)
            return (hit[0] or None) if hit else None

        try:
            from lark_oapi.api.contact.v3 import GetUserRequest  # lazy

            if trimmed.startswith("ou_"):
                id_type = "open_id"
            elif trimmed.startswith("on_"):
                id_type = "union_id"
            else:
                id_type = "user_id"

            request = GetUserRequest.builder().user_id(trimmed).user_id_type(id_type).build()
            response = await asyncio.to_thread(self._client.contact.v3.user.get, request)
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
                    self._cache[trimmed] = (name, now + _FEISHU_SENDER_NAME_TTL_SECONDS)
                    return name
        except Exception:
            logger.debug("[Feishu] Failed to resolve sender name for %s", sender_id, exc_info=True)
        return None

    def pre_warm(self, sender_id: str, *, is_bot: bool = False) -> None:
        """Fire-and-forget pre-warm if not already cached.

        Safe to call from async send paths.  If no running loop, silently skips.
        """
        if sender_id and not self.get(sender_id):
            try:
                asyncio.create_task(self.resolve(sender_id, is_bot=is_bot))
            except RuntimeError:
                # No running event loop in this context (very rare for gateway paths)
                pass

    async def _fetch_bot_names(self, bot_ids: List[str]) -> Optional[Dict[str, str]]:
        """Call Feishu bot batch API for names (bypasses contact which doesn't return bot names)."""
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
            logger.debug("[Feishu] Failed to fetch bot names for %s", bot_ids, exc_info=True)
            return None

    def bind_client(self, client: Any) -> None:
        """Update the underlying Feishu client (e.g. after connect/reconnect)."""
        self._client = client
