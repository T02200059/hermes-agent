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
