"""C26: provider models cache TTL 24h + unchanged write-skip (§2.11)."""

from __future__ import annotations

from unittest.mock import patch

import hermes_cli.models as mod


def test_provider_models_cache_ttl_is_24h():
    assert mod._PROVIDER_MODELS_CACHE_TTL == 86400


def test_store_cache_entry_skips_disk_when_catalog_unchanged():
    existing = {
        "fp": "fp1",
        "at": 1.0,
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
    assert cache["openrouter"]["at"] == 1.0


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
