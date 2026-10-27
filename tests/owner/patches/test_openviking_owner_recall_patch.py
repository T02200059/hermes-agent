"""[owner] C15 — OpenViking advisory + peer-mirror dedup (no recall card)."""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import pytest

from owner.patches import openviking_owner_recall_patch as ov
from owner.patches import openviking_recall_config as cfg


class TestDedupHelpers:
    def test_canonical_strips_peers_segment(self):
        uri = "viking://user/yangtb/peers/hermes/memories/events/x.md"
        assert ov._dedup_uri_canonical(uri) == (
            "viking://user/yangtb/memories/events/x.md"
        )

    def test_peer_mirror_keeps_first(self):
        items = [
            {"uri": "viking://user/a/memories/x.md", "score": 0.9},
            {"uri": "viking://user/a/peers/bot/memories/x.md", "score": 0.8},
            {"uri": "viking://user/a/memories/y.md", "score": 0.7},
        ]
        out = ov._dedup_peer_mirrors(items)
        assert [i["uri"] for i in out] == [
            "viking://user/a/memories/x.md",
            "viking://user/a/memories/y.md",
        ]

    def test_empty_uri_kept(self):
        items = [{"uri": "", "score": 0.1}, {"uri": "viking://user/a/memories/x.md"}]
        out = ov._dedup_peer_mirrors(items)
        assert len(out) == 2


class TestAdvisoryBlock:
    def test_empty_returns_empty(self):
        assert ov._build_advisory_memory_context_block("") == ""
        assert ov._build_advisory_memory_context_block("   ") == ""

    def test_wraps_with_advisory_note(self):
        block = ov._build_advisory_memory_context_block("Summary: hello")
        assert block.startswith("<memory-context>")
        assert "advisory reference" in block
        assert "viking_read" in block
        assert "authoritative reference data" not in block
        assert "Summary: hello" in block
        assert block.endswith("</memory-context>")


class TestConfig:
    def test_defaults_without_overlay_keys(self, monkeypatch):
        monkeypatch.setattr(cfg, "load_owner_config", lambda: {})
        monkeypatch.delenv("OPENVIKING_ADVISORY_MEMORY", raising=False)
        got = cfg.load_sync_recall_config()
        assert got == {"advisory": True, "dedup": True}

    def test_openviking_key_preferred(self, monkeypatch):
        monkeypatch.setattr(
            cfg,
            "load_owner_config",
            lambda: {
                "openviking": {"advisory": False, "dedup": False},
                "openviking_sync_recall": {"advisory": True, "dedup": True},
            },
        )
        got = cfg.load_sync_recall_config()
        assert got == {"advisory": False, "dedup": False}

    def test_legacy_key_fallback(self, monkeypatch):
        monkeypatch.setattr(
            cfg,
            "load_owner_config",
            lambda: {"openviking_sync_recall": {"advisory": False}},
        )
        got = cfg.load_sync_recall_config()
        assert got["advisory"] is False
        assert got["dedup"] is True


class TestApplyAdvisory:
    def test_apply_and_revert_swaps_memory_context(self):
        import agent.memory_context as mc

        before = mc.build_memory_context_block
        try:
            ov.revert_patch()
            ov.apply_patch(advisory=True, dedup=False)
            assert mc.build_memory_context_block is ov._build_advisory_memory_context_block
            block = mc.build_memory_context_block("note")
            assert "advisory reference" in block
        finally:
            ov.revert_patch()
        assert mc.build_memory_context_block is before


class TestApplyDedup:
    def test_dedup_wraps_provider_classmethod(self):
        # Build a fake provider module so we don't need the real plugin.
        fake = ModuleType("hermes_plugins.openviking")

        class OpenVikingMemoryProvider:
            @classmethod
            def _select_recall_candidates(cls, items, query, *, limit, score_threshold):
                return list(items)[:limit]

        fake.OpenVikingMemoryProvider = OpenVikingMemoryProvider
        sys.modules["hermes_plugins.openviking"] = fake
        try:
            ov.revert_patch()
            ov.apply_patch(advisory=False, dedup=True)
            assert ov._applied["dedup"] is True
            items = [
                {"uri": "viking://user/a/memories/x.md"},
                {"uri": "viking://user/a/peers/bot/memories/x.md"},
            ]
            selected = OpenVikingMemoryProvider._select_recall_candidates(
                items, "q", limit=10, score_threshold=0.0
            )
            assert [i["uri"] for i in selected] == [
                "viking://user/a/memories/x.md"
            ]
        finally:
            ov.revert_patch()
            sys.modules.pop("hermes_plugins.openviking", None)

    def test_dedup_skips_cleanly_without_provider(self, monkeypatch):
        monkeypatch.setattr(
            ov,
            "_resolve_ov_provider_cls",
            lambda: (_ for _ in ()).throw(ImportError("missing")),
        )
        ov.revert_patch()
        ov.apply_patch(advisory=False, dedup=True)
        assert ov._applied["dedup"] is False
