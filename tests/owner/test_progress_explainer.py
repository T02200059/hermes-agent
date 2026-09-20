"""Tests for owner ``progress_explainer`` — 沉默期进度旁白.

设计稿: owner/docs/design/silent-progress-narration/progress-explainer.md

覆盖 §12 的 1/2/5/6/7/8 项:
  1. 打点: tool started/completed、on_stream_delta 两种 kind、tool_gen
  2. 阈值边界: silence 59/60/61s、min_interval、max_per_turn 封顶
  5. 让位: stream_guard tripped → 不调 call_llm、不发送
  6. 静默失败: call_llm 抝异常/超时 → 无出站消息、无异常上抛
  7. 生命周期: stop() → 任务退出、回调还原、tracker 注销
  8. 配置: 三级查找 + 非法值回落默认

E2E (真 import + 临时 HERMES_HOME) 不在本文件范围（设计稿 §12 另列）。
所有测试 mock call_llm, 不打真网络。
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from owner.progress_explainer import config as pe_config
from owner.progress_explainer import tracker as pe_tracker
from owner.progress_explainer.dispatcher import (
    _observe_stream_delta,
    _register_tracker,
    _unregister_tracker,
    ProgressExplainer,
    install_progress_explainer,
    register_hooks,
    stop,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


class FakeAdapter:
    def __init__(self):
        self.sent: List[Dict[str, Any]] = []

    async def send(self, chat_id: str, text: str, metadata: Any = None, **kwargs):
        self.sent.append({"chat_id": chat_id, "text": text})
        return SimpleNamespace(success=True, message_id=f"msg-{len(self.sent)}")


class FakeAgent:
    def __init__(self):
        self.session_id = "sess-1"
        self._current_turn_id = "turn-1"
        self.tool_progress_callback = None
        self.tool_gen_callback = None
        self.interim_assistant_callback = None
        self.activity = {
            "current_tool": "terminal",
            "last_activity_desc": "terminal command running",
            "api_call_count": 3,
            "max_iterations": 120,
        }

    def get_activity_summary(self) -> dict:
        return dict(self.activity)


class FakeRunner:
    def __init__(self, agent):
        self._agent = agent
        self.adapter: Any = None

    def _adapter_for_source(self, source):
        return self.adapter

    def _peek_session_state(self, key):
        # turn.agent is the live agent → run considered current
        return SimpleNamespace(turn=SimpleNamespace(agent=self._agent))


def _source(platform: str = "feishu", chat_id: str = "oc_123"):
    return SimpleNamespace(platform=platform, chat_id=chat_id, session_id="sess-1")


def _full_cfg(**overrides: Any) -> Dict[str, Any]:
    full = dict(pe_config._DEFAULTS)
    full.update(overrides)
    full["enabled"] = True
    return full


def _build(**overrides: Any):
    """构造 (explainer, adapter, agent)——不调 install()（无事件循环时安全）。"""
    agent = FakeAgent()
    runner = FakeRunner(agent)
    adapter = FakeAdapter()
    runner.adapter = adapter
    expl = ProgressExplainer(
        runner=runner,
        agent=agent,
        source=_source(),
        session_key="sess-1",
        turn_ctx=SimpleNamespace(message="帮我跑个长任务", _cleanup_msg_ids=[]),
        executor_ref=lambda: None,
    )
    expl._cfg = _full_cfg(**overrides)
    return expl, adapter, agent


async def _drive(expl: ProgressExplainer, rounds: int, monkeypatch_llm=True) -> None:
    """事件循环内: install + 驱动 N 轮 tick（不 stop——由调用方控制）。"""
    expl.install()
    for _ in range(rounds):
        await expl._tick_once()


async def _run_case(**overrides: Any) -> tuple:
    """install 但不 stop：供打点类测试直接调包装后的回调。"""
    expl, adapter, agent = _build(**overrides)
    await _drive(expl, rounds=0)
    return expl, adapter, agent


def _ok_response():
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="正在执行终端命令查看目录结构。")
            )
        ]
    )


def _fake_llm_ok(*a, **k):
    return _ok_response()


# ---------------------------------------------------------------------------
# §12-1 打点
# ---------------------------------------------------------------------------


class TestInstrumentation:
    def test_tool_started_completed_events(self):
        expl, adapter, agent = asyncio.run(_run_case())
        cb = agent.tool_progress_callback
        cb("tool.started", "terminal", "ls -la", {"command": "ls -la"})
        state = expl._tracker.state()
        assert state["current_tool"] == "terminal"
        assert state["branch"] == "tool"

        cb(
            "tool.completed",
            "terminal",
            None,
            None,
            duration=2.5,
            is_error=False,
            result="file1\nfile2",
        )
        state = expl._tracker.state()
        assert state["current_tool"] is None
        # completed 后 60s 窗口内 tool_recent 仍算 tool 分支
        assert state["branch"] == "tool"

    def test_stream_delta_kinds(self):
        tr = pe_tracker.ProgressTracker(time.time(), "msg", {})
        tr.record_stream_delta("reasoning", "正在分析问题…", time.time())
        tr.record_stream_delta("text", "答:", time.time())
        state = tr.state()
        assert state["stream"]["reasoning_chars_total"] == len("正在分析问题…")
        assert state["stream"]["text_chars_total"] == len("答:")
        # reasoning 与 text 都"30s 内"：reasoning 分支优先（若 reasoning 更晚）
        assert state["branch"] in ("reasoning", "text")

    def test_on_stream_delta_observer_feeds_tracker(self):
        tr = pe_tracker.ProgressTracker(time.time(), "msg", {})
        _register_tracker("sess-9", "turn-9", tr)
        try:
            _observe_stream_delta(
                "推理增量", kind="reasoning", session_id="sess-9", turn_id="turn-9"
            )
            state = tr.state()
            assert state["stream"]["reasoning_chars_total"] == len("推理增量")
        finally:
            _unregister_tracker("sess-9", "turn-9")

    def test_tool_gen_event(self):
        expl, adapter, agent = asyncio.run(_run_case())
        gen_cb = agent.tool_gen_callback
        assert gen_cb is not None
        gen_cb("write_file")
        state = expl._tracker.state()
        evs = [e for e in state["events"] if e.get("phase") == "tool_gen"]
        assert evs and evs[0]["name"] == "write_file"

    def test_interim_resets_silence(self):
        expl, adapter, agent = asyncio.run(_run_case())
        expl._tracker._last_content_ts = time.time() - 300
        assert expl._tracker.state()["silence_seconds_since_last_content"] >= 299
        cb = agent.interim_assistant_callback
        cb("一段可见的散文")
        assert expl._tracker.state()["silence_seconds_since_last_content"] < 1

    def test_register_hooks_registers_observer(self):
        class _Ctx:
            def __init__(self):
                self.hooks: List = []

            def register_hook(self, name, cb):
                self.hooks.append((name, cb))

        ctx = _Ctx()
        register_hooks(ctx)
        assert ctx.hooks and ctx.hooks[0][0] == "on_stream_delta"


# ---------------------------------------------------------------------------
# §12-2 阈值边界
# ---------------------------------------------------------------------------


class TestThresholds:
    def test_silence_59_60_61(self, monkeypatch):
        monkeypatch.setattr("agent.auxiliary_client.call_llm", _fake_llm_ok)

        async def _case(silence_s: float, should_send: bool):
            expl, adapter, agent = _build(tick_seconds=1, silence_seconds=60)
            await _drive(expl, rounds=0)
            expl._tracker._last_content_ts = time.time() - silence_s
            expl._tracker._last_reasoning_ts = None
            expl._tracker._last_text_ts = None
            expl._tracker._last_tool_started_ts = None
            expl._tracker._current_tool = None
            await expl._tick_once()
            if should_send:
                assert len(adapter.sent) == 1, f"silence={silence_s} 应触发发送"
            else:
                assert not adapter.sent, f"silence={silence_s} 不应发送"

        asyncio.run(_case(59, False))
        asyncio.run(_case(60, True))
        asyncio.run(_case(61, True))

    def test_min_interval_dedup(self, monkeypatch):
        monkeypatch.setattr("agent.auxiliary_client.call_llm", _fake_llm_ok)

        async def _case():
            expl, adapter, agent = _build(
                tick_seconds=1, silence_seconds=1, min_interval_seconds=10**6
            )
            await _drive(expl, rounds=0)
            expl._tracker._last_content_ts = time.time() - 500
            await expl._tick_once()
            assert len(adapter.sent) == 1
            await expl._tick_once()
            # 第一条发出后 min_interval=10^6 → 第二条不再发
            assert len(adapter.sent) == 1

        asyncio.run(_case())

    def test_max_per_turn(self, monkeypatch):
        monkeypatch.setattr("agent.auxiliary_client.call_llm", _fake_llm_ok)

        async def _case():
            expl, adapter, agent = _build(
                tick_seconds=1,
                silence_seconds=1,
                min_interval_seconds=1,
                max_per_turn=2,
            )
            await _drive(expl, rounds=0)
            expl._tracker._last_content_ts = time.time() - 500
            for _ in range(8):
                await expl._tick_once()
            assert len(adapter.sent) <= 2

        asyncio.run(_case())


# ---------------------------------------------------------------------------
# §12-5 让位
# ---------------------------------------------------------------------------


class TestYield:
    def test_stream_guard_tripped_no_send(self, monkeypatch):
        import owner.progress_explainer.dispatcher as disp

        class _Tripped:
            def __call__(self, sid, tid):
                return {"tripped": True, "total_chars": 999}

        monkeypatch.setattr(disp, "_STREAM_GUARD_SNAPSHOT", _Tripped())
        calls: List = []
        monkeypatch.setattr(
            "agent.auxiliary_client.call_llm",
            lambda *a, **k: calls.append(1) or _ok_response(),
        )

        async def _case():
            expl, adapter, agent = _build(
                tick_seconds=1, silence_seconds=1, min_interval_seconds=1
            )
            await _drive(expl, rounds=0)
            expl._tracker._last_content_ts = time.time() - 500
            for _ in range(3):
                await expl._tick_once()
            return adapter

        adapter = asyncio.run(_case())
        assert not calls, "stream_guard tripped 时不应调用辅助模型"
        assert not adapter.sent, "stream_guard tripped 时不应发送"


# ---------------------------------------------------------------------------
# §12-6 静默失败
# ---------------------------------------------------------------------------


class TestSilentFailure:
    def test_llm_error_no_send_no_raise(self, monkeypatch):
        calls: List = []

        def boom(*a, **k):
            calls.append(1)
            raise RuntimeError("aux model down")

        monkeypatch.setattr("agent.auxiliary_client.call_llm", boom)

        async def _case():
            expl, adapter, agent = _build(
                tick_seconds=1, silence_seconds=1, min_interval_seconds=1
            )
            await _drive(expl, rounds=0)
            expl._tracker._last_content_ts = time.time() - 500
            for _ in range(3):
                await expl._tick_once()  # 不应抛
            return adapter

        adapter = asyncio.run(_case())
        assert calls, "辅助模型应被调用过（供下轮重试）"
        assert not adapter.sent, "模型失败时不发送半成品"

    def test_llm_timeout_treated_as_failure(self, monkeypatch):
        def _slow(*a, **k):
            time.sleep(3)
            return _ok_response()

        monkeypatch.setattr("agent.auxiliary_client.call_llm", _slow)

        async def _case():
            expl, adapter, agent = _build(
                tick_seconds=1,
                silence_seconds=1,
                min_interval_seconds=1,
                explainer_timeout_ms=300,
            )
            await _drive(expl, rounds=0)
            expl._tracker._last_content_ts = time.time() - 500
            for _ in range(2):
                await expl._tick_once()
            return adapter

        adapter = asyncio.run(_case())
        assert not adapter.sent


# ---------------------------------------------------------------------------
# §12-7 生命周期
# ---------------------------------------------------------------------------


class TestLifecycle:
    def test_stop_restores_callbacks_and_cancels_task(self):
        async def _case():
            agent = FakeAgent()
            orig_progress = agent.tool_progress_callback
            orig_gen = agent.tool_gen_callback
            runner = FakeRunner(agent)
            runner.adapter = FakeAdapter()
            expl = ProgressExplainer(
                runner=runner,
                agent=agent,
                source=_source(),
                session_key="s",
                turn_ctx=SimpleNamespace(message="m", _cleanup_msg_ids=[]),
                executor_ref=lambda: None,
            )
            expl._cfg = _full_cfg()
            expl.install()
            assert agent.tool_progress_callback is not None
            assert agent.tool_gen_callback is not None
            task = expl._tick_task
            expl.stop()
            assert agent.tool_progress_callback is orig_progress
            assert agent.tool_gen_callback is orig_gen
            # cancel 后任务在事件循环收尾（Task cancelling → done），给一拍时间
            assert task is not None
            for _ in range(3):
                if task.done():
                    break
                await asyncio.sleep(0)
            assert task.done()

        asyncio.run(_case())

    def test_install_disabled_returns_none(self, monkeypatch):
        full = dict(pe_config._DEFAULTS)
        full["enabled"] = False
        monkeypatch.setattr(pe_config, "load_config", lambda: dict(full))

        expl, _, _ = _build()
        # resolve_enabled 用 patch.yaml 真数据 → enabled=False → None
        ret = install_progress_explainer(
            runner=expl._runner,
            agent=expl._agent,
            source=_source(),
            session_key="s",
            turn_ctx=SimpleNamespace(message="m"),
        )
        assert ret is None

    def test_run_not_current_no_send(self, monkeypatch):
        monkeypatch.setattr("agent.auxiliary_client.call_llm", _fake_llm_ok)

        async def _case():
            expl, adapter, agent = _build(
                tick_seconds=1, silence_seconds=1, min_interval_seconds=1
            )
            await _drive(expl, rounds=0)
            expl._tracker._last_content_ts = time.time() - 500
            # session slot 换了 agent → 不再发
            expl._runner._peek_session_state = lambda key: SimpleNamespace(
                turn=SimpleNamespace(agent=FakeAgent())
            )
            await expl._tick_once()
            return adapter

        adapter = asyncio.run(_case())
        assert not adapter.sent


# ---------------------------------------------------------------------------
# §12-8 配置三级查找
# ---------------------------------------------------------------------------


class TestConfig:
    def test_defaults_off(self):
        cfg = pe_config.load_config()
        assert cfg["enabled"] is False
        assert cfg["silence_seconds"] == 60
        assert cfg["stall_seconds"] == 120

    def test_resolve_enabled_level3(self, monkeypatch):
        # chats 级
        monkeypatch.setattr(
            pe_config,
            "_load_progress_explainer_cfg",
            lambda: {
                "enabled": True,
                "platforms": {"feishu": False},
                "chats": {"feishu": {"oc_123": True}},
            },
        )
        assert pe_config.resolve_enabled("feishu", "oc_123") is True
        assert pe_config.resolve_enabled("feishu", "oc_other") is False

        # platforms 级
        monkeypatch.setattr(
            pe_config,
            "_load_progress_explainer_cfg",
            lambda: {"enabled": True, "platforms": {"qqbot": True}},
        )
        assert pe_config.resolve_enabled("qqbot", "any") is True

        # 顶级
        monkeypatch.setattr(
            pe_config, "_load_progress_explainer_cfg", lambda: {"enabled": False}
        )
        assert pe_config.resolve_enabled("feishu", "oc_123") is False

    def test_invalid_values_fall_back(self, monkeypatch):
        monkeypatch.setattr(
            pe_config,
            "_load_progress_explainer_cfg",
            lambda: {"enabled": "yes", "silence_seconds": "not-a-number"},
        )
        cfg = pe_config.load_config()
        assert cfg["enabled"] is True
        assert cfg["silence_seconds"] == 60  # 非法回落默认
