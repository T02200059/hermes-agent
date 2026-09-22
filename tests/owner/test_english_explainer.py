"""Tests for owner english_explainer — 英文回复中文解说."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, List
from unittest import mock

import pytest

from owner.english_explainer import config as ee_config
from owner.english_explainer.detect import looks_like_english_reply
from owner.english_explainer.hook import _on_transform_llm_output, register_hooks
from owner.english_explainer.prompt import PREFIX, format_delivery


def test_detect_full_english():
    text = (
        "I have finished reviewing the configuration files and the gateway "
        "logs. The issue is that the timeout was too short for the model to "
        "complete the request, so we should increase it and retry."
    )
    hit = looks_like_english_reply(text)
    assert hit is not None
    assert hit["language"] == "en"
    assert hit["reason"] == "english_heavy"


def test_detect_chinese_with_english_terms():
    text = (
        "我已经检查了 config.yaml 和 gateway 的 timeout 设置。"
        "建议把 max_turns 调大，然后重新运行 hermes agent。"
    )
    assert looks_like_english_reply(text) is None


def test_detect_ignores_code_fence_english():
    text = (
        "按下面命令执行即可：\n"
        "```bash\n"
        "echo the quick brown fox jumps over the lazy dog and then we wait "
        "for the process that is running with the configuration\n"
        "```\n"
        "完成后告诉我结果。"
    )
    assert looks_like_english_reply(text) is None


def test_prefix_constant_for_notice_card():
    assert PREFIX == "🔤 系统提示："
    assert format_delivery("你好").startswith(PREFIX)


def test_resolve_enabled_defaults_false(monkeypatch):
    monkeypatch.setattr(ee_config, "_load_raw", lambda: {})
    assert ee_config.load_config()["enabled"] is False
    assert ee_config.resolve_enabled("feishu", "oc_x") is False


def test_resolve_enabled_platform_override(monkeypatch):
    monkeypatch.setattr(
        ee_config,
        "_load_raw",
        lambda: {"enabled": True, "platforms": {"telegram": False, "feishu": True}},
    )
    assert ee_config.resolve_enabled("feishu") is True
    assert ee_config.resolve_enabled("telegram") is False


def test_auto_model_normalizes_to_empty(monkeypatch):
    monkeypatch.setattr(
        ee_config,
        "_load_raw",
        lambda: {"provider": "auto", "model": "auto"},
    )
    cfg = ee_config.load_config()
    assert cfg["provider"] == ""
    assert cfg["model"] == ""


def test_transform_returns_none_and_respects_language(monkeypatch):
    monkeypatch.setattr(
        "owner.english_explainer.hook.display_language_is_chinese",
        lambda: False,
    )
    english = (
        "The deployment finished successfully and the service is healthy "
        "after we restarted the workers with the new configuration."
    )
    assert _on_transform_llm_output(english, session_id="s1", platform="feishu") is None


def test_transform_schedules_when_enabled(monkeypatch):
    monkeypatch.setattr(
        "owner.english_explainer.hook.display_language_is_chinese",
        lambda: True,
    )
    monkeypatch.setattr(
        "owner.english_explainer.hook.resolve_enabled",
        lambda platform="", chat_id=None: True,
    )
    monkeypatch.setattr(
        "owner.english_explainer.hook._should_skip_recent",
        lambda session_id, text: False,
    )
    monkeypatch.setattr(
        "owner.english_explainer.hook.load_config",
        lambda: {"explainer_timeout_ms": 1000},
    )
    called: List[Any] = []

    class FakeThread:
        def __init__(self, target=None, kwargs=None, name=None, daemon=None):
            self.target = target
            self.kwargs = kwargs or {}

        def start(self):
            called.append(self.kwargs)

    monkeypatch.setattr("owner.english_explainer.hook.threading.Thread", FakeThread)

    english = (
        "I checked the logs and found that the request failed because the "
        "token was expired. Please refresh credentials and try again."
    )
    assert _on_transform_llm_output(english, session_id="s2", platform="feishu") is None
    assert len(called) == 1
    assert "response_text" in called[0]


def test_register_hooks():
    hooks = []

    class Ctx:
        def register_hook(self, name, handler):
            hooks.append(name)

    register_hooks(Ctx())
    assert "pre_gateway_dispatch" in hooks
    assert "transform_llm_output" in hooks


def test_feishu_notice_rule_pins_prefix():
    from owner.feishu.auto_card import _DEFAULT_NOTICE_RULES

    prefixes = [r["prefix"] for r in _DEFAULT_NOTICE_RULES]
    assert PREFIX in prefixes
