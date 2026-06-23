"""Tests for owner/patches/openviking_sync_recall_patch.py."""

from __future__ import annotations

import logging
from typing import Any, Dict

import pytest

import agent.memory_manager as memory_manager
from owner.patches.openviking_sync_recall_patch import (
    _build_advisory_memory_context_block,
    _noop_queue_prefetch,
    _sync_prefetch,
    apply_patch,
    revert_patch,
)
from plugins.memory.openviking import OpenVikingMemoryProvider


@pytest.fixture(autouse=True)
def _clean_env_and_patch(monkeypatch):
    """Start each test with a clean environment and a reverted patch."""
    for name in (
        "OPENVIKING_SYNC_RECALL",
        "OPENVIKING_ADVISORY_MEMORY",
        "OPENVIKING_SEARCH_TIMEOUT",
    ):
        monkeypatch.delenv(name, raising=False)
    # The sync patch auto-mounts the card patch; revert both to avoid leakage.
    from owner.patches.openviking_recall_card_patch import revert_patch as revert_card

    revert_card()
    revert_patch()
    yield
    revert_card()
    revert_patch()


class _MockResponse:
    def __init__(self, json_data: Dict[str, Any], status_code: int = 200):
        self._json_data = json_data
        self.status_code = status_code

    def json(self) -> Dict[str, Any]:
        return self._json_data


def _make_provider() -> OpenVikingMemoryProvider:
    """Return a minimally initialized OpenVikingMemoryProvider instance."""
    provider = OpenVikingMemoryProvider()
    provider._endpoint = "http://localhost:1933"
    provider._api_key = ""
    provider._account = "default"
    provider._user = "default"
    provider._agent = "hermes"
    provider._client = object()  # truthy placeholder to pass the guard
    return provider


def test_default_env_vars_enable_patch():
    """With no env vars set, apply_patch enables both sync and advisory."""
    from owner.patches.openviking_recall_card_patch import revert_patch as revert_card

    apply_patch()
    # The sync patch auto-mounts the recall card patch, which wraps prefetch.
    # Revert the card wrapper so we can verify the sync patch itself is in place.
    revert_card()
    assert OpenVikingMemoryProvider.prefetch is _sync_prefetch
    assert OpenVikingMemoryProvider.queue_prefetch is _noop_queue_prefetch
    assert memory_manager.build_memory_context_block is _build_advisory_memory_context_block


def test_sync_recall_disabled(monkeypatch):
    """OPENVIKING_SYNC_RECALL=0 leaves prefetch/queue_prefetch unchanged."""
    from owner.patches.openviking_recall_card_patch import revert_patch as revert_card

    monkeypatch.setenv("OPENVIKING_SYNC_RECALL", "0")
    original_prefetch = OpenVikingMemoryProvider.prefetch
    original_queue_prefetch = OpenVikingMemoryProvider.queue_prefetch
    apply_patch()
    # The sync patch auto-mounts the recall card patch; unwrap for identity check.
    revert_card()
    assert OpenVikingMemoryProvider.prefetch is original_prefetch
    assert OpenVikingMemoryProvider.queue_prefetch is original_queue_prefetch
    assert memory_manager.build_memory_context_block is _build_advisory_memory_context_block


def test_advisory_memory_disabled(monkeypatch):
    """OPENVIKING_ADVISORY_MEMORY=0 leaves build_memory_context_block unchanged."""
    from owner.patches.openviking_recall_card_patch import revert_patch as revert_card

    monkeypatch.setenv("OPENVIKING_ADVISORY_MEMORY", "0")
    original_build = memory_manager.build_memory_context_block
    apply_patch()
    # Unwrap the auto-mounted recall card patch for identity checks.
    revert_card()
    assert memory_manager.build_memory_context_block is original_build
    assert OpenVikingMemoryProvider.prefetch is _sync_prefetch
    assert OpenVikingMemoryProvider.queue_prefetch is _noop_queue_prefetch


def test_apply_and_revert_idempotent():
    """apply_patch and revert_patch can be called repeatedly without corruption."""
    from owner.patches.openviking_recall_card_patch import revert_patch as revert_card

    original_prefetch = OpenVikingMemoryProvider.prefetch
    original_queue_prefetch = OpenVikingMemoryProvider.queue_prefetch
    original_build = memory_manager.build_memory_context_block

    apply_patch()
    apply_patch()
    revert_card()  # unwrap auto-mounted card patch for identity checks
    assert OpenVikingMemoryProvider.prefetch is _sync_prefetch

    revert_patch()
    assert OpenVikingMemoryProvider.prefetch is original_prefetch
    assert OpenVikingMemoryProvider.queue_prefetch is original_queue_prefetch
    assert memory_manager.build_memory_context_block is original_build

    revert_patch()  # second revert should be a no-op
    assert OpenVikingMemoryProvider.prefetch is original_prefetch

    apply_patch()
    revert_card()  # unwrap auto-mounted card patch for identity check
    assert OpenVikingMemoryProvider.prefetch is _sync_prefetch


