"""Tests for owner.diff_card.dispatcher."""

import json
import threading
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.display import LocalEditSnapshot, capture_local_edit_snapshot
from gateway.config import Platform
from owner.diff_card.dispatcher import (
    make_tool_start_snapshot_callback,
    maybe_send_diff_cards,
)


def test_make_tool_start_snapshot_callback_calls_original():
    original = MagicMock()
    snapshots = {}
    lock = threading.Lock()
    cb = make_tool_start_snapshot_callback(original, snapshots, lock)

    cb("tc1", "write_file", {"path": "/tmp/foo.py"})

    original.assert_called_once_with("tc1", "write_file", {"path": "/tmp/foo.py"})
    assert "tc1" in snapshots
    assert isinstance(snapshots["tc1"], LocalEditSnapshot)


def test_make_tool_start_snapshot_callback_ignores_non_edit_tools():
    original = MagicMock()
    snapshots = {}
    lock = threading.Lock()
    cb = make_tool_start_snapshot_callback(original, snapshots, lock)

    cb("tc1", "web_search", {"query": "x"})

    original.assert_called_once()
    assert "tc1" not in snapshots


def test_make_tool_start_snapshot_callback_preserves_original_on_capture_error():
    original = MagicMock()
    snapshots = {}
    lock = threading.Lock()
    cb = make_tool_start_snapshot_callback(original, snapshots, lock)

    # Invalid args that cause capture_local_edit_snapshot to return None, not raise.
    cb("tc1", "write_file", None)  # type: ignore[arg-type]
    original.assert_called_once()


@pytest.fixture
def feishu_setup(tmp_path):
    # Create a real file so capture_local_edit_snapshot can read before-state.
    target = tmp_path / "foo.py"
    target.write_text("old\n", encoding="utf-8")

    adapter = MagicMock()
    adapter.send_card = AsyncMock(return_value=MagicMock(success=True))
    runner = MagicMock()
    runner.adapters = {Platform.FEISHU: adapter}
    source = MagicMock()
    source.platform = Platform.FEISHU
    source.chat_id = "chat_123"

    snapshots = {}
    lock = threading.Lock()
    snapshot = capture_local_edit_snapshot("write_file", {"path": str(target)})
    # Mutate the file so the snapshot diff is non-empty.
    target.write_text("new\n", encoding="utf-8")
    snapshots["tc1"] = snapshot

    # Tool result representing a successful write_file.
    result = json.dumps({"bytes_written": 10, "resolved_path": str(target)})
    prev_tools = [{
        "name": "write_file",
        "tool_call_id": "tc1",
        "arguments": {"path": str(target)},
        "result": result,
    }]

    return runner, source, adapter, snapshots, lock, prev_tools


def test_maybe_send_diff_cards_feishu(feishu_setup, monkeypatch):
    runner, source, adapter, snapshots, lock, prev_tools = feishu_setup

    scheduled = []
    def _fake_schedule(coro, loop, **kwargs):
        scheduled.append((coro, loop))
        if hasattr(coro, "close"):
            coro.close()
        return None
    monkeypatch.setattr(
        "owner.diff_card.dispatcher.safe_schedule_threadsafe", _fake_schedule
    )

    mock_loop = MagicMock()
    sent_ids = set()
    maybe_send_diff_cards(
        runner, source, prev_tools, snapshots, lock, mock_loop, sent_ids
    )

    assert len(scheduled) == 1
    coro, loop = scheduled[0]
    assert loop is mock_loop
    assert "tc1" in sent_ids


def test_maybe_send_diff_cards_dedup(feishu_setup, monkeypatch):
    runner, source, adapter, snapshots, lock, prev_tools = feishu_setup
    monkeypatch.setattr(
        "owner.diff_card.dispatcher.safe_schedule_threadsafe", lambda coro, loop, **kw: None
    )

    sent_ids = {"tc1"}
    mock_loop = MagicMock()

    maybe_send_diff_cards(
        runner, source, prev_tools, snapshots, lock, mock_loop, sent_ids
    )

    assert "tc1" in sent_ids


def test_maybe_send_diff_cards_skips_non_diff_tools():
    runner = MagicMock()
    adapter = MagicMock()
    runner.adapters = {Platform.QQBOT: adapter}
    source = MagicMock()
    source.platform = Platform.QQBOT
    source.chat_id = "qq_chat"
    snapshots = {}
    lock = threading.Lock()
    prev_tools = [{
        "name": "web_search",
        "tool_call_id": "tc1",
        "arguments": {"query": "x"},
        "result": '{"data": []}',
    }]
    mock_loop = MagicMock()

    maybe_send_diff_cards(runner, source, prev_tools, snapshots, lock, mock_loop)
    assert mock_loop.call_count == 0


def test_maybe_send_diff_cards_qqbot(tmp_path, monkeypatch):
    target = tmp_path / "foo.py"
    target.write_text("old\n", encoding="utf-8")

    adapter = MagicMock()
    adapter.send = AsyncMock(return_value=MagicMock(success=True))
    runner = MagicMock()
    runner.adapters = {Platform.QQBOT: adapter}
    source = MagicMock()
    source.platform = Platform.QQBOT
    source.chat_id = "qq_chat"

    snapshots = {}
    lock = threading.Lock()
    snapshot = capture_local_edit_snapshot("write_file", {"path": str(target)})
    target.write_text("new\n", encoding="utf-8")
    snapshots["tc2"] = snapshot

    result = json.dumps({"bytes_written": 10})
    prev_tools = [{
        "name": "write_file",
        "tool_call_id": "tc2",
        "arguments": {"path": str(target)},
        "result": result,
    }]

    scheduled = []
    def _fake_schedule(coro, loop, **kwargs):
        scheduled.append((coro, loop))
        if hasattr(coro, "close"):
            coro.close()
        return None
    monkeypatch.setattr(
        "owner.diff_card.dispatcher.safe_schedule_threadsafe", _fake_schedule
    )
    mock_loop = MagicMock()

    maybe_send_diff_cards(runner, source, prev_tools, snapshots, lock, mock_loop)
    assert len(scheduled) == 1
    assert scheduled[0][1] is mock_loop
