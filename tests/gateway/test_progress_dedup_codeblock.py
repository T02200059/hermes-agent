"""Tests for progress-message dedup counter vs markdown code fences.

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

# Mirrors the gateway/run.py dedup-concatenation logic under fix.
_FENCE = "```"


def _apply_dedup_counter(base_msg: str, count: int) -> str:
    """Reproduce the (×N) concatenation rule.

    ``count`` is the repeat count as queued (already incremented upstream),
    matching ``f"{base_msg} (×{count + 1})"`` semantics in run.py.
    """
    sep = "\n" if base_msg.endswith(_FENCE) else " "
    return f"{base_msg}{sep}(×{count + 1})"


# ---------------------------------------------------------------------------
# 1. Code-block base_msg — counter must go on its own line
# ---------------------------------------------------------------------------

def test_dedup_counter_newline_after_closing_fence_with_header():
    base = "💻 terminal\n```\nls -la\n```"
    out = _apply_dedup_counter(base, 2)  # 3rd occurrence
    assert out.endswith("\n(×3)")
    # The closing fence line must be exactly ``` (no trailing counter)
    fence_line = out.splitlines()[-2]
    assert fence_line == "```", f"closing fence polluted: {fence_line!r}"


def test_dedup_counter_newline_after_closing_fence_headerless():
    # Consecutive terminal block: header already collapsed to "".
    base = "```\nls -la\n```"
    out = _apply_dedup_counter(base, 1)  # 2nd occurrence
    assert out == "```\nls -la\n```\n(×2)"


def test_code_block_still_closes_after_counter():
    """The rendered string must contain a balanced fenced block."""
    base = "```\ngit status\n```"
    out = _apply_dedup_counter(base, 4)
    # Even number of fence lines => balanced open/close (counter line is not a fence)
    fences = [ln for ln in out.splitlines() if ln.strip() == "```"]
    assert len(fences) == 2, f"expected exactly 2 fence lines, got {fences!r}"


# ---------------------------------------------------------------------------
# 2. Plain-text base_msg — counter stays inline (unchanged behavior)
# ---------------------------------------------------------------------------

def test_dedup_counter_inline_for_plain_preview():
    base = '💻 read_file: "/tmp/x.png"'
    out = _apply_dedup_counter(base, 2)
    assert out == '💻 read_file: "/tmp/x.png" (×3)'


def test_dedup_counter_inline_for_no_preview():
    base = "💻 web_search..."
    out = _apply_dedup_counter(base, 0)
    assert out == "💻 web_search... (×1)"


# ---------------------------------------------------------------------------
# 3. CommonMark sanity — counter line never parsed as fence content
# ---------------------------------------------------------------------------

def test_counter_line_not_indented_code_fence():
    """A leading-space line would be a lazy-indented code continuation;
    the counter must sit at column 0 as a fresh paragraph."""
    base = "```\necho hi\n```"
    out = _apply_dedup_counter(base, 9)
    counter_line = out.splitlines()[-1]
    assert not counter_line.startswith(" "), f"counter must not be indented: {counter_line!r}"
    assert re.fullmatch(r"\(×\d+\)", counter_line), counter_line
