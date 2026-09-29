"""守卫 ``PluginManager.discover_and_load`` 的「定时取锁 + 薄壳委托」结构。

背景：owner 侧为消除「hermes 开局白屏挂死」引入过一次带超时的取锁。原实现把
上游 ``with self._discovery_lock, _plugin_home_scope(self.home_path):`` 拆成
``acquire`` + ``try/finally``，为套 ``try`` 把 ``with`` 块内 **40 行函数体整体
缩进 +4**，在 ``git diff`` 里表现为整段改写（纯重排 = 冲突放大器）。
现在函数体抽到 ``_discover_and_load_scoped()``，``with`` 行与 40 行正文回到上游
缩进，区域 diff 变成纯插入。

本文件钉住 8 类性质，任何一条被改坏都必须让测试失败：

1. **上游 ``with`` 行逐字保留**，且落在与 ``unload`` / ``_load_plugin`` 相同的
   8 空格缩进（没有被包进 ``try`` 又深一层）。
2. **40 行函数体保持上游缩进** —— 抽查三处代表性行的缩进，而不是比对整段文本。
3. **``discover_and_load`` 是薄壳**，函数体不在里面。
4. **取锁/释放成对**：``acquire(timeout=15.0)`` → ``with`` 进入 → 退出 →
   ``release()``，重入深度归零。
5. **护栏真的拦下**：拿不到锁时不扫描、``_discovered`` 保持 False、
   ``_discovery_deferred`` 置 True。
6. **``force=True`` 不静默丢弃**：改为上抛 ``PluginDiscoveryLockBusy``。
7. **``discover_plugins()`` 如实回报**：返回 ``False`` 表示「本次没落地」，
   且 ``force=True`` 不会被 join-timeout 短路掉。
8. **护栏不吞掉既有行为**：already-discovered / SAFE_MODE / force 三条捷径原样，
   且真实 RLock 在正常与异常路径后都不被泄漏（另一线程可非阻塞拿到）。
"""

from __future__ import annotations

import inspect
import threading
from pathlib import Path

import pytest

import hermes_cli.plugins as plugins

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

# 上游 unload() / _load_plugin() 里那一行，必须逐字一致
UPSTREAM_LOCK_WITH = (
    "with self._discovery_lock, _plugin_home_scope(self.home_path):"
)
HOUSE_INDENT = 8


# ── 工具 ──────────────────────────────────────────────────────────────────────


class _SpyLock:
    """``threading.RLock`` 替身：记录取锁顺序、跟踪重入深度、可控成败。

    真实 RLock 不暴露重入计数，无法断言「取了几层、放了几层」；替身把这件事
    变成可断言的日志。``grant=False`` 用来模拟「后台扫描仍占着锁」。
    """

    def __init__(self, *, grant: bool = True) -> None:
        self.grant = grant
        self.log: list[tuple] = []
        self.depth = 0

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        self.log.append(("acquire", timeout))
        if not self.grant:
            return False
        self.depth += 1
        return True

    def release(self) -> None:
        self.log.append(("release",))
        self.depth -= 1
        assert self.depth >= 0, "释放了未持有的锁"

    def __enter__(self):
        self.log.append(("enter",))
        if not self.grant:
            # 真 RLock 在未取到的情况下进入 with 会永久阻塞；这里改成立刻炸掉，
            # 好让「忘了 return」这类错误变成测试失败而不是挂起。
            raise RuntimeError("enter on an ungranted lock would block")
        self.depth += 1
        return self

    def __exit__(self, *exc) -> bool:
        self.log.append(("exit",))
        self.depth -= 1
        return False


class _Harness:
    def __init__(self, manager, scans, calls):
        self.manager = manager
        self.scans = scans
        self.calls = calls


@pytest.fixture
def harness(tmp_path, monkeypatch):
    """真 PluginManager，但把扫描与外设副作用全部替换成记录器。"""
    scans: list[str] = []
    calls: list[str] = []
    manager = plugins.PluginManager(scope_key=str(tmp_path / "guard-home"))
    monkeypatch.setattr(
        plugins.PluginManager, "_discover_and_load_inner",
        lambda self: scans.append("inner"),
    )
    monkeypatch.setattr(manager, "unload", lambda *a, **k: calls.append("unload"))
    monkeypatch.setattr(
        manager, "_re_register_shell_hooks_after_force",
        lambda *a, **k: calls.append("hooks"),
    )
    monkeypatch.setattr(
        manager, "_evict_stale_persistent_registrations",
        lambda *a, **k: calls.append("evict"),
    )
    monkeypatch.setattr(
        manager, "_refresh_secret_sources_after_discovery",
        lambda *a, **k: calls.append("secrets"),
    )
    return _Harness(manager, scans, calls)


