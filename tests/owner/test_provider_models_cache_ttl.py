"""C26: provider models cache TTL 24h + unchanged write-skip (§2.11)."""

from __future__ import annotations

from unittest.mock import patch

import hermes_cli.models as mod


def test_provider_models_cache_ttl_is_24h():
    assert mod._PROVIDER_MODELS_CACHE_TTL == 86400


def test_store_cache_entry_skips_disk_when_catalog_unchanged():
    existing = {
        "fp": "fp1",
        # [owner] C26 — skip-write only stands while `at` stays inside the skip window.
        "at": 98.0,
        "models": ["a", "b"],
        "fallback": False,
    }
    cache = {"openrouter": dict(existing)}
    entry = {
        "fp": "fp1",
        "at": 99.0,
        "models": ["b", "a"],  # same set, different order
        "fallback": False,
    }

    with patch.object(mod, "_load_provider_models_cache", return_value=cache), \
         patch.object(mod, "_save_provider_models_cache") as save, \
         patch("hermes_cli.models_cache_lock.write_under_cache_lock",
               side_effect=lambda _path, fn: fn()):
        mod._store_cache_entry("openrouter", entry)

    save.assert_not_called()
    # In-memory snapshot left alone (write_row returned early).
    assert cache["openrouter"]["at"] == 98.0


def test_store_cache_entry_rewrites_aged_at_when_catalog_unchanged():
    """[owner] C26 regression — fp/models/fallback identical but the stored `at` is aged past the
    skip window: the write must go through so `at` advances. b5e9c62d54 froze the timestamp here,
    leaving the row past-TTL forever: every read re-spawned an SWR refresh whose own write skipped."""
    import time

    cache = {"openrouter": {
        "fp": "fp1",
        "at": time.time() - mod._PROVIDER_MODELS_CACHE_TTL - 60,
        "models": ["a", "b"],
        "fallback": False,
    }}
    entry = {"fp": "fp1", "at": time.time(), "models": ["b", "a"], "fallback": False}

    with patch.object(mod, "_load_provider_models_cache", return_value=cache), \
         patch.object(mod, "_save_provider_models_cache") as save, \
         patch("hermes_cli.models_cache_lock.write_under_cache_lock",
               side_effect=lambda _path, fn: fn()):
        mod._store_cache_entry("openrouter", entry)

    save.assert_called_once()
    assert cache["openrouter"]["at"] == entry["at"]


def test_store_cache_entry_rewrites_when_incoming_at_is_older():
    """[owner] C26 — the window is symmetric: an incoming `at` older than the stored one past the
    window (aged test rows, clock step-back) must land on disk, not be dropped by the skip."""
    cache = {"openrouter": {"fp": "fp1", "at": 10_000.0, "models": ["a"], "fallback": False}}
    entry = {"fp": "fp1", "at": 1.0, "models": ["a"], "fallback": False}

    with patch.object(mod, "_load_provider_models_cache", return_value=cache), \
         patch.object(mod, "_save_provider_models_cache") as save, \
         patch("hermes_cli.models_cache_lock.write_under_cache_lock",
               side_effect=lambda _path, fn: fn()):
        mod._store_cache_entry("openrouter", entry)

    save.assert_called_once()
    assert cache["openrouter"]["at"] == 1.0


def test_store_cache_entry_rewrites_row_with_corrupt_at():
    """[owner] C26 — a corrupt stored `at` must not pin the row through the skip; the rewrite
    repairs the timestamp."""
    cache = {"openrouter": {"fp": "fp1", "at": "yesterday", "models": ["a"], "fallback": False}}
    entry = {"fp": "fp1", "at": 99.0, "models": ["a"], "fallback": False}

    with patch.object(mod, "_load_provider_models_cache", return_value=cache), \
         patch.object(mod, "_save_provider_models_cache") as save, \
         patch("hermes_cli.models_cache_lock.write_under_cache_lock",
               side_effect=lambda _path, fn: fn()):
        mod._store_cache_entry("openrouter", entry)

    save.assert_called_once()
    assert cache["openrouter"]["at"] == 99.0


