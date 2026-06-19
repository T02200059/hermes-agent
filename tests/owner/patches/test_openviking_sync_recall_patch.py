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