def _lock_is_free(lock) -> bool:
    """从另一线程非阻塞取锁：本线程泄漏了锁时这里会失败。"""
    seen: list[bool] = []

    def probe() -> None:
        got = lock.acquire(blocking=False)
        seen.append(got)
        if got:
            lock.release()

    worker = threading.Thread(target=probe, name="lock-probe")
    worker.start()
    worker.join(timeout=5)
    return seen == [True]


def _source_lines() -> list[str]:
    return Path(plugins.__file__).read_text(encoding="utf-8").split("\n")


# ── 1 & 3 结构：上游 with 行与函数体缩进 ─────────────────────────────────────


def test_scoped_method_keeps_upstream_with_line_verbatim():
    """抽出来的正文必须把上游那一行原封不动带过去（含 8 空格缩进）。"""
    src = inspect.getsource(plugins.PluginManager._discover_and_load_scoped)
    lines = src.split("\n")
    hits = [l for l in lines if l.strip() == UPSTREAM_LOCK_WITH]
    assert len(hits) == 1, hits
    assert len(hits[0]) - len(hits[0].lstrip()) == HOUSE_INDENT, repr(hits[0])


def test_scoped_body_keeps_upstream_indentation():
    """函数体抽查：三处代表行的缩进必须与 BASE 版 ``plugins.py`` 一致。"""
    src = inspect.getsource(plugins.PluginManager._discover_and_load_scoped)

    def indent_of(needle: str) -> int:
        hits = [l for l in src.split("\n") if l.strip() == needle]
        assert len(hits) == 1, (needle, hits)
        return len(hits[0]) - len(hits[0].lstrip())

    assert indent_of("if self._discovered and not force:") == HOUSE_INDENT + 4
    assert indent_of("except BaseException:") == HOUSE_INDENT + 4
    # 上游在 SAFE_MODE 分支与正常路径各写了一次，回退后分别落在 16 / 12
    flag_hits = [
        len(l) - len(l.lstrip())
        for l in src.split("\n")
        if l.strip() == "self._discovered = True"
    ]
    assert sorted(flag_hits) == [HOUSE_INDENT + 4, HOUSE_INDENT + 8]


def test_no_discovery_lock_with_is_nested_deeper_than_house_indent():
    """全文件不变量：这三处 with 里不得出现 12 空格（= 又被套进一层 try）。"""
    indents = sorted(
        len(l) - len(l.lstrip())
        for l in _source_lines()
        if l.strip() == UPSTREAM_LOCK_WITH
    )
    # 8 空格 ×3（unload / _load_plugin / _discover_and_load_scoped）
    # + 16 空格 ×1（deferred-loader 闭包内，与本次无关）
    assert indents == [HOUSE_INDENT] * 3 + [16], indents
    assert 12 not in indents, indents


def test_discover_and_load_is_a_thin_wrapper():
    """函数体不得再内联回来。"""
    src = inspect.getsource(plugins.PluginManager.discover_and_load)
    assert "_discover_and_load_scoped(force)" in src
    assert "with _plugin_home_scope" not in src, "函数体被内联回来了"
    for body_marker in (
        "self._evict_stale_persistent_registrations()",
        "self._refresh_secret_sources_after_discovery()",
        "self._re_register_shell_hooks_after_force()",
        "self._discover_and_load_inner()",
    ):
        assert body_marker not in src, body_marker
    assert len(src.split("\n")) <= 45, len(src.split("\n"))


# ── 4 锁平衡 ─────────────────────────────────────────────────────────────────


def test_lock_acquire_and_release_are_balanced(harness):
    spy = _SpyLock()
    harness.manager._discovery_lock = spy

    harness.manager.discover_and_load()

    assert spy.log == [("acquire", 15.0), ("enter",), ("exit",), ("release",)]
    assert spy.depth == 0
    assert harness.scans == ["inner"]


def test_lock_released_when_body_raises(harness, monkeypatch):
    spy = _SpyLock()
    harness.manager._discovery_lock = spy

    def boom(self):
        raise RuntimeError("扫描炸了")

    monkeypatch.setattr(plugins.PluginManager, "_discover_and_load_inner", boom)

    with pytest.raises(RuntimeError, match="扫描炸了"):
        harness.manager.discover_and_load()

    assert spy.log[-1] == ("release",) or ("release",) in spy.log
    assert spy.depth == 0, "异常路径泄漏了锁"
    assert harness.manager._discovered is False, "失败的扫描被缓存成已发现"


def test_real_rlock_backend_is_left_free(harness):
    """用真 RLock 复核一遍：另一线程必须能拿到锁。"""
    assert _lock_is_free(harness.manager._discovery_lock)
    harness.manager.discover_and_load()
    assert _lock_is_free(harness.manager._discovery_lock), "正常路径泄漏了锁"


# ── 5 & 6 护栏本身 ───────────────────────────────────────────────────────────


def test_busy_lock_skips_scan_and_marks_deferred(harness):
    spy = _SpyLock(grant=False)
    harness.manager._discovery_lock = spy

    assert harness.manager.discover_and_load() is None

    assert spy.log == [("acquire", 15.0)], "超时值或取锁次数被改动"
    assert spy.depth == 0
    assert harness.scans == [], "拿不到锁却仍然扫描了"
    assert harness.manager._discovered is False
    assert harness.manager._discovery_deferred is True


