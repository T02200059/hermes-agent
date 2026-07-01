"""Tests for plugins/platforms/feishu/adapter.py — WR-01 cache invalidation."""

from __future__ import annotations

import importlib
import sys
import types
from unittest.mock import patch

import pytest


def _fresh_adapter_module():
    """Import (or reimport) the adapter module to get a clean module
    state — both the success and warned-key caches are module-level."""
    import plugins.platforms.feishu.adapter as adapter

    return adapter


def test_owner_import_caches_successful_resolution():
    """A successful import is cached on the module — repeated calls
    don't re-import."""
    adapter = _fresh_adapter_module()
    adapter.invalidate_owner_imports()

    fake_module = types.ModuleType("owner.feishu.fake_present")
    fake_module.SomeClass = type("SomeClass", (), {})
    sys.modules["owner.feishu.fake_present"] = fake_module

    try:
        v1 = adapter._owner_import("owner.feishu.fake_present", "SomeClass")
        v2 = adapter._owner_import("owner.feishu.fake_present", "SomeClass")
        assert v1 is fake_module.SomeClass
        assert v2 is fake_module.SomeClass
        assert "owner.feishu.fake_present.SomeClass" in adapter._owner_lazy
    finally:
        del sys.modules["owner.feishu.fake_present"]


def test_owner_import_does_not_cache_transient_failure(monkeypatch):
    """WR-01: a transient ImportError must NOT be cached as permanent
    None. The next call must retry the import."""
    adapter = _fresh_adapter_module()
    adapter.invalidate_owner_imports()

    # Simulate: first call raises ImportError, second call succeeds.
    real_import_module = importlib.import_module
    call_count = {"n": 0}

    def flaky_import_module(name, *args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise ImportError("transient hot-reload failure")
        return real_import_module(name, *args, **kwargs)

    # Inject a real present module so the retry can succeed.
    fake_module = types.ModuleType("owner.feishu.flaky_recover")
    fake_module.Recovered = object()
    sys.modules["owner.feishu.flaky_recover"] = fake_module

    try:
        with patch.object(importlib, "import_module", side_effect=flaky_import_module):
            # First call: transient failure, returns None but does NOT cache.
            v1 = adapter._owner_import("owner.feishu.flaky_recover", "Recovered")
            assert v1 is None
            # Critically: NOT in either cache, so the next call retries.
            assert "owner.feishu.flaky_recover.Recovered" not in adapter._owner_lazy
            assert "owner.feishu.flaky_recover.Recovered" not in adapter._owner_lazy_absent

            # Second call: import_module succeeds, returns the real value.
            v2 = adapter._owner_import("owner.feishu.flaky_recover", "Recovered")
            assert v2 is fake_module.Recovered
            # Now cached for future calls.
            assert "owner.feishu.flaky_recover.Recovered" in adapter._owner_lazy
    finally:
        del sys.modules["owner.feishu.flaky_recover"]


def test_owner_import_warns_once_then_throttles(monkeypatch, caplog):
    """Repeated transient misses for the same key log a WARNING the
    first time only — subsequent misses stay silent (throttled)."""
    adapter = _fresh_adapter_module()
    adapter.invalidate_owner_imports()

    def always_fail(name, *args, **kwargs):
        raise ImportError("owner module genuinely missing")

    import logging

    with patch.object(importlib, "import_module", side_effect=always_fail), \
         caplog.at_level(logging.WARNING, logger=adapter.logger.name):
        for _ in range(5):
            v = adapter._owner_import("owner.feishu.never_present", "Nope")
            assert v is None
        warns = [
            r for r in caplog.records
            if "owner.feishu.never_present.Nope" in r.getMessage()
        ]
        assert len(warns) == 1, f"expected 1 throttled warning, got {len(warns)}"


def test_invalidate_owner_imports_clears_caches():
    """invalidate_owner_imports() drops both _owner_lazy and the
    confirmed-absent set, so the next call retries the import."""
    adapter = _fresh_adapter_module()
    adapter.invalidate_owner_imports()

    # Populate both caches.
    adapter._owner_lazy["x.y.Z"] = "cached"
    adapter._owner_lazy_absent.add("a.b.C")

    adapter.invalidate_owner_imports()

    assert adapter._owner_lazy == {}
    assert adapter._owner_lazy_absent == set()
