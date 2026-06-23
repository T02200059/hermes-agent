"""Tests for owner/patches/openviking_recall_card_patch.py."""

from __future__ import annotations

import threading
from typing import Any, Dict

import pytest

from owner.patches.openviking_recall_card_patch import (
    _TOKEN_CACHE,
    apply_patch,
    build_viking_recall_card,
    build_viking_recall_text,
    revert_patch,
)
from plugins.memory.openviking import OpenVikingMemoryProvider


@pytest.fixture(autouse=True)
def _clean_env_and_patch(monkeypatch):
    """Start each test with a clean environment and reverted patches."""
    for name in (
        "OPENVIKING_RECALL_DISPLAY",
        "OPENVIKING_RECALL_FEISHU_CARD",
        "OPENVIKING_RECALL_QQBOT_TEXT",
        "FEISHU_APP_ID",
        "FEISHU_APP_SECRET",
        "QQ_APP_ID",
        "QQ_CLIENT_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)
    _TOKEN_CACHE.clear()
    revert_patch()
    # Also revert the sync patch to avoid cross-test interference.
    from owner.patches.openviking_sync_recall_patch import revert_patch as revert_sync
    revert_sync()
    yield
    revert_patch()
    from owner.patches.openviking_sync_recall_patch import revert_patch as revert_sync
    revert_sync()


class _FakeThread:
    """Captures Thread constructor arguments without actually starting."""

    def __init__(self, target=None, args=(), kwargs=None, daemon=None, name=None):
        self.target = target
        self.args = args
        self.kwargs = kwargs or {}
        self.daemon = daemon
        self.name = name
        self._started = False

    def start(self):
        self._started = True


class _MockResponse:
    """Minimal httpx-like response for monkeypatching."""

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


def _apply_sync_and_card():
    """Apply the sync recall patch, which auto-mounts the card patch."""
    from owner.patches.openviking_sync_recall_patch import apply_patch as apply_sync
    apply_sync()


def test_build_viking_recall_card():
    """Hits produce a Feishu schema-2.0 card; empty hits return None."""
    hits = [
        {"type": "memory", "abstract": "User prefers dark mode", "score": 0.95},
        {"type": "resource", "abstract": "Project uses pytest", "score": 0.88},
    ]
    card = build_viking_recall_card(hits, 42.0)

    assert card is not None
    assert card["schema"] == "2.0"
    assert card["header"]["template"] == "blue"
    assert any("2 条匹配" in el.get("content", "") for el in card["body"]["elements"])
    assert any("0.950" in el.get("content", "") for el in card["body"]["elements"])

    assert build_viking_recall_card([], 1.0) is None


def test_build_viking_recall_text():
    """Hits produce a markdown text summary; very long text is truncated."""
    hits = [
        {"type": "memory", "abstract": "User prefers dark mode", "score": 0.95},
    ]
    text = build_viking_recall_text(hits, 42.0)

    assert "OpenViking 召回" in text
    assert "1 条匹配" in text
    assert "0.950" in text
    assert "User prefers dark mode" in text

    long_hits = [
        {"type": "memory", "abstract": "x" * 5000, "score": 0.5},
    ]
    long_text = build_viking_recall_text(long_hits, 1.0)
    assert len(long_text) <= 3800


@pytest.mark.parametrize(
    "platform,expected_target",
    [
        ("feishu", "owner.patches.openviking_recall_card_patch._send_feishu_card_sync"),
        ("qqbot", "owner.patches.openviking_recall_card_patch._send_qqbot_text_sync"),
        ("cli", None),
    ],
)
def test_fire_recall_display_platform_routing(monkeypatch, platform, expected_target):
    """Feishu/QQ trigger the right sender; other platforms are no-ops."""
    from owner.patches.openviking_recall_card_patch import _fire_recall_display

    captured: Dict[str, Any] = {}

    def fake_thread_ctor(*args, **kwargs):
        captured["target"] = kwargs.get("target")
        captured["args"] = kwargs.get("args")
        captured["daemon"] = kwargs.get("daemon")
        return _FakeThread(*args, **kwargs)

    monkeypatch.setattr(threading, "Thread", fake_thread_ctor)

    ctx = {"platform": platform, "chat_id": "chat-1", "chat_type": "group", "user_id": "user-1"}
    hits = [{"type": "memory", "abstract": "Hello", "score": 0.9}]
    _fire_recall_display(hits, ctx, 12.0)

    if expected_target is None:
        assert "target" not in captured
    else:
        assert captured["target"].__module__ + "." + captured["target"].__qualname__ == expected_target
        assert captured["daemon"] is True
        assert captured["args"][0] == "chat-1"


def test_initialize_ctx_saved():
    """Patching makes initialize store the session context on the provider."""
    apply_patch()

    provider = _make_provider()
    provider.initialize(
        "session-1",
        platform="qqbot",
        chat_id="chat-2",
        chat_type="p2p",
        user_id="user-2",
        user_name="Bob",
        chat_name="DM",
    )

    ctx = provider._recall_card_ctx
    assert ctx["platform"] == "qqbot"
    assert ctx["chat_id"] == "chat-2"
    assert ctx["chat_type"] == "p2p"
    assert ctx["user_id"] == "user-2"
    assert ctx["user_name"] == "Bob"
    assert ctx["chat_name"] == "DM"


def test_sync_prefetch_triggers_card(monkeypatch):
    """When prefetch returns hits, a daemon thread is started to send the card."""
    captured: Dict[str, Any] = {}

    def fake_thread_ctor(*args, **kwargs):
        captured["target"] = kwargs.get("target")
        captured["args"] = kwargs.get("args")
        captured["daemon"] = kwargs.get("daemon")
        return _FakeThread(*args, **kwargs)

    monkeypatch.setattr(threading, "Thread", fake_thread_ctor)

    def mock_post(url, **kwargs):
        return _MockResponse(
            {
                "result": {
                    "memories": [
                        {"uri": "viking://memories/a", "abstract": "User prefers dark mode", "score": 0.95}
                    ],
                    "resources": [
                        {"uri": "viking://resources/b", "abstract": "Project uses pytest", "score": 0.88}
                    ],
                }
            }
        )

    monkeypatch.setattr("httpx.post", mock_post)

    _apply_sync_and_card()

    provider = _make_provider()
    provider.initialize(
        "session-1",
        platform="feishu",
        chat_id="chat-1",
        chat_type="group",
        user_id="user-1",
    )
    result = provider.prefetch("what do you know about me", session_id="session-1")

    assert "## OpenViking Context" in result
    assert "target" in captured
    assert captured["target"].__name__ == "_send_feishu_card_sync"
    assert captured["daemon"] is True


def test_env_flags_disabled(monkeypatch):
    """When feature flags are off, no background thread is started."""
    monkeypatch.setenv("OPENVIKING_RECALL_DISPLAY", "0")

    captured: Dict[str, Any] = {}

    def fake_thread_ctor(*args, **kwargs):
        captured["target"] = kwargs.get("target")
        return _FakeThread(*args, **kwargs)

    monkeypatch.setattr(threading, "Thread", fake_thread_ctor)

    def mock_post(url, **kwargs):
        return _MockResponse(
            {
                "result": {
                    "memories": [
                        {"uri": "viking://memories/a", "abstract": "User prefers dark mode", "score": 0.95}
                    ]
                }
            }
        )

    monkeypatch.setattr("httpx.post", mock_post)

    _apply_sync_and_card()

    provider = _make_provider()
    provider.initialize(
        "session-1",
        platform="feishu",
        chat_id="chat-1",
        chat_type="group",
        user_id="user-1",
    )
    provider.prefetch("what do you know about me", session_id="session-1")
    assert "target" not in captured


def test_feishu_send_auth_failure(monkeypatch):
    """Missing credentials cause the Feishu sender to return False without raising."""
    from owner.patches.openviking_recall_card_patch import _send_feishu_card_sync

    monkeypatch.delenv("FEISHU_APP_ID", raising=False)
    monkeypatch.delenv("FEISHU_APP_SECRET", raising=False)

    result = _send_feishu_card_sync("chat-1", {"schema": "2.0"}, {"chat_type": "group"})
    assert result is False


def test_qq_send_auth_failure(monkeypatch):
    """Missing credentials cause the QQ sender to return False without raising."""
    from owner.patches.openviking_recall_card_patch import _send_qqbot_text_sync

    monkeypatch.delenv("QQ_APP_ID", raising=False)
    monkeypatch.delenv("QQ_CLIENT_SECRET", raising=False)

    result = _send_qqbot_text_sync("user-1", "hello", {"chat_type": "p2p"})
    assert result is False


def test_revert_patch():
    """revert_patch restores the original provider methods."""
    original_initialize = OpenVikingMemoryProvider.initialize
    original_prefetch = OpenVikingMemoryProvider.prefetch

    apply_patch()
    assert OpenVikingMemoryProvider.initialize is not original_initialize
    assert OpenVikingMemoryProvider.prefetch is not original_prefetch

    revert_patch()
    assert OpenVikingMemoryProvider.initialize is original_initialize
    assert OpenVikingMemoryProvider.prefetch is original_prefetch


import owner.patches.openviking_recall_config as recall_config


def _apply_card_only(monkeypatch, patch_data):
    """Apply just the card patch with the given patch.yaml data."""
    monkeypatch.setattr(recall_config, "_read_patch_yaml", lambda: patch_data)
    apply_patch()


def test_patch_yaml_disables_feishu_card(monkeypatch):
    """patch.yaml feishu_card=false prevents the Feishu thread from starting."""
    captured: Dict[str, Any] = {}

    def fake_thread_ctor(*args, **kwargs):
        captured["target"] = kwargs.get("target")
        return _FakeThread(*args, **kwargs)

    monkeypatch.setattr(threading, "Thread", fake_thread_ctor)

    def mock_post(url, **kwargs):
        return _MockResponse(
            {
                "result": {
                    "memories": [
                        {"uri": "viking://memories/a", "abstract": "User prefers dark mode", "score": 0.95}
                    ]
                }
            }
        )

    monkeypatch.setattr("httpx.post", mock_post)

    _apply_card_only(
        monkeypatch,
        {"owner": {"openviking_recall_card": {"feishu_card": False}}},
    )

    provider = _make_provider()
    provider.initialize(
        "session-1",
        platform="feishu",
        chat_id="chat-1",
        chat_type="group",
        user_id="user-1",
    )
    provider.prefetch("what do you know about me", session_id="session-1")
    assert "target" not in captured


def test_patch_yaml_displays_master_off(monkeypatch):
    """patch.yaml enabled=false skips recall display for all platforms."""
    captured: Dict[str, Any] = {}

    def fake_thread_ctor(*args, **kwargs):
        captured["target"] = kwargs.get("target")
        return _FakeThread(*args, **kwargs)

    monkeypatch.setattr(threading, "Thread", fake_thread_ctor)

    def mock_post(url, **kwargs):
        return _MockResponse(
            {
                "result": {
                    "memories": [
                        {"uri": "viking://memories/a", "abstract": "User prefers dark mode", "score": 0.95}
                    ]
                }
            }
        )

    monkeypatch.setattr("httpx.post", mock_post)

    _apply_card_only(
        monkeypatch,
        {"owner": {"openviking_recall_card": {"enabled": False}}},
    )

    provider = _make_provider()
    provider.initialize(
        "session-1",
        platform="qqbot",
        chat_id="chat-1",
        chat_type="group",
        user_id="user-1",
    )
    provider.prefetch("what do you know about me", session_id="session-1")
    assert "target" not in captured


def test_patch_yaml_qqbot_text_off(monkeypatch):
    """patch.yaml qqbot_text=false skips the QQ Bot text path."""
    captured: Dict[str, Any] = {}

    def fake_thread_ctor(*args, **kwargs):
        captured["target"] = kwargs.get("target")
        return _FakeThread(*args, **kwargs)

    monkeypatch.setattr(threading, "Thread", fake_thread_ctor)

    def mock_post(url, **kwargs):
        return _MockResponse(
            {
                "result": {
                    "memories": [
                        {"uri": "viking://memories/a", "abstract": "User prefers dark mode", "score": 0.95}
                    ]
                }
            }
        )

    monkeypatch.setattr("httpx.post", mock_post)

    _apply_card_only(
        monkeypatch,
        {"owner": {"openviking_recall_card": {"qqbot_text": False}}},
    )

    provider = _make_provider()
    provider.initialize(
        "session-1",
        platform="qqbot",
        chat_id="chat-1",
        chat_type="group",
        user_id="user-1",
    )
    provider.prefetch("what do you know about me", session_id="session-1")
    assert "target" not in captured
