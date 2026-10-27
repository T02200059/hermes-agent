"""Guard: synthetic 消息不触发记忆召回/回写（偿还 `memory-synthetic-guard` 债务）。

2026-10-23 新基线守卫。此前登记在 `owner/validation/coverage_gaps.txt`：

    memory-synthetic-guard  tests/owner/patches/test_memory_synthetic_guard_patch.py
    removed 2026-10-20; synthetic-prefix detection and recall/prefetch skip unpinned

按 §2.2.0 偿还策略撤销登记。

## 这道闸门防的是什么

后台进程完成、异步委派结果、watch 命中、CLI→gateway 交接，都会以**合成的
系统消息**重新进入对话（文本以固定的协议前缀开头）。它们不是用户写的输入。

若不加区分地喂给记忆系统，会发生两件都不会报错的事：

1. **召回污染**：`prefetch_all` 以 `[ASYNC DELEGATION COMPLETE — ...]` 为查询去
   检索，把这个长串当语义信号，召回结果与用户真正关心的事无关，还白花一次
   provider 往返。
2. **记忆污染（更持久）**：`sync_all` / `queue_prefetch_all` 会把合成块当作
   "用户说过的话"镜像进外部记忆库。那之后每次召回都可能把它带回来 —— 一次
   后台通知变成永久的对话事实。

所以这属于安全控制：**失效方向是"让系统生成的内容冒充用户输入进入长期记忆"**，
而且没有任何日志会响。

## 三层判据

| 判据 | 作用 |
|---|---|
| `_is_synthetic()` | 协议前缀匹配（6 个已知标记），容忍前导空白 |
| `_is_non_recallable_command()` | `/` 开头的控制命令跳过召回；5 个带用户提示的命令（queue/steer/goal/subgoal/background）放行 |
| patch apply/revert | 幂等，且 revert 必须**逐方法还原**原实现 |

## 两个容易被"优化"掉的地方

- **前缀必须整段匹配**（含 `"\u2014 "` 这种破折号+空格）。放宽成
  `startswith("[ASYNC")` 会把用户手打的 `[ASYNC] 我的笔记` 也判成合成消息，
  于是那条**真实输入**被静默排除在记忆之外。
- **`/queue 帮我总结这段` 必须放行**。它是用户写的提示，只是前面挂了命令名；
  一刀切"斜杠命令都不召回"会丢掉这类输入。
"""

from __future__ import annotations

import pytest

from owner.patches import memory_synthetic_guard_patch as g


# ── 前缀识别 ──────────────────────────────────────────────────────────────

class TestSyntheticDetection:
    @pytest.mark.parametrize("prefix", [
        "[ASYNC DELEGATION BATCH COMPLETE \u2014 ",
        "[ASYNC DELEGATION COMPLETE \u2014 ",
        "[ASYNC DELEGATION BATCH COMPLETE - ",
        "[ASYNC DELEGATION COMPLETE - ",
        "[IMPORTANT: Background process ",
        "[Session was just handed off from CLI",
    ])
    def test_every_known_prefix_is_recognised(self, prefix):
        """6 个标记逐个覆盖 —— 少测一个就等于允许那一类漏进记忆。"""
        assert g._is_synthetic(prefix + "details") is True

    def test_leading_whitespace_is_tolerated(self):
        """部分注入路径会在前面加换行/空格。"""
        assert g._is_synthetic("\n\n  [IMPORTANT: Background process 42 exited") is True

    def test_user_text_is_not_synthetic(self):
        assert g._is_synthetic("帮我看下这个报错") is False

    def test_partial_prefix_does_not_match(self):
        """**关键负例**：前缀必须整段匹配。

        放宽成 `startswith("[ASYNC")` 会把用户手打的内容也判成合成消息，
        那条真实输入就被静默排除在记忆之外 —— 记忆里少了一条，没人会发现。
        """
        assert g._is_synthetic("[ASYNC] 我在记笔记") is False
        assert g._is_synthetic("[IMPORTANT: 我的待办") is False
        assert g._is_synthetic("[Session was just handed") is False

    def test_prefix_must_be_at_the_start(self):
        """出现在中间不算 —— 用户可能在引用该格式。"""
        assert g._is_synthetic("看这个 [IMPORTANT: Background process") is False

    @pytest.mark.parametrize("value", [None, "", 123, [], {}])
    def test_non_string_input_is_not_synthetic(self, value):
        """非字符串交给原方法自己处理（空 → 跳过），不在这里判。"""
        assert g._is_synthetic(value) is False


