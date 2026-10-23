"""A QQ Bot WebSocket that stops talking must not look connected forever.

A half-open TCP link (NAT timeout, middlebox drop, server restart behind a VIP) accepts every
``send_json`` because the bytes go nowhere, while ``ws.receive()`` never returns. The adapter then
reports connected, heartbeats keep "succeeding", and no message ever arrives again — only a restart
recovered it. Two guards cover this, and each covers the other's blind spot: the read is bounded, and
the heartbeat loop watches for a server that stopped answering heartbeats (op 11).
"""

from __future__ import annotations

import asyncio
import time

import pytest

from gateway.config import PlatformConfig
from plugins.platforms.qqbot import adapter as qq_adapter


def _adapter(**extra):
    return qq_adapter.QQAdapter(PlatformConfig(enabled=True, extra=extra))


class _HangingWS:
    """Open, writable, and permanently silent — the half-open link shape."""

    closed = False

    async def receive(self):
        await asyncio.Event().wait()

    async def close(self) -> None:
        self.closed = True


class _RecordingWS:
    """Records heartbeats and lets ``close`` be observed."""

    closed = False

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, payload) -> None:
        self.sent.append(payload)

    async def close(self) -> None:
        self.closed = True


class _AnsweringWS(_RecordingWS):
    """A live server: every op-1 heartbeat comes back as op 11, which stamps liveness."""

    def __init__(self, adapter) -> None:
        super().__init__()
        self._adapter = adapter

    async def send_json(self, payload) -> None:
        await super().send_json(payload)
        self._adapter._dispatch_payload({"op": 11})


def test_read_is_bounded_so_a_half_open_link_surfaces_as_an_error(monkeypatch):
    monkeypatch.setattr(qq_adapter, "_READ_TIMEOUT_S", 0.05)
    adapter = _adapter(app_id="a", client_secret="b")
    adapter._ws = _HangingWS()
    adapter._running = True

    with pytest.raises(RuntimeError, match="half-open"):
        asyncio.run(asyncio.wait_for(adapter._read_events(), timeout=5))


def test_a_received_frame_stamps_liveness():
    adapter = _adapter(app_id="a", client_secret="b")
    assert adapter._last_frame_at == 0.0

    adapter._dispatch_payload({"op": 11})  # heartbeat ACK

    assert adapter._last_frame_at > 0.0


def test_heartbeat_loop_closes_a_silent_socket(monkeypatch):
    """No frame for >2.5 heartbeat periods: close, so ``_read_events`` raises and we reconnect."""
    adapter = _adapter(app_id="a", client_secret="b")
    ws = _RecordingWS()
    adapter._ws = ws
    adapter._running = True
    adapter._heartbeat_interval = 0.01
    adapter._last_frame_at = time.monotonic() - 100.0

    asyncio.run(asyncio.wait_for(adapter._heartbeat_loop(), timeout=5))

    assert ws.closed is True
    # It closed instead of sending into the void.
    assert ws.sent == []


def test_heartbeat_loop_keeps_beating_while_the_server_answers():
    adapter = _adapter(app_id="a", client_secret="b")
    ws = _AnsweringWS(adapter)
    adapter._ws = ws
    adapter._running = True
    adapter._heartbeat_interval = 0.01
    adapter._last_frame_at = time.monotonic()  # fresh: the link is alive

    async def _bounded_run():
        task = asyncio.create_task(adapter._heartbeat_loop())
        await asyncio.sleep(0.08)
        adapter._running = False
        task.cancel()
        # The loop suppresses CancelledError on the way out (a cancelled heartbeat is a shutdown,
        # not a failure), so the task completes instead of raising.
        await task

    asyncio.run(asyncio.wait_for(_bounded_run(), timeout=5))

    assert ws.sent, "a healthy link must keep sending op 1 heartbeats"
    assert all(payload.get("op") == 1 for payload in ws.sent)
    assert ws.closed is False


def test_never_having_heard_from_the_server_does_not_trip_the_ack_guard():
    """Right after connect ``_last_frame_at`` is 0; the read bound covers that case, not this one."""
    adapter = _adapter(app_id="a", client_secret="b")
    ws = _RecordingWS()
    adapter._ws = ws
    adapter._running = True
    adapter._heartbeat_interval = 0.01
    adapter._last_frame_at = 0.0

    async def _bounded_run():
        task = asyncio.create_task(adapter._heartbeat_loop())
        await asyncio.sleep(0.05)
        adapter._running = False
        task.cancel()
        await task

    asyncio.run(asyncio.wait_for(_bounded_run(), timeout=5))

    assert ws.sent, "heartbeats must start before the first inbound frame arrives"
    assert ws.closed is False


# ---------------------------------------------------------------------------
# B15: reconnect rebuilds the REST HTTP client (stale pools after sleep/wake)
# ---------------------------------------------------------------------------


class _CloseableClient:
    """Stand-in httpx.AsyncClient: records ``aclose`` and is identity-comparable."""

    def __init__(self, label: str) -> None:
        self.label = label
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


def test_reconnect_rebuilds_http_client_and_closes_the_old_one(monkeypatch):
    """``_reconnect`` must swap in a fresh REST client before token/gateway calls."""
    adapter = _adapter(app_id="a", client_secret="b")
    old = _CloseableClient("old")
    new = _CloseableClient("new")
    adapter._http_client = old
    adapter._access_token = "stale-token"
    adapter._token_expires_at = 9_999_999_999.0

    created: list = []

    def _fake_platform_http_client():
        created.append(new)
        return new

    monkeypatch.setattr(qq_adapter, "platform_http_client", _fake_platform_http_client)
    monkeypatch.setattr(qq_adapter, "RECONNECT_BACKOFF", [0])

    async def _fake_open_gateway_ws(*, log_url: bool = False) -> None:
        assert adapter._http_client is new, "token/gateway REST must use the rebuilt client"
        assert adapter._access_token is None, "cached OAuth token must be cleared"

    monkeypatch.setattr(adapter, "_open_gateway_ws", _fake_open_gateway_ws)

    assert asyncio.run(adapter._reconnect(0)) is True
    assert old.closed is True
    assert adapter._http_client is new
    assert created == [new]
    assert adapter._token_expires_at == 0.0


def test_rebuild_http_client_closes_previous_and_clears_token(monkeypatch):
    adapter = _adapter(app_id="a", client_secret="b")
    old = _CloseableClient("old")
    new = _CloseableClient("new")
    adapter._http_client = old
    adapter._access_token = "tok"
    adapter._token_expires_at = 123.0
    monkeypatch.setattr(qq_adapter, "platform_http_client", lambda: new)

    asyncio.run(adapter._rebuild_http_client())

    assert old.closed is True
    assert adapter._http_client is new
    assert adapter._access_token is None
    assert adapter._token_expires_at == 0.0
