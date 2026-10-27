"""Tests for Feishu context-compression summary feedback."""

from unittest.mock import MagicMock

import pytest

from agent.context_compressor import (
    COMPRESSED_SUMMARY_METADATA_KEY,
    SUMMARY_PREFIX,
    _SUMMARY_END_MARKER,
)


SAMPLE_SUMMARY_BODY = """## Historical Task Snapshot
User asked: 'refactor the auth module to use JWT instead of sessions'

## Goal
Refactor auth to JWT.

## Constraints & Preferences
- Keep existing API surface

## Completed Actions
1. READ auth.py:45 — found legacy session code [tool: read_file]
2. PATCH auth.py:45 — switched to JWT [tool: patch]
3. TEST `pytest tests/auth` — 5/5 passed [tool: terminal]

## Active State
Working directory: /home/project
Modified files: auth.py

## Historical In-Progress State
Cleaning up imports.

## Blocked
None.

## Key Decisions
Use PyJWT instead of python-jose.

## Resolved Questions
Q: Which JWT library? A: PyJWT.

## Historical Pending User Asks
None.

## Relevant Files
- auth.py — refactored session handling
- config.py — added JWT secret config

## Historical Remaining Work
Update documentation and deploy.

## Critical Context
JWT_SECRET env var must be set."""


def _build_summary_message(body: str) -> dict:
    content = f"{SUMMARY_PREFIX}\n{body}\n\n{_SUMMARY_END_MARKER}"
    return {
        "role": "assistant",
        "content": content,
        COMPRESSED_SUMMARY_METADATA_KEY: True,
    }


class TestFindCompressedSummary:
    def test_finds_message_with_metadata_key(self):
        from owner.feishu.compression_summary import find_compressed_summary

        msg = _build_summary_message("## Historical Task Snapshot\nDo X.")
        messages = [{"role": "user", "content": "hi"}, msg]
        result = find_compressed_summary(messages)
        assert result is not None
        assert "Historical Task Snapshot" in result
        assert SUMMARY_PREFIX not in result
        assert _SUMMARY_END_MARKER not in result

    def test_returns_none_when_no_summary(self):
        from owner.feishu.compression_summary import find_compressed_summary

        messages = [{"role": "user", "content": "hi"}]
        assert find_compressed_summary(messages) is None

    def test_returns_none_for_empty_list(self):
        from owner.feishu.compression_summary import find_compressed_summary

        assert find_compressed_summary([]) is None

    def test_strips_tail_message_after_end_marker(self):
        from owner.feishu.compression_summary import find_compressed_summary

        content = (
            f"{SUMMARY_PREFIX}\n## Historical Task Snapshot\nDo X.\n\n"
            f"{_SUMMARY_END_MARKER}\n\nThis is the real latest user message."
        )
        msg = {
            "role": "assistant",
            "content": content,
            COMPRESSED_SUMMARY_METADATA_KEY: True,
        }
        result = find_compressed_summary([msg])
        assert result is not None
        assert "Historical Task Snapshot" in result
        assert "real latest user message" not in result


class TestParseCompressionSummary:
    def test_parses_all_major_sections(self):
        from owner.feishu.compression_summary import parse_compression_summary

        parsed = parse_compression_summary(SAMPLE_SUMMARY_BODY)
        assert parsed["task"] == "refactor the auth module to use JWT instead of sessions"
        assert parsed["goal"] == "Refactor auth to JWT."
        assert "legacy session code" in parsed["completed actions"]
        assert "auth.py" in parsed["relevant files"]
        assert "Cleaning up imports" in parsed["in_progress"]
        assert parsed["blocked"] == "None."
        assert "PyJWT" in parsed["key decisions"]
        assert "Update documentation" in parsed["remaining"]

    def test_handles_legacy_prefix_and_end_marker(self):
        from owner.feishu.compression_summary import parse_compression_summary

        text = f"{SUMMARY_PREFIX}\n{SAMPLE_SUMMARY_BODY}\n\n{_SUMMARY_END_MARKER}"
        parsed = parse_compression_summary(text)
        assert parsed["task"] == "refactor the auth module to use JWT instead of sessions"

    def test_empty_summary_returns_empty_dict(self):
        from owner.feishu.compression_summary import parse_compression_summary

        assert parse_compression_summary("") == {}


