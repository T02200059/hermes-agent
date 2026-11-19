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


def test_static_redirect_dual_stream_overwrite_targets():
    """[回归 06d7cdbcc9] &>file / >&file 是双流覆盖写, 目标要被提取。"""
    assert static_parse("cmd &> log.txt", "/proj") == ["log.txt"]
    assert static_parse("cmd &>log.txt", "/proj") == ["log.txt"]
    assert static_parse("cmd >&log.txt", "/proj") == ["log.txt"]
    assert static_parse("cmd >& log.txt", "/proj") == ["log.txt"]
    # fd 复制 (目标为数字) 不是写文件
    assert static_parse("cmd >&2", "/proj") == []
    assert static_parse("cmd 2>&1", "/proj") == []
    assert static_parse("cmd >& 2", "/proj") == []
    # 双流追加不覆盖
    assert static_parse("cmd &>> log.txt", "/proj") == []


def test_static_git_repo_sentinel():
    assert static_parse("git reset --hard HEAD", "/proj") == [GIT_REPO_SENTINEL]
    assert static_parse("git clean -fd", "/proj") == [GIT_REPO_SENTINEL]


def test_static_readonly_unknown_returns_empty():
    assert static_parse("ls -la", "/proj") == []
    assert static_parse("cat foo.py", "/proj") == []


# ── config ───────────────────────────────────────────────────────────────────


def test_config_fail_open_defaults(monkeypatch):
    monkeypatch.setattr(cp_config, "_load_owner_checkpoints_cfg", dict)
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



def test_destructive_fallback_skips_home_cwd(monkeypatch):
    """cwd 为 home 时不拍巨型快照，也不谎称已兜底。"""
    monkeypatch.setattr(cp_config, "get_checkpoints_cfg", lambda: dict(cp_config._DEFAULTS))
    monkeypatch.setattr(static_parser, "static_parse", lambda *_: [])
    monkeypatch.setattr(llm_predict, "llm_predict", lambda *a, **k: [])
    monkeypatch.setattr(
        "agent.tool_dispatch_helpers._is_destructive_command",
        lambda cmd: True,
    )
    home = str(__import__("pathlib").Path.home())
    agent = _agent()
    predict_and_checkpoint(r"find . -exec rm {} \;", home, agent)
    agent._checkpoint_mgr.ensure_checkpoint.assert_not_called()
    # Falls through to surface warn (destructive + empty prediction)
    agent._owner_warn_callback.assert_called_once()


def test_destructive_fallback_respects_false_return(monkeypatch):
    """ensure_checkpoint 返回 False 时不算兜底成功。"""
    monkeypatch.setattr(cp_config, "get_checkpoints_cfg", lambda: dict(cp_config._DEFAULTS))
    monkeypatch.setattr(static_parser, "static_parse", lambda *_: [])
    monkeypatch.setattr(llm_predict, "llm_predict", lambda *a, **k: [])
    monkeypatch.setattr(
        "agent.tool_dispatch_helpers._is_destructive_command",
        lambda cmd: True,
    )
    agent = _agent()
    agent._checkpoint_mgr.ensure_checkpoint.return_value = False
    predict_and_checkpoint(r"find . -exec rm {} \;", "/proj", agent)
    agent._checkpoint_mgr.ensure_checkpoint.assert_called_once()
    # fallback returns False → surface uncheckpointed warn
    agent._owner_warn_callback.assert_called_once()
    assert "预测失败" in agent._owner_warn_callback.call_args[0][0]


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


# ── cd 前缀 / 黑名单 / 降噪 (2026-11) ────────────────────────────────────────


def test_effective_cwd_consumes_leading_cd_chain():
    assert static_parser.effective_cwd("cd /srv/app && python x.py", "/root") == "/srv/app"
    assert static_parser.effective_cwd("cd sub && cd deeper && ls", "/proj") == "/proj/sub/deeper"
    assert static_parser.effective_cwd("cd '/srv/a b' && ls", "/root") == "/srv/a b"


