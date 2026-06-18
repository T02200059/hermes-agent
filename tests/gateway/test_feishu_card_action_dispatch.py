"""Tests for the shared _dispatch_card_action (Component 3).

Verifies the dispatcher reused by the WebSocket SDK callback and the
sub-profile's /v1/feishu/card-actions HTTP handler:
  * allow_profile_routing=False skips the profile-routing step and dispatches
    straight to the per-type handler (the HTTP / sub-profile path);
  * allow_profile_routing=True consults try_route_card_action first and
    short-circuits when it returns a response (the main-gateway path);
  * a reconstructed SimpleNamespace event (as the HTTP handler builds) reaches
    the right handler and its card payload is extractable.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

_repo = str(Path(__file__).resolve().parents[2])
if _repo not in sys.path:
    sys.path.insert(0, _repo)


def _ensure_feishu_mocks():
    if importlib.util.find_spec("lark_oapi") is None and "lark_oapi" not in sys.modules:
        mod = MagicMock()
        for name in ("lark_oapi", "lark_oapi.api.im.v1", "lark_oapi.event"):
            sys.modules.setdefault(name, mod)
    if importlib.util.find_spec("aiohttp") is None and "aiohttp" not in sys.modules:
        aio = MagicMock()
        sys.modules.setdefault("aiohttp", aio)
        sys.modules.setdefault("aiohttp.web", aio.web)


_ensure_feishu_mocks()

from gateway.config import PlatformConfig  # noqa: E402
import gateway.platforms.feishu as feishu_module  # noqa: E402
from gateway.platforms.feishu import FeishuAdapter  # noqa: E402


def _make_adapter() -> FeishuAdapter:
    adapter = FeishuAdapter(PlatformConfig(enabled=True))
    adapter._client = MagicMock()
    return adapter


def _event(action_value, chat_id="oc_1", open_id="ou_1", user_id="u_1"):
    return SimpleNamespace(
        action=SimpleNamespace(value=action_value, tag="button"),
        operator=SimpleNamespace(open_id=open_id, user_id=user_id),
        context=SimpleNamespace(open_chat_id=chat_id),
        token="",
    )


def test_http_path_skips_routing_and_reaches_approval(monkeypatch):
    adapter = _make_adapter()
    seen = {}
    monkeypatch.setattr(
        adapter, "_handle_approval_card_action",
        lambda **kw: seen.update(kw) or "APPROVAL_RESPONSE",
    )
    # If profile routing were consulted it would import try_route_card_action;
    # make that import explode so the test fails loudly if routing runs.
    def _boom_import(mod, name):
        if name == "try_route_card_action":
            raise AssertionError("profile routing must be skipped on the HTTP path")
        return None
    monkeypatch.setattr(feishu_module, "_owner_import", _boom_import)

    out = adapter._dispatch_card_action(
        _event({"hermes_action": "approve_once", "approval_id": 7}),
        {"hermes_action": "approve_once", "approval_id": 7},
        loop=None,
        data=None,
        allow_profile_routing=False,
    )
    assert out == "APPROVAL_RESPONSE"
    assert seen["action_value"]["approval_id"] == 7


def test_main_path_short_circuits_on_route(monkeypatch):
    adapter = _make_adapter()
    sentinel = object()
    monkeypatch.setattr(
        feishu_module, "_owner_import",
        lambda mod, name: (lambda event, action_value: sentinel)
        if name == "try_route_card_action" else None,
    )
    # Approval handler must NOT be reached when routing handles it.
    monkeypatch.setattr(
        adapter, "_handle_approval_card_action",
        lambda **kw: pytest.fail("approval handler should not run when routed"),
    )
    out = adapter._dispatch_card_action(
        _event({"hermes_action": "deny", "approval_id": 7, "hermes_profile": "x"}),
        {"hermes_action": "deny", "approval_id": 7, "hermes_profile": "x"},
        loop=None,
        data=None,
        allow_profile_routing=True,
    )
    assert out is sentinel


def test_reconstructed_event_card_payload_extractable(monkeypatch):
    """Mirror the HTTP handler: dispatch, then pull response.card.data."""
    adapter = _make_adapter()
    resolved_card = {"elements": [{"tag": "markdown", "content": "✅ done"}]}

    def _fake_handler(**kw):
        return SimpleNamespace(card=SimpleNamespace(type="raw", data=resolved_card))

    monkeypatch.setattr(adapter, "_handle_clarify_card_action", _fake_handler)
    response = adapter._dispatch_card_action(
        _event({"clarify_id": "c1", "choice": "a"}),
        {"clarify_id": "c1", "choice": "a"},
        loop=None,
        data=None,
        allow_profile_routing=False,
    )
    card_obj = getattr(response, "card", None)
    card_data = getattr(card_obj, "data", None) if card_obj is not None else None
    assert card_data == resolved_card