# ── 斜杠命令判据 ──────────────────────────────────────────────────────────

class TestNonRecallableCommand:
    @pytest.mark.parametrize("cmd", ["queue", "steer", "goal", "subgoal", "background"])
    def test_recallable_commands_are_allowed(self, cmd):
        """这 5 个带用户提示（飞书 steer 卡片的对话操作），必须放行。"""
        assert g._is_non_recallable_command(f"/{cmd} 帮我总结这段") is False

    @pytest.mark.parametrize("cmd", ["status", "model", "providers", "new", "stop", "yolo"])
    def test_control_commands_skip_recall(self, cmd):
        assert g._is_non_recallable_command(f"/{cmd}") is True

    def test_at_bot_suffix_is_stripped(self):
        """飞书群聊里命令带 `@bot` 后缀：`/status@mybot`。"""
        assert g._is_non_recallable_command("/status@mybot") is True
        assert g._is_non_recallable_command("/queue@mybot 请总结") is False

    def test_subgoal_is_recallable(self):
        """真实命令名是 `/subgoal`（无下划线，见 `slash_commands._handle_subgoal_command`）。"""
        assert g._is_non_recallable_command("/subgoal 加一条") is False

    def test_underscore_variant_does_not_match_the_allowlist(self):
        """记录事实：命令名会 `replace("_", "-")`，而 allowlist 里没有带连字符的项。

        所以 `/sub_goal` 规整成 `sub-goal` 后**匹配不上** `subgoal`，被判为
        不可召回。这不算缺陷（`/sub_goal` 不是真实命令），但它说明：将来若真加了
        带下划线的命令别名，必须同步往 `_RECALLABLE_COMMANDS` 里加**连字符**形式，
        否则那条命令的用户提示会被静默排除在记忆之外。
        """
        assert g._is_non_recallable_command("/sub_goal x") is True

    def test_non_slash_text_is_not_a_command(self):
        assert g._is_non_recallable_command("普通消息") is False

    def test_bare_slash_is_handled(self):
        """单个 `/` 没有命令名，不崩。"""
        assert g._is_non_recallable_command("/") is True

    @pytest.mark.parametrize("value", [None, "", 42])
    def test_non_string_input(self, value):
        assert g._is_non_recallable_command(value) is False


# ── 四个被 patch 的方法：合成消息一律跳过 ────────────────────────────────

class _Recorder:
    """记录原方法是否被调用，作为"是否跳过了"的判据。"""

    def __init__(self):
        self.calls = []

    def __call__(self, *a, **k):
        self.calls.append((a, k))


SYNTHETIC = "[IMPORTANT: Background process 42 exited with code 0]"


@pytest.fixture
def patched(monkeypatch):
    """装上 patch，并把四个原始实现换成 recorder。

    直接替换 `_originals` 而不是真的 patch MemoryManager —— 这样测试不依赖
    MemoryManager 的构造，也不会污染全局类。
    """
    saved_applied = g._applied
    saved_orig = dict(g._originals)

    recs = {n: _Recorder() for n in
            ("prefetch_all", "queue_prefetch_all", "on_turn_start", "sync_all")}
    monkeypatch.setattr(g, "_originals", {n: r for n, r in recs.items()})
    monkeypatch.setattr(g, "_applied", True)
    yield recs

    g._applied = saved_applied
    g._originals.clear()
    g._originals.update(saved_orig)