def test_effective_cwd_leaves_unresolvable_prefix_alone():
    # 非 cd 开头 / 变量 / cd - 都不消费, 保持 session cwd
    assert static_parser.effective_cwd("ls; cd /srv", "/root") == "/root"
    assert static_parser.effective_cwd("cd $WORKDIR && ls", "/root") == "/root"
    assert static_parser.effective_cwd("cd -", "/root") == "/root"
    assert static_parser.effective_cwd("", "/root") == "/root"


def test_predict_resolves_relative_paths_against_cd_target(monkeypatch):
    """cd 前缀的目录才是相对重定向目标的基准, 不是 session cwd (不能误报 home)。"""
    monkeypatch.setattr(cp_config, "get_checkpoints_cfg", lambda: dict(cp_config._DEFAULTS))
    monkeypatch.setattr(llm_predict, "llm_predict", lambda *a, **k: [])
    agent = _agent()
    home = str(__import__("pathlib").Path.home())
    seen = []

    def get_wd(p):
        seen.append(str(p))
        return "/srv/app"

    agent._checkpoint_mgr.get_working_dir_for_path.side_effect = get_wd
    predict_and_checkpoint(
        "cd /srv/app && python3 gen.py > out.txt 2> err.txt; echo done", home, agent
    )
    assert seen == ["/srv/app/out.txt", "/srv/app/err.txt"]
    agent._checkpoint_mgr.ensure_checkpoint.assert_called_once()
    assert agent._checkpoint_mgr.ensure_checkpoint.call_args[0][0] == "/srv/app"
    agent._owner_warn_callback.assert_not_called()


def test_predict_skips_blacklisted_tmp_root(monkeypatch):
    """/tmp 这类目录的根不进快照, 也不弹卡。"""
    monkeypatch.setattr(cp_config, "get_checkpoints_cfg", lambda: dict(cp_config._DEFAULTS))
    monkeypatch.setattr(static_parser, "static_parse", lambda *_: ["/tmp/out.txt"])
    monkeypatch.setattr(llm_predict, "llm_predict", lambda *a, **k: [])
    agent = _agent()
    agent._checkpoint_mgr.get_working_dir_for_path.side_effect = lambda p: "/tmp"
    predict_and_checkpoint("echo hi > /tmp/out.txt", "/tmp", agent)
    agent._checkpoint_mgr.ensure_checkpoint.assert_not_called()
    agent._owner_warn_callback.assert_not_called()


