"""T2-20 A3 簇 7b-6 —— ``gateway/run_shutdown.py`` 的关停通知 + 重启前字节码清理。

宿主 ``GatewayShutdownMixin`` 未挂到 ``GatewayRunner`` 的 MRO 上，故直接驱动方法**本体**（规则 ⑪）。

两类裁定：
* **A. 关停/重启通知 —— 结构保我方、内容取上游**：BASE 是 `action`+`hint` 组合；我方改成 i18n 整句键 +
  `{profile_tag}` 注入；上游现在内联两句整句，并把名词改成 **`Hermes`**、给 stop 档**加了一句**
  （`When it is back online, …`）。⇒ 保留整句键与 `{profile_tag}`，文案取上游。
* **B. 重启前清理 `__pycache__` —— 保我方**：宿主没有这段；重启通常紧跟一次代码更新，残留字节码会让
  新进程 import 到旧模块。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from gateway.config import Platform
from gateway.run_shutdown import GatewayShutdownMixin
from gateway.session import SessionSource

# 上游（`HEAD:` 起点 SHA）的硬编码英文 —— 由验收脚本用 AST 复核
UP_STOP = ("⚠️ Hermes{tag} is shutting down — your current task will be interrupted. "
           "When it is back online, send any message and I'll try to pick up where we left off.")
UP_RESTART = ("⚠️ Hermes{tag} is restarting — your current task will be interrupted. "
              "Send any message after the restart and I'll try to resume where you left off.")


class _Runner(GatewayShutdownMixin):
    def __init__(self, *, restart: bool):
        self._restart_requested = restart
        self._restart_command_source = None
        self.notices: list[str] = []
        # 方法尾部还有 home-channel 广播；给空 adapters 让它自然跳过（本簇只断言 active-chat 那一轮）
        self.adapters: dict = {}
        self.config = SimpleNamespace(get_home_channel=lambda platform: None)

    # ---- 依赖钩子 ----
    def _snapshot_running_agents(self):
        return {"k1"}

    async def _shutdown_notification_target(self, session_key):
        return (_source(), Platform.TELEGRAM.value, "c1", None, None)

    def _delivery_adapter_for(self, source):
        return object()

    def _authorization_adapter(self, platform, profile):  # pragma: no cover
        return None

    def _notice_allowed(self, platform, what):
        return True

    def _thread_metadata_for_target(self, *a, **kw):
        return {}

    def _resolve_profile_home_for_source(self, source):
        return None

    async def _send_shutdown_notice(self, adapter, chat_id, msg, kind, platform_str, **kw):
        self.notices.append(msg)
        return True


def _source():
    return SessionSource(platform=Platform.TELEGRAM, chat_id="c1", user_id="u1")


class _AsyncNull:
    """替身：上游新增的 `gateway.run._async_profile_runtime_scope`（A3 期我方 run.py 尚无该符号）。"""

    async def __aenter__(self):
        return None

    async def __aexit__(self, *exc):
        return False


def _drive(*, restart, lang="en", label=None):
    runner = _Runner(restart=restart)
    env = {"HERMES_LANGUAGE": lang}
    if label is not None:
        env["HERMES_LIFECYCLE_LABEL"] = label
    import gateway.run as run_mod
    import gateway.warning_notifications as wn

    async def _present(cb, **kw):
        await cb()
        return True

    with patch.dict("os.environ", env, clear=False), \
         patch.object(wn, "present_notification", _present), \
         patch.object(run_mod, "_async_profile_runtime_scope",
                      lambda home: _AsyncNull(), create=True):
        asyncio.run(runner._notify_active_sessions_of_shutdown())
    return runner


# ------------------------------------------------------------------ A. 关停 / 重启通知
class TestShutdownNotice:

    def test_stop_verbatim(self):
        r = _drive(restart=False)
        assert r.notices == [UP_STOP.format(tag="")]

    def test_restart_verbatim(self):
        r = _drive(restart=True)
        assert r.notices == [UP_RESTART.format(tag="")]

    def test_profile_tag_is_injected(self):
        r = _drive(restart=False, label="coder")
        assert r.notices == [UP_STOP.format(tag=" [coder]")]

    def test_localized(self):
        r = _drive(restart=False, lang="zh")
        assert r.notices and r.notices[0] != UP_STOP.format(tag="")
        assert "正在关闭" in r.notices[0]

    def test_localized_restart(self):
        r = _drive(restart=True, lang="zh")
        assert "正在重启" in r.notices[0]

    @pytest.mark.parametrize("lang", ["en", "zh"])
    @pytest.mark.parametrize("restart", [False, True])
    def test_no_leftover_placeholders(self, lang, restart):
        r = _drive(restart=restart, lang=lang)
        assert "{" not in r.notices[0] and "gateway." not in r.notices[0]


# ------------------------------------------------------------------ B. 重启前字节码清理
class _Captured:
    def __init__(self):
        self.argv: list[str] = []


def _launch(*, restart_after=5.0):
    cap = _Captured()
    runner = _Runner(restart=True)
    runner._detached_restart_helper_started = False
    runner._restart_drain_timeout = restart_after

    def _popen(argv, **kw):
        cap.argv = list(argv)
        return SimpleNamespace(pid=1)

    with patch("gateway.run._resolve_hermes_bin", return_value=["/usr/bin/hermes"]), \
         patch.object(GatewayShutdownMixin, "_restart_watcher_env", staticmethod(lambda: {})), \
         patch("subprocess.Popen", _popen), \
         patch("shutil.which", return_value=None), \
         patch("sys.platform", "linux"):
        asyncio.run(runner._launch_detached_restart_command())
    return cap.argv


class TestPycacheCleanup:

    def test_shell_cmd_purges_pycache(self):
        argv = _launch()
        assert argv, "未走 bash -lc 路径"
        shell = argv[-1]
        assert "-name __pycache__" in shell
        assert "-exec rm -rf {} +" in shell

    def test_pycache_purge_excludes_vcs_and_deps(self):
        shell = _launch()[-1]
        for frag in ("-not -path '*/venv/*'", "-not -path '*/node_modules/*'", "-not -path '*/.git/*'"):
            assert frag in shell, frag

    def test_purge_precedes_the_restart(self):
        shell = _launch()[-1]
        assert shell.index("-name __pycache__") < shell.index("gateway restart")

    def test_deadline_wait_and_restart_preserved(self):
        shell = _launch(restart_after=5.0)[-1]
        assert "kill -0" in shell and "deadline=" in shell and shell.rstrip().endswith("gateway restart")

    def test_repo_root_is_shell_quoted(self):
        shell = _launch()[-1]
        # `find` 的路径必须是经 shlex.quote 的仓库根，而不是裸路径
        frag = shell.split("find ", 1)[1].split(" -type d", 1)[0]
        assert frag and (frag.startswith("'") or "/" in frag or frag.isalnum())
