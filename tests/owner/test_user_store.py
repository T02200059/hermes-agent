"""Tests for owner.feishu.user_store."""

import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from owner.feishu.user_store import FeishuUserStore, get_user_store


class TestFeishuUserStore:
    def test_cache_p2p_chat_id_and_lookup(self, tmp_path):
        store = FeishuUserStore(cache_path=tmp_path / "users.json")
        assert store.cache_p2p_chat_id("ou_a", "oc_dm") is True
        assert store.get_p2p_chat_id("ou_a") == "oc_dm"
        assert store.cache_p2p_chat_id("ou_a", "oc_dm") is False

    def test_seed_cached_name_visible_via_get_cached_name(self):
        store = FeishuUserStore(cache_path="/tmp/unused.json")
        store.seed_cached_name("ou_x", "Alice", time.time() + 600)
        assert store.get_cached_name("ou_x") == "Alice"

    def test_open_id_resolve_syncs_display_name_to_user_entry(self, tmp_path):
        store = FeishuUserStore(cache_path=tmp_path / "users.json")
        store.seed_cached_name("ou_sync", "Bob", time.time() + 600)
        entry = store.users["ou_sync"]
        assert entry.display_name == "Bob"
        assert entry.display_name_expire_at > time.time()

    @pytest.mark.asyncio
    async def test_resolve_name_fetches_via_contact_api(self):
        from types import SimpleNamespace

        user_obj = SimpleNamespace(
            name="Dan", display_name=None, nickname=None, en_name=None
        )
        mock_response = SimpleNamespace(
            success=lambda: True,
            data=SimpleNamespace(user=user_obj),
        )

        class _ContactAPI:
            def get(self, _request):
                return mock_response

        client = SimpleNamespace(
            contact=SimpleNamespace(v3=SimpleNamespace(user=_ContactAPI()))
        )
        store = FeishuUserStore(cache_path="/tmp/unused.json")
        store.bind_client(client)

        async def _direct(func, *args, **kwargs):
            return func(*args, **kwargs)

        with patch("owner.feishu.user_store.asyncio.to_thread", side_effect=_direct):
            result = await store.resolve_name("ou_new")

        assert result == "Dan"
        assert store.get_cached_name("ou_new") == "Dan"
        assert store.users["ou_new"].display_name == "Dan"

    def test_loads_v2_disk_format_into_name_ttl(self, tmp_path):
        path = tmp_path / "users.json"
        expire = time.time() + 600
        path.write_text(
            json.dumps(
                {
                    "_version": 2,
                    "users": {
                        "ou_disk": {
                            "display_name": "Carol",
                            "display_name_expire_at": expire,
                            "p2p_chat_id": "oc_dm",
                        }
                    },
                }
            )
        )
        store = FeishuUserStore(cache_path=path)
        assert store.get_cached_name("ou_disk") == "Carol"
        assert store.get_p2p_chat_id("ou_disk") == "oc_dm"


class TestGetUserStore:
    def test_returns_store_when_present(self):
        store = FeishuUserStore(cache_path="/tmp/unused.json")
        adapter = SimpleNamespace(_user_store=store)
        assert get_user_store(adapter) is store

    def test_returns_none_for_missing_or_wrong_type(self):
        assert get_user_store(SimpleNamespace()) is None
        assert get_user_store(SimpleNamespace(_user_store="not-a-store")) is None