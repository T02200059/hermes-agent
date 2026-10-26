"""C09 · skill_manage Feishu approval gate unit guards."""

from __future__ import annotations

import pytest

from owner.approval import skill_manage_gate as gate


@pytest.fixture(autouse=True)
def _reset_patches(monkeypatch):
    """Keep module-level patch flags from leaking across tests."""
    monkeypatch.setattr(gate, "_timeout_patched", False)
    monkeypatch.setattr(gate, "_bg_spawn_patched", False)
    monkeypatch.setattr(gate, "_orig_get_approval_timeout", None)
    monkeypatch.setattr(gate, "_GATEWAY_REF", None)
    yield


def _cfg(**overrides):
    base = {
        "enabled": True,
        "profiles": ["*"],
        "allow_skills": ["xy-*"],
        "approval_home_chat_id": "oc_home",
        "timeout_seconds": 86400,
        "disable_background_skill_review": True,
    }
    base.update(overrides)
    return base


@pytest.fixture
def skill_cfg(monkeypatch):
    cfg = _cfg()

    def _load():
        return dict(cfg)

    monkeypatch.setattr(gate, "_load_skill_approval_cfg", _load)
    return cfg


def test_disabled_gate_never_escalates(skill_cfg, monkeypatch):
    skill_cfg["enabled"] = False
    monkeypatch.setattr(gate, "_session_platform", lambda: "feishu")
    assert gate.should_escalate("skill_manage", {"action": "create", "name": "xy-info"}) is False


def test_non_feishu_platform_is_noop(skill_cfg, monkeypatch):
    monkeypatch.setattr(gate, "_session_platform", lambda: "cli")
    assert gate.should_escalate("skill_manage", {"action": "create", "name": "xy-info"}) is False


def test_read_actions_not_gated(skill_cfg, monkeypatch):
    monkeypatch.setattr(gate, "_session_platform", lambda: "feishu")
    assert gate.should_escalate("skill_manage", {"action": "view", "name": "xy-info"}) is False
    assert gate.should_escalate("skills_list", {"action": "create", "name": "xy-info"}) is False


def test_empty_allow_skills_gates_nothing(skill_cfg, monkeypatch):
    skill_cfg["allow_skills"] = []
    monkeypatch.setattr(gate, "_session_platform", lambda: "feishu")
    assert gate.should_escalate("skill_manage", {"action": "create", "name": "xy-info"}) is False


def test_allowlist_glob_and_exact(skill_cfg, monkeypatch):
    monkeypatch.setattr(gate, "_session_platform", lambda: "feishu")
    assert gate.should_escalate("skill_manage", {"action": "edit", "name": "xy-info"}) is True
    assert gate.should_escalate("skill_manage", {"action": "edit", "name": "other"}) is False
    skill_cfg["allow_skills"] = ["exact-skill"]
    assert gate.should_escalate("skill_manage", {"action": "patch", "name": "exact-skill"}) is True


def test_profile_whitelist_star_and_named(skill_cfg, monkeypatch):
    monkeypatch.setattr(gate, "_session_platform", lambda: "feishu")
    monkeypatch.setattr(gate, "_current_profile", lambda: "hermesxiyun")
    assert gate.is_gate_enabled() is True
    skill_cfg["profiles"] = ["default"]
    assert gate.is_gate_enabled() is False
    skill_cfg["profiles"] = ["hermesxiyun"]
    assert gate.is_gate_enabled() is True


def test_skill_matches_allowlist_helpers():
    assert gate.skill_matches_allowlist("xy-info", ["xy-*"]) is True
    assert gate.skill_matches_allowlist("xy-info", ["xy-info"]) is True
    assert gate.skill_matches_allowlist("nope", ["xy-*"]) is False
    assert gate.skill_matches_allowlist("", ["*"]) is False


def test_timeout_override_patches_approval_context(monkeypatch):
    import tools.approval_context as ctx

    original = ctx._get_approval_timeout
    monkeypatch.setattr(ctx, "_get_approval_timeout", lambda: 42)
    gate._timeout_patched = False
    gate._orig_get_approval_timeout = None
    gate.apply_timeout_patch()
    assert gate._timeout_patched is True
    with gate.approval_timeout_override(99):
        assert ctx._get_approval_timeout() == 99
    # Outside override, patched wrapper falls through to saved original
    assert ctx._get_approval_timeout() == 42
    # restore real original for other tests
    ctx._get_approval_timeout = original
    gate._timeout_patched = False
    gate._orig_get_approval_timeout = None


def test_background_suppress_forwards_focus_explicit(monkeypatch, skill_cfg):
    calls = {}

    class FakeAgent:
        def _spawn_background_review(self, messages_snapshot, review_memory=False,
                                     review_skills=False, focus=None, explicit=False):
            calls["kwargs"] = dict(
                review_memory=review_memory, review_skills=review_skills,
                focus=focus, explicit=explicit,
            )
            return "ok"

    import types, sys
    fake_mod = types.ModuleType("run_agent")
    fake_mod.AIAgent = FakeAgent
    monkeypatch.setitem(sys.modules, "run_agent", fake_mod)
    gate._bg_spawn_patched = False
    gate.apply_background_skill_suppress_patch()
    agent = FakeAgent()
    # gate enabled + review_skills → suppress
    out = agent._spawn_background_review([], review_memory=True, review_skills=True,
                                         focus="x", explicit=True)
    assert out == "ok"
    assert calls["kwargs"]["review_skills"] is False
    assert calls["kwargs"]["focus"] == "x"
    assert calls["kwargs"]["explicit"] is True
    # review_skills only → early return None
    out2 = agent._spawn_background_review([], review_memory=False, review_skills=True)
    assert out2 is None


def test_run_gate_returns_none_when_not_escalating(skill_cfg, monkeypatch):
    skill_cfg["enabled"] = False
    assert gate.run_gate("skill_manage", {"action": "create", "name": "xy-info"}) is None


def test_card_action_key_and_choice_map():
    from owner.feishu.skill_approval_card import (
        ACTION_KEY, _map_gateway_choice, build_skill_approval_card, build_resolved_card,
    )
    assert ACTION_KEY == "skill_approval_gate"
    assert _map_gateway_choice("approve") == "once"
    assert _map_gateway_choice("deny") == "deny"
    card = build_skill_approval_card(
        action="create", name="xy-info", args={"action": "create", "name": "xy-info", "content": "hi"},
        profile="default", origin_chat_id="oc_origin", session_key="sk", chat_id="oc_home",
    )
    assert card["header"]["template"] == "orange"
    buttons = [e for e in card["elements"] if e.get("tag") == "action"]
    assert buttons
    values = [b["value"] for b in buttons[0]["actions"]]
    assert all(v.get("hermes_action") == ACTION_KEY for v in values)
    assert all(v.get("session_key") == "sk" for v in values)
    resolved = build_resolved_card(choice="approve", action="create", skill_name="xy-info", review_prompt="p")
    assert "已批准" in resolved["header"]["title"]["content"]
