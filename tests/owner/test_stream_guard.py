"""Tests for owner ``stream_guard`` — the mid-stream degenerate-generation gate.

Context: the 2026-09-17 incident (session ``20260917_122148_57701e``) ran a
30,742-char thinking/output boundary loop for 4m16s and was only stopped by a
human Ctrl-C. Every existing defence missed it: ``output_guard`` judges after
the turn, and ``TurnLivenessWatchdog`` is an *idle* watchdog while a streaming
loop keeps the activity clock permanently fresh. ``stream_guard`` is the
missing progress watchdog — see
``owner/docs/degenerate-stream-guard-design.md``.

The tests load the plugin the same way ``tests/owner/test_output_guard.py``
does (the ``owner-extensions`` directory name is not importable as a package).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def _load_stream_guard():
    path = (
        Path(__file__).resolve().parents[2]
        / "owner"
        / "owner-extensions"
        / "stream_guard"
        / "__init__.py"
    )
    spec = importlib.util.spec_from_file_location("owner_stream_guard", path)
    mod = importlib.util.module_from_spec(spec)
    # Register before exec: the real plugin loader does the same, and
    # ``@dataclass`` resolves its own module through ``sys.modules``.
    sys.modules["owner_stream_guard"] = mod
    spec.loader.exec_module(mod)
    return mod


sg = _load_stream_guard()

_REPO = Path(__file__).resolve().parents[2]
_SAMPLE = (
    _REPO / "owner" / "owner-extensions" / "stream_guard"
    / "samples" / "incident_9_17_thinking_loop.txt"
)

# 事故形态的合成复刻：反复宣告"思考结束、现在输出"+ 风格签名。
_LOOP_LINE = "DONE THINKING. WRITING RESPONSE. ฅ^•ﻌ•^ฅ\n"
_LOOP_TEXT = _LOOP_LINE * 200
# 纯复读形态（2026-07-02 / 2026-08-12 事故）：只有 S3 能识别。
_REPEAT_TEXT = "call\n\n" * 600
# 正常长回复：无阶段终止语、无签名、无复读。
# 注意必须逐句不同 —— 用同一段落 * N 拼出来的"长文"本身就是复读形态，
# S3 会正确地判它为退化（这不是误伤，是测试数据造错了）。
_NORMAL_TEMPLATES = (
    "部署前需要确认配置项 {i} 的默认值与目标环境一致，避免灰度期出现行为漂移。",
    "第 {i} 节说明参数 {i} 与上游服务的交互协议，以及请求超时与重试次数的取值依据。",
    "关于开关 {i}：默认关闭，灰度放量后按批次逐步启用，回滚时按同一批次逆序关闭。",
    "依赖项 {i} 已在上一轮巡检中确认健康，本轮无需变更，仅需在发布单上登记版本号。",
    "回滚预案 {i} 沿用上一版本的快照恢复流程，恢复窗口预计不超过十五分钟。",
    "告警规则 {i} 的静默窗口已与值班同学核对，覆盖周末与节假日流量高峰。",
    "配额项 {i} 与账单口径已对齐，历史误差控制在千分之三以内，符合验收标准。",
    "监控面板 {i} 新增了三个分位指标，用于观察长尾请求对整体时延的贡献比例。",
)
_NORMAL_TEXT = "".join(
    tpl.format(i=index)
    for index in range(1, 26)
    for tpl in _NORMAL_TEMPLATES
)


class _FakeAgent:
    """Stand-in for RunAgent — the guard reaches it via ``request_stop.__self__``."""

    session_id = "sess-test"
    model = "test/model"

    def __init__(self):
        self.warnings: list[str] = []
        self.stops: list[tuple[str, str]] = []

    def _emit_warning(self, message: str) -> None:
        self.warnings.append(message)

    def _request_stream_stop(self, reason: str = "", *, turn_id: str = "") -> bool:
        self.stops.append((reason, turn_id))
        return True


class _Clock:
    def __init__(self, start: float = 1_000_000.0):
        self.now = start

    def time(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture()
def harness(monkeypatch):
    """Freeze the module clock, stub the config, reset window state per test."""
    clock = _Clock()
    monkeypatch.setattr(sg, "time", SimpleNamespace(time=clock.time))
    sg.reset_state()

    def _install(**overrides):
        cfg = dict(sg.DEFAULTS)
        cfg.update(overrides)
        monkeypatch.setattr(sg, "config", lambda: dict(cfg))
        return cfg

    yield clock, _install
    sg.reset_state()


def _feed(text, *, request_stop, kind="text", session_id="s", turn_id="t",
          iteration=1, chunk=64, clock=None, advance_after_first=None):
    """Feed *text* as streaming deltas; returns the number of deltas consumed."""
    consumed = 0
    for index, start in enumerate(range(0, len(text), chunk)):
        sg.observe(
            delta=text[start:start + chunk],
            kind=kind,
            session_id=session_id,
            turn_id=turn_id,
            iteration=iteration,
            model="test/model",
            provider="test-provider",
            surface="cli",
            request_stop=request_stop,
        )
        consumed += 1
        if index == 0 and advance_after_first and clock is not None:
            clock.advance(advance_after_first)
    return consumed


# ---------------------------------------------------------------------------
# 正例
# ---------------------------------------------------------------------------
def test_real_incident_sample_trips_and_stops(harness):
    """回放 2026-09-17 事故原文：必须命中，且远早于人工 Ctrl-C。"""
    clock, install = harness
    if not _SAMPLE.exists():
        pytest.skip("incident sample not present (samples/ is gitignored)")

    install(action="interrupt", grace_seconds=20.0)
    text = _SAMPLE.read_text(encoding="utf-8")
    agent = _FakeAgent()

    consumed = _feed(
        text, request_stop=agent._request_stream_stop,
        clock=clock, advance_after_first=21.0,
    )
    assert consumed > 0

    assert len(agent.stops) == 1, "事故必须被中止恰好一次"
    assert len(agent.warnings) == 1, "事故必须恰好告警一次"
    # 命中点应显著早于原文末尾 —— 原文是被人工打断的，不是自己停的。
    # 线上判定按 eval_interval_chars 节流，因此命中点 = 触发窗口的右沿。
    reason, turn_id = agent.stops[0]
    hit_chars = int(reason.split("chars=")[-1])
    assert 0 < hit_chars < len(text) * 0.75, f"应在生成过半前命中，实际 {hit_chars}/{len(text)}"
    warning = agent.warnings[0]
    assert "[stream-guard]" in warning
    assert "阶段终止语" in warning
    assert turn_id == "t"
    assert "degenerate stream" in reason


def test_synthetic_boundary_loop_trips_on_vote(harness):
    """合成边界循环：S1+S2 双信号投票命中。"""
    _, install = harness
    install(action="interrupt", grace_seconds=0.0)
    agent = _FakeAgent()

    _feed(_LOOP_TEXT, request_stop=agent._request_stream_stop)

    assert len(agent.stops) == 1
    assert len(agent.warnings) == 1


def test_repeat_loop_trips_on_s3_alone(harness):
    """纯复读形态：S1/S2 均为 0，靠 S3 单独成立（历史事故的主要形态）。"""
    _, install = harness
    install(action="interrupt", grace_seconds=0.0)
    agent = _FakeAgent()

    _feed(_REPEAT_TEXT, request_stop=agent._request_stream_stop)

    assert len(agent.stops) == 1
    sig = sg.evaluate_window(_REPEAT_TEXT[-4096:], dict(sg.DEFAULTS))
    assert sig["s3_no_progress"] == 1
    assert sig["s1_marker_rate"] == 0.0
    assert sig["s2_signature_multiple"] == 0.0


def test_reasoning_channel_is_evaluated_too(harness):
    """思考通道同样在闸门范围内（kind="reasoning"）。"""
    _, install = harness
    install(action="interrupt", grace_seconds=0.0)
    agent = _FakeAgent()

    _feed(_LOOP_TEXT, request_stop=agent._request_stream_stop, kind="reasoning")

    assert len(agent.stops) == 1
    assert "通道 reasoning" in agent.warnings[0]


# ---------------------------------------------------------------------------
# 反例 / 误伤控制
# ---------------------------------------------------------------------------
def test_normal_long_reply_never_trips(harness):
    """318 条真实长回复零误伤的离线结论，在回调路径上同样成立。"""
    _, install = harness
    install(action="interrupt", grace_seconds=0.0)
    agent = _FakeAgent()

    _feed(_NORMAL_TEXT, request_stop=agent._request_stream_stop)

    assert agent.stops == []
    assert agent.warnings == []


def test_grace_seconds_suppresses_early_evaluation(harness):
    """首 delta 后 grace 秒内不判定 —— 给正常长思考留余地。"""
    _, install = harness
    install(action="interrupt", grace_seconds=20.0)
    agent = _FakeAgent()

    # 时钟冻结：grace 未过，喂完整个退化文本也不应动作。
    _feed(_LOOP_TEXT, request_stop=agent._request_stream_stop)
    assert agent.stops == []


def test_min_stream_chars_suppresses_short_streams(harness):
    """短回复根本不判（阈值 1200 字符）。"""
    _, install = harness
    install(action="interrupt", grace_seconds=0.0)
    agent = _FakeAgent()

    _feed(_LOOP_LINE * 10, request_stop=agent._request_stream_stop)

    assert agent.stops == []


def test_warn_only_mode_never_stops(harness):
    """灰度模式：只告警、不中止，用来收集真实误伤率。"""
    _, install = harness
    install(action="warn_only", grace_seconds=0.0)
    agent = _FakeAgent()

    _feed(_LOOP_TEXT, request_stop=agent._request_stream_stop)

    assert agent.stops == []
    assert len(agent.warnings) == 1
    assert "灰度" in agent.warnings[0]


def test_at_most_one_action_per_turn(harness):
    """每轮最多动作一次：思考窗口与正文窗口共用 latch。"""
    _, install = harness
    install(action="interrupt", grace_seconds=0.0)
    agent = _FakeAgent()

    _feed(_LOOP_TEXT * 3, request_stop=agent._request_stream_stop, iteration=1)
    _feed(_LOOP_TEXT * 3, request_stop=agent._request_stream_stop,
          iteration=2, kind="reasoning")

    assert len(agent.stops) == 1
    assert len(agent.warnings) == 1


def test_new_turn_rearms_the_action_latch(harness):
    """latch 按 turn 计：下一轮照常受保护。"""
    _, install = harness
    install(action="interrupt", grace_seconds=0.0)

    a1 = _FakeAgent()
    _feed(_LOOP_TEXT, request_stop=a1._request_stream_stop, turn_id="turn-1")
    assert len(a1.stops) == 1

    a2 = _FakeAgent()
    _feed(_LOOP_TEXT, request_stop=a2._request_stream_stop, turn_id="turn-2")
    assert len(a2.stops) == 1


# ---------------------------------------------------------------------------
# 健壮性：观察者绝不影响 token 路径
# ---------------------------------------------------------------------------
def test_missing_request_stop_is_safe(harness):
    """载荷里没有 request_stop（旧版核心）时不崩、不误动作。"""
    _, install = harness
    install(action="interrupt", grace_seconds=0.0)

    _feed(_LOOP_TEXT, request_stop=None)  # 不应抛异常


def test_request_stop_failure_is_swallowed(harness):
    """request_stop 抛异常不影响流式，也不影响告警。"""
    _, install = harness
    install(action="interrupt", grace_seconds=0.0)
    agent = _FakeAgent()

    def _boom(*_a, **_kw):
        raise RuntimeError("core exploded")

    _feed(_LOOP_TEXT, request_stop=_boom)  # 不应抛异常
    assert agent.warnings == []  # 非本仓方法 ⇒ 拿不到 agent 句柄，安静降级


def test_foreign_bound_method_does_not_yield_agent(harness):
    """只有本仓 ``_request_stream_stop`` 才允许回溯出 agent 句柄。"""
    class _Foreign:
        def something_else(self, reason="", *, turn_id=""):
            return True

    foreign = _Foreign()
    assert sg._resolve_agent(foreign.something_else) is None
    agent = _FakeAgent()
    assert sg._resolve_agent(agent._request_stream_stop) is agent


def test_malformed_delta_is_ignored(harness):
    """非字符串 / 空 delta 直接忽略。"""
    _, install = harness
    install(action="interrupt", grace_seconds=0.0)

    sg.observe(delta=None, request_stop=None)
    sg.observe(delta="", request_stop=None)
    sg.observe(delta=123, request_stop=None)
