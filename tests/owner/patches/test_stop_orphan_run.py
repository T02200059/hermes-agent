"""Tests for owner/patches/stop_orphan_run.py.

覆盖 2026-09-20 node010 现场（/stop 打在 sentinel 窗口期 → 跳过提升的 run 继续
持 session turn lease，挡住后续消息）的修复点：被跳过提升的 agent 必须补一次硬中断。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from owner.patches import stop_orphan_run as sor


class _FakeAgent:
    """记录中断调用的最小 agent 替身（hard_interrupt 是现代 ABI）。"""

    def __init__(self) -> None:
        self.calls: list[str | None] = []

    def hard_interrupt(self, message: str | None = None) -> bool:
        self.calls.append(message)
        return True


class _LegacyAgent:
    """只有老 ABI ``interrupt()`` 的替身。"""

    def __init__(self) -> None:
        self.calls: list[str | None] = []

    def interrupt(self, message: str | None = None) -> bool:
        self.calls.append(message)
        return True


class _MuteAgent:
    """既没有 hard_interrupt 也没有 interrupt。"""


@pytest.fixture(autouse=True)
def _clean_state():
    sor.revert_patch()
    yield
    sor.revert_patch()


def _gateway(slot_agent=None, *, raise_on_peek=False):
    def _peek(_key):
        if raise_on_peek:
            raise RuntimeError("boom")
        if slot_agent is None:
            return None
        return SimpleNamespace(turn=SimpleNamespace(agent=slot_agent))

    return SimpleNamespace(_peek_session_state=_peek)


def test_cancels_stale_run_with_hard_interrupt():
    agent = _FakeAgent()
    assert sor.cancel_stale_run(_gateway(), "agent:main:feishu:dm:oc_x", 48, agent) is True
    assert len(agent.calls) == 1
    assert "stale run cancelled" in (agent.calls[0] or "")


def test_cancels_stale_run_legacy_interrupt_abi():
    agent = _LegacyAgent()
    assert sor.cancel_stale_run(_gateway(), "k", 49, agent) is True
    assert len(agent.calls) == 1


def test_dedupe_same_session_and_generation():
    agent = _FakeAgent()
    gw = _gateway()
    assert sor.cancel_stale_run(gw, "k", 48, agent) is True
    assert sor.cancel_stale_run(gw, "k", 48, agent) is False
    assert len(agent.calls) == 1
    # 新的 generation（下一次 /stop 后的另一个孤儿）仍然会补发
    assert sor.cancel_stale_run(gw, "k", 50, agent) is True
    assert len(agent.calls) == 2


def test_skips_when_agent_is_current_slot_agent():
    """已提升进槽位 → /stop 的实时中断路径管得到它，不重复中断。"""
    agent = _FakeAgent()
    assert sor.cancel_stale_run(_gateway(slot_agent=agent), "k", 48, agent) is False
    assert agent.calls == []


def test_skips_without_agent():
    assert sor.cancel_stale_run(_gateway(), "k", 48, None) is False


def test_skips_without_session_key():
    agent = _FakeAgent()
    assert sor.cancel_stale_run(_gateway(), "", 48, agent) is False
    assert agent.calls == []


def test_agent_without_interrupt_api_is_reported_not_raised(caplog):
    with caplog.at_level("WARNING"):
        assert sor.cancel_stale_run(_gateway(), "k", 48, _MuteAgent()) is False
    assert any("no interrupt API" in rec.message for rec in caplog.records)


def test_disabled_by_patch_yaml(monkeypatch):
    monkeypatch.setattr(
        "owner.patch_config._load_patch_owner_config",
        lambda *a, **kw: {"gateway_stop_orphan": {"enabled": False}},
    )
    agent = _FakeAgent()
    assert sor.cancel_stale_run(_gateway(), "k", 48, agent) is False
    assert agent.calls == []


def test_enabled_by_default_when_patch_yaml_lacks_section(monkeypatch):
    monkeypatch.setattr("owner.patch_config._load_patch_owner_config", lambda *a, **kw: {})
    agent = _FakeAgent()
    assert sor.cancel_stale_run(_gateway(), "k", 48, agent) is True


def test_fail_open_when_gateway_probe_raises():
    agent = _FakeAgent()
    # _peek_session_state 抛错 → 保守起见仍然补发中断（否则孤儿继续持租约）
    assert sor.cancel_stale_run(_gateway(raise_on_peek=True), "k", 48, agent) is True


def test_gateway_glue_is_wired():
    """契约测试：官方文件里的 5 行 [owner] 委托必须在（防 merge 丢失）。"""
    src = Path("gateway/run.py").read_text(encoding="utf-8")
    assert "Skipping stale agent promotion" in src
    anchor = "from owner.patches.stop_orphan_run import cancel_stale_run"
    assert src.count(anchor) == 1
    # 必须紧跟在 stale 分支的日志之后、return 之前
    idx = src.index(anchor)
    tail = src[idx:]
    assert "cancel_stale_run(self, session_key, run_generation, agent_holder[0])" in tail[:200]
    assert "[owner] stop-orphan-run" in src[:idx][-600:]