def test_store_cache_entry_writes_when_models_change():
    cache = {
        "openrouter": {"fp": "fp1", "at": 1.0, "models": ["a"], "fallback": False},
    }
    entry = {"fp": "fp1", "at": 99.0, "models": ["a", "b"], "fallback": False}

    with patch.object(mod, "_load_provider_models_cache", return_value=cache), \
         patch.object(mod, "_save_provider_models_cache") as save, \
         patch("hermes_cli.models_cache_lock.write_under_cache_lock",
               side_effect=lambda _path, fn: fn()):
        mod._store_cache_entry("openrouter", entry)

    save.assert_called_once()
    assert cache["openrouter"]["models"] == ["a", "b"]
    assert cache["openrouter"]["at"] == 99.0


def test_models_config_allowlist_helper_exists():
    """§2.10 model-switch whitelist — covered by official has_explicit_models."""
    from hermes_cli.model_switch import _models_config_is_allowlist

    assert _models_config_is_allowlist(["a", "b"]) is True
    assert _models_config_is_allowlist({"x": {}}) is False


class _InlineThread:
    """Run the SWR refresh body synchronously in the caller's thread."""

    def __init__(self, target=None, daemon=None, name=None):
        self._target = target

    def start(self):
        self._target()


def test_swr_background_refresh_renews_aged_at(tmp_path, monkeypatch):
    """[owner] C26 e2e — a row past the 24h TTL whose fp/models are unchanged on the wire: the SWR
    background refresh must advance the stored `at` (row returns to the fresh tier). b5e9c62d54
    skipped that write, so the row stayed stale forever and every read re-spawned a refresh."""
    import time

    monkeypatch.setattr(mod, "_provider_models_cache_path",
                        lambda: tmp_path / "provider_models_cache.json")
    fp = "fp1"
    aged_at = time.time() - mod._PROVIDER_MODELS_CACHE_TTL - 60
    mod._save_provider_models_cache({
        "openrouter": {"fp": fp, "at": aged_at, "models": ["m1", "m2"]}})

    with patch.object(mod.threading, "Thread", _InlineThread), \
         patch.object(mod, "provider_model_ids", return_value=["m2", "m1"]), \
         patch.object(mod, "_credential_fingerprint", return_value=fp):
        mod._spawn_swr_refresh("openrouter")

    stored = mod._load_provider_models_cache()["openrouter"]
    assert stored["at"] > aged_at + mod._PROVIDER_MODELS_SKIP_WRITE_MAX_AT_AGE
    assert stored["models"] == ["m2", "m1"]
    assert stored["fp"] == fp


def test_swr_background_refresh_renews_aged_fallback_at(tmp_path, monkeypatch):
    """[owner] C26 e2e — same liveness for a curated fallback row past its short TTL: an unchanged
    degraded catalog still re-stamps `at`, instead of re-probing on every single read."""
    import time

    from hermes_cli.models_catalog_static import CuratedFallbackModels

    monkeypatch.setattr(mod, "_provider_models_cache_path",
                        lambda: tmp_path / "provider_models_cache.json")
    fp = "fp1"
    aged_at = time.time() - mod._PROVIDER_MODELS_FALLBACK_TTL - 60
    mod._save_provider_models_cache({
        "openrouter": {"fp": fp, "at": aged_at, "models": ["m1"], "fallback": True}})

    with patch.object(mod.threading, "Thread", _InlineThread), \
         patch.object(mod, "provider_model_ids", return_value=CuratedFallbackModels(["m1"])), \
         patch.object(mod, "_credential_fingerprint", return_value=fp):
        mod._spawn_swr_refresh("openrouter")

    stored = mod._load_provider_models_cache()["openrouter"]
    assert stored["fallback"] is True
    assert stored["at"] > aged_at + mod._PROVIDER_MODELS_SKIP_WRITE_MAX_AT_AGE
