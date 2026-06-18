"""Tests for sub-profile default send-target resolution."""
from __future__ import annotations

import types

from owner.feishu.default_target import resolve_default_send_target, _parse_chat_type


def _pconfig(mode="send_only"):
    return types.SimpleNamespace(extra={"connection_mode": mode})


def _session(monkeypatch, *, platform="feishu", chat_id="oc_1",
             user_id="ou_1", key="agent:main:feishu:dm:oc_1", thread_id=""):
    vals = {
        "HERMES_SESSION_PLATFORM": platform,
        "HERMES_SESSION_CHAT_ID": chat_id,
        "HERMES_SESSION_USER_ID": user_id,
        "HERMES_SESSION_KEY": key,
        "HERMES_SESSION_THREAD_ID": thread_id,
    }
    for k, v in vals.items():
        if v:
            monkeypatch.setenv(k, v)
        else:
            monkeypatch.delenv(k, raising=False)


def test_dm_session_returns_open_id_metadata(monkeypatch):
    _session(monkeypatch, key="agent:main:feishu:dm:oc_1")
    out = resolve_default_send_target("feishu", _pconfig())
    assert out == ("oc_1", {"chat_type": "dm", "open_id": "ou_1"})


def test_group_session_uses_chat_type_group(monkeypatch):
    _session(monkeypatch, key="agent:main:feishu:group:oc_9")
    chat_id, md = resolve_default_send_target("feishu", _pconfig())
    assert chat_id == "oc_1"  # chat_id comes from HERMES_SESSION_CHAT_ID
    assert md["chat_type"] == "group"


def test_thread_session_includes_thread_id(monkeypatch):
    _session(monkeypatch, key="agent:main:feishu:thread:oc_1:omt_x", thread_id="omt_x")
    _, md = resolve_default_send_target("feishu", _pconfig())
    assert md["chat_type"] == "thread"
    assert md["thread_id"] == "omt_x"


def test_unparseable_key_defaults_group_with_warning(monkeypatch, caplog):
    _session(monkeypatch, key="garbage")
    with caplog.at_level("WARNING"):
        _, md = resolve_default_send_target("feishu", _pconfig())
    assert md["chat_type"] == "group"
    assert any("chat_type" in r.message for r in caplog.records)


def test_main_gateway_websocket_returns_none(monkeypatch):
    _session(monkeypatch)
    assert resolve_default_send_target("feishu", _pconfig(mode="websocket")) is None


def test_non_feishu_session_returns_none(monkeypatch):
    _session(monkeypatch, platform="cli")
    assert resolve_default_send_target("feishu", _pconfig()) is None


def test_no_chat_id_returns_none(monkeypatch):
    _session(monkeypatch, chat_id="")
    assert resolve_default_send_target("feishu", _pconfig()) is None


def test_non_feishu_platform_returns_none(monkeypatch):
    _session(monkeypatch)
    assert resolve_default_send_target("telegram", _pconfig()) is None


def test_parse_chat_type_scans_tokens():
    assert _parse_chat_type("agent:main:feishu:p2p:oc_1") == "p2p"
    assert _parse_chat_type("a:b:group:oc_1:extra") == "group"
    assert _parse_chat_type("") == "group"