def test_predict_skips_hermes_scratch_roots(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(cp_config, "get_checkpoints_cfg", lambda: dict(cp_config._DEFAULTS))
    monkeypatch.setattr(static_parser, "static_parse", lambda *_: ["out.txt"])
    monkeypatch.setattr(llm_predict, "llm_predict", lambda *a, **k: [])
    agent = _agent()
    scratch = tmp_path / "cache" / "scratch"
    scratch.mkdir(parents=True)
    agent._checkpoint_mgr.get_working_dir_for_path.side_effect = lambda p: str(scratch)
    predict_and_checkpoint(f"cd {scratch} && python3 gen.py > out.txt", str(tmp_path), agent)
    agent._checkpoint_mgr.ensure_checkpoint.assert_not_called()
    agent._owner_warn_callback.assert_not_called()


def test_predict_quiet_for_non_destructive_home_write(monkeypatch):
    """落在 home 的非破坏性写入只记 debug, 不弹卡。"""
    monkeypatch.setattr(cp_config, "get_checkpoints_cfg", lambda: dict(cp_config._DEFAULTS))
    monkeypatch.setattr(static_parser, "static_parse", lambda *_: ["out.txt"])
    monkeypatch.setattr(llm_predict, "llm_predict", lambda *a, **k: [])
    agent = _agent()
    home = str(__import__("pathlib").Path.home())
    agent._checkpoint_mgr.get_working_dir_for_path.side_effect = lambda p: home
    predict_and_checkpoint("echo hi | tee out.txt", home, agent)
    agent._checkpoint_mgr.ensure_checkpoint.assert_not_called()
    agent._owner_warn_callback.assert_not_called()


def test_predict_still_warns_for_destructive_home_write(monkeypatch):
    monkeypatch.setattr(cp_config, "get_checkpoints_cfg", lambda: dict(cp_config._DEFAULTS))
    monkeypatch.setattr(static_parser, "static_parse", lambda *_: ["important.txt"])
    monkeypatch.setattr(llm_predict, "llm_predict", lambda *a, **k: [])
    agent = _agent()
    home = str(__import__("pathlib").Path.home())
    agent._checkpoint_mgr.get_working_dir_for_path.side_effect = lambda p: home
    predict_and_checkpoint("rm important.txt", home, agent)
    agent._checkpoint_mgr.ensure_checkpoint.assert_not_called()
    agent._owner_warn_callback.assert_called_once()


@pytest.mark.parametrize("cmd", ["westcloud sync &> log.txt", "westcloud sync >&log.txt"])
def test_predict_warns_for_dual_stream_overwrite_home_write(monkeypatch, cmd):
    """[回归 06d7cdbcc9+190a300a16] &>file / >&file 是覆盖写:

    预测目标被 home 安全过滤时, destructive_signal 必须为真,
    否则 warn 收敛后连用户告警都消失。
    """
    monkeypatch.setattr(cp_config, "get_checkpoints_cfg", lambda: dict(cp_config._DEFAULTS))
    monkeypatch.setattr(llm_predict, "llm_predict", lambda *a, **k: [])
    agent = _agent()
    home = str(__import__("pathlib").Path.home())
    agent._checkpoint_mgr.get_working_dir_for_path.side_effect = lambda p: home
    predict_and_checkpoint(cmd, home, agent)
    agent._checkpoint_mgr.ensure_checkpoint.assert_not_called()
    agent._owner_warn_callback.assert_called_once()


def test_destructive_fallback_skips_blacklisted_cwd(monkeypatch):
    monkeypatch.setattr(cp_config, "get_checkpoints_cfg", lambda: dict(cp_config._DEFAULTS))
    monkeypatch.setattr(static_parser, "static_parse", lambda *_: [])
    monkeypatch.setattr(llm_predict, "llm_predict", lambda *a, **k: [])
    monkeypatch.setattr(
        "agent.tool_dispatch_helpers._is_destructive_command", lambda cmd: True
    )
    agent = _agent()
    predict_and_checkpoint("find . -delete", "/tmp", agent)
    agent._checkpoint_mgr.ensure_checkpoint.assert_not_called()


# ── heredoc 内 Python 比较误判降噪 (2026-11-09) ──────────────────────────────


_HEREDOC_READONLY_SQLITE = (
    "cd /root && python3 - <<'EOF'\n"
    "import sqlite3, datetime, re\n"
    "c=sqlite3.connect('/root/.hermes/state.db'); c.row_factory=sqlite3.Row\n"
    "def dump(sid, maxlen=700, kw=None, maxn=60):\n"
    "    printed=0\n"
    "    for i,r in enumerate(rows):\n"
    "        n=i+1\n"
    "        if n>=maxn: break\n"
    "        if printed>0: print('---')\n"
    "        printed+=1\n"
    "EOF"
)


def test_static_heredoc_python_comparison_not_redirect():
    """heredoc 里的 n>=maxn / printed>0 不能当成 > file 重定向。"""
    assert static_parse(_HEREDOC_READONLY_SQLITE, "/root") == []
    assert static_parse("echo hi > out.txt", "/proj") == ["out.txt"]
    assert static_parse("echo hi >> out.txt", "/proj") == []


def test_static_redirect_after_heredoc_still_detected():
    cmd = (
        "python3 - <<'EOF'\n"
        "print(1)\n"
        "EOF\n"
        "echo hi > out.txt"
    )
    assert static_parse(cmd, "/proj") == ["out.txt"]


def test_strip_heredoc_bodies_keeps_outer_redirect():
    cmd = "cat > /tmp/x <<'EOF'\nline with n>=1 and a>b\nEOF"
    visible = static_parser.strip_heredoc_bodies(cmd)
    assert "n>=1" not in visible
    assert "a>b" not in visible
    assert "cat > /tmp/x <<'EOF'" in visible or visible.startswith("cat > /tmp/x")


def test_predict_heredoc_python_comparison_no_feishu_tip(monkeypatch):
    """只读 python heredoc（体含 >= / > 比较）+ 根被滤掉 → 不建快照、不发飞书 tip。"""
    monkeypatch.setattr(cp_config, "get_checkpoints_cfg", lambda: dict(cp_config._DEFAULTS))
    monkeypatch.setattr(llm_predict, "llm_predict", lambda *a, **k: [])
    agent = _agent()

    def get_wd(p):
        # any predicted path under /root or home resolves to unsafe root
        return "/"

    agent._checkpoint_mgr.get_working_dir_for_path.side_effect = get_wd
    predict_and_checkpoint(_HEREDOC_READONLY_SQLITE, "/root", agent)
    agent._checkpoint_mgr.ensure_checkpoint.assert_not_called()
    agent._owner_warn_callback.assert_not_called()


def test_predict_real_redirect_home_still_tips(monkeypatch):
    """真 shell 重定向写 home、根被滤掉 → 仍用户可见 tip（真实破坏性）。"""
    monkeypatch.setattr(cp_config, "get_checkpoints_cfg", lambda: dict(cp_config._DEFAULTS))
    monkeypatch.setattr(llm_predict, "llm_predict", lambda *a, **k: [])
    agent = _agent()
    home = str(__import__("pathlib").Path.home())
    agent._checkpoint_mgr.get_working_dir_for_path.side_effect = lambda p: home
    predict_and_checkpoint("echo hi > important.txt", home, agent)
    agent._checkpoint_mgr.ensure_checkpoint.assert_not_called()
    agent._owner_warn_callback.assert_called_once()
    assert "预测失败" in agent._owner_warn_callback.call_args[0][0]


# ── 引号感知重定向 / 只读闸门 (2026-11-12 线上回归) ──────────────────────────


@pytest.mark.parametrize(
    "cmd",
    [
        "awk '$1>2048{print $1\"KB\\t\"$2}' files.txt",  # 线上 11-12 10:30
        "awk 'NR>1' all_nodes.yml",  # 线上 11-11 16:38
        "grep -c 'a>b' x.txt",
        'echo "=== 1. expired -> 2. done ==="',
        "docker inspect c --format '{{range .Mounts}}{{.Source}} -> {{.Dest}}{{end}}'",
    ],
)
def test_static_quoted_gt_is_not_redirect(cmd):
    """引号里的 > / -> / >= 是文本, 不是重定向 (旧正则把它们都当写信号)。"""
    assert static_parse(cmd, "/proj") == []


def test_static_redirect_multiple_targets_skip_dev_null():
    assert static_parse("python3 gen.py > out.txt 2> err.txt 2>/dev/null", "/proj") == [
        "out.txt",
        "err.txt",
    ]


def test_static_multiline_chain_detects_cp_target():
    """cd/赋值/cp 用 && 串起来时也要认出真目标 (线上 11-12 18:57 漏拍的那条)。"""
    cmd = (
        "cd /data/hermes/profiles/zhangwg && TS=$(date +%Y%m%d-%H%M%S) && "
        "echo \"TS=$TS\" && cp config.yaml config.yaml.bak-$TS"
    )
    assert static_parse(cmd, "/root") == ["config.yaml.bak-$TS"]


@pytest.mark.parametrize(
    "cmd",
    [
        "ls -la",
        "cat foo.py | head -20",
        "cd /data/xy-portal && grep -n expired bmc.py",
        "docker logs --since 1h hermes 2>&1 | tail -50",
        "docker inspect x --format '{{.Mounts}}'",
        "kubectl -n prod get pods",
        "ssh -o BatchMode=yes root@10.0.0.1 'kubectl get node'",
        "git stash list; git ls-files | wc -l; du -sh .git",
        "git ls-files -z | xargs -0 -I{} du -k '{}' | sort -rn | head",
        "sed -n '1,40p' config.yaml",
        "systemctl status nginx",
        "find /var/log -name '*.log' | head",
        "mysql --defaults-extra-file=/tmp/x.cnf -e \"START TRANSACTION; SELECT 1; COMMIT\"",
        "nvidia-smi",
    ],
)
def test_is_read_only_command_accepts_inspection(cmd):
    assert static_parser.is_read_only_command(cmd) is True


@pytest.mark.parametrize(
    "cmd",
    [
        "rm -rf build",
        "cp a b",
        "sed -i 's/a/b/' f.py",
        "echo hi > out.txt",
        "echo hi >> out.txt",
        "find . -delete",
        r"find . -exec rm {} \;",
        "python3 - <<'EOF'\nprint(1)\nEOF",
        "bash deploy.sh",
        "git stash push -m x",
        "git reset --hard",
        "docker exec c sh -c 'rm /x'",
        "awk '{print > \"out\"}' f",
        "kubectl delete pod x",
        "mysql -e 'DELETE FROM t'",
        "nvidia-smi --gpu-reset",
    ],
)
def test_is_read_only_command_rejects_writes(cmd):
    assert static_parser.is_read_only_command(cmd) is False


@pytest.mark.parametrize(
    "cmd,expected",
    [
        ("rm -rf x", True),
        ("sed -i 's/a/b/' f", True),
        ("echo hi > out.txt", True),
        ("echo hi >> out.txt", False),  # 追加不覆盖
        ("awk '$1>2048{print}' f", False),
        ("docker logs x --format '{{.A}} -> {{.B}}'", False),
        ("grep -n 'n>=3' f", False),
        ("find . -exec rm {} \\;", True),
    ],
)
def test_destructive_signal_is_quote_aware(cmd, expected):
    assert static_parser.destructive_signal(cmd) is expected


@pytest.mark.parametrize(
    "cmd,expected",
    [
        # fd 复制 (目标为数字) — 非破坏性 (06d7cdbcc9 原始意图, 不得回退)
        ("cmd 2>&1", False),
        ("cmd 1>&2", False),
        ("cmd >&2", False),
        ("cmd >& 2", False),
        ("cmd 2>&1 >> app.log", False),
        ("git fetch origin 2>&1 | tail -3", False),
        # bash 双流覆盖写文件 — 破坏性 (06d7cdbcc9 回归漏判)
        ("cmd &> log.txt", True),
        ("cmd &>log.txt", True),
        ("cmd &> log.txt 2>&1", True),
        ("cmd >&log.txt", True),
        ("cmd >& log.txt", True),
        # 常规覆盖写 — 破坏性 (现状保持)
        ("cmd > file.txt", True),
        ("cmd >file.txt", True),
        ("cmd 2> err.txt", True),
        ("cmd > out 2>&1", True),
        # 追加 — 非破坏性 (现状保持)
        ("cmd >> file.txt", False),
        ("cmd &>> log.txt", False),
        # a4d5a41f70 引号感知不得回退
        ('echo "a -> b"', False),
        ("awk '$3>10' f", False),
        ("awk 'NR>1' f", False),
        ('grep -n "n>=3" f', False),
    ],
)
def test_destructive_signal_redirect_semantics_matrix(cmd, expected):
    """fd 复制 / 覆盖写 / 追加 / 引号文本 的完整语义矩阵。"""
    assert static_parser.destructive_signal(cmd) is expected


def test_read_only_gate_dual_stream_overwrite():
    """&>file / >&file 构成写信号 → 不是只读命令; fd 复制不构成。"""
    assert static_parser.is_read_only_command("docker logs x 2>&1") is True
    assert static_parser.is_read_only_command("ls -la &> log.txt") is False
    assert static_parser.is_read_only_command("ls -la >&log.txt") is False
    assert static_parser.is_read_only_command("ls -la &>> log.txt") is False


def test_predict_readonly_command_skips_llm_and_snapshot(monkeypatch):
    """线上 11-12 18:57: sed/diff 只读命令 → 不调 LLM、不拍快照、不弹 tip。"""
    monkeypatch.setattr(cp_config, "get_checkpoints_cfg", lambda: dict(cp_config._DEFAULTS))
    called = {"llm": False}

    def fake_llm(*a, **k):
        called["llm"] = True
        return ["config.yaml"]

    monkeypatch.setattr(llm_predict, "llm_predict", fake_llm)
    agent = _agent()
    cmd = (
        "cd /data/hermes/profiles/zhangwg; echo '--- model block'; "
        "sed -n '/^model:/,/^providers:/p' config.yaml; "
        "diff config.yaml.bak-x config.yaml | grep -c '^[<>]'"
    )
    predict_and_checkpoint(cmd, "/root", agent)
    assert called["llm"] is False
    agent._checkpoint_mgr.ensure_checkpoint.assert_not_called()
    agent._owner_warn_callback.assert_not_called()


def test_predict_awk_comparison_skips_llm(monkeypatch):
    """线上 11-11 16:38 / 11-12 10:30: awk 里的 NR>1 / $1>2048 不再触发预测。"""
    monkeypatch.setattr(cp_config, "get_checkpoints_cfg", lambda: dict(cp_config._DEFAULTS))
    called = {"llm": False}

    def fake_llm(*a, **k):
        called["llm"] = True
        return ["bmc.py"]

    monkeypatch.setattr(llm_predict, "llm_predict", fake_llm)
    agent = _agent()
    predict_and_checkpoint(
        "cd /data/xy-portal/backend/app/routers\n"
        "grep -n expired bmc.py | head -10\n"
        "awk 'NR>1 {print $1}' bmc.py",
        "/data/xy-portal",
        agent,
    )
    assert called["llm"] is False
    agent._checkpoint_mgr.ensure_checkpoint.assert_not_called()
    agent._owner_warn_callback.assert_not_called()


def test_predict_ssh_pipeline_skips_llm(monkeypatch):
    """ssh 远程命令不动本地文件 → 不调 LLM、不拍快照。"""
    monkeypatch.setattr(cp_config, "get_checkpoints_cfg", lambda: dict(cp_config._DEFAULTS))
    called = {"llm": False}

    def fake_llm(*a, **k):
        called["llm"] = True
        return ["known_hosts"]

    monkeypatch.setattr(llm_predict, "llm_predict", fake_llm)
    agent = _agent()
    predict_and_checkpoint(
        "ssh -o BatchMode=yes root@10.10.100.9 'kubectl get node -o wide'",
        "/root",
        agent,
    )
    assert called["llm"] is False
    agent._checkpoint_mgr.ensure_checkpoint.assert_not_called()
    agent._owner_warn_callback.assert_not_called()


def test_predict_script_ssh_guess_is_blacklisted(monkeypatch):
    """线上 11-11 11:54: LLM 对 bash 脚本猜出 ~/.ssh → 被凭据黑名单挡掉。"""
    monkeypatch.setattr(cp_config, "get_checkpoints_cfg", lambda: dict(cp_config._DEFAULTS))
    monkeypatch.setattr(llm_predict, "llm_predict", lambda *a, **k: ["known_hosts"])
    agent = _agent()
    ssh_dir = str(__import__("pathlib").Path.home() / ".ssh")
    agent._checkpoint_mgr.get_working_dir_for_path.side_effect = lambda p: ssh_dir
    predict_and_checkpoint(
        "bash /data/hermes/cache/scratch/maas_rack_ip.sh 2>&1 | grep -E 'ip|host'",
        "/root",
        agent,
    )
    agent._checkpoint_mgr.ensure_checkpoint.assert_not_called()
    agent._owner_warn_callback.assert_not_called()


def test_predict_blacklists_secret_dirs(monkeypatch):
    """凭据目录 (如 ~/.ssh) 不作为快照根, 即使预测命中也不弹卡。"""
    monkeypatch.setattr(cp_config, "get_checkpoints_cfg", lambda: dict(cp_config._DEFAULTS))
    monkeypatch.setattr(static_parser, "static_parse", lambda *_: ["known_hosts"])
    monkeypatch.setattr(llm_predict, "llm_predict", lambda *a, **k: [])
    agent = _agent()
    ssh_dir = str(__import__("pathlib").Path.home() / ".ssh")
    agent._checkpoint_mgr.get_working_dir_for_path.side_effect = lambda p: ssh_dir
    predict_and_checkpoint("ssh-keygen -R host", ssh_dir, agent)
    agent._checkpoint_mgr.ensure_checkpoint.assert_not_called()
    agent._owner_warn_callback.assert_not_called()
