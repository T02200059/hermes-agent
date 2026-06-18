"""send_message sub-profile no-target auto-fill + extra_metadata plumbing."""
from __future__ import annotations

import types

import pytest


@pytest.mark.asyncio
async def test_send_feishu_merges_extra_metadata(monkeypatch):
    """_send_feishu must merge extra_metadata (chat_type/open_id) into the
    metadata passed to adapter.send — this is what makes DMs deliver via open_id."""
    import tools.send_message_tool as smt

    captured = {}

    class FakeAdapter:
        _domain_name = "feishu"

        def __init__(self, pconfig):
            pass

        def _build_lark_client(self, domain):
            return object()

        async def send(self, chat_id, message, metadata=None):
            captured["chat_id"] = chat_id
            captured["metadata"] = metadata
            return types.SimpleNamespace(success=True, message_id="m1")

    import gateway.platforms.feishu as feishu_mod
    monkeypatch.setattr(feishu_mod, "FeishuAdapter", FakeAdapter, raising=False)
    monkeypatch.setattr(feishu_mod, "FEISHU_AVAILABLE", True, raising=False)

    out = await smt._send_feishu(
        types.SimpleNamespace(extra={}),
        "oc_1",
        "hi",
        extra_metadata={"chat_type": "dm", "open_id": "ou_1"},
    )
    assert out["success"] is True
    assert captured["metadata"]["chat_type"] == "dm"
    assert captured["metadata"]["open_id"] == "ou_1"


def test_resolver_wired_into_no_target_branch(monkeypatch):
    """The no-target branch must consult resolve_default_send_target before the
    home-channel fallback, and pass its metadata through as extra_metadata."""
    import tools.send_message_tool as smt
    from gateway.config import Platform

    monkeypatch.setattr(
        "owner.feishu.default_target.resolve_default_send_target",
        lambda platform_name, pconfig: ("oc_session", {"chat_type": "dm", "open_id": "ou_x"}),
    )

    seen = {}

    def _fake_send_to_platform(platform, pconfig, chat_id, message, **kw):
        seen["chat_id"] = chat_id
        seen["extra_metadata"] = kw.get("extra_metadata")

        async def _coro():
            return {"success": True, "platform": "feishu", "chat_id": chat_id}

        return _coro()

    monkeypatch.setattr(smt, "_send_to_platform", _fake_send_to_platform)

    pconfig = types.SimpleNamespace(enabled=True, extra={"connection_mode": "send_only"}, token="")

    class _GwConfig:
        platforms = {Platform.FEISHU: pconfig}

        def get_home_channel(self, platform):
            return None

    # load_gateway_config is imported function-locally inside _handle_send via
    # `from gateway.config import load_gateway_config`, so patch it at the source module.
    monkeypatch.setattr("gateway.config.load_gateway_config", lambda: _GwConfig())

    result = smt._handle_send({"target": "feishu", "message": "hi"})

    assert seen["chat_id"] == "oc_session"
    assert seen["extra_metadata"] == {"chat_type": "dm", "open_id": "ou_x"}
