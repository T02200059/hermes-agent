"""Tests for owner.approval.skill_manage_gate (Feishu skill approval gate v2)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from owner.approval import skill_manage_gate as gate


@pytest.fixture(autouse=True)
def _reset_patches(monkeypatch):
    # Isolate profile / platform / config per test
    monkeypatch.setattr(gate, "_GATEWAY_REF", None)
    yield


def _patch_cfg(monkeypatch, *, enabled=True, profiles=None, timeout=86400,
               disable_bg=True, home_chat_id="oc_home", allow_skills=None):
    cfg = {
        "enabled": enabled,
        "profiles": profiles if profiles is not None else ["hermesxiyun"],
        "approval_home_chat_id": home_chat_id,
        "timeout_seconds": timeout,
        "disable_background_skill_review": disable_bg,
    }
    if allow_skills is not None:
        cfg["allow_skills"] = allow_skills

    monkeypatch.setattr(gate, "_load_skill_approval_cfg", lambda: cfg)
    return cfg


def test_should_escalate_requires_feishu_and_whitelist(monkeypatch):
    _patch_cfg(monkeypatch, profiles=["hermesxiyun"], allow_skills=["*"])
    monkeypatch.setattr(gate, "_current_profile", lambda: "hermesxiyun")
    monkeypatch.setattr(gate, "_session_platform", lambda: "feishu")
    monkeypatch.setattr(gate, "_is_background_review", lambda: False)

    assert gate.should_escalate("skill_manage", {"action": "create", "name": "x"})
    assert not gate.should_escalate("skill_view", {"name": "x"})
    assert not gate.should_escalate("skills_list", {})
    assert not gate.should_escalate("write_file", {"path": "a.md"})
    assert not gate.should_escalate("skill_manage", {"action": "list"})


def test_should_escalate_whitelist_filters_skills(monkeypatch):
    _patch_cfg(monkeypatch, profiles=["hermesxiyun"], allow_skills=["xy-*", "hermes-agent"])
    monkeypatch.setattr(gate, "_current_profile", lambda: "hermesxiyun")
    monkeypatch.setattr(gate, "_session_platform", lambda: "feishu")
    monkeypatch.setattr(gate, "_is_background_review", lambda: False)

    # Exact name and glob match -> gated
    assert gate.should_escalate("skill_manage", {"action": "create", "name": "hermes-agent"})
    assert gate.should_escalate("skill_manage", {"action": "patch", "name": "xy-damodel"})
    # Not in whitelist -> not gated
    assert not gate.should_escalate("skill_manage", {"action": "create", "name": "other-skill"})
    # Empty allow_skills -> nothing gated
    _patch_cfg(monkeypatch, profiles=["hermesxiyun"], allow_skills=[])
    assert not gate.should_escalate("skill_manage", {"action": "create", "name": "xy-damodel"})


def test_should_escalate_skips_cli_and_other_profiles(monkeypatch):
    _patch_cfg(monkeypatch, profiles=["hermesxiyun"])
    monkeypatch.setattr(gate, "_current_profile", lambda: "hermesxiyun")
    monkeypatch.setattr(gate, "_session_platform", lambda: "cli")
    monkeypatch.setattr(gate, "_is_background_review", lambda: False)
    assert not gate.should_escalate("skill_manage", {"action": "create", "name": "x"})

    monkeypatch.setattr(gate, "_session_platform", lambda: "feishu")
    monkeypatch.setattr(gate, "_current_profile", lambda: "other")
    assert not gate.should_escalate("skill_manage", {"action": "create", "name": "x"})


def test_empty_profiles_never_activates(monkeypatch):
    _patch_cfg(monkeypatch, enabled=True, profiles=[])
    monkeypatch.setattr(gate, "_current_profile", lambda: "hermesxiyun")
    assert not gate.is_gate_enabled()
    assert not gate.should_suppress_background_skill_review()


def test_suppress_bg_skill_when_gate_active(monkeypatch):
    _patch_cfg(monkeypatch, disable_bg=True)
    monkeypatch.setattr(gate, "_current_profile", lambda: "hermesxiyun")
    assert gate.should_suppress_background_skill_review()

    _patch_cfg(monkeypatch, disable_bg=False)
    monkeypatch.setattr(gate, "_current_profile", lambda: "hermesxiyun")
    assert not gate.should_suppress_background_skill_review()


def test_run_gate_returns_none_when_not_escalating(monkeypatch):
    _patch_cfg(monkeypatch)
    monkeypatch.setattr(gate, "should_escalate", lambda *a, **k: False)
    assert gate.run_gate("skill_manage", {"action": "create"}) is None


def test_run_gate_blocks_background_review(monkeypatch):
    _patch_cfg(monkeypatch)
    monkeypatch.setattr(gate, "should_escalate", lambda *a, **k: True)
    monkeypatch.setattr(gate, "_is_background_review", lambda: True)
    stopped = []
    monkeypatch.setattr(gate, "hard_stop_turn", lambda msg: stopped.append(msg))

    result = gate.run_gate("skill_manage", {"action": "create", "name": "foo"})
    assert result is not None
    assert result["action"] == "block"
    assert "background review" in result["message"]
    assert stopped


def test_get_approval_home_chat_id(monkeypatch):
    _patch_cfg(monkeypatch, home_chat_id="oc_home_group")
    assert gate.get_approval_home_chat_id() == "oc_home_group"


def test_run_gate_approved_returns_none(monkeypatch):
    _patch_cfg(monkeypatch, timeout=120)
    monkeypatch.setattr(gate, "should_escalate", lambda *a, **k: True)
    monkeypatch.setattr(gate, "_is_background_review", lambda: False)
    monkeypatch.setattr(gate, "_prepare_activity_keepalive", lambda: None)
    monkeypatch.setattr(gate, "apply_timeout_patch", lambda: None)
    monkeypatch.setattr(gate, "get_approval_home_chat_id", lambda: "")
    monkeypatch.setattr(gate, "_send_origin_chat_notice", lambda **kw: None)
    monkeypatch.setattr(gate, "_get_origin_chat_id", lambda: "")
    monkeypatch.setattr(gate, "_current_profile", lambda: "test")

    import tools.approval as approval_mod

    monkeypatch.setattr(approval_mod, "get_current_session_key", lambda default="": "sess-1")
    monkeypatch.setattr(approval_mod, "is_approved", lambda sk, pk: False)
    monkeypatch.setattr(
        approval_mod, "_gateway_notify_cbs", {"sess-1": lambda data: None},
    )
    monkeypatch.setattr(
        approval_mod,
        "_await_gateway_decision",
        lambda *a, **k: {"resolved": True, "choice": "once", "reason": None},
    )

    result = gate.run_gate(
        "skill_manage", {"action": "create", "name": "my-skill"},
    )
    assert result is None


def test_run_gate_uses_home_notify(monkeypatch):
    _patch_cfg(monkeypatch, timeout=120, home_chat_id="oc_home123")
    monkeypatch.setattr(gate, "should_escalate", lambda *a, **k: True)
    monkeypatch.setattr(gate, "_is_background_review", lambda: False)
    monkeypatch.setattr(gate, "_prepare_activity_keepalive", lambda: None)
    monkeypatch.setattr(gate, "apply_timeout_patch", lambda: None)
    monkeypatch.setattr(gate, "_send_origin_chat_notice", lambda **kw: None)
    monkeypatch.setattr(gate, "_get_origin_chat_id", lambda: "oc_origin")
    monkeypatch.setattr(gate, "_current_profile", lambda: "test")

    home_notifies = []

    def _fake_home_notify(session_key, home_chat_id, **kw):
        def _cb(data):
            home_notifies.append((session_key, home_chat_id, data))
        return _cb

    monkeypatch.setattr(gate, "_make_home_approval_notify", _fake_home_notify)

    import tools.approval as approval_mod

    monkeypatch.setattr(approval_mod, "get_current_session_key", lambda default="": "sess-1")
    monkeypatch.setattr(approval_mod, "is_approved", lambda sk, pk: False)
    monkeypatch.setattr(
        approval_mod, "_gateway_notify_cbs", {"sess-1": lambda data: None},
    )
    seen = {}

    def _await(session_key, notify_cb, approval_data, surface="gateway"):
        seen["session_key"] = session_key
        notify_cb(approval_data)
        return {"resolved": True, "choice": "once", "reason": None}

    monkeypatch.setattr(approval_mod, "_await_gateway_decision", _await)

    result = gate.run_gate(
        "skill_manage", {"action": "create", "name": "my-skill"},
    )
    assert result is None
    assert home_notifies
    assert home_notifies[0][1] == "oc_home123"
    assert seen["session_key"] == "sess-1"


def test_run_gate_deny_hard_stops(monkeypatch):
    _patch_cfg(monkeypatch, timeout=120)
    monkeypatch.setattr(gate, "should_escalate", lambda *a, **k: True)
    monkeypatch.setattr(gate, "_is_background_review", lambda: False)
    monkeypatch.setattr(gate, "_prepare_activity_keepalive", lambda: None)
    monkeypatch.setattr(gate, "apply_timeout_patch", lambda: None)
    monkeypatch.setattr(gate, "get_approval_home_chat_id", lambda: "")
    monkeypatch.setattr(gate, "_send_origin_chat_notice", lambda **kw: None)
    monkeypatch.setattr(gate, "_get_origin_chat_id", lambda: "")
    monkeypatch.setattr(gate, "_current_profile", lambda: "test")
    stopped = []
    monkeypatch.setattr(gate, "hard_stop_turn", lambda msg: stopped.append(msg))

    import tools.approval as approval_mod

    monkeypatch.setattr(approval_mod, "get_current_session_key", lambda default="": "sess-1")
    monkeypatch.setattr(approval_mod, "is_approved", lambda sk, pk: False)
    monkeypatch.setattr(
        approval_mod, "_gateway_notify_cbs", {"sess-1": lambda data: None},
    )
    monkeypatch.setattr(
        approval_mod,
        "_await_gateway_decision",
        lambda *a, **k: {"resolved": True, "choice": "deny", "reason": None},
    )

    result = gate.run_gate(
        "skill_manage", {"action": "patch", "name": "my-skill"},
    )
    assert result is not None
    assert result["action"] == "block"
    assert "denied" in result["message"].lower() or "BLOCKED" in result["message"]
    assert stopped


def test_run_gate_timeout_hard_stops(monkeypatch):
    _patch_cfg(monkeypatch, timeout=120)
    monkeypatch.setattr(gate, "should_escalate", lambda *a, **k: True)
    monkeypatch.setattr(gate, "_is_background_review", lambda: False)
    monkeypatch.setattr(gate, "_prepare_activity_keepalive", lambda: None)
    monkeypatch.setattr(gate, "apply_timeout_patch", lambda: None)
    monkeypatch.setattr(gate, "get_approval_home_chat_id", lambda: "")
    monkeypatch.setattr(gate, "_send_origin_chat_notice", lambda **kw: None)
    monkeypatch.setattr(gate, "_get_origin_chat_id", lambda: "")
    monkeypatch.setattr(gate, "_current_profile", lambda: "test")
    stopped = []
    monkeypatch.setattr(gate, "hard_stop_turn", lambda msg: stopped.append(msg))

    import tools.approval as approval_mod

    monkeypatch.setattr(approval_mod, "get_current_session_key", lambda default="": "sess-1")
    monkeypatch.setattr(approval_mod, "is_approved", lambda sk, pk: False)
    monkeypatch.setattr(
        approval_mod, "_gateway_notify_cbs", {"sess-1": lambda data: None},
    )
    monkeypatch.setattr(
        approval_mod,
        "_await_gateway_decision",
        lambda *a, **k: {"resolved": False, "choice": None, "reason": None},
    )

    result = gate.run_gate(
        "skill_manage", {"action": "delete", "name": "old"},
    )
    assert result is not None
    assert result["action"] == "block"
    assert "timed out" in result["message"].lower()
    assert stopped


def test_timeout_override_context(monkeypatch):
    monkeypatch.setattr(gate, "_orig_get_approval_timeout", lambda: 60)
    with gate.approval_timeout_override(86400):
        assert gate._patched_get_approval_timeout() == 86400
    # Outside override falls back to original
    assert gate._patched_get_approval_timeout() == 60


def test_rule_key_and_message():
    args = {"action": "create", "name": "demo", "category": "ops"}
    assert gate.rule_key_for_args(args) == "skill_manage:create"
    msg = gate.build_approval_message(args)
    assert "create" in msg
    assert "demo" in msg


# ---------------------------------------------------------------------------
# Skill approval card tests
# ---------------------------------------------------------------------------

def test_skill_approval_card_build():
    from owner.feishu.skill_approval_card import build_skill_approval_card

    card = build_skill_approval_card(
        action="create",
        name="my-skill",
        args={"action": "create", "name": "my-skill", "category": "devops",
              "content": "# My Skill\nDoes stuff with terminal and ssh."},
        profile="hermesxiyun",
        origin_chat_id="oc_abc",
        session_key="sess-1",
        chat_id="oc_home",
    )
    assert card["header"]["template"] == "orange"
    assert "create" in card["header"]["title"]["content"]
    assert "my-skill" in card["header"]["title"]["content"]
    # Three markdown sections + hr + buttons
    elements = card["elements"]
    markdowns = [e for e in elements if e.get("tag") == "markdown"]
    assert len(markdowns) == 3  # summary, assessment, review prompt
    actions = [e for e in elements if e.get("tag") == "action"]
    assert len(actions) == 1
    buttons = actions[0]["actions"]
    assert len(buttons) == 2  # approve + deny


def test_skill_approval_card_assessment_detects_risks():
    from owner.feishu.skill_approval_card import _build_assessment_section

    assessment = _build_assessment_section(
        action="create",
        name="dangerous",
        args={"action": "create", "content": "run rm -rf / && sudo chmod 777 /etc"},
    )
    assert "rm -rf" in assessment
    assert "sudo" in assessment
    assert "⚠️" in assessment


def test_skill_approval_card_review_prompt():
    from owner.feishu.skill_approval_card import _build_review_prompt

    prompt = _build_review_prompt(
        action="edit",
        name="my-skill",
        args={"action": "edit", "name": "my-skill", "content": "Some content"},
        profile="hermesxiyun",
        origin_chat_id="oc_abc",
    )
    assert "edit" in prompt
    assert "my-skill" in prompt
    assert "审查要点" in prompt
    assert "安全性" in prompt


def test_skill_approval_card_click_resolve():
    """UI 'approve' must resolve as gateway token 'once' (not 'approve')."""
    from owner.feishu.skill_approval_card import handle_card_click, ACTION_KEY

    resolved_calls = []

    def _fake_resolve(session_key, choice, **kw):
        resolved_calls.append((session_key, choice))
        return 1

    with patch("tools.approval.resolve_gateway_approval", _fake_resolve):
        result = handle_card_click(
            adapter=MagicMock(),
            event=MagicMock(),
            action_value={
                "hermes_action": ACTION_KEY,
                "choice": "approve",
                "session_key": "sess-1",
                "chat_id": "oc_home",
                "action": "create",
                "skill_name": "my-skill",
                "review_prompt": "review text here",
            },
            loop=MagicMock(),
        )
    assert resolved_calls
    # Critical: gate only accepts once/session/always — never "approve".
    assert resolved_calls[0] == ("sess-1", "once")


def test_skill_approval_card_click_deny():
    """Test that deny choice also resolves."""
    from owner.feishu.skill_approval_card import handle_card_click, ACTION_KEY

    resolved_calls = []

    def _fake_resolve(session_key, choice, **kw):
        resolved_calls.append((session_key, choice))
        return 1

    with patch("tools.approval.resolve_gateway_approval", _fake_resolve):
        result = handle_card_click(
            adapter=MagicMock(),
            event=MagicMock(),
            action_value={
                "hermes_action": ACTION_KEY,
                "choice": "deny",
                "session_key": "sess-1",
                "chat_id": "oc_home",
                "action": "delete",
                "skill_name": "old-skill",
                "review_prompt": "",
            },
            loop=MagicMock(),
        )
    assert resolved_calls
    assert resolved_calls[0] == ("sess-1", "deny")


def test_skill_approval_card_click_zero_pending_still_updates_card():
    """count=0 (wrong process / already resolved) must not crash; card freezes."""
    from owner.feishu.skill_approval_card import handle_card_click, ACTION_KEY

    with patch("tools.approval.resolve_gateway_approval", return_value=0):
        result = handle_card_click(
            adapter=MagicMock(),
            event=MagicMock(),
            action_value={
                "hermes_action": ACTION_KEY,
                "choice": "approve",
                "session_key": "sess-missing",
                "chat_id": "oc_home",
                "action": "create",
                "skill_name": "x",
                "review_prompt": "",
            },
            loop=MagicMock(),
        )
    # Result may be empty response if lark_oapi missing; must not raise.
    assert result is None or result is not False


def test_skill_approval_card_stamps_hermes_profile():
    """Sub-profile cards stamp hermes_profile for main→sub card routing."""
    from owner.feishu.skill_approval_card import build_skill_approval_card

    card = build_skill_approval_card(
        action="create",
        name="my-skill",
        args={"action": "create", "name": "my-skill", "content": "x"},
        profile="hermesxiyun",
        session_key="sess-1",
        chat_id="oc_home",
    )
    actions = [e for e in card["elements"] if e.get("tag") == "action"]
    assert actions
    for btn in actions[0]["actions"]:
        assert btn["value"].get("hermes_profile") == "hermesxiyun"


def test_skill_approval_card_skips_profile_tag_for_default():
    from owner.feishu.skill_approval_card import build_skill_approval_card

    card = build_skill_approval_card(
        action="create",
        name="my-skill",
        args={"action": "create", "name": "my-skill", "content": "x"},
        profile="default",
        session_key="sess-1",
        chat_id="oc_home",
    )
    actions = [e for e in card["elements"] if e.get("tag") == "action"]
    for btn in actions[0]["actions"]:
        assert "hermes_profile" not in btn["value"]


def test_run_gate_accepts_approve_alias(monkeypatch):
    """Defense-in-depth: raw 'approve' from an old card still unblocks."""
    _patch_cfg(monkeypatch, timeout=120)
    monkeypatch.setattr(gate, "should_escalate", lambda *a, **k: True)
    monkeypatch.setattr(gate, "_is_background_review", lambda: False)
    monkeypatch.setattr(gate, "_prepare_activity_keepalive", lambda: None)
    monkeypatch.setattr(gate, "apply_timeout_patch", lambda: None)
    monkeypatch.setattr(gate, "get_approval_home_chat_id", lambda: "")
    monkeypatch.setattr(gate, "_send_origin_chat_notice", lambda **kw: None)
    monkeypatch.setattr(gate, "_get_origin_chat_id", lambda: "")
    monkeypatch.setattr(gate, "_current_profile", lambda: "test")
    stopped = []
    monkeypatch.setattr(gate, "hard_stop_turn", lambda msg: stopped.append(msg))

    import tools.approval as approval_mod

    monkeypatch.setattr(approval_mod, "get_current_session_key", lambda default="": "sess-1")
    monkeypatch.setattr(approval_mod, "is_approved", lambda sk, pk: False)
    monkeypatch.setattr(
        approval_mod, "_gateway_notify_cbs", {"sess-1": lambda data: None},
    )
    monkeypatch.setattr(
        approval_mod,
        "_await_gateway_decision",
        lambda *a, **k: {"resolved": True, "choice": "approve", "reason": None},
    )

    result = gate.run_gate(
        "skill_manage", {"action": "create", "name": "my-skill"},
    )
    assert result is None
    assert not stopped


def test_skill_approval_real_queue_approve_maps_once():
    """Real tools.approval queue: handle_card_click(approve) unblocks with once."""
    import threading
    import tools.approval as approval_mod
    from owner.feishu.skill_approval_card import handle_card_click, ACTION_KEY

    session_key = "sess-real-queue-approve"
    with approval_mod._lock:
        approval_mod._gateway_queues.pop(session_key, None)

    result_holder: dict = {}

    def _waiter():
        def _notify(_data):
            # Click runs on "gateway" side after notify.
            handle_card_click(
                adapter=MagicMock(),
                event=MagicMock(),
                action_value={
                    "hermes_action": ACTION_KEY,
                    "choice": "approve",
                    "session_key": session_key,
                    "chat_id": "oc_home",
                    "action": "create",
                    "skill_name": "q-skill",
                    "review_prompt": "",
                },
                loop=MagicMock(),
            )

        # Short timeout so a mapping regression fails fast.
        with patch.object(approval_mod, "_get_approval_timeout", return_value=5):
            result_holder["decision"] = approval_mod._await_gateway_decision(
                session_key,
                _notify,
                {
                    "command": "<skill_manage create q-skill>",
                    "pattern_key": "plugin_rule:skill_manage:create",
                    "pattern_keys": ["plugin_rule:skill_manage:create"],
                    "description": "test",
                    "allow_permanent": False,
                },
                surface="skill_approval",
            )

    t = threading.Thread(target=_waiter, daemon=True)
    t.start()
    t.join(timeout=10)
    assert not t.is_alive(), "approval waiter hung — choice mapping likely broken"
    decision = result_holder.get("decision") or {}
    assert decision.get("resolved") is True
    assert decision.get("choice") == "once"


def test_skill_approval_card_click_wrong_action():
    """Non-matching hermes_action returns None."""
    from owner.feishu.skill_approval_card import handle_card_click

    result = handle_card_click(
        adapter=MagicMock(),
        event=MagicMock(),
        action_value={"hermes_action": "something_else"},
        loop=MagicMock(),
    )
    assert result is None


def test_skill_approval_resolved_card():
    from owner.feishu.skill_approval_card import build_resolved_card

    card = build_resolved_card(choice="approve", action="create", skill_name="x")
    assert card["header"]["template"] == "green"
    assert "已批准" in card["header"]["title"]["content"]

    card = build_resolved_card(choice="deny", action="delete", skill_name="y")
    assert card["header"]["template"] == "red"
    assert "已拒绝" in card["header"]["title"]["content"]
