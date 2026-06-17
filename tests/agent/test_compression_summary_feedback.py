"""Tests for agent.compression_summary_feedback."""

from __future__ import annotations

import pytest

from agent.compression_summary_feedback import (
    summarize_compression_fallback,
    summarize_compression_feedback,
)
from agent.context_compressor import SUMMARY_PREFIX


_SAMPLE_SUMMARY = f"""{SUMMARY_PREFIX}
## Historical Task Snapshot
User asked: ' refactor the auth module to use JWT instead of sessions'

## Goal
Refactor authentication to JWT tokens.

## Constraints & Preferences
- Keep existing tests green.
- Use python-jose.

## Completed Actions
1. READ config.py:45 — found `==` should be `!=` [tool: read_file]
2. PATCH config.py:45 — changed `==` to `!=` [tool: patch]
3. TEST `pytest tests/` — 3/50 failed: test_parse, test_validate, test_edge [tool: terminal]
4. READ jwt_handler.py — reviewed token signing flow [tool: read_file]

## Active State
Working directory: /home/user/project
Modified files: config.py, jwt_handler.py
Test status: 47/50 passing
Branch: feature/jwt-auth

## Historical In-Progress State
Updating session middleware to validate JWT.

## Blocked
None.

## Key Decisions
Use RS256 for production, HS256 for tests.

## Resolved Questions
Q: Should we keep session cookies? A: No, remove in follow-up PR.

## Historical Pending User Asks
None.

## Relevant Files
- config.py — fixed equality bug at line 45
- jwt_handler.py — token signing logic
- tests/test_auth.py — new JWT tests
- tests/test_session.py — legacy session tests

## Historical Remaining Work
Update middleware and run full test suite.

## Critical Context
RS256 key path: /secrets/jwt.pub
"""


def test_summarize_compression_feedback_basic():
    result = summarize_compression_feedback(
        summary_text=_SAMPLE_SUMMARY,
        before_count=32,
        after_count=8,
        compression_count=1,
        before_tokens=15000,
        after_tokens=5000,
    )

    assert "32 → 8" in result["headline"]
    assert "缩短 75%" in result["text"]
    assert "~15,000 → ~5,000 tokens" in result["text"]
    assert "任务：" in result["text"]
    assert "refactor the auth module" in result["text"]
    assert "进度：" in result["text"]
    assert "config.py" in result["text"]
    assert "47/50 passing" in result["text"]
    assert result["task"]
    assert len(result["completed"]) == 3
    assert len(result["files"]) == 4


def test_summarize_compression_feedback_uses_goal_when_no_task():
    summary = f"""{SUMMARY_PREFIX}
## Goal
Deploy the new feature to staging.

## Completed Actions
1. Ran tests — all green [tool: terminal]

## Active State
Ready to deploy.
"""
    result = summarize_compression_feedback(summary, 10, 5)
    assert "Deploy the new feature to staging" in result["task"]


def test_summarize_compression_feedback_skips_none_sections():
    summary = f"""{SUMMARY_PREFIX}
## Historical Task Snapshot
User asked: 'fix bug'

## Completed Actions
None.

## Active State
None.

## Blocked
None.

## Relevant Files
None.
"""
    result = summarize_compression_feedback(summary, 10, 5)
    assert "进度：" not in result["text"]
    assert "文件：" not in result["text"]
    assert "阻塞：" not in result["text"]


def test_summarize_compression_feedback_truncates_long_items():
    long_action = "A" * 500
    summary = f"""{SUMMARY_PREFIX}
## Historical Task Snapshot
User asked: 'do thing'

## Completed Actions
1. {long_action}
"""
    result = summarize_compression_feedback(summary, 10, 5)
    assert len(result["completed"][0]) < 300
    assert result["completed"][0].endswith("…")


def test_summarize_compression_fallback_shape():
    result = summarize_compression_fallback(
        before_count=20,
        after_count=10,
        compression_count=2,
        before_tokens=8000,
        after_tokens=4000,
    )
    assert "20 → 10" in result["headline"]
    assert "第 2 次" in result["headline"]
    assert result["text"] == result["headline"]
    assert result["task"] == ""
    assert result["completed"] == []


@pytest.mark.parametrize(
    "before,after,expected_pct",
    [
        (100, 50, 50),
        (100, 100, 0),
        (4, 3, 25),
        (0, 0, 0),
    ],
)
def test_saved_percentage(before, after, expected_pct):
    result = summarize_compression_fallback(before, after)
    assert f"缩短 {expected_pct}%" in result["headline"]
