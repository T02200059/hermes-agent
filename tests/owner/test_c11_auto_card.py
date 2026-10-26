"""C11 base: auto-card config / notice / progress-skip / early-typing lock helpers."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from unittest.mock import MagicMock, patch

import pytest

from owner.feishu import auto_card, card_sender


def test_threshold_reads_patch(monkeypatch):
    monkeypatch.setattr(
        auto_card, "load_patch_config", lambda: {"feishu_card": {"auto_card_threshold": 57}}
    )
    assert auto_card.get_auto_card_threshold() == 57


def test_threshold_disabled_when_zero(monkeypatch):
    monkeypatch.setattr(
        auto_card, "load_patch_config", lambda: {"feishu_card": {"auto_card_threshold": 0}}
    )
    assert auto_card.get_auto_card_threshold() == 0


def test_split_max_chars_clamped(monkeypatch):
    monkeypatch.setattr(
        auto_card, "load_patch_config",
        lambda: {"feishu_card": {"split_max_chars": 1}},
    )
    assert auto_card.get_auto_card_split_max_chars() == auto_card._AUTO_CARD_SPLIT_MIN_MAX_CHARS


def test_notice_rule_match_stream_guard(monkeypatch):
    monkeypatch.setattr(
        auto_card,
        "load_patch_config",
        lambda: {
            "feishu_card": {
                "notice_titles": [
                    {
                        "prefix": "⚠️ [stream-guard]",
                        "title": "⚠️ [stream-guard] 生成退化告警",
                        "template": "orange",
                        "strip_prefix": True,
                    }
                ]
            }
        },
    )
    rule = auto_card.match_notice_rule("⚠️ [stream-guard] hello")
    assert rule is not None
    assert "stream-guard" in rule["title"]


@pytest.mark.asyncio
async def test_try_auto_card_skips_progress_bubble():
    adapter = MagicMock()
    result = await auto_card.try_auto_card(
        adapter,
        "x" * 200,
        {"__hermes_progress_bubble": True},
        chat_id="oc_test",
        force=True,
    )
    assert result is None
    adapter.send_card.assert_not_called()


@pytest.mark.asyncio
async def test_try_auto_card_skips_when_threshold_zero(monkeypatch):
    monkeypatch.setattr(auto_card, "get_auto_card_threshold", lambda: 0)
    adapter = MagicMock()
    result = await auto_card.try_auto_card(
        adapter, "x" * 200, {}, chat_id="oc_test", force=True,
    )
    assert result is None


def test_get_card_send_lock_lru():
    adapter = MagicMock()
    adapter.CHAT_LOCK_MAX_SIZE = 2
    adapter._card_send_locks = OrderedDict()
    lock_a = card_sender.get_card_send_lock(adapter, "a")
    lock_b = card_sender.get_card_send_lock(adapter, "b")
    assert lock_a is card_sender.get_card_send_lock(adapter, "a")
    # third chat evicts unlocked victim
    lock_c = card_sender.get_card_send_lock(adapter, "c")
    assert "c" in adapter._card_send_locks
    assert len(adapter._card_send_locks) <= 2
    assert lock_c is adapter._card_send_locks["c"]


@pytest.mark.asyncio
async def test_send_card_surfaces_api_failure():
    adapter = MagicMock()

    class _Resp:
        def success(self):
            return False
        code = 9499
        msg = "fail"

    async def _retry(**kwargs):
        return _Resp()

    adapter._feishu_send_with_retry = _retry
    adapter._finalize_send_result = MagicMock(
        return_value=type("R", (), {"success": False, "error": "[9499] fail", "message_id": None})()
    )
    result = await card_sender.send_card(
        adapter, chat_id="oc_x", card={"elements": []}, metadata=None,
    )
    assert result.success is False
