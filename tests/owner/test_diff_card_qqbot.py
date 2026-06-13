"""Tests for owner.diff_card.qqbot markdown rendering."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from owner.diff_card.qqbot import diff_to_qq_markdown, send_qqbot_diff_markdown


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


def test_diff_to_qq_markdown(sample_diff):
    md = diff_to_qq_markdown(sample_diff, "write_file", file_path="foo.py", max_lines=10)
    assert md is not None
    assert "✍️ write_file: foo.py" in md
    assert "```diff" in md
    assert "-old" in md
    assert "+new" in md
    assert "+1 -1" in md


def test_diff_to_qq_markdown_truncate_lines(sample_diff):
    long_diff = "--- a/f\n+++ b/f\n@@ -1,1 +1,1 @@\n" + "-line\n+line\n" * 100
    md = diff_to_qq_markdown(long_diff, "patch", file_path="f", max_lines=5)
    assert "… 198 more line(s)" in md


def test_diff_to_qq_markdown_char_limit(sample_diff):
    huge = sample_diff + "+x\n" * 5000
    md = diff_to_qq_markdown(huge, "patch", file_path="foo.py", max_lines=10000)
    assert len(md) <= 4000
    assert "… (truncated)" in md


def test_diff_to_qq_markdown_empty():
    assert diff_to_qq_markdown("   ", "write_file") is None


@pytest.mark.asyncio
async def test_send_qqbot_diff_markdown(sample_diff):
    adapter = MagicMock()
    adapter.send = AsyncMock(return_value=MagicMock(success=True))

    result = await send_qqbot_diff_markdown(
        adapter, "qq_chat", sample_diff, "write_file", "foo.py", 10
    )

    assert result is not None
    adapter.send.assert_awaited_once()
    call_args = adapter.send.call_args
    assert call_args[0][0] == "qq_chat"
    assert "✍️ write_file: foo.py" in call_args[0][1]
