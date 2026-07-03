"""Tests for owner hygiene compression user-facing notice."""

from __future__ import annotations

from types import SimpleNamespace

import pytest


class CaptureAdapter:
    def __init__(self):
        self.sent = []

    async def send(self, chat_id, content, metadata=None):
        self.sent.append({"chat_id": chat_id, "content": content, "metadata": metadata})
        return SimpleNamespace(success=True, message_id="notice-1")


@pytest.mark.asyncio
async def test_success_notice_reports_before_and_after_counts():
    from owner.gateway.hygiene_compression_notice import send_hygiene_compression_notice

    adapter = CaptureAdapter()
    source = SimpleNamespace(chat_id="chat-1")
    metadata = {"thread_id": "thread-1"}

    await send_hygiene_compression_notice(
        adapter,
        source,
        msg_count=300,
        new_count=30,
        approx_tokens=120_000,
        new_tokens=12_000,
        hard_msg_limit=250,
        hyg_threshold_pct=0.85,
        hyg_context_length=200_000,
        metadata=metadata,
    )

    assert len(adapter.sent) == 1
    sent = adapter.sent[0]
    assert sent["chat_id"] == "chat-1"
    assert sent["metadata"] is metadata
    assert "自动压缩" in sent["content"]
    assert "压缩前" in sent["content"]
    assert "压缩后" in sent["content"]
    assert "120K tokens" in sent["content"]
    assert "12K tokens" in sent["content"]


@pytest.mark.asyncio
async def test_missing_adapter_or_chat_id_is_noop():
    from owner.gateway.hygiene_compression_notice import send_hygiene_compression_notice

    adapter = CaptureAdapter()

    await send_hygiene_compression_notice(
        None,
        SimpleNamespace(chat_id="chat-1"),
        msg_count=300,
        new_count=30,
        approx_tokens=120_000,
        new_tokens=12_000,
        hard_msg_limit=250,
        hyg_threshold_pct=0.85,
        hyg_context_length=200_000,
    )
    await send_hygiene_compression_notice(
        adapter,
        SimpleNamespace(chat_id=None),
        msg_count=300,
        new_count=30,
        approx_tokens=120_000,
        new_tokens=12_000,
        hard_msg_limit=250,
        hyg_threshold_pct=0.85,
        hyg_context_length=200_000,
    )

    assert adapter.sent == []