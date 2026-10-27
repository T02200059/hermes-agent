"""C17 — Checkpoint Mutation Predictor (static path + orchestrator, no live LLM)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from owner.checkpoint_predictor import config as cp_config
from owner.checkpoint_predictor import llm_predict, static_parser
from owner.checkpoint_predictor.predictor import predict_and_checkpoint
from owner.checkpoint_predictor.static_parser import GIT_REPO_SENTINEL, static_parse


# ── static_parser ────────────────────────────────────────────────────────────


def test_static_rm_extracts_paths():
    assert static_parse("rm -rf build/tmp foo.txt", "/proj") == ["build/tmp", "foo.txt"]


def test_static_sed_inplace():
    assert static_parse("sed -i 's/a/b/' src/main.py", "/proj") == ["src/main.py"]


def test_static_sed_without_inplace_returns_empty():
    assert static_parse("sed 's/a/b/' src/main.py", "/proj") == []


def test_static_cp_mv_target_is_last_positional():
    assert static_parse("cp a.py b.py dest/", "/proj") == ["dest/"]
    assert static_parse("mv old.py new.py", "/proj") == ["new.py"]


def test_static_dd_of():
    assert static_parse("dd if=/dev/zero of=/tmp/out.img bs=1M", "/proj") == ["/tmp/out.img"]


def test_static_redirect_overwrite():
    assert static_parse("echo hi > out.txt", "/proj") == ["out.txt"]
    assert static_parse("echo hi >> out.txt", "/proj") == []  # append, not overwrite


def test_static_git_repo_sentinel():
    assert static_parse("git reset --hard HEAD", "/proj") == [GIT_REPO_SENTINEL]
    assert static_parse("git clean -fd", "/proj") == [GIT_REPO_SENTINEL]


def test_static_readonly_unknown_returns_empty():
    assert static_parse("ls -la", "/proj") == []
    assert static_parse("cat foo.py", "/proj") == []


# ── config ───────────────────────────────────────────────────────────────────


def test_config_fail_open_defaults(monkeypatch):
    monkeypatch.setattr(cp_config, "_load_owner_checkpoints_cfg", lambda: {})
    cfg = cp_config.get_checkpoints_cfg()
    assert cfg["predict_enabled"] is True
    assert cfg["predict_static_threshold"] == 1
    assert cfg["predict_cache_size"] == 32


def test_config_coerces_user_values(monkeypatch):
    monkeypatch.setattr(
        cp_config,
        "_load_owner_checkpoints_cfg",
        lambda: {
            "predict_enabled": "false",
            "predict_llm_timeout_ms": "5000",
            "predict_cache_size": "8",
            "predict_static_threshold": "2",
        },
    )
    cfg = cp_config.get_checkpoints_cfg()
    assert cfg["predict_enabled"] is False
    assert cfg["predict_llm_timeout_ms"] == 5000
    assert cfg["predict_cache_size"] == 8
    assert cfg["predict_static_threshold"] == 2


# ── predictor orchestrator ───────────────────────────────────────────────────


def _agent(enabled=True):
    mgr = MagicMock()
    mgr.enabled = enabled
    home = str(__import__("pathlib").Path.home())

    def get_wd(p):
        s = str(p)
        if s in {"/", home} or s.rstrip("/") == home:
            return home if s.rstrip("/") == home or s == home else s
        return "/proj"

    mgr.get_working_dir_for_path.side_effect = get_wd
    return SimpleNamespace(_checkpoint_mgr=mgr, _owner_warn_callback=MagicMock())


def test_predict_disabled_noop(monkeypatch):
    monkeypatch.setattr(
        cp_config, "get_checkpoints_cfg", lambda: {**cp_config._DEFAULTS, "predict_enabled": False}
    )
    agent = _agent()
    predict_and_checkpoint("rm -rf x", "/proj", agent)
    agent._checkpoint_mgr.ensure_checkpoint.assert_not_called()


def test_predict_static_rm_checkpoints_project_root(monkeypatch):
    monkeypatch.setattr(cp_config, "get_checkpoints_cfg", lambda: dict(cp_config._DEFAULTS))
    # avoid LLM
    monkeypatch.setattr(llm_predict, "llm_predict", lambda *a, **k: [])
    agent = _agent()
    predict_and_checkpoint("rm foo.txt", "/proj", agent)
    agent._checkpoint_mgr.ensure_checkpoint.assert_called_once()
    args, _kwargs = agent._checkpoint_mgr.ensure_checkpoint.call_args
    assert args[0] == "/proj"
    assert "before terminal" in args[1]
    agent._owner_warn_callback.assert_not_called()


def test_predict_empty_readonly_does_not_surface_warn(monkeypatch):
    """静态+LLM 皆空的只读命令：不拍 cwd，也不向用户弹 warn。"""
    monkeypatch.setattr(cp_config, "get_checkpoints_cfg", lambda: dict(cp_config._DEFAULTS))
    monkeypatch.setattr(static_parser, "static_parse", lambda *_: [])
    monkeypatch.setattr(llm_predict, "llm_predict", lambda *a, **k: [])
    monkeypatch.setattr(
        "agent.tool_dispatch_helpers._is_destructive_command",
        lambda cmd: False,
    )
    agent = _agent()
    predict_and_checkpoint("ls -la", "/proj", agent)
    agent._checkpoint_mgr.ensure_checkpoint.assert_not_called()
    agent._owner_warn_callback.assert_not_called()


def test_predict_empty_destructive_surfaces_warn(monkeypatch):
    """静态+LLM 皆空但官方判定破坏性、且兜底未拍到 → 仍用户可见 warn。"""
    monkeypatch.setattr(cp_config, "get_checkpoints_cfg", lambda: dict(cp_config._DEFAULTS))
    monkeypatch.setattr(static_parser, "static_parse", lambda *_: [])
    monkeypatch.setattr(llm_predict, "llm_predict", lambda *a, **k: [])
    # Force destructive=True but make fallback's ensure fail so we hit warn path.
    monkeypatch.setattr(
        "agent.tool_dispatch_helpers._is_destructive_command",
        lambda cmd: True,
    )
    agent = _agent()
    agent._checkpoint_mgr.ensure_checkpoint.side_effect = RuntimeError("snap fail")
    predict_and_checkpoint(r"find . -exec rm {} \;", "/proj", agent)
    agent._owner_warn_callback.assert_called_once()


def test_predict_filters_home_and_root(monkeypatch):
    monkeypatch.setattr(cp_config, "get_checkpoints_cfg", lambda: dict(cp_config._DEFAULTS))
    monkeypatch.setattr(static_parser, "static_parse", lambda *_: ["/etc/passwd"])
    monkeypatch.setattr(llm_predict, "llm_predict", lambda *a, **k: [])
    agent = _agent()
    home = str(__import__("pathlib").Path.home())

    def get_wd(p):
        return "/"  # simulate unsafe root

    agent._checkpoint_mgr.get_working_dir_for_path.side_effect = get_wd
    predict_and_checkpoint("rm /etc/passwd", home, agent)
    agent._checkpoint_mgr.ensure_checkpoint.assert_not_called()
    agent._owner_warn_callback.assert_called_once()


def test_predict_llm_used_when_static_empty(monkeypatch):
    monkeypatch.setattr(cp_config, "get_checkpoints_cfg", lambda: dict(cp_config._DEFAULTS))
    monkeypatch.setattr(static_parser, "static_parse", lambda *_: [])
    called = {}

    def fake_llm(command, cwd, timeout_ms, cache_size=None):
        called["yes"] = (command, cwd, timeout_ms, cache_size)
        return ["generated.py"]

    monkeypatch.setattr(llm_predict, "llm_predict", fake_llm)
    agent = _agent()
    predict_and_checkpoint("python gen.py", "/proj", agent)
    assert called["yes"][0] == "python gen.py"
    agent._checkpoint_mgr.ensure_checkpoint.assert_called_once()


def test_predict_never_raises(monkeypatch):
    monkeypatch.setattr(
        cp_config, "get_checkpoints_cfg", lambda: (_ for _ in ()).throw(RuntimeError("cfg boom"))
    )
    agent = _agent()
    # should not raise
    predict_and_checkpoint("rm x", "/proj", agent)


def test_llm_predict_parses_json_array(monkeypatch):
    llm_predict._cache_clear()

    class Msg:
        content = 'Here: ["a.py", "b.py"]'

    class Choice:
        message = Msg()

    class Resp:
        choices = [Choice()]

    monkeypatch.setattr(llm_predict, "_call_llm_sync", lambda **kw: Resp())
    assert llm_predict.llm_predict("x", "/p", 1000, cache_size=8) == ["a.py", "b.py"]
    # cache hit — call again without changing mock; still works
    assert llm_predict.llm_predict("x", "/p", 1000, cache_size=8) == ["a.py", "b.py"]


def test_llm_predict_failure_returns_empty(monkeypatch):
    llm_predict._cache_clear()

    def boom(**kw):
        raise TimeoutError("slow")

    monkeypatch.setattr(llm_predict, "_call_llm_sync", boom)
    assert llm_predict.llm_predict("x", "/p", 100, cache_size=4) == []


def test_destructive_empty_static_falls_back_to_cwd(monkeypatch):
    """静态为空 + 官方破坏性判定 → 仍 ensure_checkpoint(cwd) 并 warn。"""
    monkeypatch.setattr(cp_config, "get_checkpoints_cfg", lambda: dict(cp_config._DEFAULTS))
    monkeypatch.setattr(static_parser, "static_parse", lambda *_: [])
    monkeypatch.setattr(llm_predict, "llm_predict", lambda *a, **k: [])
    monkeypatch.setattr(
        "agent.tool_dispatch_helpers._is_destructive_command",
        lambda cmd: True,
    )
    agent = _agent()
    predict_and_checkpoint("bash deploy.sh", "/proj", agent)
    agent._checkpoint_mgr.ensure_checkpoint.assert_called_once()
    args, _kwargs = agent._checkpoint_mgr.ensure_checkpoint.call_args
    assert args[0] == "/proj"
    assert "destructive cwd fallback" in args[1]
    agent._owner_warn_callback.assert_called_once()


def test_warn_falls_back_to_emit_warning_when_callback_missing(monkeypatch):
    """无 _owner_warn_callback 时回落 _emit_warning，避免静默丢失。"""
    monkeypatch.setattr(cp_config, "get_checkpoints_cfg", lambda: dict(cp_config._DEFAULTS))
    # Predicted paths all map to unsafe root → surface warn regardless of destructive.
    monkeypatch.setattr(static_parser, "static_parse", lambda *_: ["/etc/passwd"])
    monkeypatch.setattr(llm_predict, "llm_predict", lambda *a, **k: [])
    mgr = MagicMock()
    mgr.enabled = True
    mgr.get_working_dir_for_path.side_effect = lambda p: "/"
    emit = MagicMock()
    agent = SimpleNamespace(_checkpoint_mgr=mgr, _emit_warning=emit)
    # deliberately no _owner_warn_callback
    predict_and_checkpoint("rm /etc/passwd", "/proj", agent)
    mgr.ensure_checkpoint.assert_not_called()
    emit.assert_called_once()
