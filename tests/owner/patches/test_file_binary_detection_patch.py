"""Tests for owner/patches/file_binary_detection_patch.py.

E2E tests with real files + real subprocess env, covering the four
scenarios that distinguish truncation artifacts from genuine illegal
bytes.  Asserts behavioral contracts (not source snapshots):

  - UTF-8 file with a multi-byte char straddling byte 1000 -> TEXT
  - UTF-8 file with CJK prefix + emoji straddling byte 1000  -> TEXT
  - File with genuine illegal bytes in the sample middle    -> BINARY
  - GBK-encoded legacy file (per 021a07688 policy)          -> BINARY
  - apply/revert is idempotent and restores the exact original
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from owner.patches.file_binary_detection_patch import (
    apply_patch,
    revert_patch,
)
from tools.file_operations import ShellFileOperations


@pytest.fixture(autouse=True)
def _ensure_reverted():
    revert_patch()
    yield
    revert_patch()


def _real_env(cwd: str) -> MagicMock:
    env = MagicMock()
    env.cwd = cwd

    def execute(command, **kwargs):
        completed = subprocess.run(
            command, shell=True, capture_output=True,
            input=kwargs.get("stdin_data"),
        )
        output = completed.stdout.decode("utf-8", errors="replace")
        return {"output": output, "returncode": completed.returncode}

    env.execute = execute
    return env


def _make_file(path: Path, content: str | bytes, encoding: str = "utf-8") -> None:
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding=encoding)


class TestApplyRevertIdempotent:
    def test_apply_twice_is_noop(self):
        apply_patch()
        apply_patch()
        from owner.patches.file_binary_detection_patch import _applied
        assert _applied is True

    def test_revert_without_apply_is_safe(self):
        revert_patch()
        revert_patch()

    def test_revert_restores_original(self):
        from tools.file_operations import ShellFileOperations as SFO
        original = SFO._is_likely_binary
        apply_patch()
        assert SFO._is_likely_binary is not original
        revert_patch()
        assert SFO._is_likely_binary is original


class TestPatchedBinaryDetection:
    """The four-scenario matrix from the root-cause investigation."""

    def setup_method(self):
        apply_patch()

    def _ops(self, cwd: str) -> ShellFileOperations:
        return ShellFileOperations(_real_env(cwd))

    def test_multibyte_char_straddling_byte_1000_is_text(self, tmp_path):
        prefix = "x" * 998
        p = tmp_path / "boundary.py"
        _make_file(p, prefix + "😀😀😀\nprint('hi')\n")
        ops = self._ops(str(tmp_path))
        result = ops.read_file(str(p))
        assert result.is_binary is not True, "legitimate UTF-8 file misclassified as binary"
        assert result.error is None

    def test_cjk_prefix_then_emoji_straddling_boundary_is_text(self, tmp_path):
        header = "# coding: utf-8\n"
        body = header + "中" * 327 + "x"
        p = tmp_path / "cjk_boundary.py"
        _make_file(p, body + "😀😀😀\n")
        ops = self._ops(str(tmp_path))
        result = ops.read_file(str(p))
        assert result.is_binary is not True

    def test_genuine_illegal_bytes_in_middle_is_binary(self, tmp_path):
        p = tmp_path / "garbage.py"
        _make_file(p, b"import os\n" * 50 + b"\x00\xff\xfe garbage" + b"\ncode = 1\n" * 50)
        ops = self._ops(str(tmp_path))
        result = ops.read_file(str(p))
        assert result.is_binary is True

    def test_gbk_legacy_file_is_binary(self, tmp_path):
        p = tmp_path / "gbk_legacy.py"
        _make_file(p, ("# -*- coding: gbk -*-\n变量 = '中文'\n" * 30).encode("gbk"))
        ops = self._ops(str(tmp_path))
        result = ops.read_file(str(p))
        assert result.is_binary is True

    def test_pure_ascii_file_is_text(self, tmp_path):
        p = tmp_path / "pure.py"
        _make_file(p, "import os\n" * 200)
        ops = self._ops(str(tmp_path))
        result = ops.read_file(str(p))
        assert result.is_binary is not True
        assert result.error is None

    def test_binary_extension_short_circuits(self, tmp_path):
        p = tmp_path / "image.png"
        _make_file(p, b"\x89PNG\r\n\x1a\n" + b"\x00" * 200)
        ops = self._ops(str(tmp_path))
        result = ops.read_file(str(p))
        assert result.is_binary is True

    def test_read_file_raw_also_fixed(self, tmp_path):
        prefix = "x" * 998
        p = tmp_path / "raw_boundary.py"
        _make_file(p, prefix + "😀😀😀\nprint('hi')\n")
        ops = self._ops(str(tmp_path))
        result = ops.read_file_raw(str(p))
        assert result.is_binary is not True
        assert result.error is None


class TestDirectPatchedMethod:
    """Call the patched method directly for precise boundary cases."""

    def setup_method(self):
        apply_patch()
        self.ops = ShellFileOperations(_real_env("/tmp"))

    def test_sample_with_only_tail_replacement_is_text(self):
        sample = "hello world" + "\ufffd"
        assert self.ops._is_likely_binary("foo.py", sample) is False

    def test_sample_with_middle_replacement_is_binary(self):
        sample = "hel\ufffdlo world"
        assert self.ops._is_likely_binary("foo.py", sample) is True

    def test_sample_with_multiple_replacements_is_binary(self):
        sample = "hello" + "\ufffd" + "world" + "\ufffd"
        assert self.ops._is_likely_binary("foo.py", sample) is True

    def test_clean_sample_uses_ratio_check(self):
        sample = "a" * 1000
        assert self.ops._is_likely_binary("foo.py", sample) is False

    def test_clean_sample_high_nonprintable_is_binary(self):
        sample = "\x00" * 400 + "a" * 600
        assert self.ops._is_likely_binary("foo.py", sample) is True

    def test_no_sample_returns_false(self):
        assert self.ops._is_likely_binary("foo.py", None) is False  # type: ignore[arg-type]
        assert self.ops._is_likely_binary("foo.py", "") is False
