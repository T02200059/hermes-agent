"""Tests for owner.feishu.user_cache."""

import json
import tempfile
import time
from pathlib import Path

from owner.feishu.user_cache import (
    USER_CACHE_VERSION,
    FeishuUserEntry,
    cache_p2p_chat_id,
    get_cached_chat_id,
    get_cached_display_name,
    get_user_entry,
    load_user_cache,
    save_user_cache,
    set_cached_display_name,
)


class TestFeishuUserEntry:
    def test_defaults(self):
        e = FeishuUserEntry()
        assert e.display_name == ""
        assert e.display_name_expire_at == 0.0
        assert e.p2p_chat_id == ""
        assert e.last_seen_at == 0.0

    def test_can_set_fields(self):
        e = FeishuUserEntry()
        e.display_name = "Alice"
        e.p2p_chat_id = "oc_123"
        assert e.display_name == "Alice"
        assert e.p2p_chat_id == "oc_123"


class TestGetUserEntry:
    def test_create_new(self):
        cache = {}
        entry = get_user_entry(cache, "open_id_1")
        assert isinstance(entry, FeishuUserEntry)
        assert "open_id_1" in cache
        assert entry.last_seen_at > 0

    def test_update_existing(self):
        cache = {}
        e1 = get_user_entry(cache, "open_id_2")
        e1.display_name = "Bob"
        ts = e1.last_seen_at
        e2 = get_user_entry(cache, "open_id_2")
        assert e2 is e1
        assert e2.display_name == "Bob"
        assert e2.last_seen_at >= ts


class TestDisplayNameCache:
    def test_set_and_get_within_ttl(self):
        cache = {}
        expire = time.time() + 600
        set_cached_display_name(cache, "ou_a", "Alice", expire)
        assert get_cached_display_name(cache, "ou_a") == "Alice"

    def test_expired_display_name_evicted(self):
        cache = {}
        set_cached_display_name(cache, "ou_a", "Alice", time.time() - 1)
        assert get_cached_display_name(cache, "ou_a") is None
        assert cache["ou_a"].display_name == ""


class TestCacheP2pChatId:
    def test_writes_new_mapping(self):
        cache = {}
        assert cache_p2p_chat_id(cache, "ou_a", "oc_dm1") is True
        assert get_cached_chat_id(cache, "ou_a") == "oc_dm1"

    def test_noop_when_unchanged(self):
        cache = {}
        cache_p2p_chat_id(cache, "ou_a", "oc_dm1")
        assert cache_p2p_chat_id(cache, "ou_a", "oc_dm1") is False

    def test_updates_changed_chat_id(self):
        cache = {}
        cache_p2p_chat_id(cache, "ou_a", "oc_old")
        assert cache_p2p_chat_id(cache, "ou_a", "oc_new") is True
        assert get_cached_chat_id(cache, "ou_a") == "oc_new"

    def test_skips_empty_ids(self):
        cache = {}
        assert cache_p2p_chat_id(cache, "", "oc_x") is False
        assert cache_p2p_chat_id(cache, "ou_a", "") is False


class TestGetCachedChatId:
    def test_hit(self):
        cache = {}
        entry = get_user_entry(cache, "o1")
        entry.p2p_chat_id = "chat_abc"
        assert get_cached_chat_id(cache, "o1") == "chat_abc"

    def test_miss(self):
        assert get_cached_chat_id({}, "unknown") is None

    def test_empty_chat_id_returns_none(self):
        cache = {}
        get_user_entry(cache, "o1")
        assert get_cached_chat_id(cache, "o1") is None


class TestLoadUserCache:
    def test_loads_v1_flat_json(self):
        path = Path(tempfile.mktemp(suffix=".json"))
        path.write_text(json.dumps({"o1": "chat_x", "o2": "chat_y"}))
        cache = {}
        try:
            load_user_cache(str(path), cache)
            assert cache["o1"].p2p_chat_id == "chat_x"
            assert cache["o2"].p2p_chat_id == "chat_y"
        finally:
            path.unlink(missing_ok=True)

    def test_loads_v2_json(self):
        path = Path(tempfile.mktemp(suffix=".json"))
        expire = time.time() + 600
        path.write_text(
            json.dumps(
                {
                    "_version": USER_CACHE_VERSION,
                    "users": {
                        "o1": {
                            "p2p_chat_id": "chat_x",
                            "display_name": "Alice",
                            "display_name_expire_at": expire,
                        }
                    },
                }
            )
        )
        cache = {}
        try:
            load_user_cache(str(path), cache)
            assert cache["o1"].p2p_chat_id == "chat_x"
            assert cache["o1"].display_name == "Alice"
        finally:
            path.unlink(missing_ok=True)

    def test_missing_file_is_silent(self):
        cache = {}
        load_user_cache("/no/such/file.json", cache)
        assert cache == {}

    def test_invalid_json_is_silent(self):
        path = Path(tempfile.mktemp(suffix=".json"))
        path.write_text("{bad json")
        cache = {}
        try:
            load_user_cache(str(path), cache)
            assert cache == {}
        finally:
            path.unlink(missing_ok=True)

    def test_skips_non_dict_toplevel(self):
        path = Path(tempfile.mktemp(suffix=".json"))
        path.write_text("[1, 2, 3]")
        cache = {}
        try:
            load_user_cache(str(path), cache)
            assert cache == {}
        finally:
            path.unlink(missing_ok=True)

    def test_v1_skips_non_string_values(self):
        path = Path(tempfile.mktemp(suffix=".json"))
        path.write_text(json.dumps({"o1": 123, "o2": "valid"}))
        cache = {}
        try:
            load_user_cache(str(path), cache)
            assert "o1" not in cache
            assert cache["o2"].p2p_chat_id == "valid"
        finally:
            path.unlink(missing_ok=True)


class TestSaveUserCache:
    def test_saves_v2_snapshot(self):
        path = Path(tempfile.mktemp(suffix=".json"))
        cache = {}
        e = get_user_entry(cache, "o1")
        e.p2p_chat_id = "chat_z"
        e2 = get_user_entry(cache, "o2")
        try:
            save_user_cache(str(path), cache)
            data = json.loads(path.read_text())
            assert data["_version"] == USER_CACHE_VERSION
            assert data["users"]["o1"]["p2p_chat_id"] == "chat_z"
            assert "o2" not in data["users"]
        finally:
            path.unlink(missing_ok=True)

    def test_save_empty_cache(self):
        path = Path(tempfile.mktemp(suffix=".json"))
        try:
            save_user_cache(str(path), {})
            data = json.loads(path.read_text())
            assert data == {"_version": USER_CACHE_VERSION, "users": {}}
        finally:
            path.unlink(missing_ok=True)