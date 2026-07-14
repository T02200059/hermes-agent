"""Tests for reasoning code-fence escaping.

When reasoning is shown on platforms like Feishu/Telegram it is wrapped in a
```` ``` ```` fenced block and inlined before the answer. Triple-backtick
fences *inside* the reasoning must be escaped or they terminate the wrapping
block early and the rest of the reasoning leaks as plain markdown, breaking
the whole message's formatting.

These tests assert the contract — "no fence inside the reasoning can close
the wrapping block" — not a snapshot of current output.
"""

import re

import gateway.run as gateway_run


_FENCE_LINE_RE = re.compile(r'^[ \t]*`{3,}', re.MULTILINE)


def _wrap(reasoning: str) -> str:
    """Mirror the gateway's wrap: escape, then wrap in a fenced block."""
    safe = gateway_run._escape_code_fences_for_inline_block(reasoning)
    return f"```\n{safe}\n```"


def _fence_line_count(text: str) -> int:
    """Count lines that look like a code fence (3+ backticks, optional indent).

    The wrapping block always contributes exactly 2 — the opening and closing
    ```` ``` ```` on their own lines. Any count > 2 means a fence from inside
    the reasoning survived escaping and will break out of the wrapping block.
    """
    return len(_FENCE_LINE_RE.findall(text))


def test_top_level_fence_is_escaped():
    reasoning = "思考如下:\n```python\ndef f():\n    pass\n```\n结束"
    assert _fence_line_count(_wrap(reasoning)) == 2


def test_fence_with_no_lang_is_escaped():
    reasoning = "代码:\n```\ncode\n```"
    assert _fence_line_count(_wrap(reasoning)) == 2


def test_indented_fence_is_escaped():
    """Indented fences (e.g. code blocks nested in a list item) are the case
    the old ^``` regex missed and leaked."""
    reasoning = "思考:\n  ```python\n  code\n  ```\n结束"
    assert _fence_line_count(_wrap(reasoning)) == 2


def test_tab_indented_fence_is_escaped():
    reasoning = "思考:\n\t```python\n\tcode\n\t```\n结束"
    assert _fence_line_count(_wrap(reasoning)) == 2


def test_leading_space_fence_is_escaped():
    reasoning = "然后:\n   ```\nx\n   ```"
    assert _fence_line_count(_wrap(reasoning)) == 2


def test_four_backtick_fence_is_escaped():
    """A 4+-backtick fence is a distinct CommonMark delimiter and must also be
    neutralized (replaced with 4 quotes) so it can't close a 3-backtick wrap."""
    reasoning = "代码:\n````python\ncode\n````"
    wrapped = _wrap(reasoning)
    assert _fence_line_count(wrapped) == 2
    # And the quotes should match the backtick count.
    assert "''''python" in wrapped


def test_fence_at_start_of_reasoning():
    reasoning = "```python\ncode\n```"
    assert _fence_line_count(_wrap(reasoning)) == 2


def test_crlf_line_endings():
    """CRLF must not prevent fence detection on platforms/clients that pass
    through Windows-style line endings."""
    reasoning = "思考\r\n```python\r\ncode\r\n```"
    assert _fence_line_count(_wrap(reasoning)) == 2


def test_inline_single_backticks_left_untouched():
    """Inline code spans (single backticks) are not fences and must survive
    verbatim — escaping them would corrupt legitimate inline code in the
    reasoning."""
    reasoning = "use `foo` and `bar` here"
    escaped = gateway_run._escape_code_fences_for_inline_block(reasoning)
    assert escaped == reasoning


def test_fence_with_trailing_info_string_preserved():
    """The info string after a fence (language tag) is preserved, only the
    backticks are rewritten."""
    reasoning = "```python\nx\n```"
    escaped = gateway_run._escape_code_fences_for_inline_block(reasoning)
    assert "'''python" in escaped
    assert "```" not in escaped


def test_multiple_fences_all_escaped():
    reasoning = "```python\na\n```\nmid\n```js\nb\n```"
    assert _fence_line_count(_wrap(reasoning)) == 2


def test_empty_string_passthrough():
    assert gateway_run._escape_code_fences_for_inline_block("") == ""


def test_no_fences_passthrough():
    reasoning = "just plain thinking, no code at all."
    assert gateway_run._escape_code_fences_for_inline_block(reasoning) == reasoning
