"""Tests for owner.feishu.sender_name_helpers."""

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from owner.feishu.sender_name_cache import FeishuSenderNameCache
from owner.feishu.sender_name_helpers import (
    ensure_name_cache,
    get_cached_sender_name,
    operator_display_name,
    pre_warm_sender_name,
    resolve_sender_name,
)
from owner.feishu.user_store import FeishuUserStore


class TestEnsureNameCache:
    def test_returns_existing_cache(self):
        cache = FeishuSenderNameCache(None)
        adapter = SimpleNamespace(_name_cache=cache, _client=MagicMock())
        assert ensure_name_cache(adapter) is cache

    def test_lazy_binds_and_preserves_legacy(self):
        client = MagicMock()
        adapter = SimpleNamespace(
            _name_cache=None,
            _client=client,
            _sender_name_cache={"ou_legacy": ("Legacy", time.time() + 600)},
        )
        cache = ensure_name_cache(adapter)
        assert cache is not None
        assert adapter._name_cache is cache
        assert adapter._sender_name_cache is cache._cache
        assert cache.get("ou_legacy") == "Legacy"

    def test_no_client_returns_none(self):
        adapter = SimpleNamespace(_name_cache=None, _client=None)
        assert ensure_name_cache(adapter) is None


class TestGetCachedSenderName:
    def test_legacy_dict_hit(self):
        adapter = SimpleNamespace(
            _sender_name_cache={"ou_x": ("Alice", time.time() + 600)},
            _name_cache=None,
        )
        assert get_cached_sender_name(adapter, "ou_x") == "Alice"

    def test_legacy_dict_expired(self):
        adapter = SimpleNamespace(
            _sender_name_cache={"ou_x": ("Alice", time.time() - 1)},
            _name_cache=None,
        )
        assert get_cached_sender_name(adapter, "ou_x") is None
        assert "ou_x" not in adapter._sender_name_cache

    def test_bound_cache_hit(self):
        cache = FeishuSenderNameCache(None)
        cache._cache["ou_y"] = ("Bob", time.time() + 600)
        adapter = SimpleNamespace(_name_cache=cache, _sender_name_cache=cache._cache)
        assert get_cached_sender_name(adapter, "ou_y") == "Bob"


class TestOperatorDisplayName:
    def test_fallback_to_open_id(self):
        adapter = SimpleNamespace(_name_cache=None, _sender_name_cache={})
        assert operator_display_name(adapter, "ou_fallback") == "ou_fallback"

    def test_uses_cached_name(self):
        adapter = SimpleNamespace(
            _sender_name_cache={"ou_z": ("Carol", time.time() + 600)},
            _name_cache=None,
        )
        assert operator_display_name(adapter, "ou_z") == "Carol"


class TestResolveSenderName:
    @pytest.mark.asyncio
    async def test_returns_cached_without_api(self):
        cache = FeishuSenderNameCache(None)
        cache._cache["ou_cached"] = ("Dan", time.time() + 600)
        adapter = SimpleNamespace(_name_cache=cache, _sender_name_cache=cache._cache)
        with patch.object(cache, "resolve", new_callable=AsyncMock) as mock_resolve:
            result = await resolve_sender_name(adapter, "ou_cached")
        assert result == "Dan"
        mock_resolve.assert_not_called()

    @pytest.mark.asyncio
    async def test_delegates_to_cache_resolve(self):
        client = MagicMock()
        adapter = SimpleNamespace(_name_cache=None, _client=client, _sender_name_cache={})
        cache = FeishuSenderNameCache(client)
        adapter._name_cache = cache
        adapter._sender_name_cache = cache._cache
        with patch.object(cache, "resolve", new_callable=AsyncMock, return_value="Eve") as mock_resolve:
            result = await resolve_sender_name(adapter, "ou_new")
        assert result == "Eve"
        mock_resolve.assert_awaited_once_with("ou_new", is_bot=False)


class TestSenderNameHelpersViaUserStore:
    def test_get_cached_name_routes_through_user_store(self):
        legacy = {"ou_store": ("Eve", time.time() + 600)}
        store = FeishuUserStore(chat_id_cache_path="/tmp/unused.json", legacy_name_dict=legacy)
        adapter = SimpleNamespace(_user_store=store, _client=MagicMock())
        assert get_cached_sender_name(adapter, "ou_store") == "Eve"


class TestPreWarmSenderName:
    def test_skips_when_already_cached(self):
        cache = FeishuSenderNameCache(None)
        cache._cache["ou_hit"] = ("Frank", time.time() + 600)
        adapter = SimpleNamespace(_name_cache=cache, _sender_name_cache=cache._cache)
        with patch.object(cache, "pre_warm") as mock_pre_warm:
            pre_warm_sender_name(adapter, "ou_hit")
        mock_pre_warm.assert_not_called()

    def test_pre_warms_uncached_sender(self):
        client = MagicMock()
        adapter = SimpleNamespace(_name_cache=None, _client=client, _sender_name_cache={})
        with patch.object(FeishuSenderNameCache, "pre_warm") as mock_pre_warm:
            pre_warm_sender_name(adapter, "ou_cold", is_bot=True)
        mock_pre_warm.assert_called_once_with("ou_cold", is_bot=True)