class TestBuildCompressionSummaryText:
    def test_builds_chinese_markdown(self):
        from owner.feishu.compression_summary import build_compression_summary_text

        messages = [
            {"role": "user", "content": "hi"},
            _build_summary_message(SAMPLE_SUMMARY_BODY),
        ]
        text = build_compression_summary_text(
            messages, before_count=10, after_count=4, compression_count=1
        )
        assert text is not None
        assert "🗜️ 上下文已压缩" in text
        assert "10 → 4 条消息" in text
        assert "**目标**：" in text
        assert "auth module" in text
        assert "**进度**：" in text
        assert "**涉及文件**：" in text
        assert "**待办**：" in text or "**剩余工作**：" in text

    def test_includes_token_segment(self):
        from owner.feishu.compression_summary import build_compression_summary_text

        messages = [_build_summary_message("## Historical Task Snapshot\nDo X.")]
        text = build_compression_summary_text(
            messages, before_count=10, after_count=4, before_tokens=1200, after_tokens=400
        )
        assert text is not None
        assert "1,200" in text
        assert "400" in text

    def test_returns_none_when_no_summary(self):
        from owner.feishu.compression_summary import build_compression_summary_text

        assert (
            build_compression_summary_text(
                [{"role": "user", "content": "hi"}], before_count=2, after_count=2
            )
            is None
        )

    def test_compression_count_appended(self):
        from owner.feishu.compression_summary import build_compression_summary_text

        messages = [_build_summary_message("## Historical Task Snapshot\nDo X.")]
        text = build_compression_summary_text(
            messages, before_count=6, after_count=3, compression_count=2
        )
        assert text is not None
        assert "第 2 次" in text


class TestEmitCompressionSummary:
    def test_emits_for_feishu_platform(self):
        from owner.feishu.compression_summary import emit_compression_summary

        agent = MagicMock()
        agent.platform = "feishu"
        agent._emit_status = MagicMock()
        messages = [_build_summary_message(SAMPLE_SUMMARY_BODY)]

        emit_compression_summary(agent, messages, before_count=10, after_count=4)

        agent._emit_status.assert_called_once()
        call_args = agent._emit_status.call_args[0][0]
        assert "🗜️ 上下文已压缩" in call_args

    def test_skips_non_feishu_platform(self):
        from owner.feishu.compression_summary import emit_compression_summary

        agent = MagicMock()
        agent.platform = "cli"
        agent._emit_status = MagicMock()
        messages = [_build_summary_message(SAMPLE_SUMMARY_BODY)]

        emit_compression_summary(agent, messages, before_count=10, after_count=4)

        agent._emit_status.assert_not_called()

    def test_missing_platform_skips(self):
        from owner.feishu.compression_summary import emit_compression_summary

        agent = MagicMock()
        del agent.platform
        agent._emit_status = MagicMock()
        messages = [_build_summary_message(SAMPLE_SUMMARY_BODY)]

        emit_compression_summary(agent, messages, before_count=10, after_count=4)

        agent._emit_status.assert_not_called()

    def test_no_summary_skips(self):
        from owner.feishu.compression_summary import emit_compression_summary

        agent = MagicMock()
        agent.platform = "feishu"
        agent._emit_status = MagicMock()

        emit_compression_summary(agent, [{"role": "user", "content": "hi"}], before_count=2, after_count=2)

        agent._emit_status.assert_not_called()

    def test_emit_failure_is_fail_open(self):
        from owner.feishu.compression_summary import emit_compression_summary

        agent = MagicMock()
        agent.platform = "feishu"
        agent._emit_status = MagicMock(side_effect=RuntimeError("boom"))
        messages = [_build_summary_message("## Historical Task Snapshot\nDo X.")]

        emit_compression_summary(agent, messages, before_count=2, after_count=2)