def test_sync_prefetch_success(monkeypatch):
    """Synchronously fetch ranked memories/resources and format them."""
    captured: Dict[str, Any] = {}

    def mock_post(url, **kwargs):
        captured["url"] = url
        captured["timeout"] = kwargs.get("timeout")
        return _MockResponse(
            {
                "result": {
                    "memories": [
                        {
                            "uri": "viking://memories/preferences/a",
                            "abstract": "User prefers dark mode",
                            "score": 0.95,
                        }
                    ],
                    "resources": [
                        {
                            "uri": "viking://resources/docs/b",
                            "abstract": "Project uses pytest",
                            "score": 0.88,
                        }
                    ],
                }
            }
        )

    monkeypatch.setattr("httpx.post", mock_post)
    apply_patch()

    provider = _make_provider()
    result = provider.prefetch("what do you know about me")

    assert captured["timeout"] == 10.0
    assert captured["url"].endswith("/api/v1/search/find")
    assert "## OpenViking Context" in result
    assert "User prefers dark mode" in result
    assert "Project uses pytest" in result
    assert "[0.95]" in result
    assert "[0.88]" in result


def test_sync_prefetch_timeout(monkeypatch, caplog):
    """A timeout exception returns an empty string and logs a warning."""
    import httpx

    def mock_post(url, **kwargs):
        raise httpx.TimeoutException("OpenViking timed out")

    monkeypatch.setattr("httpx.post", mock_post)
    apply_patch()

    provider = _make_provider()
    with caplog.at_level(logging.WARNING, logger="owner.patches.openviking_sync_recall_patch"):
        result = provider.prefetch("anything")

    assert result == ""
    assert any("OpenViking synchronous prefetch failed" in rec.message for rec in caplog.records)


