"""Guard: read_file / search_files 的单次执行超时（偿还 `file-tool-timeout` 债务）。

2026-10-23 新基线守卫。此前登记在 `owner/validation/coverage_gaps.txt`：

    file-tool-timeout  tests/owner/test_file_tool_timeout.py removed 2026-10-20;
    timeout/budget/restore semantics of read_file and search_files unpinned

按 §2.2.0 偿还策略撤销登记。

## 这道守卫防的是什么

`read_file` / `search_files` 是唯一会读**任意大小外部资源**的工具。在 NFS 挂载、
超大目录、坏磁盘上，一次调用可以把整个 turn 挂死 —— 没有超时的话，用户看到的是
agent 永久无响应，且日志里什么都没有（线程还活着，只是卡在 `read()` 里）。

超时机制的失效方向是**可用性**而非安全，但它有两个安全相关的副作用必须钉住：

1. **超时后不能静默**：必须返回结构化的 `status: timeout`，让 agent 知道
   "这是超时不是空结果"。若退化成返回空字符串，模型会把"没读到"当"文件是空的"
   继续推理 —— 那比报错更糟。
2. **线程不能被无限拖住**：`executor.shutdown(wait=False, cancel_futures=True)`
   是刻意的非阻塞收尾。改成 `wait=True` 会让超时本身变成挂死 —— 守卫把自己
   等的正是它要防的东西。

## 三道语义

| 能力 | 契约 |
|---|---|
| `resolve_file_tool_timeout` | 优先继承 terminal env 的 timeout；否则读 config；再否则 180s |
| `is/set_guard_active` | **线程局部**去重标志：`_run_tool` 与 `invoke_tool` 都知道要护同一个调用，避免嵌套两层 ThreadPoolExecutor |
| `guard_file_tool_call` | 单线程池 + 墙钟预算；超时返回结构化错误而不是抛 |

## 预算继承为什么重要

terminal env 的超时已经实现了 deadline + killpg + 部分输出 + rc=124。文件工具
复用同一个预算，意味着两类工具在同一个 turn 里**不会各自重置计时**：用户在
180s 的终端预算下调大文件，不应该因为"换了个工具"又拿到新的 180s。
"""

from __future__ import annotations

import json
import threading
import time

import pytest

from owner import file_tool_timeout as ftt


# ── 守卫标志：线程局部 + 返回旧值 ─────────────────────────────────────────

class TestGuardFlag:
    def test_default_is_inactive(self):
        assert ftt.is_guard_active() is False

    def test_set_returns_previous_value(self):
        """返回旧值是让调用方能精确还原，而不是靠"记得之前是 false"。"""
        assert ftt.set_guard_active(True) is False
        assert ftt.set_guard_active(True) is True
        assert ftt.set_guard_active(False) is True
        assert ftt.is_guard_active() is False

    def test_flag_is_thread_local(self):
        """**关键**：标志必须是线程局部的。

        用全局 bool 的话，并发 tool 调用会互相看到对方的标志 —— 后者的守卫被
        跳过，于是那次调用**没有超时保护**。表现为"偶尔挂死"，且无法复现。
        """
        seen: dict = {}
        ready = threading.Event()
        proceed = threading.Event()

        def worker():
            ready.set()
            proceed.wait(timeout=5)
            seen["active"] = ftt.is_guard_active()

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        ready.wait(timeout=5)
        ftt.set_guard_active(True)   # 主线程置位
        proceed.set()
        t.join(timeout=5)

        assert seen["active"] is False, (
            "守卫标志泄漏到了另一个线程 —— 并发调用会互相跳过超时保护"
        )

    def test_flag_reset_after_write(self):
        ftt.set_guard_active(True)
        try:
            assert ftt.is_guard_active() is True
        finally:
            ftt.set_guard_active(False)
        assert ftt.is_guard_active() is False


# ── 预算解析：三级优先 ───────────────────────────────────────────────────

