"""Tests for card-action routing to sub-profile containers (Component 2).

Covers try_route_card_action's tag-driven routing and _forward_card_action_sync's
relay / error-card behaviour.
"""

from __future__ import annotations

import json
import types

from owner.feishu import profile_routing as pr


def _event(open_id="ou_1", chat_id="oc_1", user_id="u_1"):
    return types.SimpleNamespace(
        operator=types.SimpleNamespace(open_id=open_id, user_id=user_id),
        context=types.SimpleNamespace(open_chat_id=chat_id),
    )


def test_untagged_action_returns_none_for_local_handling():
    assert pr.try_route_card_action(_event(), {"hermes_action": "approve_once"}) is None


def test_tagged_known_profile_forwards(monkeypatch):
    monkeypatch.setattr(
        pr, "resolve_profile_route_by_name",
        lambda name: ("hermesxiyun", "http://localhost:26026", "key"),
    )
    captured = {}

    def _fake_forward(route, event, action_value):
        captured["route"] = route
        captured["value"] = action_value
        return "FORWARDED"

    monkeypatch.setattr(pr, "_forward_card_action_sync", _fake_forward)
    out = pr.try_route_card_action(
        _event(), {"hermes_action": "deny", "hermes_profile": "hermesxiyun"}
    )
    assert out == "FORWARDED"
    assert captured["route"][0] == "hermesxiyun"


def test_tagged_unknown_profile_returns_error_card(monkeypatch):
    monkeypatch.setattr(pr, "resolve_profile_route_by_name", lambda name: None)
    out = pr.try_route_card_action(
        _event(), {"hermes_action": "deny", "hermes_profile": "ghost"}
    )
    # Real P2CardActionTriggerResponse carrying an error CallBackCard.
    assert out is not None
    assert getattr(out, "card", None) is not None
    assert "暂时不可用" in json.dumps(out.card.data, ensure_ascii=False)


class _Resp:
    def __init__(self, status, body):
        self.status = status
        self._body = body.encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_forward_relays_returned_card(monkeypatch):
    resolved_card = {"config": {}, "elements": [{"tag": "markdown", "content": "✅ 已同意"}]}

    def _fake_urlopen(req, timeout=0):
        return _Resp(200, json.dumps({"card": resolved_card}))

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    out = pr._forward_card_action_sync(
        ("hermesxiyun", "http://x", "key"), _event(), {"hermes_action": "approve_once"}
    )
    assert out.card is not None
    assert out.card.data == resolved_card
    assert out.card.type == "raw"


def test_forward_no_card_returns_empty_ack(monkeypatch):
    def _fake_urlopen(req, timeout=0):
        return _Resp(200, json.dumps({"card": None}))

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    out = pr._forward_card_action_sync(
        ("hermesxiyun", "http://x", "key"), _event(), {"a": 1}
    )
    assert out is not None
    assert getattr(out, "card", None) is None


def test_forward_failure_returns_error_card(monkeypatch):
    def _boom(req, timeout=0):
        raise OSError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", _boom)
    out = pr._forward_card_action_sync(
        ("hermesxiyun", "http://x", "key"), _event(), {"a": 1}
    )
    assert out.card is not None
    assert "子网关「hermesxiyun」" in json.dumps(out.card.data, ensure_ascii=False)


def test_handle_card_action_request_retags_relayed_card(monkeypatch):
    """The relayed updated card (e.g. recall toggle) must be re-tagged so the
    next click still routes back to this sub-profile."""
    monkeypatch.setattr(
        "hermes_cli.profiles.get_active_profile_name", lambda: "hermesxiyun"
    )
    # Untagged updated card with an active toggle button, as a handler would build.
    relayed = {
        "elements": [
            {"tag": "action", "actions": [
                {"tag": "button", "value": {"collapse_recall": True, "recall_id": "r1"}}
            ]}
        ]
    }
    adapter = types.SimpleNamespace(
        _connection_mode="send_only",
        _loop=None,
        _dispatch_card_action=lambda *a, **k: types.SimpleNamespace(
            card=types.SimpleNamespace(type="raw", data=relayed)
        ),
    )
    out = pr.handle_card_action_request(
        adapter,
        {"action_value": {"collapse_recall": True, "recall_id": "r1"},
         "open_id": "ou_1", "chat_id": "oc_1"},
    )
    btn = out["elements"][0]["actions"][0]["value"]
    assert btn["hermes_profile"] == "hermesxiyun"
    assert btn["collapse_recall"] is True


def test_handle_card_action_request_none_card_returns_none(monkeypatch):
    adapter = types.SimpleNamespace(
        _connection_mode="send_only",
        _loop=None,
        _dispatch_card_action=lambda *a, **k: types.SimpleNamespace(card=None),
    )
    out = pr.handle_card_action_request(
        adapter, {"action_value": {"hermes_action": "approve_once"}}
    )
    assert out is None


def test_forward_strips_hermes_profile_from_payload(monkeypatch):
    sent = {}

    def _fake_urlopen(req, timeout=0):
        sent["body"] = json.loads(req.data.decode("utf-8"))
        return _Resp(200, json.dumps({"card": None}))

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    pr._forward_card_action_sync(
        ("p", "http://x", "key"), _event(),
        {"hermes_action": "deny", "hermes_profile": "p"},
    )
    assert "hermes_profile" not in sent["body"]["action_value"]
    assert sent["body"]["action_value"]["hermes_action"] == "deny"