def test_sync_prefetch_connection_error(monkeypatch, caplog):
    """Any network/parse exception returns an empty string and logs a warning."""
    import httpx

    def mock_post(url, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("httpx.post", mock_post)
    apply_patch()

    provider = _make_provider()
    with caplog.at_level(logging.WARNING, logger="owner.patches.openviking_sync_recall_patch"):
        result = provider.prefetch("anything")

    assert result == ""
    assert any("OpenViking synchronous prefetch failed" in rec.message for rec in caplog.records)


def test_advisory_wording():
    """The memory-context block uses advisory language, not authoritative."""
    apply_patch()

    block = memory_manager.build_memory_context_block("- [0.9] User likes tea")
    text = block.lower()

    assert block.startswith("<memory-context>")
    assert block.rstrip().endswith("</memory-context>")
    assert "NOT new user input" in block
    assert "may help inform" in text
    assert "only when relevant" in text
    assert "helpful hints" in text

    # Old authoritative phrases must be gone.
    assert "authoritative reference data" not in text
    assert "should inform all responses" not in text
    assert "this is the agent's persistent memory" not in text


def test_queue_prefetch_is_noop():
    """queue_prefetch replacement does nothing and returns None."""
    apply_patch()
    provider = _make_provider()
    assert provider.queue_prefetch("query") is None


import owner.patches.openviking_recall_config as recall_config


def test_patch_yaml_overrides_env(monkeypatch):
    """patch.yaml enabled=false wins over OPENVIKING_SYNC_RECALL=1."""
    from owner.patches.openviking_recall_card_patch import revert_patch as revert_card

    monkeypatch.setenv("OPENVIKING_SYNC_RECALL", "1")
    monkeypatch.setattr(
        recall_config,
        "_read_patch_yaml",
        lambda: {"owner": {"openviking_sync_recall": {"enabled": False}}},
    )
    original_prefetch = OpenVikingMemoryProvider.prefetch
    apply_patch()
    revert_card()  # unwrap auto-mounted card patch for identity check
    assert OpenVikingMemoryProvider.prefetch is original_prefetch


def test_patch_yaml_sets_search_timeout(monkeypatch):
    """patch.yaml search_timeout is used by the synchronous HTTP call."""
    captured: Dict[str, Any] = {}

    def mock_post(url, **kwargs):
        captured["timeout"] = kwargs.get("timeout")
        return _MockResponse(
            {
                "result": {
                    "memories": [
                        {
                            "uri": "viking://memories/preferences/a",
                            "abstract": "User prefers dark mode",
                            "score": 0.95,
                        }
                    ]
                }
            }
        )

    monkeypatch.setattr("httpx.post", mock_post)
    monkeypatch.setattr(
        recall_config,
        "_read_patch_yaml",
        lambda: {"owner": {"openviking_sync_recall": {"search_timeout": 5}}},
    )
    apply_patch()

    provider = _make_provider()
    provider.prefetch("what do you know about me")

    assert captured["timeout"] == 5.0


def test_force_sync_param_wins_over_patch_yaml(monkeypatch):
    """apply_patch(force_sync=True) applies even when patch.yaml says false."""
    from owner.patches.openviking_recall_card_patch import revert_patch as revert_card

    monkeypatch.setattr(
        recall_config,
        "_read_patch_yaml",
        lambda: {"owner": {"openviking_sync_recall": {"enabled": False}}},
    )
    apply_patch(force_sync=True)
    revert_card()  # unwrap auto-mounted card patch for identity check
    assert OpenVikingMemoryProvider.prefetch is _sync_prefetch
    assert OpenVikingMemoryProvider.queue_prefetch is _noop_queue_prefetch


# ---------------------------------------------------------------------------
# recall-dedup tests (T1-T8 in owner/patches/openviking_sync_recall_patch.DEDUP_DESIGN.md)
# ---------------------------------------------------------------------------


def test_recall_dedup_no_duplicates(monkeypatch):
    """T1: 10 unique hits → top_n=6 by score, no dedup log."""
    hits_memories = [
        {"uri": f"viking://user/yangtb/memories/e/{i}.md",
         "abstract": f"unique memory {i}", "score": round(0.9 - i * 0.05, 3)}
        for i in range(5)
    ]
    hits_resources = [
        {"uri": f"viking://user/yangtb/resources/d/{i}.md",
         "abstract": f"unique doc {i}", "score": round(0.8 - i * 0.05, 3)}
        for i in range(5)
    ]
    monkeypatch.setattr(
        "httpx.post",
        lambda *a, **kw: _MockResponse(
            {"result": {"memories": hits_memories, "resources": hits_resources}}),
    )
    apply_patch()
    provider = _make_provider()
    out = provider.prefetch("anything")
    # 6 lines under ## OpenViking Context
    lines = [l for l in out.splitlines() if l.startswith("- [")]
    assert len(lines) == 6
    assert len(provider._recall_card_hits) == 6


def test_recall_dedup_peer_mirrors(monkeypatch):
    """T2: 3 peer-mirror duplicates collapse; top_n=6 by score."""
    owner_uri = "viking://user/yangtb/memories/events/2026/06/22/{name}.md"
    peer_uri = "viking://user/yangtb/peers/hermes/memories/events/2026/06/22/{name}.md"
    dup_pairs = [
        ("sop_recorded.md", "viking_delete SOP procedure", 0.561),
        ("peer_mirror_deleted.md", "deletion SOP for peer mirrors", 0.458),
        ("dedup_root_cause.md", "root cause of recall dedup issue", 0.402),
    ]
    memories = []
    for name, abstract, score in dup_pairs:
        # owner copy
        memories.append({"uri": owner_uri.format(name=name),
                         "abstract": abstract, "score": score})
        # peer mirror — same abstract + score, different URI
        memories.append({"uri": peer_uri.format(name=name),
                         "abstract": abstract, "score": score})
    # 6 memories (3 owner + 3 peer) + 4 unique = 10 total
    memories += [
        {"uri": "viking://user/yangtb/memories/events/x1.md",
         "abstract": "unique A", "score": 0.35},
        {"uri": "viking://user/yangtb/memories/events/x2.md",
         "abstract": "unique B", "score": 0.30},
        {"uri": "viking://user/yangtb/memories/entities/n1.md",
         "abstract": "unique C", "score": 0.25},
        {"uri": "viking://user/yangtb/memories/events/x3.md",
         "abstract": "unique D", "score": 0.20},
    ]
    monkeypatch.setattr(
        "httpx.post",
        lambda *a, **kw: _MockResponse({"result": {"memories": memories, "resources": []}}),
    )
    apply_patch()
    provider = _make_provider()
    out = provider.prefetch("peers SOP")
    lines = [l for l in out.splitlines() if l.startswith("- [")]
    # 7 unique after dedup, top_n=6 → 6 lines
    assert len(lines) == 6
    assert len(provider._recall_card_hits) == 6
    # peer-mirror URIs must NOT appear in card_hits (they were dropped)
    assert all("/peers/hermes/" not in h.get("uri", "") for h in provider._recall_card_hits)


def test_recall_dedup_cross_bucket(monkeypatch):
    """T3: Same abstract in memories AND resources → only one survives."""
    shared = "shared abstract about deployment"
    monkeypatch.setattr(
        "httpx.post",
        lambda *a, **kw: _MockResponse({"result": {
            "memories": [{"uri": "viking://m/a.md", "abstract": shared, "score": 0.7}],
            "resources": [{"uri": "viking://r/a.md", "abstract": shared, "score": 0.7}],
        }}),
    )
    apply_patch()
    provider = _make_provider()
    provider.prefetch("deployment")
    assert len(provider._recall_card_hits) == 1
    # First-seen wins (memories bucket iterates first in current order).
    # Note: ctx_type[:-1] gives "memorie" / "resource" (existing convention).
    assert provider._recall_card_hits[0]["type"] == "memorie"


def test_recall_dedup_keeps_peer_only(monkeypatch):
    """T4: A peer-only URI (no owner copy) must survive dedup."""
    monkeypatch.setattr(
        "httpx.post",
        lambda *a, **kw: _MockResponse({"result": {
            "memories": [{
                "uri": "viking://user/yangtb/peers/hermes/memories/entities/节点配置/node010 OpenViking.md",
                "abstract": "node010 OpenViking configuration", "score": 0.5}],
            "resources": [],
        }}),
    )
    apply_patch()
    provider = _make_provider()
    out = provider.prefetch("node010")
    assert "node010 OpenViking" in out
    assert len(provider._recall_card_hits) == 1


def test_recall_dedup_disabled(monkeypatch):
    """T5: dedup=false restores pre-patch behavior (peer mirrors surface)."""
    monkeypatch.setattr(
        recall_config, "_read_patch_yaml",
        lambda: {"owner": {"openviking_sync_recall": {"dedup": False}}},
    )
    owner = "viking://user/yangtb/memories/x.md"
    peer = "viking://user/yangtb/peers/hermes/memories/x.md"
    monkeypatch.setattr(
        "httpx.post",
        lambda *a, **kw: _MockResponse({"result": {
            "memories": [
                {"uri": owner, "abstract": "same", "score": 0.5},
                {"uri": peer, "abstract": "same", "score": 0.5},
            ],
            "resources": [],
        }}),
    )
    apply_patch()
    provider = _make_provider()
    provider.prefetch("x")
    # Without dedup, both copies appear (back-compat path)
    assert len(provider._recall_card_hits) == 2


def test_recall_dedup_top_n_1(monkeypatch):
    """T6: top_n=1 → exactly 1 hit after dedup, even if both buckets have data."""
    monkeypatch.setattr(
        recall_config, "_read_patch_yaml",
        lambda: {"owner": {"openviking_sync_recall": {"top_n": 1}}},
    )
    monkeypatch.setattr(
        "httpx.post",
        lambda *a, **kw: _MockResponse({"result": {
            "memories": [
                {"uri": "viking://m/a", "abstract": "alpha", "score": 0.9},
                {"uri": "viking://m/b", "abstract": "beta", "score": 0.7},
            ],
            "resources": [
                {"uri": "viking://r/c", "abstract": "gamma", "score": 0.6},
            ],
        }}),
    )
    apply_patch()
    provider = _make_provider()
    out = provider.prefetch("anything")
    lines = [l for l in out.splitlines() if l.startswith("- [")]
    assert len(lines) == 1
    assert "alpha" in lines[0]
    assert len(provider._recall_card_hits) == 1


def test_dedup_uri_canonical_strips_peer_segment():
    """T7: _dedup_uri_canonical strips /peers/<name>/ segments."""
    from owner.patches.openviking_sync_recall_patch import _dedup_uri_canonical
    assert _dedup_uri_canonical(
        "viking://user/yangtb/peers/hermes/memories/x.md"
    ) == "viking://user/yangtb/memories/x.md"
    assert _dedup_uri_canonical(
        "viking://user/yangtb/memories/x.md"
    ) == "viking://user/yangtb/memories/x.md"
    assert _dedup_uri_canonical("") == ""
    # multiple peer segments (defensive)
    assert _dedup_uri_canonical(
        "viking://u/peers/a/memories/peers/b/x.md"
    ) == "viking://u/memories/x.md"


def test_recall_dedup_logs_skipped(monkeypatch, caplog):
    """T8: Skipped peer mirrors emit a logger.debug line."""
    owner = "viking://user/yangtb/memories/x.md"
    peer = "viking://user/yangtb/peers/hermes/memories/x.md"
    monkeypatch.setattr(
        "httpx.post",
        lambda *a, **kw: _MockResponse({"result": {
            "memories": [
                {"uri": owner, "abstract": "same", "score": 0.5},
                {"uri": peer, "abstract": "same", "score": 0.5},
            ], "resources": [],
        }}),
    )
    apply_patch()
    provider = _make_provider()
    with caplog.at_level(
        logging.DEBUG,
        logger="owner.patches.openviking_sync_recall_patch",
    ):
        provider.prefetch("x")
    assert any("recall-dedup: skipped peer mirror" in rec.message
               for rec in caplog.records)
