"""Tests for steer-mode vision enrichment of attached images.

When ``busy_input_mode=steer`` and an inbound event carries ``media_urls``
(e.g. a Feishu photo+text post), the busy handler must enrich the steer
text with vision descriptions before passing it to ``agent.steer()``.
Without this, ``event.media_urls`` are silently discarded.
"""
from __future__ import annotations

import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_tg = types.ModuleType("telegram")
_tg.constants = types.ModuleType("telegram.constants")
_ct = MagicMock()
_ct.SUPERGROUP = "supergroup"
_ct.GROUP = "group"
_ct.PRIVATE = "private"
_tg.constants.ChatType = _ct
sys.modules.setdefault("telegram", _tg)
sys.modules.setdefault("telegram.constants", _tg.constants)
sys.modules.setdefault("telegram.ext", types.ModuleType("telegram.ext"))

from gateway.platforms.base import (  # noqa: E402
    MessageEvent,
    MessageType,
    SessionSource,
    build_session_key,
)
from gateway.run import GatewayRunner  # noqa: E402


def _make_runner() -> GatewayRunner:
    runner = object.__new__(GatewayRunner)
    runner._running_agents = {}
    runner._running_agents_ts = {}
    runner._pending_messages = {}
    runner._busy_ack_ts = {}
    runner._draining = False
    runner.adapters = {}
    runner.config = MagicMock()
    runner.session_store = None
    runner.hooks = MagicMock()
    runner.hooks.emit = AsyncMock()
    runner.pairing_store = MagicMock()
    runner.pairing_store.is_approved.return_value = True
    runner._is_user_authorized = lambda _source: True
    runner._busy_input_mode = "steer"
    runner._busy_text_mode = "interrupt"
    runner._agent_has_active_subagents = lambda _agent: False
    runner._session_has_compression_in_flight = AsyncMock(return_value=False)
    runner._queue_or_replace_pending_event = MagicMock()
    runner._queue_depth = lambda _sk, adapter=None: 0
    runner._BUSY_QUEUE_MAX_PENDING = 5
    runner._pending_event_audio_paths = lambda _event: []
    runner._transcribe_and_echo_pending_voice = AsyncMock(return_value=("", []))
    runner._reply_anchor_for_event = lambda _event: None
    runner._thread_metadata_for_source = lambda *_a, **_kw: {}
    runner._adapter_for_source = lambda _source: _make_adapter()
    runner._send_busy_ack = AsyncMock()
    return runner


def _make_adapter() -> MagicMock:
    adapter = MagicMock()
    adapter._pending_messages = {}
    adapter._send_with_retry = AsyncMock()
    adapter.config = MagicMock()
    adapter.config.extra = {}
    adapter.platform = MagicMock(value="feishu")
    return adapter


def _make_event(text: str, media_urls=None) -> MessageEvent:
    source = SessionSource(
        platform=MagicMock(value="feishu"),
        chat_id="c1",
        chat_type="dm",
        user_id="u1",
    )
    return MessageEvent(
        text=text,
        message_type=MessageType.TEXT,
        source=source,
        message_id="m1",
        media_urls=media_urls or [],
    )


def _make_running_agent() -> MagicMock:
    agent = MagicMock()
    agent.steer.return_value = True
    return agent


@pytest.mark.asyncio
async def test_steer_enriches_with_vision_when_media_urls_present():
    """When event has media_urls, _enrich_message_with_vision is called
    and the enriched text is passed to agent.steer()."""
    runner = _make_runner()
    event = _make_event("check this screenshot", media_urls=["/tmp/img1.png"])
    sk = build_session_key(event.source)
    agent = _make_running_agent()
    runner._running_agents[sk] = agent

    with patch.object(
        runner,
        "_enrich_message_with_vision",
        new=AsyncMock(return_value="[Image description]\n\ncheck this screenshot"),
    ) as mock_enrich:
        await runner._handle_active_session_busy_message(event, sk)

    mock_enrich.assert_called_once_with("check this screenshot", ["/tmp/img1.png"])
    agent.steer.assert_called_once_with("[Image description]\n\ncheck this screenshot")


@pytest.mark.asyncio
async def test_steer_falls_back_to_plain_text_on_enrichment_failure():
    """If _enrich_message_with_vision raises, agent.steer() gets the
    original text — the steer must not be lost."""
    runner = _make_runner()
    event = _make_event("look at the bug", media_urls=["/tmp/crash.png"])
    sk = build_session_key(event.source)
    agent = _make_running_agent()
    runner._running_agents[sk] = agent

    with patch.object(
        runner,
        "_enrich_message_with_vision",
        new=AsyncMock(side_effect=RuntimeError("vision API down")),
    ):
        await runner._handle_active_session_busy_message(event, sk)

    agent.steer.assert_called_once_with("look at the bug")


@pytest.mark.asyncio
async def test_steer_without_media_urls_does_not_call_enrichment():
    """When event has no media_urls, _enrich_message_with_vision is not
    called — behaviour unchanged from before the fix."""
    runner = _make_runner()
    event = _make_event("just a text steer")
    sk = build_session_key(event.source)
    agent = _make_running_agent()
    runner._running_agents[sk] = agent

    with patch.object(
        runner,
        "_enrich_message_with_vision",
        new=AsyncMock(),
    ) as mock_enrich:
        await runner._handle_active_session_busy_message(event, sk)

    mock_enrich.assert_not_called()
    agent.steer.assert_called_once_with("just a text steer")


@pytest.mark.asyncio
async def test_steer_with_empty_text_and_media_urls_does_not_enrich():
    """Empty steer_text with media_urls should not trigger enrichment —
    the steer will fall back to queue anyway (can_steer is False)."""
    runner = _make_runner()
    event = _make_event("", media_urls=["/tmp/img.png"])
    sk = build_session_key(event.source)
    agent = _make_running_agent()
    runner._running_agents[sk] = agent

    with patch.object(
        runner,
        "_enrich_message_with_vision",
        new=AsyncMock(),
    ) as mock_enrich:
        await runner._handle_active_session_busy_message(event, sk)

    mock_enrich.assert_not_called()
    agent.steer.assert_not_called()
