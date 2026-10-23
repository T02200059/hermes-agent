"""Guard: cron 会话标记的 ContextVar 隔离（偿还 `cron-env-isolation` 债务）。

2026-10-23 新基线守卫。此前登记在 `owner/validation/coverage_gaps.txt`：

    cron-env-isolation  tests/tools/test_cron_session_contextvar_isolation.py removed
    2026-10-20; per-thread ContextVar isolation and env scrub after finally unpinned

按 §2.2.0 偿还策略撤销登记。

## 已有半个覆盖，缺的正是要害

`tests/tools/test_cron_approval_mode.py::TestCronContextVarDetection` 已经断言了
「审批门读 ContextVar 而不是 os.environ」。它覆盖的是**读侧**。

本文件补的是**写侧与清理侧**：

1. `owner_cron_session_enter()` 只写 ContextVar，**绝不**碰 `os.environ`。
2. `owner_cron_session_exit()` 复位 ContextVar **并且**兜底擦除环境变量。
3. **线程隔离**：scheduler 的 worker 线程之间互不可见。旧实现写 `os.environ`
   是全局共享的，所以一个 worker 的 cron 标记会让**并发跑在其它 worker 里的
   交互会话**被当作 cron —— 那会把交互会话的危险命令判定路径整个改掉。
4. `exit()` 在 token 缺失/失效时不得抛（`finally` 里调用，抛了会盖掉真异常）。

## 为什么这属于安全控制

`HERMES_CRON_SESSION` 被审批链路读取以决定「是否允许自动批准」。它若从 cron
泄漏到交互会话，后果是**交互会话获得 cron 的宽松判定**；反过来若 cron 内的标记
丢失，则 cron 任务的危险命令会被当成交互命令拦下（可用性）。两个方向都不报错，
只有行为差异。

## 一条容易被"优化"掉的约束

`session_context.py` 刻意**复用**上游 `_VAR_MAP` 里已有的同名 ContextVar，而不是
新建一个。新建会导致 `set_session_vars()` 写入的那个与 `get_session_env()` 读取的
那个不是同一个实例 —— 读写分叉，表现为「设了但读不到」（2026-10-18 踩过）。
`test_reuses_the_upstream_var_and_does_not_create_a_second_instance` 钉住这一点。
"""

from __future__ import annotations

import os
import threading

import pytest

from owner.cron import run_job_hook as hook
from owner.cron.session_context import _CRON_SESSION


ENV_KEY = "HERMES_CRON_SESSION"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(ENV_KEY, raising=False)
    yield


def _marker() -> object:
    """当前上下文里 cron 标记的值（未设置时返回 var 的 default）。"""
    return _CRON_SESSION.get()


# ── 写侧：只动 ContextVar，不动 os.environ ────────────────────────────────

def test_enter_sets_the_context_var():
    tok = hook.owner_cron_session_enter()
    try:
        assert _marker() == "1"
    finally:
        hook.owner_cron_session_exit(tok)


def test_enter_does_not_write_the_environment():
    """这是本次修复的核心：旧实现写 `os.environ["HERMES_CRON_SESSION"] = "1"`。

    写环境变量会让标记跨线程泄漏 —— scheduler worker 之间共享 `os.environ`。
    """
    tok = hook.owner_cron_session_enter()
    try:
        assert ENV_KEY not in os.environ, (
            "enter() 写了环境变量 —— cron 标记会泄漏到并发线程里的交互会话"
        )
    finally:
        hook.owner_cron_session_exit(tok)


# ── 清理侧：复位 ContextVar + 兜底擦环境 ──────────────────────────────────

def test_exit_resets_the_context_var():
    before = _marker()
    tok = hook.owner_cron_session_enter()
    hook.owner_cron_session_exit(tok)
    assert _marker() == before


def test_exit_scrubs_a_stale_environment_variable(monkeypatch):
    """即便环境变量是被别人（旧代码 / 子进程）写进去的，exit() 也要擦掉。

    这是防御性的第二道保险：`enter()` 已经不写了，但历史进程或第三方 wrapper
    可能写过。留着它会让下一轮读侧误判。
    """
    monkeypatch.setenv(ENV_KEY, "1")
    tok = hook.owner_cron_session_enter()
    hook.owner_cron_session_exit(tok)
    assert ENV_KEY not in os.environ, "exit() 没有擦除残留的环境变量"


