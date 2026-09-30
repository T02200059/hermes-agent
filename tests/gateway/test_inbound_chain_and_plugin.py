"""Chained quick commands and ctx-aware plugin dispatch live in ``gateway/run_inbound.py``.

Both are owner behaviour that upstream's split of ``gateway/run.py`` dropped, and both are
invisible to a source-text check: the alias block used to expand exactly one level, and the
cold lane used to call plugin handlers positionally. The assertions below therefore drive the
real ``GatewayInboundMixin`` methods through a minimal stand-in for the runner — the mixin is
not on ``GatewayRunner``'s MRO yet, so ``GatewayRunner._handle_message`` would exercise the
monolith instead of the module under test.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import gateway.run_inbound as inbound
from gateway.config import Platform
from gateway.platforms.base import MessageEvent
from gateway.run_inbound import GatewayInboundMixin
from gateway.session import SessionSource


def _make_source() -> SessionSource:
    return SessionSource(
        platform=Platform.TELEGRAM,
        user_id="u1",
        chat_id="c1",
        user_name="tester",
        chat_type="dm",
    )


def _make_event(text: str) -> MessageEvent:
    return MessageEvent(text=text, source=_make_source(), message_id="m1")


class _InboundRunner(GatewayInboundMixin):
    """Only the collaborators ``_hm_resolve_command`` / ``_hm_dispatch_quick_and_plugin_commands``
    touch. ``_handle_message`` is stubbed to record the fragments the chain re-enters with."""

    def __init__(self, quick_commands=None, replies=None, draining=False):
        self.config = {"quick_commands": quick_commands or {}}
        self.adapters = {Platform.TELEGRAM: object()}
        self.hooks = SimpleNamespace(emit_collect=AsyncMock(return_value=[]))
        self._draining = draining
        self.dispatched: list[str] = []
        self._replies = replies or {}

    async def _handle_message(self, event):
        self.dispatched.append(event.text)
        return self._replies.get(event.text)

    def _check_slash_access(self, source, canonical_cmd):
        return None


async def _resolve(runner, event, quick_key="k"):
    return await GatewayInboundMixin._hm_resolve_command(
        runner, event, event.source, quick_key
    )


# --------------------------------------------------------------------------- chained aliases

@pytest.mark.asyncio
async def test_chained_alias_runs_every_fragment_in_order():
    """``target`` carrying ``;;`` runs each fragment and joins the replies in order."""
    runner = _InboundRunner(
        {"chain": {"type": "alias", "target": "/model x ;; /reasoning low"}},
        replies={"/model x": "model ok", "/reasoning low": "reasoning ok"},
    )
    event = _make_event("/chain")

    handled, result, _command, _canonical = await _resolve(runner, event)

    assert handled is True
    assert result == "model ok\nreasoning ok"
    assert runner.dispatched == ["/model x", "/reasoning low"]


@pytest.mark.asyncio
async def test_chained_alias_appends_the_user_args_to_the_last_fragment():
    """The typed args belong to the chain text, so they land on the tail fragment."""
    runner = _InboundRunner(
        {"chain": {"type": "alias", "target": "/model x ;; /reasoning"}},
        replies={"/model x": "M", "/reasoning low": "R"},
    )
    event = _make_event("/chain low")

    handled, result, _command, _canonical = await _resolve(runner, event)

    assert (handled, result) == (True, "M\nR")
    assert runner.dispatched == ["/model x", "/reasoning low"]


@pytest.mark.asyncio
async def test_chained_alias_leaves_the_event_text_untouched():
    """A chain dispatches copies — the event the caller still holds must not be rewritten
    (the single-fragment lane does rewrite it, and that difference is load-bearing)."""
    runner = _InboundRunner(
        {"chain": {"type": "alias", "target": "/a ;; /b"}},
        replies={"/a": "A", "/b": "B"},
    )
    event = _make_event("/chain")

    await _resolve(runner, event)

    assert event.text == "/chain"


@pytest.mark.asyncio
async def test_chained_alias_without_output_reports_via_locale(monkeypatch):
    """Every fragment silent ⇒ the localized "ran it" line, not an empty string."""
    monkeypatch.setenv("HERMES_LANGUAGE", "zh")
    runner = _InboundRunner({"chain": {"type": "alias", "target": "/a ;; /b"}})
    event = _make_event("/chain")

    handled, result, _command, _canonical = await _resolve(runner, event)

    assert handled is True
    assert result == "命令已执行。"


@pytest.mark.asyncio
async def test_chained_alias_result_is_english_identical(monkeypatch):
    monkeypatch.setenv("HERMES_LANGUAGE", "en")
    runner = _InboundRunner({"chain": {"type": "alias", "target": "/a ;; /b"}})

    _handled, result, _command, _canonical = await _resolve(runner, _make_event("/chain"))

    assert result == "Commands executed."


@pytest.mark.asyncio
async def test_single_fragment_alias_still_falls_through_to_dispatch():
    """A one-element target is not a chain: the alias is rewritten in place and the caller
    keeps resolving it (``handled`` stays False)."""
    runner = _InboundRunner({"one": {"type": "alias", "target": "/help"}})
    event = _make_event("/one")

    handled, result, command, canonical = await _resolve(runner, event)

    assert handled is False
    assert result is None
    assert command == "help" and canonical == "help"
    assert event.text == "/help"
    assert runner.dispatched == []


@pytest.mark.asyncio
async def test_alias_without_target_is_not_a_chain():
    """``target`` empty ⇒ no fragments, so the chain branch never fires."""
    runner = _InboundRunner({"empty": {"type": "alias", "target": ""}})
    event = _make_event("/empty")

    handled, _result, command, _canonical = await _resolve(runner, event)

    assert handled is False
    assert command == "empty"
    assert runner.dispatched == []


def test_chain_splitter_comes_from_the_shared_parser():
    """The gateway must not grow its own splitter — CLI/TUI/gateway share one definition,
    and the shared parser hangs the typed args off the tail fragment (``"…low x"``)."""
    no_args = GatewayInboundMixin._hm_alias_quick_command_chain(
        _make_event("/chain"), {"target": "/model x ;; /reasoning low"}
    )
    with_args = GatewayInboundMixin._hm_alias_quick_command_chain(
        _make_event("/chain x"), {"target": "/model x ;; /reasoning low"}
    )
    assert no_args == ["/model x", "/reasoning low"]
    assert with_args == ["/model x", "/reasoning low x"]


# ----------------------------------------------------------------------- cold-lane plugin cmds

async def _dispatch_plugin(monkeypatch, runner, text, entry):
    from hermes_cli import plugins as plugins_mod

    monkeypatch.setattr(plugins_mod, "get_plugin_command_entry", lambda name: entry)
    event = _make_event(text)
    return await GatewayInboundMixin._hm_dispatch_quick_and_plugin_commands(
        runner, event, event.source, text.split()[0].lstrip("/")
    ), event


@pytest.mark.asyncio
async def test_cold_lane_hands_hermes_ctx_to_a_ctx_aware_handler(monkeypatch):
    """A handler declaring ``*, hermes_ctx`` must receive the bundle, not be called positionally."""
    seen = {}

    async def _handler(args, *, hermes_ctx):
        seen.update(
            args=args,
            platform=hermes_ctx.platform,
            event=hermes_ctx.event,
            adapters=hermes_ctx.adapters,
            runner=hermes_ctx.runner,
        )
        return "ctx ok"

    runner = _InboundRunner()
    entry = {"handler": _handler, "accepts_ctx": True}
    (handled, result, command), event = await _dispatch_plugin(
        monkeypatch, runner, "/ctxcmd alpha", entry
    )

    assert (handled, result, command) == (True, "ctx ok", "ctxcmd")
    assert seen == {
        "args": "alpha",
        "platform": "telegram",
        "event": event,
        "adapters": runner.adapters,
        "runner": runner,
    }


@pytest.mark.asyncio
async def test_cold_lane_still_calls_legacy_handlers_positionally(monkeypatch):
    """Handlers without ``accepts_ctx`` keep the original ``fn(raw_args)`` call shape."""
    calls = []

    def _handler(args):
        calls.append(args)
        return "plain ok"

    entry = {"handler": _handler, "accepts_ctx": False}
    (handled, result, command), _event = await _dispatch_plugin(
        monkeypatch, _InboundRunner(), "/plaincmd beta", entry
    )

    assert (handled, result, command) == (True, "plain ok", "plaincmd")
    assert calls == ["beta"]


@pytest.mark.asyncio
async def test_cold_lane_normalizes_underscores_before_lookup(monkeypatch):
    """Telegram's underscored autocomplete form must resolve to the hyphenated plugin name."""
    looked_up = []

    def _entry_for(name):
        looked_up.append(name)
        return {"handler": lambda args: "ok", "accepts_ctx": False}

    from hermes_cli import plugins as plugins_mod

    monkeypatch.setattr(plugins_mod, "get_plugin_command_entry", _entry_for)
    runner = _InboundRunner()
    event = _make_event("/feishu_guide")
    await GatewayInboundMixin._hm_dispatch_quick_and_plugin_commands(
        runner, event, event.source, "feishu_guide"
    )

    assert looked_up == ["feishu-guide"]


@pytest.mark.asyncio
async def test_cold_lane_unknown_plugin_command_falls_through(monkeypatch):
    runner = _InboundRunner()
    (handled, result, command), _event = await _dispatch_plugin(
        monkeypatch, runner, "/nope", None
    )

    assert (handled, result, command) == (False, None, "nope")


def test_cold_lane_no_longer_uses_the_handler_only_lookup():
    """Guard: reverting to ``get_plugin_command_handler`` silently drops ``hermes_ctx`` again."""
    src = open(inbound.__file__, encoding="utf-8").read()
    assert "get_plugin_command_entry" in src
    assert "get_plugin_command_handler" not in src