class TestResolveTimeout:
    def test_inherits_from_the_active_terminal_env(self, monkeypatch):
        """最高优先级：terminal env 的 timeout。"""
        import tools.terminal_tool as tt

        class _Env:
            timeout = 42

        monkeypatch.setattr(tt, "get_active_env", lambda tid: _Env(), raising=True)
        assert ftt.resolve_file_tool_timeout("t") == 42.0

    def test_falls_back_to_config(self, monkeypatch):
        import tools.terminal_tool as tt
        import hermes_cli.config as cfgmod

        monkeypatch.setattr(tt, "get_active_env", lambda tid: None, raising=True)
        monkeypatch.setattr(
            cfgmod, "load_config",
            lambda: {"terminal": {"timeout": 90}}, raising=True,
        )
        assert ftt.resolve_file_tool_timeout("t") == 90.0

    def test_falls_back_to_default_when_config_missing_key(self, monkeypatch):
        import tools.terminal_tool as tt
        import hermes_cli.config as cfgmod

        monkeypatch.setattr(tt, "get_active_env", lambda tid: None, raising=True)
        monkeypatch.setattr(cfgmod, "load_config", lambda: {}, raising=True)
        assert ftt.resolve_file_tool_timeout("t") == 180.0

    def test_non_positive_env_timeout_is_ignored(self, monkeypatch):
        """`timeout=0` 或负数不是"无限制"，应视为无效并往下走。

        若把 0 当作真值传下去，`fut.result(timeout=0)` 会**立刻超时**，
        每次文件读取都失败 —— 一个配置笔误变成全站功能不可用。
        """
        import tools.terminal_tool as tt
        import hermes_cli.config as cfgmod

        class _Env:
            timeout = 0

        monkeypatch.setattr(tt, "get_active_env", lambda tid: _Env(), raising=True)
        monkeypatch.setattr(
            cfgmod, "load_config", lambda: {"terminal": {"timeout": 90}}, raising=True
        )
        assert ftt.resolve_file_tool_timeout("t") == 90.0

    def test_env_lookup_exception_falls_through(self, monkeypatch):
        """terminal 模块不可用（最小上下文）时不能抛，应降级到 config。"""
        import tools.terminal_tool as tt
        import hermes_cli.config as cfgmod

        def _boom(tid):
            raise RuntimeError("no env")

        monkeypatch.setattr(tt, "get_active_env", _boom, raising=True)
        monkeypatch.setattr(
            cfgmod, "load_config", lambda: {"terminal": {"timeout": 90}}, raising=True
        )
        assert ftt.resolve_file_tool_timeout("t") == 90.0

    def test_config_exception_falls_back_to_default(self, monkeypatch):
        import tools.terminal_tool as tt
        import hermes_cli.config as cfgmod

        monkeypatch.setattr(tt, "get_active_env", lambda tid: None, raising=True)

        def _boom():
            raise RuntimeError("config gone")

        monkeypatch.setattr(cfgmod, "load_config", _boom, raising=True)
        assert ftt.resolve_file_tool_timeout("t") == 180.0

    def test_empty_task_id_is_tolerated(self, monkeypatch):
        """`task_id` 可能为空（CLI 单次调用），不应因此抛或跳过 env 查询。"""
        import tools.terminal_tool as tt
        import hermes_cli.config as cfgmod

        got: list = []

        class _Env:
            timeout = 30

        def _get(tid):
            got.append(tid)
            return _Env()

        monkeypatch.setattr(tt, "get_active_env", _get, raising=True)
        monkeypatch.setattr(cfgmod, "load_config", lambda: {}, raising=True)
        assert ftt.resolve_file_tool_timeout("") == 30.0
        assert got == ["default"], "空 task_id 应归一化为 default 再查"


# ── 执行包装：成功透传 / 超时结构化 / 收尾不阻塞 ─────────────────────────

class TestGuardFileToolCall:
    def test_success_result_is_returned_unchanged(self):
        assert ftt.guard_file_tool_call(
            lambda: {"content": "hi"}, function_name="read_file", budget=5
        ) == {"content": "hi"}

    def test_timeout_returns_a_structured_error_not_an_exception(self):
        """超时必须**返回**而不是抛 —— 抛了会让整个 turn 中断。

        返回结构化 JSON 让 agent 能把"超时"如实转告模型，而不是静默当成空结果。
        """
        def _slow():
            time.sleep(2)
            return "too late"

        out = ftt.guard_file_tool_call(_slow, function_name="read_file", budget=0.05)
        assert isinstance(out, str), "超时应返回 JSON 字符串"
        payload = json.loads(out)
        assert payload["status"] == "timeout"
        assert payload["tool"] == "read_file"
        assert payload["inherited_timeout"] == 0.05

    def test_timeout_payload_is_self_describing(self):
        """报文要告诉模型**怎么办**（缩小范围/查 NFS），否则它只会重试一次。

        这是"失败可见化"在工具层的体现：错误信息必须携带可行动的线索。
        """
        out = ftt.guard_file_tool_call(
            lambda: time.sleep(1), function_name="search_files", budget=0.05
        )
        payload = json.loads(out)
        err = payload["error"]
        assert "offset/limit" in err or "limit" in err
        assert "超时" in err

    def test_timeout_does_not_block_on_the_stuck_thread(self):
        """**关键**：超时后不能等那个卡住的线程。

        `shutdown(wait=True)` 会让守卫自己去等它要防的东西 —— 超时退化回挂死。
        这里用一个睡 3s 的 fn 配 0.05s 预算：若实现阻塞，本用例会耗时 3s。
        """
        def _very_slow():
            time.sleep(3)
            return "done"

        start = time.monotonic()
        out = ftt.guard_file_tool_call(_very_slow, function_name="read_file", budget=0.05)
        elapsed = time.monotonic() - start

        assert json.loads(out)["status"] == "timeout"
        assert elapsed < 2.0, (
            f"超时返回耗时 {elapsed:.1f}s —— 守卫在等卡住的线程，等于没有超时"
        )

    def test_exception_from_fn_is_not_swallowed_by_the_guard(self):
        """真实异常应原样冒泡，不能被当成超时吞掉。

        吞掉会让"文件不存在"和"读超时"在模型眼里变成同一件事。
        """
        def _boom():
            raise FileNotFoundError("nope")

        with pytest.raises(FileNotFoundError):
            ftt.guard_file_tool_call(_boom, function_name="read_file", budget=5)

    def test_task_id_is_echoed_in_the_timeout_payload(self):
        out = ftt.guard_file_tool_call(
            lambda: time.sleep(1), function_name="read_file", budget=0.05, task_id="t-9"
        )
        assert json.loads(out)["task_id"] == "t-9"

    def test_guarded_tool_set_is_exactly_the_two_heavy_readers(self):
        """加入新工具必须是有意的：这个集合决定哪些调用会被包一层线程池。"""
        assert ftt.GUARDED_TOOLS == frozenset({"read_file", "search_files"})
