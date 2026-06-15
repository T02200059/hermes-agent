"""Tests for owner.feishu.user_store."""

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from owner.feishu.sender_name_cache import FeishuSenderNameCache
from owner.feishu.user_store import FeishuUserStore, get_user_store


class TestFeishuUserStore:
    def test_cache_p2p_chat_id_and_lookup(self, tmp_path):
        store = FeishuUserStore(chat_id_cache_path=tmp_path / "chats.json")
        assert store.cache_p2p_chat_id("ou_a", "oc_dm") is True
        assert store.get_p2p_chat_id("ou_a") == "oc_dm"
        assert store.cache_p2p_chat_id("ou_a", "oc_dm") is False

    def test_legacy_name_dict_mutation_visible_via_get_cached_name(self):
        legacy = {"ou_x": ("Alice", time.time() + 600)}
        store = FeishuUserStore(chat_id_cache_path="/tmp/unused.json", legacy_name_dict=legacy)
        assert store.get_cached_name("ou_x") == "Alice"

    def test_replace_legacy_name_dict(self):
        store = FeishuUserStore(chat_id_cache_path="/tmp/unused.json", legacy_name_dict={})
        store.replace_legacy_name_dict({"ou_y": ("Bob", time.time() + 600)})
        assert store.get_cached_name("ou_y") == "Bob"

    def test_name_cache_setter_syncs_legacy_dict(self):
        cache = FeishuSenderNameCache(None)
        cache._cache["ou_z"] = ("Carol", time.time() + 600)
        store = FeishuUserStore(chat_id_cache_path="/tmp/unused.json")
        store.name_cache = cache
        assert store.get_cached_name("ou_z") == "Carol"
        assert store.legacy_name_dict is cache._cache

    @pytest.mark.asyncio
    async def test_resolve_name_uses_name_cache(self):
        client = MagicMock()
        store = FeishuUserStore(chat_id_cache_path="/tmp/unused.json")
        store._client = client
        cache = FeishuSenderNameCache(client)
        store._name_cache = cache
        with patch.object(cache, "resolve", new_callable=AsyncMock, return_value="Dan") as mock_resolve:
            result = await store.resolve_name("ou_new")
        assert result == "Dan"
        mock_resolve.assert_awaited_once_with("ou_new", is_bot=False)


class TestGetUserStore:
    def test_returns_store_when_present(self):
        store = FeishuUserStore(chat_id_cache_path="/tmp/unused.json")
        adapter = SimpleNamespace(_user_store=store)
        assert get_user_store(adapter) is store

    def test_returns_none_for_missing_or_wrong_type(self):
        assert get_user_store(SimpleNamespace()) is None
        assert get_user_store(SimpleNamespace(_user_store="not-a-store")) is None