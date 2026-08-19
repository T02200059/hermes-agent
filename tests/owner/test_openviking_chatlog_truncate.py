"""Tests for OpenViking ChatLog truncation (P2-8)."""

from __future__ import annotations

from plugins.memory.openviking import (
    OpenVikingMemoryProvider,
    _CHATLOG_RE,
    _truncate_chatlog_from_recall,
)


def test_dated_chatlog_is_stripped():
    content = (
        "Summary: talked about billing.\n"
        "2026-07-28 ChatLog:\n"
        "[user]: please check damodel 400\n"
        "[hermes]: looking into it\n"
    )
    out = _truncate_chatlog_from_recall(content, uri="mem://x")
    assert "Summary: talked about billing." in out
    assert "[user]:" not in out
    assert "viking_read" in out


def test_summary_mentioning_chatlog_is_not_stripped():
    content = (
        "Summary: we discussed whether ChatLog: belongs in the recall "
        "payload and decided to strip it on the full-read path.\n"
        "Next step: keep abstracts intact.\n"
    )
    assert _CHATLOG_RE.search(content) is None
    out = _truncate_chatlog_from_recall(content, uri="mem://x")
    assert out == content


def test_dateless_heading_requires_role_line():
    content = (
        "Summary: overview.\n"
        "ChatLog:\n"
        "[杨天宝]: hello\n"
        "[hermes]: hi\n"
    )
    out = _truncate_chatlog_from_recall(content, uri="mem://x")
    assert "Summary: overview." in out
    assert "[杨天宝]:" not in out


def test_abstract_path_also_strips_chatlog():
    class Dummy:
        def _recall_abstract(self, item):
            return item.get("abstract", "")

    out = OpenVikingMemoryProvider._resolve_recall_content(
        Dummy(),
        client=None,
        item={
            "abstract": "Summary: x\nChatLog:\n[user]: hi\n",
            "uri": "mem://u",
        },
        prefer_abstract=True,
        deadline=0,
        request_timeout=1,
        read_state={"full_reads": 0},
        full_read_limit=3,
    )
    assert "Summary: x" in out
    assert "[user]:" not in out
