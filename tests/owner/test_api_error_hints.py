"""Tests for owner.api_error_hints."""

from __future__ import annotations

import pytest

from owner.api_error_hints import get_api_error_hint


@pytest.mark.parametrize(
    ("status_code", "reason", "expected_substring"),
    [
        (429, None, "请求过于频繁"),
        (None, "rate_limit", "请求过于频繁"),
        (500, None, "模型服务端异常"),
        (502, None, "模型服务端异常"),
        (503, None, "负载过高"),
        (529, None, "负载过高"),
        (504, None, "上游响应超时"),
        (524, None, "上游响应超时"),
        (400, None, "请求被服务端拒绝"),
        (None, "billing", "账户余额或额度不足"),
    ],
)
def test_get_api_error_hint_zh(monkeypatch, status_code, reason, expected_substring):
    monkeypatch.setenv("HERMES_LANGUAGE", "zh")
    hint = get_api_error_hint(status_code, reason)
    assert hint is not None
    assert expected_substring in hint


def test_get_api_error_hint_english_returns_none(monkeypatch):
    monkeypatch.setenv("HERMES_LANGUAGE", "en")
    assert get_api_error_hint(429) is None


def test_get_api_error_hint_unknown_status_returns_none(monkeypatch):
    monkeypatch.setenv("HERMES_LANGUAGE", "zh")
    assert get_api_error_hint(418) is None
