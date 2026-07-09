"""Regression tests for stray thinking-debris in assistant content.

After the upstream merge started routing Qwen models on OpenCode Go through
``anthropic_messages``, the model occasionally emits visible text that starts
with a lone backtick (sometimes followed by CJK punctuation/whitespace) right
after its reasoning block.  Hermes was stripping ``<think>`` tags but leaving
the backtick, which breaks markdown rendering when the gateway prepends the
reasoning inside a code block.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from run_agent import AIAgent


def _make_tool_defs(*names):
    return [{"type": "function", "function": {"name": n}} for n in names]


@pytest.fixture
def agent():
    """Minimal AIAgent for exercising the assistant-message builder."""
    with (
        patch(
            "run_agent.get_tool_definitions", return_value=_make_tool_defs("web_search")
        ),
        patch("run_agent.check_toolset_requirements", return_value={}),
        patch("run_agent.OpenAI"),
    ):
        a = AIAgent(
            api_key="test-key-1234567890",
            base_url="https://openrouter.ai/api/v1",
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=True,
        )
        a.client = MagicMock()
        return a


def _assistant(content, *, reasoning=None, reasoning_details=None):
    """Build a fake API assistant message."""
    msg = SimpleNamespace(
        content=content,
        tool_calls=None,
        reasoning=reasoning,
        reasoning_content=None,
        reasoning_details=reasoning_details,
    )
    return msg


class TestThinkingDebrisCleanup:
    """``_build_assistant_message`` must clean up leading backtick debris."""

    def test_backtick_cjk_period_after_think_block_is_removed(self, agent):
        raw = "<think>internal reasoning</think>`。实际内容"
        msg = _assistant(raw, reasoning="internal reasoning")
        result = agent._build_assistant_message(msg, "stop")
        assert not result["content"].startswith("`")
        assert "。实际内容" not in result["content"][:10]
        assert result["content"].startswith("实际内容")

    def test_backtick_whitespace_after_think_block_is_removed(self, agent):
        raw = "<think>internal reasoning</think>` 那行硬编码英文"
        msg = _assistant(raw, reasoning="internal reasoning")
        result = agent._build_assistant_message(msg, "stop")
        assert not result["content"].startswith("`")
        assert result["content"].startswith("那行硬编码英文")

    def test_leading_backtick_before_newline_is_removed(self, agent):
        raw = "<think>reasoning</think>`\n\n**当前进度**"
        msg = _assistant(raw, reasoning="reasoning")
        result = agent._build_assistant_message(msg, "stop")
        assert not result["content"].startswith("`")
        assert result["content"].startswith("**当前进度**")

    def test_legitimate_inline_code_is_preserved(self, agent):
        raw = "`foo` is inline code"
        msg = _assistant(raw)
        result = agent._build_assistant_message(msg, "stop")
        # Normal inline code that starts with a letter must survive cleanup.
        assert result["content"].startswith("`foo`")

    def test_code_fence_is_preserved(self, agent):
        raw = "```python\nprint('hi')\n```\nthat was code"
        msg = _assistant(raw)
        result = agent._build_assistant_message(msg, "stop")
        assert result["content"].startswith("```python")

    def test_only_debris_removed_empty_content_stays_empty(self, agent):
        raw = "<think>all reasoning</think>`  "
        msg = _assistant(raw, reasoning="all reasoning")
        result = agent._build_assistant_message(msg, "stop")
        assert result["content"] == ""

    def test_reasoning_details_path_also_cleans_content(self, agent):
        """When reasoning arrives via structured reasoning_details, the visible
        text can still carry the stray backtick and must be cleaned."""
        raw = "` 的残留。让我看看具体数据。"
        details = [{"type": "thinking", "thinking": "structured reasoning"}]
        msg = _assistant(raw, reasoning_details=details)
        result = agent._build_assistant_message(msg, "stop")
        assert not result["content"].startswith("`")
        assert "的残留" in result["content"]
