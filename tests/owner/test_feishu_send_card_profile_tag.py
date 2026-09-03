"""Regression tests: FeishuAdapter.send_card stamps hermes_profile on buttons.

Root cause this locks in (2026-09): ``send_model_picker_card`` (the /providers
picker) and clarify cards send through ``FeishuAdapter.send_card`` → the lark
SDK path. The ``hermes_profile`` button tag — the ONLY key
``try_route_card_action`` uses to route a click back to the sub-profile
container — was stamped exclusively in ``send_card_via_rest`` (REST path).
A send_only container's picker card therefore reached the user untagged; the
click landed on the main gateway (the only WebSocket), whose adapter had no
``_model_picker_state`` entry → "会话已过期，请重新执行 /providers".

The fix moves tagging into ``send_card`` itself (before serialization),
gated on ``_connection_mode == "send_only"`` — a no-op on the main gateway.

Contract asserted here (behavior, not source shape):
  1. send_only container → every dict button value gains hermes_profile
  2. websocket main gateway → buttons stay untagged (no-op)
  3. card_sender module absent → send still succeeds, untagged (fail-open)
  4. existing tags are never overwritten (idempotent setdefault semantics)
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from plugins.platforms.feishu.adapter import FeishuAdapter


def _button_card() -> dict:
    """Minimal v2-schema card with a nested button (action container)."""
    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": "test", "tag": "plain_text"},
            "template": "blue",
        },
        "body": {
            "elements": [
                {"tag": "markdown", "content": "pick one:"},
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "A"},
                            "type": "default",
                            "value": {"hermes_model_picker": "provider", "picker_id": "p1"},
                        }
                    ],
                },
            ]
        },
    }


def _iter_button_values(card: dict):
    """Walk every dict button value in a card (any nesting depth)."""
    stack = [card]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if node.get("tag") == "button":
                value = node.get("value")
                if isinstance(value, dict):
                    yield value
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)


def _make_skeleton_adapter(connection_mode: str):
    """Bare adapter with just the attributes send_card touches.

    ``_send_raw_message`` / ``_finalize_send_result`` are replaced so no lark
    SDK client is needed; the card payload is captured before it would hit
    the API (tagging happens before serialization — that is the contract).

    Returns ``(adapter, captured)`` where ``captured["payload"]`` is the JSON
    string the adapter serialized.
    """
    adapter = object.__new__(FeishuAdapter)
    adapter._connection_mode = connection_mode
    captured: dict[str, str] = {}

    async def _fake_send_raw(*, chat_id, msg_type, payload, reply_to, metadata):
        captured["payload"] = payload
        return SimpleNamespace(
            success=lambda: True,
            data=SimpleNamespace(message_id="om_test"),
        )

    def _fake_finalize(response, default_message, *, chat_id=None):
        from gateway.platforms.base import SendResult

        return SendResult(success=True, message_id="om_test", raw_response=response)

    adapter._send_raw_message = _fake_send_raw  # type: ignore[method-assign]
    adapter._finalize_send_result = _fake_finalize  # type: ignore[method-assign]
    return adapter, captured


def _sent_button_values(captured: dict) -> list:
    """Parse the serialized payload and return its button values."""
    payload = json.loads(captured["payload"])
    return list(_iter_button_values(payload))


@pytest.mark.asyncio
async def test_send_card_tags_buttons_in_send_only_container(monkeypatch):
    """A send_only (sub-profile) container must stamp hermes_profile on every
    button so the main gateway can route the click back to this container."""
    adapter, captured = _make_skeleton_adapter("send_only")
    monkeypatch.setattr(
        "hermes_cli.profiles.get_active_profile_name",
        lambda: "hermesxiyun",
        raising=False,
    )

    result = await adapter.send_card(chat_id="oc_chat", card=_button_card())

    assert result.success is True
    values = _sent_button_values(captured)
    assert values, "card must contain at least one button"
    for value in values:
        assert value.get("hermes_profile") == "hermesxiyun"


@pytest.mark.asyncio
async def test_send_card_leaves_websocket_gateway_untagged(monkeypatch):
    """The main gateway (websocket mode) holds its own correlation state —
    its cards must stay untagged or clicks would be forwarded nowhere."""
    adapter, captured = _make_skeleton_adapter("websocket")
    monkeypatch.setattr(
        "hermes_cli.profiles.get_active_profile_name",
        lambda: "hermesxiyun",
        raising=False,
    )

    result = await adapter.send_card(chat_id="oc_chat", card=_button_card())

    assert result.success is True
    for value in _sent_button_values(captured):
        assert "hermes_profile" not in value


@pytest.mark.asyncio
async def test_send_card_fail_open_when_card_sender_absent():
    """owner/feishu/card_sender missing → card still sends (untagged).
    Removability contract: deleting owner/ never crashes the adapter."""
    adapter, captured = _make_skeleton_adapter("send_only")

    with patch(
        "plugins.platforms.feishu.adapter._owner_import", return_value=None
    ):
        result = await adapter.send_card(chat_id="oc_chat", card=_button_card())

    assert result.success is True
    for value in _sent_button_values(captured):
        assert "hermes_profile" not in value


@pytest.mark.asyncio
async def test_send_card_never_overwrites_existing_profile_tag(monkeypatch):
    """A button already carrying hermes_profile keeps it (setdefault
    semantics — the HTTP re-tag path relies on this idempotency)."""
    adapter, captured = _make_skeleton_adapter("send_only")
    card = _button_card()
    for value in _iter_button_values(card):
        value["hermes_profile"] = "other-profile"

    monkeypatch.setattr(
        "hermes_cli.profiles.get_active_profile_name",
        lambda: "hermesxiyun",
        raising=False,
    )

    result = await adapter.send_card(chat_id="oc_chat", card=card)

    assert result.success is True
    for value in _sent_button_values(captured):
        assert value["hermes_profile"] == "other-profile"


@pytest.mark.asyncio
async def test_model_picker_card_emits_tagged_card_from_container(monkeypatch):
    """The original bug's exact entry point: send_model_picker_card (state
    write + send_card) must emit a tagged card from a send_only container,
    so the container-side state it just wrote is reachable by the click
    (try_route_card_action → /v1/feishu/card-actions → local state hit)."""
    adapter, captured = _make_skeleton_adapter("send_only")
    adapter._model_picker_state = {}
    monkeypatch.setattr(
        "hermes_cli.profiles.get_active_profile_name",
        lambda: "hermesxiyun",
        raising=False,
    )

    source = SimpleNamespace(chat_id="oc_chat", chat_type="dm", user_id="ou_open")
    await FeishuAdapter.send_model_picker_card(
        adapter,
        chat_id="oc_chat",
        providers=[{"slug": "openrouter", "name": "OpenRouter", "models": ["m1"]}],
        source=source,
    )

    values = _sent_button_values(captured)
    assert values, "picker card must contain buttons"
    for value in values:
        assert value.get("hermes_profile") == "hermesxiyun"
    # state was registered on the SAME adapter that emitted the tagged card —
    # the click will route back here and find it (no "会话已过期").
    assert adapter._model_picker_state, "picker state must be registered"
