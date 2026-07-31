"""Tests for owner.approval.skill_manage_gate (Feishu skill_manage write gate)."""

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


def _patch_cfg(monkeypatch, *, enabled=True, profiles=None, timeout=86400, disable_bg=True):
    cfg = {
        "enabled": enabled,
        "profiles": profiles if profiles is not None else ["hermesxiyun"],
        "timeout_seconds": timeout,
        "disable_background_skill_review": disable_bg,
    }

    def _load():
        return {"approvals": {"skill_manage": cfg}}

    monkeypatch.setattr(gate, "_load_skill_manage_cfg", lambda: cfg)
    return cfg


def test_should_escalate_requires_feishu_and_whitelist(monkeypatch):
    _patch_cfg(monkeypatch, profiles=["hermesxiyun"])
    monkeypatch.setattr(gate, "_current_profile", lambda: "hermesxiyun")
    monkeypatch.setattr(gate, "_session_platform", lambda: "feishu")
    monkeypatch.setattr(gate, "_is_background_review", lambda: False)

    assert gate.should_escalate("skill_manage", {"action": "create", "name": "x"})
    assert not gate.should_escalate("skill_view", {"name": "x"})
    assert not gate.should_escalate("skills_list", {})
    assert not gate.should_escalate("write_file", {"path": "a.md"})
    assert not gate.should_escalate("skill_manage", {"action": "list"})


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
    _patch_cfg(monkeypatch)
    monkeypatch.setattr(
        gate,
        "_load_skill_manage_cfg",
        lambda: {
            "approval_home_chat_id": "oc_home_group",
            "profiles": ["default"],
            "enabled": True,
        },
    )
    assert gate.get_approval_home_chat_id() == "oc_home_group"


def test_run_gate_approved_returns_none(monkeypatch):
    _patch_cfg(monkeypatch, timeout=120)
    monkeypatch.setattr(gate, "should_escalate", lambda *a, **k: True)
    monkeypatch.setattr(gate, "_is_background_review", lambda: False)
    monkeypatch.setattr(gate, "_prepare_activity_keepalive", lambda: None)
    monkeypatch.setattr(gate, "apply_timeout_patch", lambda: None)
    monkeypatch.setattr(gate, "get_approval_home_chat_id", lambda: "")

    import tools.approval as approval_mod

    monkeypatch.setattr(approval_mod, "get_current_session_key", lambda default="": "sess-1")
    monkeypatch.setattr(approval_mod, "is_approved", lambda sk, pk: False)
    monkeypatch.setattr(
        approval_mod, "_gateway_notify_cbs", {"sess-1": lambda data: None},
    )
    # unlock uses real RLock
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
    _patch_cfg(monkeypatch, timeout=120)
    monkeypatch.setattr(gate, "should_escalate", lambda *a, **k: True)
    monkeypatch.setattr(gate, "_is_background_review", lambda: False)
    monkeypatch.setattr(gate, "_prepare_activity_keepalive", lambda: None)
    monkeypatch.setattr(gate, "apply_timeout_patch", lambda: None)
    monkeypatch.setattr(
        gate, "get_approval_home_chat_id", lambda: "oc_f206b3d2a547a12f430593ea44076031",
    )
    home_notifies = []

    def _fake_home_notify(session_key, home_chat_id):
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
        seen["home"] = True
        notify_cb(approval_data)
        return {"resolved": True, "choice": "once", "reason": None}

    monkeypatch.setattr(approval_mod, "_await_gateway_decision", _await)

    result = gate.run_gate(
        "skill_manage", {"action": "create", "name": "my-skill"},
    )
    assert result is None
    assert home_notifies
    assert home_notifies[0][1] == "oc_f206b3d2a547a12f430593ea44076031"
    assert seen["session_key"] == "sess-1"


def test_run_gate_deny_hard_stops(monkeypatch):
    _patch_cfg(monkeypatch, timeout=120)
    monkeypatch.setattr(gate, "should_escalate", lambda *a, **k: True)
    monkeypatch.setattr(gate, "_is_background_review", lambda: False)
    monkeypatch.setattr(gate, "_prepare_activity_keepalive", lambda: None)
    monkeypatch.setattr(gate, "apply_timeout_patch", lambda: None)
    monkeypatch.setattr(gate, "get_approval_home_chat_id", lambda: "")
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
