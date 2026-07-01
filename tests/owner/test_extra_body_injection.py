"""Tests for owner/extra_body_injection.py — WR-02 allowlist."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from owner import extra_body_injection as ebi
from owner.patch_config import invalidate_patch_owner_config_cache


@pytest.fixture
def patch_yaml(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    invalidate_patch_owner_config_cache()
    yield tmp_path
    invalidate_patch_owner_config_cache()


def _write_patch_yaml(home: Path, provider: str, model: str, additions: dict) -> None:
    p = home / "patch.yaml"
    p.write_text(
        json.dumps({"owner": {"model_extra_body": {provider: {model: additions}}}}),
        encoding="utf-8",
    )
    invalidate_patch_owner_config_cache()


def test_inject_passes_through_allowed_top_level_keys(patch_yaml):
    _write_patch_yaml(patch_yaml, "xfyun", "xopglm51", {"enable_thinking": True})
    body: dict = {}
    ebi.inject_model_extra_body(body, "xfyun", "xopglm51")
    assert body == {"enable_thinking": True}


def test_inject_passes_through_allowed_nested_keys(patch_yaml):
    _write_patch_yaml(
        patch_yaml,
        "damodel",
        "glm-5.1",
        {"thinking": {"type": "enabled", "clear_thinking": False}},
    )
    body: dict = {}
    ebi.inject_model_extra_body(body, "damodel", "glm-5.1")
    assert body == {"thinking": {"type": "enabled", "clear_thinking": False}}


def test_inject_drops_non_allowlisted_top_level_keys(patch_yaml, caplog):
    """WR-02: a hostile patch.yaml entry like `tools: [...]` must NOT
    reach the upstream LLM request. The allowlist drops it and logs a
    warning so the operator notices the misconfiguration."""
    _write_patch_yaml(
        patch_yaml,
        "xfyun",
        "xopglm51",
        {
            "tools": [{"type": "function", "function": {"name": "evil"}}],
            "response_format": {"type": "json_object"},
            "enable_thinking": True,
        },
    )
    body: dict = {}
    with caplog.at_level(logging.WARNING, logger="owner.extra_body_injection"):
        ebi.inject_model_extra_body(body, "xfyun", "xopglm51")
    # The two hostile keys are dropped; the allowlisted one survives.
    assert "tools" not in body
    assert "response_format" not in body
    assert body == {"enable_thinking": True}
    # And the operator gets a warning for each dropped key.
    dropped = [r for r in caplog.records if "dropping non-allowlisted" in r.getMessage()]
    assert len(dropped) >= 2


def test_inject_drops_non_allowlisted_nested_keys(patch_yaml, caplog):
    """Inside an allowlisted parent (thinking), unknown nested keys are dropped."""
    _write_patch_yaml(
        patch_yaml,
        "damodel",
        "glm-5.1",
        {
            "thinking": {
                "type": "enabled",
                "clear_thinking": False,
                "sneaky_injection": "rm -rf /",
            }
        },
    )
    body: dict = {}
    ebi.inject_model_extra_body(body, "damodel", "glm-5.1")
    assert body == {"thinking": {"type": "enabled", "clear_thinking": False}}


def test_inject_preserves_existing_extra_body_keys(patch_yaml):
    """The transport pre-populates extra_body with the provider's own
    keys (e.g. upstream defaults). Injection must not clobber them."""
    _write_patch_yaml(patch_yaml, "xfyun", "xopglm51", {"enable_thinking": True})
    body = {"some_provider_key": "preserved"}
    ebi.inject_model_extra_body(body, "xfyun", "xopglm51")
    assert body["some_provider_key"] == "preserved"
    assert body["enable_thinking"] is True


def test_inject_noop_when_provider_or_model_missing(patch_yaml):
    body: dict = {}
    ebi.inject_model_extra_body(body, "", "xopglm51")
    ebi.inject_model_extra_body(body, "xfyun", "")
    ebi.inject_model_extra_body(body, None, None)
    assert body == {}


def test_inject_noop_when_patch_yaml_empty(patch_yaml):
    body: dict = {}
    ebi.inject_model_extra_body(body, "xfyun", "no-such-model")
    assert body == {}
