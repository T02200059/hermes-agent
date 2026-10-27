"""Tests for progress-message dedup counter vs markdown code fences (C25 / WR-04).

Bug: when a terminal tool fires 3+ times with the same command on a
``supports_code_blocks=True`` platform (Feishu/Slack), the progress
bubble renders the command as a fenced code block ending in ```` ``` ````.
The dedup counter ``(×N)`` was appended inline after the closing fence,
producing ```` ``` (×3) ```` — not a valid CommonMark closing fence, so
the code block never closes and subsequent tool lines get swallowed.

The fix: append the counter on a NEW line when ``base_msg`` ends with the
fence, inline (space-separated) otherwise.
"""

from __future__ import annotations

import re

# Exercise the PRODUCTION helper (owner rule + thin glue in run_turn_progress).
from gateway.run_turn_progress import _append_progress_repeat_count as _apply_dedup_counter
from owner.gateway.turn_helpers import append_dedup_counter


def test_dedup_counter_newline_after_closing_fence_with_header():
    base = "💻 terminal\n```\nls -la\n```"
    out = _apply_dedup_counter(base, 3)  # occurrences=3 → (×3)
    assert out.endswith("\n(×3)")
    fence_line = out.splitlines()[-2]
    assert fence_line == "```", f"closing fence polluted: {fence_line!r}"


def test_dedup_counter_newline_after_closing_fence_headerless():
    base = "```\nls -la\n```"
    out = _apply_dedup_counter(base, 2)
    assert out == "```\nls -la\n```\n(×2)"


def test_code_block_still_closes_after_counter():
    base = "```\ngit status\n```"
    out = _apply_dedup_counter(base, 5)
    fences = [ln for ln in out.splitlines() if ln.strip() == "```"]
    assert len(fences) == 2, f"expected exactly 2 fence lines, got {fences!r}"


def test_dedup_counter_inline_for_plain_preview():
    base = '💻 read_file: "/tmp/x.png"'
    out = _apply_dedup_counter(base, 3)
    assert out == '💻 read_file: "/tmp/x.png" (×3)'


def test_dedup_counter_inline_for_no_preview():
    base = "💻 web_search..."
    out = _apply_dedup_counter(base, 1)
    assert out == "💻 web_search... (×1)"


def test_counter_line_not_indented_code_fence():
    base = "```\necho hi\n```"
    out = _apply_dedup_counter(base, 10)
    counter_line = out.splitlines()[-1]
    assert not counter_line.startswith(" "), f"counter must not be indented: {counter_line!r}"
    assert re.fullmatch(r"\(×\d+\)", counter_line), counter_line


def test_owner_helper_matches_glue_path():
    """Owner helper (0-based count) agrees with the thin-glue production path."""
    base = "```\nls\n```"
    assert append_dedup_counter(base, 2) == _apply_dedup_counter(base, 3)
