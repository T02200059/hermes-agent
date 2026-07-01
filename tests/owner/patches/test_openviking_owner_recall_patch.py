"""Tests for owner OpenViking recall patch (advisory/dedup/recall-card)."""

from unittest.mock import patch

import pytest

from owner.patches.openviking_owner_recall_patch import (
    _dedup_uri_canonical,
    _dedup_peer_mirrors,
    apply_patch,
    build_viking_recall_card,
    build_viking_recall_text,
    revert_patch,
)
from owner.patches.openviking_recall_config import (
    load_recall_card_config,
    load_sync_recall_config,
)


@pytest.fixture(autouse=True)
def _cleanup_patch():
    """Ensure patch is reverted after each test."""
    revert_patch()
    yield
    revert_patch()


class TestAdvisoryMemoryContext:
    """ Advisory wording replaces the authoritative system note. """

    def test_advisory_wording(self):
        apply_patch()
        import agent.memory_manager as mm

        block = mm.build_memory_context_block("some context")
        assert "helpful hints, not authoritative facts" in block
        assert "authoritative reference data" not in block
        assert "<memory-context>" in block

    def test_advisory_empty_context(self):
        apply_patch()
        import agent.memory_manager as mm

        assert mm.build_memory_context_block("") == ""
        assert mm.build_memory_context_block("   ") == ""


class TestPeerMirrorDedup:
    """ Peer-mirror URIs collapse to the owner URI for deduplication. """

    def test_dedup_uri_canonical_strips_peer_segment(self):
        owner = "viking://user/yangtb/memories/events/x.md"
        peer = "viking://user/yangtb/peers/hermes/memories/events/x.md"
        assert _dedup_uri_canonical(owner) == owner
        assert _dedup_uri_canonical(peer) == owner
        assert _dedup_uri_canonical("") == ""

    def test_dedup_peer_mirrors_keeps_first(self):
        owner = {"uri": "viking://user/yangtb/memories/events/x.md", "score": 0.9}
        peer = {"uri": "viking://user/yangtb/peers/hermes/memories/events/x.md", "score": 0.85}
        other = {"uri": "viking://user/yangtb/memories/events/y.md", "score": 0.7}
        result = _dedup_peer_mirrors([owner, peer, other])
        assert len(result) == 2
        assert result[0] is owner
        assert result[1] is other

    def test_dedup_peer_mirrors_keeps_peer_only(self):
        """A peer-only hit is kept when no owner copy exists."""
        peer = {"uri": "viking://user/yangtb/peers/hermes/memories/events/x.md", "score": 0.85}
        result = _dedup_peer_mirrors([peer])
        assert len(result) == 1
        assert result[0] is peer

    def test_patched_select_recall_candidates_dedups_peer_mirrors(self):
        """The patched _select_recall_candidates collapses peer mirrors."""
        apply_patch()
        from plugins.memory.openviking import OpenVikingMemoryProvider

        owner = {"uri": "viking://user/yangtb/memories/events/x.md", "score": 0.9, "abstract": "x"}
        peer = {"uri": "viking://user/yangtb/peers/hermes/memories/events/x.md", "score": 0.85, "abstract": "x"}
        other = {"uri": "viking://user/yangtb/memories/events/y.md", "score": 0.7, "abstract": "y"}
        selected = OpenVikingMemoryProvider._select_recall_candidates(
            [owner, peer, other],
            "query",
            limit=10,
            score_threshold=0.0,
        )
        uris = {h.get("uri", "") for h in selected}
        assert len(selected) == 2
        assert peer["uri"] not in uris
        assert owner["uri"] in uris
        assert other["uri"] in uris


class TestConfigDefaults:
    """ patch.yaml config helpers return expected defaults. """

    def test_sync_recall_defaults(self, monkeypatch):
        monkeypatch.delenv("OPENVIKING_ADVISORY_MEMORY", raising=False)
        cfg = load_sync_recall_config()
        assert cfg["advisory"] is True
        assert cfg["dedup"] is True
        assert cfg["top_n"] == 6

    def test_recall_card_defaults(self, monkeypatch):
        monkeypatch.delenv("OPENVIKING_RECALL_DISPLAY", raising=False)
        monkeypatch.delenv("OPENVIKING_RECALL_FEISHU_CARD", raising=False)
        monkeypatch.delenv("OPENVIKING_RECALL_QQBOT_TEXT", raising=False)
        cfg = load_recall_card_config()
        assert cfg["enabled"] is True
        assert cfg["feishu_card"] is True
        assert cfg["qqbot_text"] is True


class TestRecallCardBuilders:
    """ Feishu card and QQ text builders produce expected output. """

    def test_build_viking_recall_card_title(self):
        hits = [
            {"uri": "viking://u/m/x.md", "score": 0.9, "abstract": "something", "type": "memory"},
        ]
        card = build_viking_recall_card(hits, elapsed_ms=42)
        assert card is not None
        assert card["header"]["title"]["content"] == "🧠 知识库召回"

    def test_build_viking_recall_card_empty(self):
        assert build_viking_recall_card([], elapsed_ms=0) is None

    def test_build_viking_recall_text_contains_header(self):
        hits = [
            {"uri": "viking://u/m/x.md", "score": 0.9, "abstract": "something", "type": "memory"},
        ]
        text = build_viking_recall_text(hits, elapsed_ms=42)
        assert "OpenViking 召回" in text
        assert "0.900" in text

    def test_build_viking_recall_text_empty(self):
        assert build_viking_recall_text([], elapsed_ms=0) == ""


class TestPatchIdempotency:
    """ apply/revert can be repeated safely. """

    def test_apply_revert_idempotent(self):
        apply_patch()
        apply_patch()
        revert_patch()
        revert_patch()
