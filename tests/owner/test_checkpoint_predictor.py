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
    assert cfg["predict_enabled"] is True
    assert cfg["predict_llm_timeout_ms"] == 3000


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
    """LLM 返回非 JSON → 空列表。"""
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
    assert call_count["n"] == 1


# ── predictor.py ───────────────────────────────────────────────────────
from pathlib import Path
from unittest.mock import MagicMock


@pytest.fixture
def mock_agent(tmp_path):
    """构造一个最小 mock agent, 含 _checkpoint_mgr 和报错回调。"""
    agent = MagicMock()
    agent._checkpoint_mgr = MagicMock()
    agent._checkpoint_mgr.enabled = True
    agent._checkpoint_mgr.get_working_dir_for_path = lambda p: str(
        Path(p).expanduser().resolve().parent
    )
    agent._checkpoint_mgr.ensure_checkpoint = MagicMock(return_value=True)
    agent._owner_warn_callback = MagicMock()
    return agent


def test_predict_disabled_does_nothing(mock_agent, monkeypatch):
    """predict_enabled=false → 不调 ensure_checkpoint。"""
    from owner.checkpoint_predictor import config, predictor, llm_predict

    monkeypatch.setattr(
        config, "_load_owner_checkpoints_cfg", lambda: {"predict_enabled": False}
    )
    llm_predict._cache_clear()
    predictor.predict_and_checkpoint("rm foo.py", "/cwd", mock_agent)
    mock_agent._checkpoint_mgr.ensure_checkpoint.assert_not_called()


def test_static_success_checkpoints_without_llm(mock_agent, monkeypatch):
    """静态解析成功 → ensure_checkpoint 被调用, LLM 不调。"""
    from owner.checkpoint_predictor import config, predictor, llm_predict

    monkeypatch.setattr(config, "_load_owner_checkpoints_cfg", lambda: {})
    llm_predict._cache_clear()

    llm_calls = {"n": 0}

    def _count_llm(**kw):
        llm_calls["n"] += 1
        return None

    monkeypatch.setattr(llm_predict, "_call_llm_sync", _count_llm)

    predictor.predict_and_checkpoint("sed -i \'s/a/b/\' foo.py", "/cwd", mock_agent)
    mock_agent._checkpoint_mgr.ensure_checkpoint.assert_called_once()
    assert llm_calls["n"] == 0


def test_llm_success_checkpoints(mock_agent, monkeypatch):
    """静态空 + LLM 成功 → ensure_checkpoint 被调用。"""
    from owner.checkpoint_predictor import config, predictor, llm_predict

    monkeypatch.setattr(config, "_load_owner_checkpoints_cfg", lambda: {})
    llm_predict._cache_clear()

    class _FakeResp:
        class _Choice:
            class _Msg:
                content = '["out.txt"]'
            message = _Msg()
        choices = [_Choice()]

    monkeypatch.setattr(
        llm_predict, "_call_llm_sync", lambda **kw: _FakeResp()
    )

    predictor.predict_and_checkpoint("npm run build", "/cwd", mock_agent)
    mock_agent._checkpoint_mgr.ensure_checkpoint.assert_called_once()


def test_llm_failure_no_checkpoint_but_warns(mock_agent, monkeypatch):
    """静态空 + LLM 失败 → ensure_checkpoint 不被调用, 报错回调被调用。"""
    from owner.checkpoint_predictor import config, predictor, llm_predict

    monkeypatch.setattr(config, "_load_owner_checkpoints_cfg", lambda: {})
    llm_predict._cache_clear()

    def _raise(**kw):
        raise TimeoutError("timed out")

    monkeypatch.setattr(llm_predict, "_call_llm_sync", _raise)

    predictor.predict_and_checkpoint("make", "/cwd", mock_agent)
    mock_agent._checkpoint_mgr.ensure_checkpoint.assert_not_called()
    mock_agent._owner_warn_callback.assert_called_once()


def test_safe_roots_drops_home_and_root(mock_agent, monkeypatch):
    """预测路径解析到 / 或 home → 丢弃, 不快照。"""
    from owner.checkpoint_predictor import config, predictor, llm_predict

    monkeypatch.setattr(config, "_load_owner_checkpoints_cfg", lambda: {})
    llm_predict._cache_clear()

    class _FakeResp:
        class _Choice:
            class _Msg:
                content = '["~/foo.txt"]'
            message = _Msg()
        choices = [_Choice()]

    monkeypatch.setattr(
        llm_predict, "_call_llm_sync", lambda **kw: _FakeResp()
    )

    mock_agent._checkpoint_mgr.get_working_dir_for_path = lambda p: str(Path.home())

    predictor.predict_and_checkpoint("python -c \'x\'", "/cwd", mock_agent)
    mock_agent._checkpoint_mgr.ensure_checkpoint.assert_not_called()
    mock_agent._owner_warn_callback.assert_called_once()


# ── E2E: 消息隔离 ──────────────────────────────────────────────────────


def test_e2e_predictor_does_not_touch_main_messages(mock_agent, monkeypatch):
    """预测器的 LLM 调用走 auxiliary 侧路, 不进 agent 主 messages。"""
    from owner.checkpoint_predictor import config, predictor, llm_predict

    monkeypatch.setattr(config, "_load_owner_checkpoints_cfg", lambda: {})
    llm_predict._cache_clear()

    captured_messages = []

    class _FakeResp:
        class _Choice:
            class _Msg:
                content = '["out.txt"]'
            message = _Msg()
        choices = [_Choice()]

    def _capture_messages(**kwargs):
        captured_messages.append(kwargs.get("messages"))
        return _FakeResp()

    monkeypatch.setattr(llm_predict, "_call_llm_sync", _capture_messages)

    predictor.predict_and_checkpoint("make", "/tmp/fakeproj", mock_agent)

    assert len(captured_messages) == 1
    side_messages = captured_messages[0]
    assert len(side_messages) == 1
    assert side_messages[0]["role"] == "user"
    assert "file-mutation predictor" in side_messages[0]["content"]