def test_exit_without_token_still_scrubs_the_environment(monkeypatch):
    """`finally` 里可能拿不到 token（异常早于 set）。此时仍要擦环境。"""
    monkeypatch.setenv(ENV_KEY, "1")
    hook.owner_cron_session_exit(None)
    assert ENV_KEY not in os.environ


def test_exit_tolerates_an_invalid_token():
    """token 失效/重复复位不得抛 —— 它在 `finally` 里，抛了会盖掉真异常。"""
    hook.owner_cron_session_exit("not-a-token")  # type: ignore[arg-type]


def test_exit_is_idempotent():
    tok = hook.owner_cron_session_enter()
    hook.owner_cron_session_exit(tok)
    hook.owner_cron_session_exit(tok)  # 再调一次不应抛


# ── 线程隔离：本债务的核心 ────────────────────────────────────────────────

def test_marker_does_not_leak_to_another_thread():
    """在一个线程里置标记，另一个已存在的线程必须看不到。

    旧实现（写 os.environ）下这条会失败：环境变量是进程级的，两个 scheduler
    worker 共享它，于是 worker A 的 cron 任务会让 worker B 里的交互会话被误判为
    cron 会话，进而拿到 cron 的审批宽松度。
    """
    seen: dict = {}
    ready = threading.Event()
    proceed = threading.Event()

    def worker():
        ready.set()
        proceed.wait(timeout=5)
        seen["marker"] = _CRON_SESSION.get()
        seen["env"] = os.environ.get(ENV_KEY)

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    ready.wait(timeout=5)

    tok = hook.owner_cron_session_enter()
    try:
        proceed.set()
        t.join(timeout=5)
    finally:
        hook.owner_cron_session_exit(tok)

    assert not t.is_alive(), "worker 线程未结束"
    assert seen["env"] is None, (
        "环境变量泄漏到了另一个线程 —— cron 标记不是线程隔离的"
    )
    assert seen["marker"] != "1", (
        "ContextVar 标记泄漏到了另一个线程 —— 隔离失效"
    )


def test_two_threads_hold_independent_markers():
    """两个线程各自置标记、各自复位，互不干扰。"""
    results: dict = {}
    barrier = threading.Barrier(2, timeout=5)

    def worker(name: str):
        tok = hook.owner_cron_session_enter()
        barrier.wait()
        results[name] = _CRON_SESSION.get()
        hook.owner_cron_session_exit(tok)
        results[name + "_after"] = _CRON_SESSION.get()

    ts = [threading.Thread(target=worker, args=(n,), daemon=True) for n in ("a", "b")]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout=5)

    assert results["a"] == "1" and results["b"] == "1"
    # 各自 exit 后都回到未设置
    assert results["a_after"] != "1"
    assert results["b_after"] != "1"


# ── 不新建第二个 ContextVar（2026-10-18 读写分叉）─────────────────────────

def test_reuses_the_upstream_var_and_does_not_create_a_second_instance():
    """必须与 `gateway.session_context._VAR_MAP` 里的是**同一个对象**。

    新建第二个同名 ContextVar 会让 `set_session_vars()` 写入的和
    `get_session_env()` 读取的不是同一个实例 —— 表现为"设了但读不到"，
    且没有任何报错。这条钉住"复用而非新建"。
    """
    from gateway import session_context as sc

    mapped = sc._VAR_MAP.get("HERMES_CRON_SESSION")
    assert mapped is not None, "上游 _VAR_MAP 里没有 HERMES_CRON_SESSION"
    assert _CRON_SESSION is mapped, (
        "owner 侧用的不是上游注册的那个 ContextVar 实例 —— 读写会分叉"
    )


def test_get_session_env_sees_the_marker():
    """端到端：置标记后，上游的读取入口能读到它。

    这是"读写同一实例"的行为层验证 —— 结构断言过了但行为不通的情况确实存在过。
    """
    from gateway.session_context import get_session_env

    tok = hook.owner_cron_session_enter()
    try:
        assert get_session_env("HERMES_CRON_SESSION", "") == "1"
    finally:
        hook.owner_cron_session_exit(tok)
    assert get_session_env("HERMES_CRON_SESSION", "") != "1"
