"""Tests for owner.feishu.media_guard — feishu upload size pre-check + SDK-crash fallback.

Covers the silent-failure bug class documented in
``owner/feishu/media_guard.py``:

  * ``check_file_size`` returns None (放行) for files ≤ 30 MB and a
    user-visible SendResult (超限) above it.
  * ``check_image_size`` does the same against the 10 MB image limit.
  * ``check_upload_exception`` / ``check_image_upload_exception`` translate the
    SDK crash (empty response body → JSONDecodeError / "Expecting value") into
    a Chinese hint instead of leaking ``str(exc)``.
  * Neither check reads the file body (no partial upload), and a missing file
    falls through (None) so the caller's own ``open()`` handles FileNotFound.

These tests touch only stdlib + pytest + the module under test — no network.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from owner.feishu import media_guard
from owner.feishu.media_guard import (
    FEISHU_FILE_MAX_BYTES,
    FEISHU_IMAGE_MAX_BYTES,
    check_file_size,
    check_image_size,
    check_image_upload_exception,
    check_upload_exception,
)


# ---------------------------------------------------------------------------
# Invariant: the documented limits are what the code actually enforces.
# These are contracts (the constant == the feishu platform limit), not
# change-detectors — they pin the guard to the externally-documented values.
# ---------------------------------------------------------------------------

def test_file_limit_is_30_mb():
    assert FEISHU_FILE_MAX_BYTES == 30 * 1024 * 1024


def test_image_limit_is_10_mb():
    assert FEISHU_IMAGE_MAX_BYTES == 10 * 1024 * 1024


# ---------------------------------------------------------------------------
# check_file_size
# ---------------------------------------------------------------------------

def test_check_file_size_none_when_under_limit(tmp_path):
    f = tmp_path / "small.xlsx"
    f.write_bytes(b"x" * 1024)
    assert check_file_size(str(f)) is None


def test_check_file_size_none_at_exact_limit(tmp_path):
    f = tmp_path / "edge.bin"
    f.write_bytes(b"x" * FEISHU_FILE_MAX_BYTES)
    assert check_file_size(str(f)) is None


def test_check_file_size_blocks_over_limit(tmp_path):
    f = tmp_path / "big.xlsx"
    f.write_bytes(b"x" * (FEISHU_FILE_MAX_BYTES + 1))
    result = check_file_size(str(f))
    assert result is not None
    assert result.success is False
    # user-visible Chinese hint, mentions the 30 MB ceiling
    assert "30 MB" in result.error
    assert "⚠️" in result.error
    # does NOT leak the host filesystem path into the hint text
    assert str(f) not in result.error


def test_check_file_size_uses_display_name(tmp_path):
    f = tmp_path / "report.xlsx"
    f.write_bytes(b"x" * (FEISHU_FILE_MAX_BYTES + 1))
    result = check_file_size(str(f), display_name="季度报告.xlsx")
    assert result is not None
    assert "季度报告.xlsx" in result.error


def test_check_file_size_missing_file_returns_none(tmp_path):
    # Missing file → None so the caller's own open() handles FileNotFound.
    # Returning an error here would race with the caller's existence check.
    missing = tmp_path / "ghost.bin"
    assert check_file_size(str(missing)) is None


# ---------------------------------------------------------------------------
# check_image_size
# ---------------------------------------------------------------------------

def test_check_image_size_none_when_under_limit(tmp_path):
    f = tmp_path / "small.png"
    f.write_bytes(b"x" * 1024)
    assert check_image_size(str(f)) is None


def test_check_image_size_blocks_over_limit(tmp_path):
    f = tmp_path / "big.png"
    f.write_bytes(b"x" * (FEISHU_IMAGE_MAX_BYTES + 1))
    result = check_image_size(str(f))
    assert result is not None
    assert result.success is False
    assert "10 MB" in result.error
    assert "⚠️" in result.error
    assert str(f) not in result.error


def test_check_image_size_at_limit_passes(tmp_path):
    f = tmp_path / "edge.png"
    f.write_bytes(b"x" * FEISHU_IMAGE_MAX_BYTES)
    assert check_image_size(str(f)) is None


# ---------------------------------------------------------------------------
# check_upload_exception — the SDK-crash (empty response body) case
# ---------------------------------------------------------------------------

def test_check_upload_exception_translates_json_decode_error():
    # The exact exception lark SDK raises on empty response body.
    exc = json.JSONDecodeError("Expecting value", "", 0)
    result = check_upload_exception(exc, file_path="/tmp/x.xlsx", display_name="x.xlsx")
    assert result.success is False
    # must mention the 30 MB ceiling — that's the most likely root cause
    assert "30 MB" in result.error
    assert "⚠️" in result.error
    assert "x.xlsx" in result.error
    # raw exc preserved for upstream consumers / logs
    assert result.raw_response is exc


def test_check_upload_exception_translates_value_error_expecting_value():
    # Some SDK versions wrap JSONDecodeError as a plain ValueError.
    exc = ValueError("Expecting value: line 1 column 1 (char 0)")
    result = check_upload_exception(exc, file_path="/tmp/x.xlsx", display_name="x.xlsx")
    assert result.success is False
    assert "30 MB" in result.error


def test_check_upload_exception_friendly_for_other_exceptions():
    exc = RuntimeError("connection reset")
    result = check_upload_exception(exc, file_path="/tmp/x.xlsx", display_name="x.xlsx")
    assert result.success is False
    assert "⚠️" in result.error
    # generic message, does NOT claim it was over-limit
    assert "30 MB" not in result.error
    # does NOT leak the raw exception string into the user-visible hint
    assert "connection reset" not in result.error


def test_check_upload_exception_falls_back_to_basename(tmp_path):
    exc = RuntimeError("boom")
    result = check_upload_exception(exc, file_path=str(tmp_path / "data.xlsx"))
    assert "data.xlsx" in result.error


# ---------------------------------------------------------------------------
# check_image_upload_exception
# ---------------------------------------------------------------------------

def test_check_image_upload_exception_translates_decode_error():
    exc = json.JSONDecodeError("Expecting value", "", 0)
    result = check_image_upload_exception(exc, image_path="/tmp/big.png")
    assert result.success is False
    assert "10 MB" in result.error
    assert "⚠️" in result.error
    assert "big.png" in result.error


def test_check_image_upload_exception_friendly_for_other():
    exc = ConnectionError("timeout")
    result = check_image_upload_exception(exc, image_path="/tmp/x.png")
    assert result.success is False
    assert "⚠️" in result.error
    assert "10 MB" not in result.error
    assert "timeout" not in result.error


# ---------------------------------------------------------------------------
# _is_empty_body_decode_error — branch coverage for the detector
# ---------------------------------------------------------------------------

def test_is_empty_body_decode_error_value_error_with_no_json_object():
    # The alternate message shape ("No JSON object") is also recognized.
    exc = ValueError("No JSON object could be decoded")
    assert media_guard._is_empty_body_decode_error(exc) is True


def test_is_empty_body_decode_error_unrelated_value_error():
    exc = ValueError("something else entirely")
    assert media_guard._is_empty_body_decode_error(exc) is False


def test_is_empty_body_decode_error_non_value_error():
    assert media_guard._is_empty_body_decode_error(RuntimeError("x")) is False


# ---------------------------------------------------------------------------
# _format_size — boundary behavior
# ---------------------------------------------------------------------------

def test_format_size_under_one_mb():
    assert media_guard._format_size(512 * 1024) == "<1 MB"


def test_format_size_rounded():
    # 5.2 MB → "5.2 MB"
    assert media_guard._format_size(int(5.2 * 1024 * 1024)) == "5.2 MB"
