"""C05 M1: /v1/feishu/inbound only accepted on send_only adapters."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.config import PlatformConfig
from gateway.platforms import api_server as api_mod
from gateway.platforms.api_server import APIServerAdapter


class _FakeRequest:
    headers = {"Authorization": "Bearer test-key"}


def _make_server(monkeypatch, adapter):
    cfg = PlatformConfig(enabled=True, extra={"key": "test-key", "port": 18666})
    server = APIServerAdapter(cfg)
    server._check_auth = MagicMock(return_value=None)
    server._read_json_body = AsyncMock(
        return_value=(
            {
                "schema_version": 1,
                "text": "hi",
                "open_id": "ou_a",
                "chat_id": "oc_x",
                "chat_type": "p2p",
                "target_profile": "yangtb",
            },
            None,
        )
    )
    monkeypatch.setattr(api_mod, "_owner_inbound_profile_rejection", lambda body: None)
    monkeypatch.setattr(
        api_mod,
        "_owner_import",
        lambda mod, name: (lambda: adapter)
        if name == "_get_inprocess_feishu_adapter"
        else None,
    )
    return server


def _body(resp) -> dict:
    raw = resp.body
    if isinstance(raw, (bytes, bytearray)):
        return json.loads(raw.decode())
    return json.loads(raw)


@pytest.mark.asyncio
async def test_hub_websocket_inbound_returns_403(monkeypatch):
    hub_adapter = SimpleNamespace(
        _connection_mode="websocket",
        build_forwarded_inbound_event=AsyncMock(),
        _client=object(),
    )
    server = _make_server(monkeypatch, hub_adapter)
    resp = await server._handle_feishu_inbound(_FakeRequest())
    assert resp.status == 403
    assert _body(resp)["error"]["code"] == "inbound_not_send_only"
    hub_adapter.build_forwarded_inbound_event.assert_not_called()


@pytest.mark.asyncio
async def test_send_only_passes_mode_gate(monkeypatch):
    admitted = {"called": False}

    async def _build(**kwargs):
        admitted["called"] = True
        raise RuntimeError("stop-after-mode-gate")

    send_only_adapter = SimpleNamespace(
        _connection_mode="send_only",
        build_forwarded_inbound_event=_build,
        _client=object(),
    )
    server = _make_server(monkeypatch, send_only_adapter)
    resp = await server._handle_feishu_inbound(_FakeRequest())
    assert admitted["called"] is True
    assert resp.status == 503
