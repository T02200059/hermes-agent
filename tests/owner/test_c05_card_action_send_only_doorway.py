"""C05 M1: /v1/feishu/card-actions only accepted on send_only adapters.

Same threat model as /v1/feishu/inbound (see test_c05_inbound_send_only_doorway):
a fleet api_key holder must not be able to replay approval / skill-card clicks
on the websocket-mode Hub — only send_only sub-profile containers accept them.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.config import PlatformConfig
from gateway.platforms import api_server as api_mod
from gateway.platforms.api_server import APIServerAdapter
from owner.feishu.profile_routing import send_only_gate_rejection


class _FakeRequest:
    headers = {"Authorization": "Bearer test-key"}


def _make_server(monkeypatch, adapter, card_handler):
    cfg = PlatformConfig(enabled=True, extra={"key": "test-key", "port": 18667})
    server = APIServerAdapter(cfg)
    server._check_auth = MagicMock(return_value=None)
    server._read_json_body = AsyncMock(
        return_value=(
            {
                "open_id": "ou_a",
                "chat_id": "oc_x",
                "action_value": {"action": "approve"},
                "target_profile": "yangtb",
            },
            None,
        )
    )
    monkeypatch.setattr(api_mod, "_owner_inbound_profile_rejection", lambda body: None)
    monkeypatch.setattr(
        api_mod,
        "_owner_import",
        lambda mod, name: {
            "_get_inprocess_feishu_adapter": (lambda: adapter),
            "send_only_gate_rejection": send_only_gate_rejection,
            "handle_card_action_request": card_handler,
        }.get(name),
    )
    return server


def _body(resp) -> dict:
    raw = resp.body
    if isinstance(raw, (bytes, bytearray)):
        return json.loads(raw.decode())
    return json.loads(raw)


@pytest.mark.asyncio
async def test_hub_websocket_card_action_returns_403(monkeypatch):
    dispatch = MagicMock()
    hub_adapter = SimpleNamespace(
        _connection_mode="websocket",
        _dispatch_card_action=dispatch,
        _client=object(),
    )
    handler = MagicMock()
    server = _make_server(monkeypatch, hub_adapter, handler)
    resp = await server._handle_feishu_card_action(_FakeRequest())
    assert resp.status == 403
    assert _body(resp)["error"]["code"] == "card_action_not_send_only"
    handler.assert_not_called()
    dispatch.assert_not_called()


@pytest.mark.asyncio
async def test_send_only_card_action_passes_mode_gate(monkeypatch):
    send_only_adapter = SimpleNamespace(
        _connection_mode="send_only",
        _dispatch_card_action=MagicMock(),
        _client=object(),
    )
    handler = MagicMock(return_value={"toast": "done"})
    server = _make_server(monkeypatch, send_only_adapter, handler)
    resp = await server._handle_feishu_card_action(_FakeRequest())
    handler.assert_called_once()
    assert handler.call_args[0][0] is send_only_adapter
    assert resp.status == 200
    assert _body(resp) == {"card": {"toast": "done"}}


@pytest.mark.asyncio
async def test_card_action_gate_fails_closed_without_owner_checker(monkeypatch):
    """Checker import gone → the wrapper must still deny a websocket Hub."""
    hub_adapter = SimpleNamespace(
        _connection_mode="websocket",
        _dispatch_card_action=MagicMock(),
        _client=object(),
    )
    handler = MagicMock()
    cfg = PlatformConfig(enabled=True, extra={"key": "test-key", "port": 18667})
    server = APIServerAdapter(cfg)
    server._check_auth = MagicMock(return_value=None)
    server._read_json_body = AsyncMock(
        return_value=({"open_id": "ou_a", "target_profile": "yangtb"}, None)
    )
    monkeypatch.setattr(api_mod, "_owner_inbound_profile_rejection", lambda body: None)
    monkeypatch.setattr(
        api_mod,
        "_owner_import",
        lambda mod, name: (lambda: hub_adapter)
        if name == "_get_inprocess_feishu_adapter"
        else None,
    )
    resp = await server._handle_feishu_card_action(_FakeRequest())
    assert resp.status == 403
    assert _body(resp)["error"]["code"] == "card_action_not_send_only"
    handler.assert_not_called()
