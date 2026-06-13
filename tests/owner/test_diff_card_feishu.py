"""Tests for owner.diff_card.feishu card rendering and callbacks."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from owner.diff_card.feishu import (
    diff_to_feishu_card,
    handle_feishu_diff_action,
    send_feishu_diff_card,
)


@pytest.fixture
def sample_diff():
    return (
        "--- a/foo.py\n"
        "+++ b/foo.py\n"
        "@@ -1,2 +1,2 @@\n"
        "-old\n"
        "+new\n"
        " context\n"
    )


def test_diff_to_feishu_card_compact(sample_diff):
    card = diff_to_feishu_card(
        sample_diff, "write_file", file_path="foo.py", diff_id="abc123",
        max_lines=10, compact=True,
    )
    assert card is not None
    assert card["schema"] == "2.0"
    assert "foo.py" in card["header"]["title"]["content"]
    assert "🔍 展开 diff" in _button_texts(card)
    # compact mode should not include the actual +/- lines
    body = card["body"]["elements"][0]["content"]
    assert "--- foo.py" in body
    assert "-old" not in body


def test_diff_to_feishu_card_expanded(sample_diff):
    card = diff_to_feishu_card(
        sample_diff, "write_file", file_path="foo.py", diff_id="abc123",
        max_lines=10, compact=False,
    )
    assert card is not None
    body = card["body"]["elements"][0]["content"]
    assert "-old" in body
    assert "+new" in body
    texts = _button_texts(card)
    assert "⬆️ 折叠" in texts
    assert "📄 查看完整 diff" in texts


def test_diff_to_feishu_card_returns_none_for_empty_diff():
    assert diff_to_feishu_card("   ", "write_file") is None


def _button_texts(card):
    texts = []
    for el in card["body"]["elements"]:
        if el.get("tag") == "button":
            texts.append(el["text"]["content"])
    return texts


@pytest.mark.asyncio
async def test_send_feishu_diff_card(sample_diff):
    adapter = MagicMock()
    adapter.send_card = AsyncMock(return_value=MagicMock(success=True))
    adapter._diff_card_cache = {}

    result = await send_feishu_diff_card(
        adapter, "chat_123", sample_diff, "write_file", "foo.py", 10
    )

    assert result is not None
    adapter.send_card.assert_awaited_once()
    call_args = adapter.send_card.call_args
    assert call_args[0][0] == "chat_123"
    card = call_args[0][1]
    assert card["schema"] == "2.0"
    assert "🔍 展开 diff" in _button_texts(card)
    # cache should contain the diff state
    assert len(adapter._diff_card_cache) == 1
    diff_id = next(iter(adapter._diff_card_cache))
    cached = adapter._diff_card_cache[diff_id]
    assert cached["diff"] == sample_diff
    assert cached["tool_name"] == "write_file"


def test_handle_feishu_diff_action_expand(monkeypatch, sample_diff):
    # Mock lark callback classes
    MockCard = MagicMock()
    MockResponse = MagicMock()
    monkeypatch.setattr(
        "owner.diff_card.feishu.CallBackCard", MockCard
    )
    monkeypatch.setattr(
        "owner.diff_card.feishu.P2CardActionTriggerResponse", MockResponse
    )

    adapter = MagicMock()
    adapter._diff_card_cache = {}
    send_feishu_diff_card_sync = None  # populate cache manually
    from owner.diff_card.common import cache_put
    cache_put(adapter._diff_card_cache, "abc123", {
        "diff": sample_diff,
        "tool_name": "write_file",
        "file_path": "foo.py",
        "max_lines": 10,
    })

    event = SimpleNamespace()
    action_value = {"expand_diff": True, "diff_id": "abc123"}

    response = handle_feishu_diff_action(adapter, event, action_value)

    assert response is MockResponse.return_value
    MockResponse.assert_called_once()
    assert MockCard.call_count == 1
    cb_card = MockCard.return_value
    assert cb_card.type == "raw"
    assert cb_card.data is not None
    assert "⬆️ 折叠" in _button_texts(cb_card.data)


def test_handle_feishu_diff_action_missing_cache():
    adapter = MagicMock()
    adapter._diff_card_cache = {}

    event = SimpleNamespace()
    action_value = {"expand_diff": True, "diff_id": "missing"}

    # With lark unavailable this returns None; the function still handles missing cache gracefully.
    response = handle_feishu_diff_action(adapter, event, action_value)
    assert response is None or hasattr(response, "card")
