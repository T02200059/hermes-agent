"""Tests for the owner ``request_stop`` seam on ``AIAgent``.

``agent/plugin_stream_hooks.py`` is fire-and-forget: it queues observer
callbacks and discards their return values, so a plugin that recognises a
degenerate generation mid-stream has no way to act on it. ``_request_stream_stop``
is that missing channel — it is handed to every stream observer as the
``request_stop`` payload key (see ``owner/owner-extensions/stream_guard/`` and
``owner/docs/degenerate-stream-guard-design.md`` §4.3).

The contract under test:

* the payload exposes the bound method;
* a stop is published through ``_interrupt_requested`` (the flag the streaming
  consumers poll once per chunk);
* a stale observation carried on the per-consumer queue can never abort the
  NEXT turn (turn-id fence);
* at most one stop per turn (latch), re-arming on the next turn id;
* an interrupt that is already live is never re-claimed.
"""

from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path

import pytest


def _agent():
    from run_agent import AIAgent

    return AIAgent(
        api_key="test-key",
        base_url="https://openrouter.ai/api/v1",
        provider="openrouter",
        model="test/model",
        quiet_mode=True,
        skip_context_files=True,
        skip_memory=True,
    )


@pytest.fixture()
def agent():
    a = _agent()
    a._current_turn_id = "turn-1"
    a._interrupt_requested = False
    a._interrupt_message = None
    yield a
    a.clear_interrupt()


def test_payload_exposes_request_stop_callable(agent):
    payload = agent._stream_hook_base_payload()

    assert callable(payload["request_stop"])
    assert payload["request_stop"] == agent._request_stream_stop
    # The existing payload keys must survive the addition.
    assert payload["turn_id"] == "turn-1"
    assert payload["session_id"] == agent.session_id


def test_stop_is_published_through_the_interrupt_flag(agent):
    assert agent._request_stream_stop(reason="degenerate", turn_id="turn-1") is True

    assert agent._interrupt_requested is True
    assert agent._stream_stop_reason == "degenerate"


def test_stale_turn_observation_is_refused(agent):
    """A queued delta from an earlier turn must not abort the live one."""
    agent._current_turn_id = "turn-2"

    assert agent._request_stream_stop(reason="stale", turn_id="turn-1") is False
    assert agent._interrupt_requested is False


def test_at_most_one_stop_per_turn(agent):
    assert agent._request_stream_stop(reason="first", turn_id="turn-1") is True
    # Clear the live interrupt to isolate the LATCH from the "already live" rule.
    agent._interrupt_requested = False

    assert agent._request_stream_stop(reason="second", turn_id="turn-1") is False
    assert agent._interrupt_requested is False


def test_latch_rearms_on_the_next_turn(agent):
    assert agent._request_stream_stop(reason="first", turn_id="turn-1") is True
    agent._interrupt_requested = False

    agent._current_turn_id = "turn-2"
    assert agent._request_stream_stop(reason="second", turn_id="turn-2") is True
    assert agent._interrupt_requested is True


def test_live_interrupt_is_never_reclaimed(agent):
    """A user Ctrl-C / /stop must keep its own reason and message."""
    agent._interrupt_requested = True
    agent._interrupt_message = "user pressed stop"

    assert agent._request_stream_stop(reason="degenerate", turn_id="turn-1") is False
    assert agent._interrupt_message == "user pressed stop"
    assert not hasattr(agent, "_stream_stop_latched_turn") or \
        getattr(agent, "_stream_stop_latched_turn", None) != "turn-1"


def test_missing_turn_identity_still_latches_per_interrupt_cycle(agent):
    """Defensive path: embedded / mocked agents may report no turn id."""
    agent._current_turn_id = ""

    assert agent._request_stream_stop(reason="first", turn_id="") is True
    # The live-interrupt rule caps the no-turn-id path at one stop per cycle.
    assert agent._request_stream_stop(reason="second", turn_id="") is False

    agent._interrupt_requested = False
    assert agent._request_stream_stop(reason="third", turn_id="") is True


# ---------------------------------------------------------------------------
# 端到端：真实 `_fire_stream_delta` → 插件队列 → stream_guard → request_stop
# ---------------------------------------------------------------------------
def _load_stream_guard():
    path = (
        Path(__file__).resolve().parents[2]
        / "owner" / "owner-extensions" / "stream_guard" / "__init__.py"
    )
    spec = importlib.util.spec_from_file_location("owner_stream_guard_e2e", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["owner_stream_guard_e2e"] = mod
    spec.loader.exec_module(mod)
    return mod


def _wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_real_stream_path_reaches_the_guard_and_aborts(agent, monkeypatch):
    """打通 queue 边界：真实 delta → 插件 → request_stop → 中断位。

    This is the only test that exercises the whole chain as production runs it:
    ``_fire_stream_delta`` builds the payload (including the new ``request_stop``
    key), ``agent/plugin_stream_hooks.py`` hands it to the plugin on its own
    worker thread, and ``stream_guard`` aborts the turn through the seam. Every
    other test in this file calls ``_request_stream_stop`` directly.
    """
    sgm = _load_stream_guard()
    sgm.reset_state()
    cfg = dict(sgm.DEFAULTS)
    cfg.update(action="interrupt", grace_seconds=0.0)
    monkeypatch.setattr(sgm, "config", lambda: dict(cfg))

    from agent.plugin_stream_hooks import shutdown_plugin_stream_hook_dispatcher

    shutdown_plugin_stream_hook_dispatcher()
    monkeypatch.setattr(
        "hermes_cli.plugins.iter_hook_callbacks",
        lambda name: (sgm.observe,) if name == "on_stream_delta" else (),
    )

    agent._current_turn_id = "turn-e2e"
    agent._interrupt_requested = False
    warnings: list[str] = []
    agent._emit_warning = lambda message: warnings.append(message)

    loop_text = "DONE THINKING. WRITING RESPONSE. ฅ^•ﻌ•^ฅ\n" * 200
    for start in range(0, len(loop_text), 64):
        agent._fire_stream_delta(loop_text[start:start + 64])

    assert _wait_for(lambda: agent._interrupt_requested), \
        "闸门未在真实流式路径上触发中断"
    assert _wait_for(lambda: bool(warnings)), "闸门未发出用户告警"
    assert "[stream-guard]" in warnings[0]

    # 每轮一次：继续喂 delta 不应再产生第二条告警。
    extra = len(warnings)
    for start in range(0, 2000, 64):
        agent._fire_stream_delta(loop_text[start:start + 64])
    time.sleep(0.2)
    assert len(warnings) == extra

    shutdown_plugin_stream_hook_dispatcher()
    sgm.reset_state()
