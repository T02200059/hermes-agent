"""C19 — chained quick commands (``;;``) + Quick Alias helper."""

from __future__ import annotations

from owner.commands.chained_quick import (
    ensure_leading_slash,
    expand_chained_quick_alias,
    parse_chained_commands,
    strip_leading_slash,
)


def test_parse_absent_sep_returns_single():
    assert parse_chained_commands("/model x") == ["/model x"]
    assert parse_chained_commands("") == []


def test_parse_splits_on_double_semicolon():
    assert parse_chained_commands("/model x ;; /reasoning low") == [
        "/model x",
        "/reasoning low",
    ]


def test_parse_drops_empty_fragments():
    assert parse_chained_commands("/a ;;  ;; /b") == ["/a", "/b"]


def test_expand_joins_target_and_user_args_then_splits():
    assert expand_chained_quick_alias("/model", "gpt-4 ;; /status") == [
        "/model gpt-4",
        "/status",
    ]
    assert expand_chained_quick_alias("/help", "") == ["/help"]


def test_expand_empty_target_yields_empty_or_args_only():
    assert expand_chained_quick_alias("", "") == []
    assert expand_chained_quick_alias("", "/a ;; /b") == ["/a", "/b"]


def test_slash_helpers():
    assert ensure_leading_slash("help") == "/help"
    assert ensure_leading_slash("/help") == "/help"
    assert strip_leading_slash("/help") == "help"
    assert strip_leading_slash("help") == "help"
