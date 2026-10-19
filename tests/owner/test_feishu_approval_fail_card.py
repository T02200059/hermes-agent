"""Tests for Feishu approval CallBackCard failure states."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from owner.feishu import approval as fa


def test_build_failed_approval_card_unauthorized():
    card = fa.build_failed_approval_card(
        reason="unauthorized",
        command="skill_manage create foo",
    )
    assert card["header"]["template"] == "red"
    assert "header" in card
    assert "elements" in card
    body = card["elements"][0]["content"]
    assert "skill_manage create foo" in body
    # Title uses i18n; at least non-empty
    assert card["header"]["title"]["content"]


def test_build_failed_approval_card_already_resolved_is_orange():
    card = fa.build_failed_approval_card(reason="already_resolved")
    assert card["header"]["template"] == "orange"


def test_handle_missing_approval_id_returns_fail_card(monkeypatch):
    CallBackCard = type("CallBackCard", (), {})
    P2Resp = type("P2Resp", (), {"__init__": lambda self: setattr(self, "card", None)})

    monkeypatch.setattr(
        fa,
        "handle_approval_card_action",
        fa.handle_approval_card_action,
    )
    # Patch SDK import path inside function by injecting via sys.modules is heavy;
    # call helpers directly for unit shape, and exercise handle with mocked import.
    import owner.feishu.approval as mod

    orig_import = __import__

    def _fake_import(name, *args, **kwargs):
        if "p2_card_action_trigger" in name:
            m = MagicMock()
            m.CallBackCard = CallBackCard
            m.P2CardActionTriggerResponse = P2Resp
            return m
        return orig_import(name, *args, **kwargs)

    # Simpler: use _fail path via real handle with mocked lark import
    class FakeCallBackCard:
        def __init__(self):
            self.type = None
            self.data = None

    class FakeResp:
        def __init__(self):
            self.card = None

    import builtins

    real_import = builtins.__import__

    def import_mock(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "lark_oapi.event.callback.model.p2_card_action_trigger" or (
            fromlist and "P2CardActionTriggerResponse" in fromlist
        ):
            mod_fake = MagicMock()
            mod_fake.CallBackCard = FakeCallBackCard
            mod_fake.P2CardActionTriggerResponse = FakeResp
            return mod_fake
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", import_mock)

    adapter = MagicMock()
    ctx = fa.FeishuApprovalContext()
    resp = fa.handle_approval_card_action(
        adapter=adapter,
        ctx=ctx,
        event=SimpleNamespace(operator=None, context=None),
        action_value={},  # no approval_id
        loop=None,
    )
    assert resp is not None
    assert resp.card is not None
    assert resp.card.data["header"]["template"] == "red"


def test_handle_unauthorized_operator(monkeypatch):
    """Out-of-allowlist operator ⇒ 红卡且不弹 state。

    注意：审批路径**不再**过 `_allow_group_message`（群策略门问的是「此人能否在这个群说话」，
    而不是「此人能否批这次审批」；group_policy=open 时它对谁都返回 True，而空 allowlist 的
    DM 配对模式又会被它误杀 —— 见 a89706e4cb / #96045）。授权唯一入口是
    `_is_interactive_operator_authorized`（admins ∪ allowed_group_users，通配 `*` 与
    空 allowlist 保持放行语义）。
    """

    class FakeCallBackCard:
        def __init__(self):
            self.type = None
            self.data = None

    class FakeResp:
        def __init__(self):
            self.card = None

    import builtins

    real_import = builtins.__import__

    def import_mock(name, globals=None, locals=None, fromlist=(), level=0):
        if "p2_card_action_trigger" in name:
            m = MagicMock()
            m.CallBackCard = FakeCallBackCard
            m.P2CardActionTriggerResponse = FakeResp
            return m
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", import_mock)

    adapter = MagicMock()
    adapter._is_interactive_operator_authorized.return_value = False

    ctx = fa.FeishuApprovalContext()
    aid = ctx.next_id()
    ctx.register(
        aid,
        session_key="sess",
        message_id="om_1",
        chat_id="oc_home",
        command="rm -rf /",
    )

    event = SimpleNamespace(
        operator=SimpleNamespace(open_id="ou_attacker", user_id=""),
        context=SimpleNamespace(open_chat_id="oc_home"),
    )
    resp = fa.handle_approval_card_action(
        adapter=adapter,
        ctx=ctx,
        event=event,
        action_value={"approval_id": aid, "hermes_action": "approve_once"},
        loop=None,
    )
    assert resp.card.data["header"]["template"] == "red"
    # Must NOT have popped state (unauthorized must not resolve)
    assert ctx.get(aid) is not None
    adapter._submit_on_loop.assert_not_called()


def test_handle_already_resolved(monkeypatch):
    class FakeCallBackCard:
        def __init__(self):
            self.type = None
            self.data = None

    class FakeResp:
        def __init__(self):
            self.card = None

    import builtins

    real_import = builtins.__import__

    def import_mock(name, globals=None, locals=None, fromlist=(), level=0):
        if "p2_card_action_trigger" in name:
            m = MagicMock()
            m.CallBackCard = FakeCallBackCard
            m.P2CardActionTriggerResponse = FakeResp
            return m
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", import_mock)

    adapter = MagicMock()
    ctx = fa.FeishuApprovalContext()
    resp = fa.handle_approval_card_action(
        adapter=adapter,
        ctx=ctx,
        event=SimpleNamespace(operator=None, context=None),
        action_value={"approval_id": 999, "hermes_action": "deny"},
        loop=None,
    )
    assert resp.card.data["header"]["template"] == "orange"
