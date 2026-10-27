"""B17 飞书半边：clarify 真超时 → 补发提示 + 返回 CANCELLED。"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from owner.clarify.feishu_timeout_stop import (
    apply_feishu_timeout_stop,
    is_feishu_inactivity_timeout,
    timeout_notice_text,
)
from tools.clarify_gateway import CANCELLED


def test_detects_feishu_inactivity_timeout_only():
    resp = "[user did not respond within 10m]"
    assert is_feishu_inactivity_timeout(platform="feishu", answered=False, response=resp)
    assert not is_feishu_inactivity_timeout(platform="feishu", answered=True, response=resp)
    assert not is_feishu_inactivity_timeout(platform="telegram", answered=False, response=resp)
    assert not is_feishu_inactivity_timeout(
        platform="feishu", answered=False, response=CANCELLED,
    )
    assert not is_feishu_inactivity_timeout(
        platform="feishu", answered=False, response="yes please",
    )


def test_timeout_notice_mentions_minutes_and_stop():
    text = timeout_notice_text(600)
    assert "10" in text
    assert "停止" in text or "stopped" in text.lower()


def test_apply_schedules_notice_and_returns_cancelled():
    sent = []

    class _Adapter:
        def send(self, chat_id, text, metadata=None):
            sent.append((chat_id, text, metadata))
            return "coro"

    scheduled = []

    def _schedule(coro, err):
        scheduled.append((coro, err))
        return coro

    runner = SimpleNamespace(
        _ctx=SimpleNamespace(
            source=SimpleNamespace(platform=SimpleNamespace(value="feishu")),
            _status_adapter=_Adapter(),
            _status_chat_id="oc_test",
            _status_thread_metadata={"thread": "1"},
        ),
        _schedule=_schedule,
    )
    clarify_mod = SimpleNamespace(
        CANCELLED=CANCELLED,
        get_clarify_timeout=lambda: 600,
    )

    out = apply_feishu_timeout_stop(
        runner,
        response="[user did not respond within 10m]",
        answered=False,
        clarify_mod=clarify_mod,
    )
    assert out == (CANCELLED, False)
    assert len(scheduled) == 1
    assert scheduled[0][0] == "coro"
    assert sent and sent[0][0] == "oc_test"
    assert "10" in sent[0][1]


def test_apply_noop_for_other_platforms():
    runner = SimpleNamespace(
        _ctx=SimpleNamespace(
            source=SimpleNamespace(platform=SimpleNamespace(value="slack")),
            _status_adapter=MagicMock(),
            _status_chat_id="C1",
            _status_thread_metadata=None,
        ),
        _schedule=MagicMock(),
    )
    clarify_mod = SimpleNamespace(
        CANCELLED=CANCELLED,
        get_clarify_timeout=lambda: 60,
    )
    assert (
        apply_feishu_timeout_stop(
            runner,
            response="[user did not respond within 1m]",
            answered=False,
            clarify_mod=clarify_mod,
        )
        is None
    )
    runner._schedule.assert_not_called()


def test_run_turn_runner_hook_wired():
    from pathlib import Path

    src = Path("gateway/run_turn_runner.py").read_text(encoding="utf-8")
    assert "apply_feishu_timeout_stop" in src
    assert "[owner] B17" in src


def test_timeout_notice_english_via_lang_and_display_language(monkeypatch):
    en = timeout_notice_text(600, lang="en")
    assert "10" in en
    assert "stopped" in en.lower() or "No response" in en
    assert "停止" not in en

    monkeypatch.setattr(
        "owner.explainers.common.display_language",
        lambda: "en",
    )
    import agent.i18n as i18n_mod

    def _fake_t(key, lang=None, **kw):
        return key  # miss → contains clarify_timeout_notice → fallback

    monkeypatch.setattr(i18n_mod, "t", _fake_t)
    text = timeout_notice_text(120)  # no lang → display_language()
    assert "2" in text
    assert "stopped" in text.lower() or "No response" in text
    assert "停止" not in text


def test_timeout_notice_locale_catalog_has_zh_and_en():
    from agent.i18n import t

    zh = t("gateway.clarify_timeout_notice", lang="zh", minutes=5)
    en = t("gateway.clarify_timeout_notice", lang="en", minutes=5)
    assert "clarify_timeout_notice" not in zh
    assert "clarify_timeout_notice" not in en
    assert "5" in zh and "停止" in zh
    assert "5" in en and ("stopped" in en.lower() or "No response" in en)
