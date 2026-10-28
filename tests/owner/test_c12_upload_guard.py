"""C12-upload-guard — Feishu outbound media size guard + user-visible Chinese hints."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from owner.feishu.media_guard import (
    FEISHU_FILE_MAX_BYTES,
    FEISHU_IMAGE_MAX_BYTES,
    check_file_size,
    check_image_size,
    check_image_upload_exception,
    check_upload_exception,
    send_media_guard_hint,
)


def test_limits_match_feishu_docs():
    assert FEISHU_IMAGE_MAX_BYTES == 10 * 1024 * 1024
    assert FEISHU_FILE_MAX_BYTES == 30 * 1024 * 1024


def test_check_image_size_allows_under_limit(tmp_path: Path):
    p = tmp_path / "ok.png"
    p.write_bytes(b"x" * 1024)
    assert check_image_size(str(p)) is None


def test_check_image_size_blocks_over_limit(tmp_path: Path):
    p = tmp_path / "big.png"
    # Avoid allocating 10MB+ of RAM: create sparse-ish by seeking.
    with open(p, "wb") as f:
        f.seek(FEISHU_IMAGE_MAX_BYTES)
        f.write(b"x")
    result = check_image_size(str(p))
    assert result is not None
    assert result.success is False
    assert "10 MB" in result.error
    assert "图片过大" in result.error
    assert "big.png" in result.error


def test_check_file_size_allows_under_limit(tmp_path: Path):
    p = tmp_path / "ok.bin"
    p.write_bytes(b"y" * 2048)
    assert check_file_size(str(p), display_name="report.pdf") is None


def test_check_file_size_blocks_over_limit(tmp_path: Path):
    p = tmp_path / "huge.bin"
    with open(p, "wb") as f:
        f.seek(FEISHU_FILE_MAX_BYTES)
        f.write(b"y")
    result = check_file_size(str(p), display_name="资料.zip")
    assert result is not None
    assert result.success is False
    assert "30 MB" in result.error
    assert "文件过大" in result.error
    assert "资料.zip" in result.error


def test_check_file_size_missing_file_returns_none(tmp_path: Path):
    assert check_file_size(str(tmp_path / "missing.bin")) is None


def test_check_upload_exception_empty_body():
    exc = json.JSONDecodeError("Expecting value", "", 0)
    result = check_upload_exception(exc, file_path="/tmp/a.bin", display_name="a.bin")
    assert result.success is False
    assert "30 MB" in result.error
    assert "a.bin" in result.error
    assert "上传失败" in result.error


def test_check_upload_exception_generic():
    result = check_upload_exception(RuntimeError("boom"), file_path="/tmp/b.bin", display_name="b.bin")
    assert result.success is False
    assert result.error == "💡 文件上传失败：b.bin"


def test_check_image_upload_exception_empty_body():
    exc = ValueError("Expecting value: line 1 column 1 (char 0)")
    result = check_image_upload_exception(exc, image_path="/tmp/c.png")
    assert result.success is False
    assert "10 MB" in result.error
    assert "c.png" in result.error


@pytest.mark.asyncio
async def test_send_media_guard_hint_best_effort():
    adapter = MagicMock()
    adapter.send = AsyncMock(return_value=None)
    await send_media_guard_hint(adapter, "oc_1", "💡 提示", None, None)
    adapter.send.assert_awaited_once()
    kwargs = adapter.send.await_args.kwargs
    assert kwargs["chat_id"] == "oc_1"
    assert kwargs["content"] == "💡 提示"


@pytest.mark.asyncio
async def test_send_media_guard_hint_swallows_send_error():
    adapter = MagicMock()
    adapter.send = AsyncMock(side_effect=RuntimeError("offline"))
    await send_media_guard_hint(adapter, "oc_1", "💡 提示", None, None)  # must not raise


@pytest.mark.asyncio
async def test_send_media_guard_hint_noop_on_empty():
    adapter = MagicMock()
    adapter.send = AsyncMock()
    await send_media_guard_hint(adapter, "oc_1", None, None, None)
    await send_media_guard_hint(adapter, "oc_1", "", None, None)
    adapter.send.assert_not_called()
