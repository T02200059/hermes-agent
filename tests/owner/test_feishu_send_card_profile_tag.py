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

import itertools
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

    The REAL ``_send_raw_message`` runs (that is where the hermes_profile
    tagging choke point lives since 2026-09-15); only the lark SDK layer
    underneath is faked: the create-message body builder captures the
    serialized payload and ``_run_blocking`` returns a canned success
    response. This way every card path (send_card, send_exec_approval,
    send_update_prompt, direct _send_raw_message) exercises the production
    wiring, not test scaffolding.

    Returns ``(adapter, captured)`` where ``captured["payload"]`` is the JSON
    string the adapter serialized.
    """
    adapter = object.__new__(FeishuAdapter)
    adapter._connection_mode = connection_mode

    def _fake_message_create(request):
        return SimpleNamespace(
            success=lambda: True,
            data=SimpleNamespace(message_id="om_test"),
        )

    # _send_raw_message resolves self._client.im.v1.message.create BEFORE
    # calling _run_blocking, so the fake client needs the full attr chain.
    adapter._client = SimpleNamespace(
        im=SimpleNamespace(
            v1=SimpleNamespace(
                message=SimpleNamespace(
                    create=_fake_message_create,
                    reply=_fake_message_create,
                )
            )
        )
    )
    captured: dict[str, str] = {}

    def _fake_build_body(*, receive_id, msg_type, content, uuid_value):
        captured["payload"] = content
        return SimpleNamespace(
            receive_id=receive_id, msg_type=msg_type, content=content,
            uuid=uuid_value,
        )

    def _fake_build_request(receive_id_type, request_body):
        return SimpleNamespace(
            receive_id_type=receive_id_type, request_body=request_body
        )

    async def _fake_run_blocking(func, *args):
        return SimpleNamespace(
            success=lambda: True,
            data=SimpleNamespace(message_id="om_test"),
        )

    def _fake_finalize(response, default_message, *, chat_id=None):
        from gateway.platforms.base import SendResult

        return SendResult(success=True, message_id="om_test", raw_response=response)

    adapter._build_create_message_body = _fake_build_body  # type: ignore[method-assign]
    adapter._build_create_message_request = _fake_build_request  # type: ignore[method-assign]
    adapter._run_blocking = _fake_run_blocking  # type: ignore[method-assign]
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


# ---------------------------------------------------------------------------
# Root-fix regression tests (2026-09-15): _send_raw_message choke point.
#
# send_exec_approval and send_update_prompt serialize their cards straight
# into _send_raw_message / _feishu_send_with_retry, bypassing send_card. The
# hermes_profile tag used to be stamped only in send_card (and REST card
# sends), so those two card types reached users untagged from a send_only
# container. The click landed on the main gateway (only WebSocket), which
# had no approval state →「已处理」(exec approval) or a silent no-op (update
# prompt). The fix moved tagging into _send_raw_message itself so every
# interactive payload is tagged regardless of the sending path.
# ---------------------------------------------------------------------------


def _approval_button_card() -> dict:
    """Minimal approval-shaped card (the buttons send_exec_approval builds)."""
    return {
        "config": {"wide_screen_mode": True},
        "header": {"title": {"content": "Approval", "tag": "plain_text"}},
        "elements": [
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "Allow once"},
                        "type": "primary",
                        "value": {"hermes_action": "approve_once", "approval_id": 1},
                    }
                ],
            }
        ],
    }


@pytest.mark.asyncio
async def test_send_raw_message_tags_interactive_payload_in_send_only(monkeypatch):
    """The choke point: any interactive payload funneled through
    _send_raw_message must come out tagged from a send_only container, even
    when the caller serialized an untagged card (the exec-approval bypass
    shape). This is the root fix for the「已处理」card bug."""
    adapter, captured = _make_skeleton_adapter("send_only")
    monkeypatch.setattr(
        "hermes_cli.profiles.get_active_profile_name",
        lambda: "hermesxiyun",
        raising=False,
    )

    untagged = json.dumps(_approval_button_card(), ensure_ascii=False)
    await adapter._send_raw_message(
        chat_id="oc_chat",
        msg_type="interactive",
        payload=untagged,
        reply_to=None,
        metadata=None,
    )

    values = _sent_button_values(captured)
    assert values, "payload must contain buttons"
    for value in values:
        assert value.get("hermes_profile") == "hermesxiyun"


@pytest.mark.asyncio
async def test_send_raw_message_leaves_non_interactive_untouched(monkeypatch):
    """Text/post payloads must pass through byte-identical (no JSON
    parse/re-serialize churn on non-card traffic)."""
    adapter, captured = _make_skeleton_adapter("send_only")
    monkeypatch.setattr(
        "hermes_cli.profiles.get_active_profile_name",
        lambda: "hermesxiyun",
        raising=False,
    )

    text_payload = json.dumps({"text": "hello"}, ensure_ascii=False)
    await adapter._send_raw_message(
        chat_id="oc_chat",
        msg_type="text",
        payload=text_payload,
        reply_to=None,
        metadata=None,
    )

    assert captured["payload"] == text_payload


@pytest.mark.asyncio
async def test_send_raw_message_tags_websocket_gateway_not(monkeypatch):
    """Main gateway (websocket) interactive payloads stay untagged — its own
    card state lives in-process and must be resolved locally."""
    adapter, captured = _make_skeleton_adapter("websocket")
    monkeypatch.setattr(
        "hermes_cli.profiles.get_active_profile_name",
        lambda: "hermesxiyun",
        raising=False,
    )

    payload = json.dumps(_approval_button_card(), ensure_ascii=False)
    await adapter._send_raw_message(
        chat_id="oc_chat",
        msg_type="interactive",
        payload=payload,
        reply_to=None,
        metadata=None,
    )

    for value in _sent_button_values(captured):
        assert "hermes_profile" not in value


@pytest.mark.asyncio
async def test_send_raw_message_fail_open_when_card_sender_absent():
    """owner/feishu/card_sender missing → payload passes through untagged.
    Removability contract: deleting owner/ never breaks the send path."""
    adapter, captured = _make_skeleton_adapter("send_only")

    with patch(
        "plugins.platforms.feishu.adapter._owner_import", return_value=None
    ):
        payload = json.dumps(_approval_button_card(), ensure_ascii=False)
        await adapter._send_raw_message(
            chat_id="oc_chat",
            msg_type="interactive",
            payload=payload,
            reply_to=None,
            metadata=None,
        )

    for value in _sent_button_values(captured):
        assert "hermes_profile" not in value


@pytest.mark.asyncio
async def test_send_raw_message_preserves_existing_tag(monkeypatch):
    """A button already carrying hermes_profile keeps it (idempotent
    setdefault — the HTTP re-tag path in handle_card_action_request relies
    on this)."""
    adapter, captured = _make_skeleton_adapter("send_only")
    monkeypatch.setattr(
        "hermes_cli.profiles.get_active_profile_name",
        lambda: "hermesxiyun",
        raising=False,
    )

    card = _approval_button_card()
    for value in _iter_button_values(card):
        value["hermes_profile"] = "other-profile"
    await adapter._send_raw_message(
        chat_id="oc_chat",
        msg_type="interactive",
        payload=json.dumps(card, ensure_ascii=False),
        reply_to=None,
        metadata=None,
    )

    for value in _sent_button_values(captured):
        assert value["hermes_profile"] == "other-profile"


@pytest.mark.asyncio
async def test_send_raw_message_tagging_is_malformed_json_fail_open(monkeypatch):
    """An interactive payload that is not valid JSON must pass through
    unchanged rather than raise (fail-open contract)."""
    adapter, captured = _make_skeleton_adapter("send_only")
    monkeypatch.setattr(
        "hermes_cli.profiles.get_active_profile_name",
        lambda: "hermesxiyun",
        raising=False,
    )

    broken = "{not json at all"
    await adapter._send_raw_message(
        chat_id="oc_chat",
        msg_type="interactive",
        payload=broken,
        reply_to=None,
        metadata=None,
    )

    assert captured["payload"] == broken


@pytest.mark.asyncio
async def test_send_exec_approval_bypass_path_is_tagged(monkeypatch):
    """The exact production bug entry point (「已处理」): send_exec_approval
    builds an approval card, json.dumps it and calls _send_raw_message
    directly. From a send_only container the serialized payload must come
    out tagged, so the click routes back to the container that owns
    _approval_ctx (main gateway has no approval_id state → already_resolved
    misfire)."""
    adapter, captured = _make_skeleton_adapter("send_only")
    # Attributes send_exec_approval touches (client chain is already faked
    # by the skeleton — the connected guard passes).
    from owner.feishu.approval import FeishuApprovalContext

    adapter._approval_ctx = FeishuApprovalContext()
    adapter._admins = []
    adapter._allowed_group_users = []
    monkeypatch.setattr(
        FeishuAdapter,
        "_pre_warm_sender_name",
        lambda *a, **k: None,
        raising=True,
    )
    monkeypatch.setattr(
        "hermes_cli.profiles.get_active_profile_name",
        lambda: "hermesxiyun",
        raising=False,
    )

    result = await adapter.send_exec_approval(
        chat_id="oc_chat",
        command="rm -rf /tmp/x",
        session_key="sess-1",
        description="dangerous command",
    )

    assert result.success is True
    values = _sent_button_values(captured)
    assert values, "approval card must contain buttons"
    for value in values:
        assert value.get("hermes_profile") == "hermesxiyun"
    # The correlation state was registered on the same container that emitted
    # the tagged card — the click will route back here and resolve it.
    assert 1 in adapter._approval_state


@pytest.mark.asyncio
async def test_send_update_prompt_bypass_path_is_tagged(monkeypatch):
    """Same bypass shape for send_update_prompt (Yes/No card): from a
    send_only container the payload must be tagged, or the click is a
    silent no-op on the main gateway (no _update_prompt_state there)."""
    adapter, captured = _make_skeleton_adapter("send_only")
    adapter._update_prompt_state = {}
    adapter._update_prompt_counter = itertools.count(1)
    monkeypatch.setattr(
        "hermes_cli.profiles.get_active_profile_name",
        lambda: "hermesxiyun",
        raising=False,
    )

    result = await adapter.send_update_prompt(
        chat_id="oc_chat",
        prompt="Apply config update?",
        default="y",
        session_key="sess-1",
    )

    assert result.success is True
    values = _sent_button_values(captured)
    assert values, "update prompt card must contain buttons"
    for value in values:
        assert value.get("hermes_profile") == "hermesxiyun"
    assert adapter._update_prompt_state, "prompt state must be registered"
