"""Tests for hermes_profile button-tag injection in card_sender.

Covers Component 1 of the Feishu card-action routing fix: sub-profile
containers (send_only mode) tag every button value with their profile name so
the main gateway can route the click back; the main gateway leaves cards
untagged.
"""

from __future__ import annotations

import types

import pytest

from owner.feishu import card_sender


def _collect_button_values(node, out):
    if isinstance(node, dict):
        if node.get("tag") == "button":
            out.append(node.get("value"))
        for v in node.values():
            _collect_button_values(v, out)
    elif isinstance(node, list):
        for item in node:
            _collect_button_values(item, out)


def test_inject_tags_nested_buttons():
    card = {
        "elements": [
            {
                "tag": "action",
                "actions": [
                    {"tag": "button", "value": {"hermes_action": "approve_once", "approval_id": 3}},
                    {"tag": "button", "value": {"hermes_action": "deny", "approval_id": 3}},
                ],
            },
            {
                "tag": "column_set",
                "columns": [
                    {"tag": "column", "elements": [{"tag": "button", "value": {"clarify_id": "x"}}]}
                ],
            },
        ]
    }
    card_sender._inject_profile_tag(card, "hermesxiyun")
    values = []
    _collect_button_values(card, values)
    assert len(values) == 3
    assert all(v.get("hermes_profile") == "hermesxiyun" for v in values)


def test_inject_is_idempotent_and_preserves_existing_tag():
    btn = {"tag": "button", "value": {"hermes_profile": "other", "x": 1}}
    card_sender._inject_profile_tag(btn, "hermesxiyun")
    assert btn["value"]["hermes_profile"] == "other"


def test_inject_ignores_non_dict_button_value():
    btn = {"tag": "button", "value": "not-a-dict"}
    # Must not raise.
    card_sender._inject_profile_tag(btn, "hermesxiyun")
    assert btn["value"] == "not-a-dict"


def test_main_gateway_leaves_card_untagged():
    adapter = types.SimpleNamespace(_connection_mode="websocket")
    card = {"tag": "button", "value": {"a": 1}}
    card_sender._maybe_tag_card_profile(adapter, card)
    assert "hermes_profile" not in card["value"]


@pytest.mark.parametrize("profile", ["default", "custom"])
def test_send_only_skips_unroutable_profile_names(monkeypatch, profile):
    monkeypatch.setattr(
        "hermes_cli.profiles.get_active_profile_name", lambda: profile
    )
    adapter = types.SimpleNamespace(_connection_mode="send_only")
    card = {"tag": "button", "value": {"a": 1}}
    card_sender._maybe_tag_card_profile(adapter, card)
    assert "hermes_profile" not in card["value"]


def test_send_only_tags_real_profile_name(monkeypatch):
    monkeypatch.setattr(
        "hermes_cli.profiles.get_active_profile_name", lambda: "hermesxiyun"
    )
    adapter = types.SimpleNamespace(_connection_mode="send_only")
    card = {"tag": "button", "value": {"a": 1}}
    card_sender._maybe_tag_card_profile(adapter, card)
    assert card["value"]["hermes_profile"] == "hermesxiyun"
