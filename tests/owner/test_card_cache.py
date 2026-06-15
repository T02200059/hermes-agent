"""Tests for owner/feishu/card_cache.py — TTL-based cache with eviction."""

import time
from unittest import mock

from owner.feishu.card_cache import cache_get, cache_put, CARD_CACHE_TTL_SEC


class TestCachePut:
    def test_put_adds_entry_with_timestamp(self):
        cache: dict = {}
        cache_put(cache, "key1", {"data": "hello"})
        assert "key1" in cache
        assert cache["key1"]["data"] == "hello"
        assert "_ts" in cache["key1"]

    def test_put_evicts_expired_entries(self):
        cache: dict = {}
        now = time.time()
        # Seed an expired entry
        cache["old"] = {"data": "stale", "_ts": now - CARD_CACHE_TTL_SEC - 10}
        cache_put(cache, "key1", {"data": "fresh"})
        assert "old" not in cache
        assert "key1" in cache

    def test_put_keeps_non_expired_entries(self):
        cache: dict = {}
        now = time.time()
        cache["old"] = {"data": "still-good", "_ts": now - 30}
        cache_put(cache, "key1", {"data": "fresh"})
        assert "old" in cache
        assert "key1" in cache


class TestCacheGet:
    def test_get_returns_value_for_valid_entry(self):
        cache: dict = {}
        cache_put(cache, "key1", {"data": "hello"})
        result = cache_get(cache, "key1")
        assert result is not None
        assert result["data"] == "hello"

    def test_get_returns_none_for_missing_key(self):
        cache: dict = {}
        assert cache_get(cache, "nonexistent") is None

    def test_get_returns_none_for_expired_entry_and_deletes(self):
        cache: dict = {}
        now = time.time()
        cache["old"] = {"data": "stale", "_ts": now - CARD_CACHE_TTL_SEC - 10}
        result = cache_get(cache, "old")
        assert result is None
        assert "old" not in cache


class TestCacheTTLBoundary:
    def test_entry_just_before_expiry_is_still_valid(self):
        cache: dict = {}
        now = time.time()
        cache["recent"] = {"_ts": now - CARD_CACHE_TTL_SEC + 60}
        assert cache_get(cache, "recent") is not None

    def test_entry_exactly_at_expiry_is_expired(self):
        cache: dict = {}
        now = time.time()
        # Put well into the future — ">" means > TTL_SEC, so exactly TTL may
        # still be valid if < 1 ms has elapsed, or expired if 1+ ms elapsed.
        # Test the non-flaky case: well past TTL.
        cache["expired"] = {"_ts": now - CARD_CACHE_TTL_SEC - 1}
        assert cache_get(cache, "expired") is None
        # Entry within TTL is still valid.
        cache["fresh"] = {"_ts": now - 1}
        assert cache_get(cache, "fresh") is not None