class TestPatchedMethods:
    def test_prefetch_all_skips_synthetic(self, patched):
        assert g._prefetch_all(object(), SYNTHETIC) == ""
        assert patched["prefetch_all"].calls == []

    def test_prefetch_all_skips_control_command(self, patched):
        assert g._prefetch_all(object(), "/status") == ""
        assert patched["prefetch_all"].calls == []

    def test_prefetch_all_delegates_for_real_input(self, patched):
        """真实输入必须落到原实现 —— 判据是"原方法被调用"，不是返回值。"""
        g._prefetch_all(object(), "帮我看下日志")
        assert len(patched["prefetch_all"].calls) == 1

    def test_prefetch_all_returns_the_original_result(self, patched):
        """放行时返回值必须透传（调用方依赖它拿到召回文本）。"""
        patched["prefetch_all"].calls.clear()
        monkey_string = "recall-text"
        patched["prefetch_all"] = lambda *a, **k: monkey_string
        g._originals["prefetch_all"] = patched["prefetch_all"]
        assert g._prefetch_all(object(), "帮我看下日志") == monkey_string

    def test_prefetch_all_delegates_for_recallable_command(self, patched):
        g._prefetch_all(object(), "/queue 帮我总结")
        assert len(patched["prefetch_all"].calls) == 1, (
            "/queue 带的是用户提示，不该被当成控制命令跳过"
        )

    def test_queue_prefetch_all_skips_synthetic(self, patched):
        g._queue_prefetch_all(object(), SYNTHETIC)
        assert patched["queue_prefetch_all"].calls == []

    def test_queue_prefetch_all_delegates_otherwise(self, patched):
        g._queue_prefetch_all(object(), "普通输入")
        assert len(patched["queue_prefetch_all"].calls) == 1

    def test_on_turn_start_skips_synthetic(self, patched):
        g._on_turn_start(object(), 1, SYNTHETIC)
        assert patched["on_turn_start"].calls == []

    def test_on_turn_start_delegates_otherwise(self, patched):
        g._on_turn_start(object(), 1, "普通输入")
        assert len(patched["on_turn_start"].calls) == 1

    def test_sync_all_skips_synthetic_user_content(self, patched):
        """最重要的一条：合成块不得被回写进记忆库。

        一旦写进去，它就变成"用户说过的话"，此后每次召回都可能带回来。
        """
        g._sync_all(object(), SYNTHETIC, "好的")
        assert patched["sync_all"].calls == [], "合成消息被写进了记忆库"

    def test_sync_all_delegates_otherwise(self, patched):
        g._sync_all(object(), "用户输入", "助手回复")
        assert len(patched["sync_all"].calls) == 1

    def test_session_id_is_forwarded(self, patched):
        """原方法的 session_id 关键字必须透传，否则记忆会落到错误会话。"""
        g._sync_all(object(), "输入", "回复", session_id="s-1")
        _a, kw = patched["sync_all"].calls[0]
        assert kw.get("session_id") == "s-1"

    def test_extra_kwargs_are_forwarded(self, patched):
        g._sync_all(object(), "输入", "回复", session_id="s-1", extra_flag=True)
        _a, kw = patched["sync_all"].calls[0]
        assert kw.get("extra_flag") is True


# ── apply / revert ────────────────────────────────────────────────────────

class TestApplyRevert:
    def test_apply_then_revert_restores_every_method(self):
        import agent.memory_manager as mm

        names = ("prefetch_all", "queue_prefetch_all", "on_turn_start", "sync_all")
        before = {n: getattr(mm.MemoryManager, n) for n in names}
        try:
            g.apply_patch()
            assert getattr(mm.MemoryManager, "prefetch_all") is g._prefetch_all
            assert getattr(mm.MemoryManager, "sync_all") is g._sync_all
        finally:
            g.revert_patch()
        for n in names:
            assert getattr(mm.MemoryManager, n) is before[n], f"{n} 没有被还原"

    def test_apply_is_idempotent(self):
        import agent.memory_manager as mm

        before = mm.MemoryManager.prefetch_all
        try:
            g.apply_patch()
            g.apply_patch()  # 第二次应是 no-op
            assert mm.MemoryManager.prefetch_all is g._prefetch_all
        finally:
            g.revert_patch()
        assert mm.MemoryManager.prefetch_all is before

    def test_revert_without_apply_is_safe(self):
        """从未 apply 过时 revert 不得抛（启动顺序不确定）。"""
        g.revert_patch()

    def test_revert_twice_is_safe(self):
        try:
            g.apply_patch()
        finally:
            g.revert_patch()
            g.revert_patch()
