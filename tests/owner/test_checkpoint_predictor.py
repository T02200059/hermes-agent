"""Tests for owner/checkpoint_predictor/ — 预测式 checkpoint 触发源。

纯 stdlib + pytest + unittest.mock。无网络调用。
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


# ── config.py ──────────────────────────────────────────────────────────


def test_config_defaults_when_patch_missing(monkeypatch):
    """patch.yaml 不存在时, 返回默认值。"""
    from owner.checkpoint_predictor import config

    monkeypatch.setattr(config, "_load_owner_checkpoints_cfg", lambda: {})
    cfg = config.get_checkpoints_cfg()
    assert cfg["predict_enabled"] is True
    assert cfg["predict_llm_timeout_ms"] == 3000
    assert cfg["predict_cache_size"] == 32
    assert cfg["predict_static_threshold"] == 1


def test_config_respects_explicit_values(monkeypatch):
    """patch.yaml 显式配置覆盖默认值。"""
    from owner.checkpoint_predictor import config

    monkeypatch.setattr(
        config,
        "_load_owner_checkpoints_cfg",
        lambda: {
            "predict_enabled": False,
            "predict_llm_timeout_ms": 5000,
            "predict_cache_size": 64,
            "predict_static_threshold": 2,
        },
    )
    cfg = config.get_checkpoints_cfg()
    assert cfg["predict_enabled"] is False
    assert cfg["predict_llm_timeout_ms"] == 5000
    assert cfg["predict_cache_size"] == 64
    assert cfg["predict_static_threshold"] == 2


def test_config_failopen_on_wrong_types(monkeypatch):
    """配置值类型错误时, 回退默认值。"""
    from owner.checkpoint_predictor import config

    monkeypatch.setattr(
        config,
        "_load_owner_checkpoints_cfg",
        lambda: {"predict_enabled": "not-a-bool", "predict_llm_timeout_ms": "fast"},
    )
    cfg = config.get_checkpoints_cfg()
    assert cfg["predict_enabled"] is True  # 默认
    assert cfg["predict_llm_timeout_ms"] == 3000  # 默认


# ── llm_predict.py ─────────────────────────────────────────────────────


def test_llm_predict_parses_json_array(monkeypatch):
    """LLM 返回合法 JSON array → 正确解析。"""
    from owner.checkpoint_predictor import llm_predict

    class _FakeResp:
        class _Choice:
            class _Msg:
                content = '["out.txt", "build/"]'
            message = _Msg()
        choices = [_Choice()]

    def _fake_call_llm(**kwargs):
        return _FakeResp()

    monkeypatch.setattr(llm_predict, "_call_llm_sync", _fake_call_llm)
    llm_predict._cache_clear()
    result = llm_predict.llm_predict("python -c 'open(\"x\").write()'", "/cwd", 3000)
    assert result == ["out.txt", "build/"]


def test_llm_predict_returns_empty_on_non_json(monkeypatch):
    """LLM 返回非 JSON → 空列表 (触发不拍快照 + 报错)。"""
    from owner.checkpoint_predictor import llm_predict

    class _FakeResp:
        class _Choice:
            class _Msg:
                content = "I cannot determine the files."
            message = _Msg()
        choices = [_Choice()]

    monkeypatch.setattr(llm_predict, "_call_llm_sync", lambda **kw: _FakeResp())
    llm_predict._cache_clear()
    result = llm_predict.llm_predict("npm run build", "/cwd", 3000)
    assert result == []


def test_llm_predict_returns_empty_on_exception(monkeypatch):
    """LLM 调用抛异常 → 空列表。"""
    from owner.checkpoint_predictor import llm_predict

    def _raise(**kw):
        raise TimeoutError("LLM timed out")

    monkeypatch.setattr(llm_predict, "_call_llm_sync", _raise)
    llm_predict._cache_clear()
    result = llm_predict.llm_predict("make", "/cwd", 3000)
    assert result == []


def test_llm_predict_caches_repeat_calls(monkeypatch):
    """同 (command, cwd) 二次调用命中缓存, 不再调 LLM。"""
    from owner.checkpoint_predictor import llm_predict

    call_count = {"n": 0}

    class _FakeResp:
        class _Choice:
            class _Msg:
                content = '["x.txt"]'
            message = _Msg()
        choices = [_Choice()]

    def _fake_call_llm(**kwargs):
        call_count["n"] += 1
        return _FakeResp()

    monkeypatch.setattr(llm_predict, "_call_llm_sync", _fake_call_llm)
    llm_predict._cache_clear()
    llm_predict.llm_predict("make", "/cwd", 3000)
    llm_predict.llm_predict("make", "/cwd", 3000)
    assert call_count["n"] == 1  # 第二次命中缓存