def test_busy_lock_raises_for_forced_rescan(harness):
    spy = _SpyLock(grant=False)
    harness.manager._discovery_lock = spy

    with pytest.raises(plugins.PluginDiscoveryLockBusy):
        harness.manager.discover_and_load(force=True)

    assert harness.scans == [], "强制重扫拿不到锁却仍然扫描了"
    assert harness.manager._discovery_deferred is True


def test_deferred_flag_is_cleared_by_a_successful_scan(harness):
    harness.manager._discovery_deferred = True
    harness.manager._discovery_lock = _SpyLock()

    harness.manager.discover_and_load()

    assert harness.manager._discovery_deferred is False
    assert harness.scans == ["inner"]


# ── 8 护栏不吞掉既有行为 ─────────────────────────────────────────────────────


def test_already_discovered_short_circuit_is_unchanged(harness):
    harness.manager._discovered = True
    harness.manager.discover_and_load()
    assert harness.scans == []
    assert harness.manager._discovery_deferred is False


def test_safe_mode_short_circuit_is_unchanged(harness, monkeypatch):
    monkeypatch.setenv("HERMES_SAFE_MODE", "1")
    harness.manager.discover_and_load()
    assert harness.scans == []
    assert harness.manager._discovered is True
    assert harness.manager._discovery_deferred is False


def test_force_path_still_unloads_and_reinstalls_hooks(harness):
    harness.manager.discover_and_load(force=True)
    assert "unload" in harness.calls
    assert "hooks" in harness.calls
    assert harness.scans == ["inner"]


def test_force_rescans_even_when_already_discovered(harness):
    """force 必须绕过 already-discovered 捷径，否则配置改动在长会话里永远看不见。"""
    harness.manager._discovered = True
    harness.manager.discover_and_load(force=True)
    assert harness.scans == ["inner"], "force 被 already-discovered 捷径吞掉了"
    assert "unload" in harness.calls


# ── 7 discover_plugins 的回报契约 ────────────────────────────────────────────


class _StubManager:
    def __init__(self) -> None:
        self._discovery_deferred = False
        self.seen: list[bool] = []

    def discover_and_load(self, force: bool = False) -> None:
        self.seen.append(force)


def _detach_background(monkeypatch, alive: bool, timed_out: bool) -> None:
    class _Thread:
        def is_alive(self) -> bool:
            return alive

    monkeypatch.setattr(plugins, "_background_discovery_thread", _Thread())
    monkeypatch.setattr(plugins, "_background_discovery_join_timed_out", timed_out)
    monkeypatch.setattr(
        plugins, "_join_background_discovery", lambda timeout=30.0: None
    )


def test_discover_plugins_returns_true_when_registry_landed(monkeypatch):
    _detach_background(monkeypatch, alive=False, timed_out=False)
    stub = _StubManager()
    monkeypatch.setattr(plugins, "get_plugin_manager", lambda: stub)

    assert plugins.discover_plugins() is True
    assert stub.seen == [False]


def test_discover_plugins_returns_false_when_deferred(monkeypatch):
    _detach_background(monkeypatch, alive=False, timed_out=False)
    stub = _StubManager()
    stub._discovery_deferred = True
    monkeypatch.setattr(plugins, "get_plugin_manager", lambda: stub)

    assert plugins.discover_plugins() is False


def test_discover_plugins_returns_false_while_background_still_running(monkeypatch):
    _detach_background(monkeypatch, alive=True, timed_out=True)
    called: list[str] = []
    monkeypatch.setattr(
        plugins, "get_plugin_manager", lambda: called.append("manager") or None
    )

    assert plugins.discover_plugins() is False
    assert called == [], "join 超时后不该再去碰 manager"


def test_discover_plugins_never_short_circuits_a_forced_rescan(monkeypatch):
    """force=True 必须真的走到 discover_and_load，不能被 join 超时早返回吞掉。"""
    _detach_background(monkeypatch, alive=True, timed_out=True)
    stub = _StubManager()
    monkeypatch.setattr(plugins, "get_plugin_manager", lambda: stub)

    plugins.discover_plugins(force=True)

    assert stub.seen == [True], "强制重扫被静默丢弃了"


def test_forced_rescan_raises_through_ensure_plugins_discovered(harness):
    """操作台那条路径拿不到锁时必须看得见异常，而不是被当成成功。"""
    harness.manager._discovery_lock = _SpyLock(grant=False)
    original = plugins.get_plugin_manager
    plugins.get_plugin_manager = lambda: harness.manager
    try:
        with pytest.raises(plugins.PluginDiscoveryLockBusy):
            plugins._ensure_plugins_discovered(force=True)
    finally:
        plugins.get_plugin_manager = original
