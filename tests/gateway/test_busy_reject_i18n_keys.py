"""Mid-run slash dispatch keeps its reject copy in locales, not in a class table.

``gateway/run_busy.py`` is one of upstream's split modules; the per-command reject
table lives on the busy mixin and is resolved to localized text at call time. Two
things must hold:

* a ``busy_handler`` outside ``_BUSY_SPECIAL_HANDLERS`` (``/model``,
  ``/codex-runtime``, ``/moa``) resolves through the i18n table — it must not reach
  for upstream's ``_BUSY_REJECT_TEXT``, which only ``gateway/run.py`` ever defined;
* everything else that is rejected mid-run gets the generic catch-all, also from
  locales;
* the busy-drain notice renders through ``owner.gateway.lifecycle_copy`` so the
  ``{profile_tag}`` injection keeps working from the split module.
"""
from types import SimpleNamespace

import pytest

from agent.i18n import t
from gateway.run_busy import GatewayBusySessionMixin


class _DispatchRunner(GatewayBusySessionMixin):
    """Bare runner: only the reject tables and the catch-all are exercised."""

    def _gateway_plain_command_handlers(self):
        return {}


def _cmd(name: str, *, busy_policy: str = "reject", busy_handler=None):
    return SimpleNamespace(name=name, busy_policy=busy_policy, busy_handler=busy_handler)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "handler_key, key",
    [
        ("model", "gateway.busy_model_blocked"),
        ("codex-runtime", "gateway.busy_codex_runtime_blocked"),
        ("moa", "gateway.busy_moa_blocked"),
    ],
)
async def test_reject_handler_resolves_localized_copy(handler_key: str, key: str) -> None:
    runner = object.__new__(_DispatchRunner)
    got = await runner._dispatch_busy_slash_command(
        None, _cmd("x", busy_handler=handler_key), "session", None
    )
    assert got == t(key)


@pytest.mark.asyncio
async def test_unknown_reject_handler_uses_generic_copy() -> None:
    runner = object.__new__(_DispatchRunner)
    got = await runner._dispatch_busy_slash_command(
        None, _cmd("frobnicate", busy_handler="frobnicate"), "session", None
    )
    assert got == t("gateway.busy_cmd_blocked", cmd="frobnicate")


@pytest.mark.asyncio
async def test_no_busy_handler_uses_generic_copy() -> None:
    runner = object.__new__(_DispatchRunner)
    got = await runner._dispatch_busy_slash_command(None, _cmd("model"), "session", None)
    assert got == t("gateway.busy_cmd_blocked", cmd="model")


@pytest.mark.asyncio
async def test_special_handler_still_wins_over_reject_table() -> None:
    """`/queue` has a mid-run variant — it must not be rejected."""

    class _SpecialRunner(_DispatchRunner):
        async def _busy_queue_command(self, event, quick_key, source):
            return "queued!"

    runner = object.__new__(_SpecialRunner)
    got = await runner._dispatch_busy_slash_command(
        None, _cmd("queue", busy_policy="dispatch", busy_handler="queue"), "session", None
    )
    assert got == "queued!"


class _DrainRunner(GatewayBusySessionMixin):
    def _delivery_adapter_for(self, source):
        return self.adapter

    def _queue_during_drain_enabled(self, effective_mode: str) -> bool:
        return self.queue_during_drain

    def _queue_or_replace_pending_event(self, session_key, event) -> None:
        self.queued.append(session_key)

    def _status_action_gerund(self) -> str:
        return "restarting"

    async def _send_busy_reply(self, event, adapter, message: str) -> None:
        self.sent.append(message)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "queue_during_drain, key",
    [
        (False, "gateway.busy_drain_not_accepting"),
        (True, "gateway.busy_drain_queued"),
    ],
)
async def test_drain_notice_renders_through_owner_lifecycle_copy(
    monkeypatch, queue_during_drain: bool, key: str
) -> None:
    monkeypatch.setattr("owner.gateway.lifecycle_copy.profile_tag", lambda: "")
    runner = _DrainRunner()
    runner.adapter = object()
    runner.queued = []
    runner.sent = []
    runner.queue_during_drain = queue_during_drain

    await runner._send_busy_drain_notice(
        SimpleNamespace(source=SimpleNamespace(chat_id="c1")), "s1", "queue"
    )

    assert runner.sent == [t(key, profile_tag="", action="restarting")]
    if queue_during_drain:
        assert runner.queued == ["s1"]
    else:
        assert runner.queued == []


@pytest.mark.asyncio
async def test_drain_notice_keeps_profile_tag(monkeypatch) -> None:
    monkeypatch.setattr("owner.gateway.lifecycle_copy.profile_tag", lambda: " [coder]")
    runner = _DrainRunner()
    runner.adapter = object()
    runner.queued = []
    runner.sent = []
    runner.queue_during_drain = False

    await runner._send_busy_drain_notice(
        SimpleNamespace(source=SimpleNamespace(chat_id="c1")), "s1", "queue"
    )

    assert runner.sent == [
        t("gateway.busy_drain_not_accepting", profile_tag=" [coder]", action="restarting")
    ]
