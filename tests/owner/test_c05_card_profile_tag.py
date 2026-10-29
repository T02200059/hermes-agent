"""C05 S1: hermes_profile card tagging uses container_profile_identity."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from owner.feishu.card_sender import _maybe_tag_card_profile
from owner.feishu import profile_routing as pr


def _card_with_button() -> dict:
    return {
        "elements": [
            {
                "tag": "action",
                "actions": [
                    {"tag": "button", "value": {"hermes_action": "approve"}}
                ],
            }
        ]
    }


def test_send_only_tags_from_hermes_profile_env(monkeypatch, tmp_path):
    """Target-state HERMES_HOME=.../.hermes must still tag when HERMES_PROFILE set."""
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv(pr.CONTAINER_PROFILE_ENV, "yangtb")
    monkeypatch.setattr(pr, "_load_routing_config", dict)

    # Old path-shape helper would mis-identify this layout as default/custom;
    # tagging must still use HERMES_PROFILE via container_profile_identity.
    from hermes_cli.profiles import get_active_profile_name

    assert get_active_profile_name() in (None, "default", "custom")

    adapter = SimpleNamespace(_connection_mode="send_only")
    card = _card_with_button()
    _maybe_tag_card_profile(adapter, card)
    value = card["elements"][0]["actions"][0]["value"]
    assert value.get("hermes_profile") == "yangtb"


def test_send_only_without_identity_leaves_untagged(monkeypatch, tmp_path, caplog):
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.delenv(pr.CONTAINER_PROFILE_ENV, raising=False)
    monkeypatch.setattr(pr, "_load_routing_config", dict)

    adapter = SimpleNamespace(_connection_mode="send_only")
    card = _card_with_button()
    with caplog.at_level("WARNING"):
        _maybe_tag_card_profile(adapter, card)
    assert "hermes_profile" not in card["elements"][0]["actions"][0]["value"]
    assert any("not tagged" in r.message for r in caplog.records)


def test_non_send_only_is_noop(monkeypatch):
    monkeypatch.setenv(pr.CONTAINER_PROFILE_ENV, "yangtb")
    adapter = SimpleNamespace(_connection_mode="websocket")
    card = _card_with_button()
    _maybe_tag_card_profile(adapter, card)
    assert "hermes_profile" not in card["elements"][0]["actions"][0]["value"]
