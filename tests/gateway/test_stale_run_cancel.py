"""``/stop`` during the runner-construction window must not leave an orphan turn holding the lease.

``_run_agent_track_agent`` waits for the agent object, then checks whether its run generation is
still current. When it is not (``/stop`` cleared the slot while the agent was being built) the old
code logged and returned: the agent kept running in its executor, and because it had already taken
``state.db::session_turn_leases`` at turn start, the next message saw an empty slot (session reads
idle) but found the lease held, so it queued behind a turn nobody could address. The stale branch
now stops that agent the same way ``/stop`` does.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

import gateway.run as gateway_run
from gateway.config import GatewayConfig
from gateway.turn_context import TurnContext


class _SpyAgent:
    """Minimal agent exposing the interrupt ABI the stale path reaches for."""

    def __init__(self) -> None:
        self.hard_interrupts: list[str | None] = []
        self.interrupts: list[str | None] = []

    def hard_interrupt(self, message=None, *, tool_reason=None) -> None:
        self.hard_interrupts.append(message)

    def interrupt(self, message=None, **kwargs) -> None:
        self.interrupts.append(message)


class _LegacyAgent:
    """Third-party/legacy agent: no ``hard_interrupt``, only the old ``interrupt(message)``."""

    def __init__(self) -> None:
        self.interrupts: list[str | None] = []

    def interrupt(self, message=None) -> None:
        self.interrupts.append(message)


class _NoInterruptAgent:
    """A test double with neither callable — the stale path must stay silent, not raise."""


@pytest.fixture()
def runner():
    """A GatewayRunner with only the state the track-agent path touches."""
    r = gateway_run.GatewayRunner.__new__(gateway_run.GatewayRunner)
    r._draining = False
    r._session_states = {}
    r._session_state = MagicMock(side_effect=lambda key: MagicMock())
    return r


def _run(coro):
    return asyncio.run(coro)


def _turn_ctx(agent, session_key="agent:main:telegram:dm:42", generation=7):
    ctx = TurnContext()
    ctx.session_key = session_key
    ctx.run_generation = generation
    ctx.agent_holder = [agent]
    return ctx


def test_stale_run_is_interrupted_so_it_releases_the_lease(runner):
    agent = _SpyAgent()
    runner._is_session_run_current = lambda _key, _gen: False

    _run(runner._run_agent_track_agent(_turn_ctx(agent)))

    assert agent.hard_interrupts == ["Stop requested (stale run cancelled)"]
    # A stale run must never be promoted into the session slot: that slot belongs to the newer run.
    runner._session_state.assert_not_called()


def test_current_run_is_promoted_and_never_interrupted(runner):
    agent = _SpyAgent()
    runner._is_session_run_current = lambda _key, _gen: True
    turn_state = MagicMock()
    runner._session_state = MagicMock(return_value=MagicMock(turn=turn_state))
    ctx = _turn_ctx(agent)

    _run(runner._run_agent_track_agent(ctx))

    assert agent.hard_interrupts == []
    assert turn_state.agent is agent
    assert turn_state.ctx is ctx


def test_the_same_stale_run_is_interrupted_once(runner):
    agent = _SpyAgent()
    runner._is_session_run_current = lambda _key, _gen: False
    ctx = _turn_ctx(agent)

    _run(runner._run_agent_track_agent(ctx))
    _run(runner._run_agent_track_agent(ctx))

    assert len(agent.hard_interrupts) == 1


def test_a_different_generation_of_the_same_session_is_interrupted_too(runner):
    agent = _SpyAgent()
    runner._is_session_run_current = lambda _key, _gen: False

    _run(runner._run_agent_track_agent(_turn_ctx(agent, generation=7)))
    _run(runner._run_agent_track_agent(_turn_ctx(agent, generation=8)))

    assert len(agent.hard_interrupts) == 2


def test_legacy_agent_without_hard_interrupt_still_gets_stopped(runner):
    agent = _LegacyAgent()
    runner._is_session_run_current = lambda _key, _gen: False

    _run(runner._run_agent_track_agent(_turn_ctx(agent)))

    assert agent.interrupts == ["Stop requested (stale run cancelled)"]


def test_agent_without_any_interrupt_abi_does_not_break_the_stale_path(runner):
    runner._is_session_run_current = lambda _key, _gen: False

    # No raise: cleanup must never become a new failure mode.
    _run(runner._run_agent_track_agent(_turn_ctx(_NoInterruptAgent())))
