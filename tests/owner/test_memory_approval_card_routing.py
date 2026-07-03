"""Tests for owner.feishu.memory_approval card + plugin bridge."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from owner.feishu.memory_approval import (
    ACTION_KEY,
    build_approval_card,
    build_preview,
    build_resolved_card,
    extract_feishu_chat_id,
    handle_card_click,
)


# ---------------------------------------------------------------------------
# extract_feishu_chat_id
# ---------------------------------------------------------------------------

def test_extract_chat_id_dm():
    assert extract_feishu_chat_id("agent:main:feishu:dm:oc_abc123") == "oc_abc123"


def test_extract_chat_id_dm_with_thread():
    assert extract_feishu_chat_id("agent:main:feishu:dm:oc_abc123:thread_1") == "oc_abc123"


def test_extract_chat_id_group():
    assert extract_feishu_chat_id("agent:main:feishu:group:oc_group:thread_x") == "oc_group"


def test_extract_chat_id_non_feishu_empty():
    assert extract_feishu_chat_id("agent:main:telegram:dm:12345") == ""


def test_extract_chat_id_too_short():
    assert extract_feishu_chat_id("agent:main:feishu") == ""


def test_extract_chat_id_empty_string():
    assert extract_feishu_chat_id("") == ""


# ---------------------------------------------------------------------------
# build_approval_card
# ---------------------------------------------------------------------------

def test_build_approval_card_shape():
    card = build_approval_card(
        pending_id="a1b2c3d4",
        summary="add to memory",
        content_preview="new content here",
        chat_id="oc_abc123",
        session_id="agent:main:feishu:dm:oc_abc123",
    )

    assert card["config"]["wide_screen_mode"] is True
    assert card["header"]["template"] == "purple"
    assert "Memory approval" in card["header"]["title"]["content"]

    elements = card["elements"]
    md = elements[0]
    assert md["tag"] == "markdown"
    assert "a1b2c3d4" in md["content"]
    assert "add to memory" in md["content"]
    assert "new content here" in md["content"]

    actions = elements[1]["actions"]
    assert len(actions) == 2
    assert actions[0]["text"]["content"] == "✅ Approve"
    assert actions[0]["value"]["hermes_action"] == ACTION_KEY
    assert actions[0]["value"]["choice"] == "approve"
    assert actions[1]["text"]["content"] == "🟥 Deny"
    assert actions[1]["value"]["choice"] == "deny"


def test_build_approval_card_button_values():
    card = build_approval_card(
        pending_id="deadbeef",
        summary="replace in user profile",
        content_preview="old: x\nnew: y",
        chat_id="oc_xyz",
        session_id="agent:main:feishu:dm:oc_xyz",
    )
    approve_btn = card["elements"][1]["actions"][0]
    val = approve_btn["value"]
    assert val["pending_id"] == "deadbeef"
    assert val["choice"] == "approve"
    assert val["chat_id"] == "oc_xyz"
    assert val["session_id"] == "agent:main:feishu:dm:oc_xyz"
    assert "deadbeef" in val["proposal_md"]
    assert "replace in user profile" in val["proposal_md"]


def test_build_approval_card_truncated_content():
    long_content = "x" * 2000
    card = build_approval_card(
        pending_id="1234", summary="long", content_preview=long_content,
        chat_id="c1",
    )
    md = card["elements"][0]["content"]
    assert len(md) < 2000
    assert "…" in md  # truncation indicator


# ---------------------------------------------------------------------------
# build_resolved_card
# ---------------------------------------------------------------------------

def test_build_resolved_approved_card():
    card = build_resolved_card(choice="approve", proposal_md="**ID**: `x`\n```y```")
    assert card["header"]["template"] == "green"
    assert "✅" in card["header"]["title"]["content"]
    assert "已批准" in card["header"]["title"]["content"]
    assert len(card["elements"]) == 1
    assert card["elements"][0]["tag"] == "markdown"
    assert "**ID**" in card["elements"][0]["content"]


def test_build_resolved_denied_card():
    card = build_resolved_card(choice="deny")
    assert card["header"]["template"] == "red"
    assert "🟥" in card["header"]["title"]["content"]
    assert "已拒绝" in card["header"]["title"]["content"]
    assert card["elements"] == []


def test_build_resolved_denied_with_md():
    card = build_resolved_card(choice="deny", proposal_md="info")
    assert card["header"]["template"] == "red"
    assert len(card["elements"]) == 1
    assert "info" in card["elements"][0]["content"]


# ---------------------------------------------------------------------------
# handle_card_click — routing to slash commands
# ---------------------------------------------------------------------------

class _CapturingSubmit:
    def __init__(self):
        self.calls = []

    def __call__(self, loop, coro):
        self.calls.append((loop, coro))


class _CallBackCard:
    pass


class _P2CardActionTriggerResponse:
    pass


def _make_ok_card_click(choice="approve"):
    """Return (adapter, event, loop, action_value) for a happy-path click."""
    adapter = SimpleNamespace(_submit_on_loop=_CapturingSubmit())
    loop = object()
    event = SimpleNamespace(context=None)
    action_value = {
        "hermes_action": ACTION_KEY,
        "choice": choice,
        "pending_id": "a1b2",
        "chat_id": "oc_test",
        "session_id": "agent:main:feishu:dm:oc_test",
        "proposal_md": "content",
    }
    return adapter, event, loop, action_value


def test_handle_card_click_approve():
    """✅ click routes /memory approve <id> via adapter._submit_on_loop."""
    adapter, event, loop, action_value = _make_ok_card_click("approve")

    with patch(
        "owner.feishu.memory_approval._route_command", lambda *a, **kw: None,
    ):
        result = handle_card_click(
            adapter=adapter, event=event, action_value=action_value, loop=loop,
        )

    assert result is not None
    response_card_data = result.card.data
    assert response_card_data["header"]["template"] == "green"
    assert "✅" in response_card_data["header"]["title"]["content"]


def test_handle_card_click_deny():
    """🟥 click routes /memory reject <id>."""
    adapter, event, loop, action_value = _make_ok_card_click("deny")

    with patch(
        "owner.feishu.memory_approval._route_command", lambda *a, **kw: None,
    ):
        result = handle_card_click(
            adapter=adapter, event=event, action_value=action_value, loop=loop,
        )

    assert result is not None
    response_card_data = result.card.data
    assert response_card_data["header"]["template"] == "red"
    assert "🟥" in response_card_data["header"]["title"]["content"]


def test_handle_card_click_non_matching_action():
    result = handle_card_click(
        adapter=object(), event=None,
        action_value={"hermes_action": "some_other_action"}, loop=object(),
    )
    assert result is None


def test_handle_card_click_not_a_dict():
    assert handle_card_click(
        adapter=object(), event=None, action_value="not_a_dict", loop=object(),
    ) is None


def test_handle_card_click_empty_pending_id():
    adapter = SimpleNamespace(_submit_on_loop=lambda *a: None)
    result = handle_card_click(
        adapter=adapter,
        event=SimpleNamespace(context=None),
        action_value={"hermes_action": ACTION_KEY, "choice": "approve"},
        loop=object(),
    )
    assert result is not None


def test_handle_card_click_bad_choice():
    """Unknown choice skips routing."""
    adapter = SimpleNamespace(_submit_on_loop=lambda *a: None)
    result = handle_card_click(
        adapter=adapter,
        event=SimpleNamespace(context=None),
        action_value={
            "hermes_action": ACTION_KEY,
            "choice": "bogus",
            "pending_id": "abc",
        },
        loop=object(),
    )
    assert result is not None  # returns empty, no crash


# ---------------------------------------------------------------------------
# Plugin bridge tests — importable after sys.path fix above
# ---------------------------------------------------------------------------

def test_plugin_post_tool_non_memory_tool():
    from plugins.owner_memory_feishu_bridge import _on_post_tool_call

    adapter = MagicMock()
    import plugins.owner_memory_feishu_bridge as bridge
    with patch.object(bridge, "_FEISHU_ADAPTER", adapter):
        _on_post_tool_call(tool_name="write_file", result="some text")
    adapter._submit_on_loop.assert_not_called()


def test_plugin_post_tool_non_staged_result():
    from plugins.owner_memory_feishu_bridge import _on_post_tool_call

    adapter = MagicMock()
    import plugins.owner_memory_feishu_bridge as bridge
    with patch.object(bridge, "_FEISHU_ADAPTER", adapter):
        _on_post_tool_call(
            tool_name="memory",
            args=_simple_memory_args(),
            result=json.dumps({"success": True}),
            session_id="agent:main:feishu:dm:oc_test",
        )
    adapter._submit_on_loop.assert_not_called()


def test_plugin_post_tool_invalid_json():
    from plugins.owner_memory_feishu_bridge import _on_post_tool_call

    import plugins.owner_memory_feishu_bridge as bridge
    with patch.object(bridge, "_FEISHU_ADAPTER", MagicMock()):
        _on_post_tool_call(
            tool_name="memory",
            args=_simple_memory_args(),
            result="not json at all",
            session_id="agent:main:feishu:dm:oc_test",
        )


def test_plugin_post_tool_no_feishu_adapter():
    from plugins.owner_memory_feishu_bridge import _on_post_tool_call

    import plugins.owner_memory_feishu_bridge as bridge
    with patch.object(bridge, "_FEISHU_ADAPTER", None):
        _on_post_tool_call(
            tool_name="memory",
            args=_simple_memory_args(),
            result=json.dumps({"staged": True, "pending_id": "abc123"}),
            session_id="agent:main:feishu:dm:oc_test",
        )


def test_plugin_post_tool_non_feishu_session():
    from plugins.owner_memory_feishu_bridge import _on_post_tool_call

    adapter = MagicMock()
    import plugins.owner_memory_feishu_bridge as bridge
    with patch.object(bridge, "_FEISHU_ADAPTER", adapter):
        _on_post_tool_call(
            tool_name="memory",
            args=_simple_memory_args(),
            result=json.dumps({"staged": True, "pending_id": "abc123"}),
            session_id="agent:main:telegram:dm:12345",
        )
    adapter._submit_on_loop.assert_not_called()


def test_plugin_pre_gateway_dispatch():
    from plugins.owner_memory_feishu_bridge import (
        _on_pre_gateway_dispatch,
    )
    from gateway.config import Platform

    adapter = MagicMock()
    gateway = SimpleNamespace(adapters={Platform.FEISHU: adapter})

    import plugins.owner_memory_feishu_bridge as bridge
    bridge._FEISHU_ADAPTER = None  # clean state

    _on_pre_gateway_dispatch(gateway=gateway)
    assert bridge._FEISHU_ADAPTER is adapter
    assert bridge._GATEWAY_REF is gateway


# ---------------------------------------------------------------------------
# build_preview (owner/feishu/memory_approval.py)
# ---------------------------------------------------------------------------

def test_build_preview_add():
    s, c = build_preview({"action": "add", "target": "memory", "content": "hello"})
    assert "add to memory" in s
    assert "hello" in c


def test_build_preview_replace():
    s, c = build_preview({
        "action": "replace", "target": "user",
        "old_text": "before", "content": "after",
    })
    assert "replace in user profile" in s
    assert "before" in c
    assert "after" in c


def test_build_preview_remove():
    s, c = build_preview({"action": "remove", "target": "memory", "old_text": "stale"})
    assert "remove from memory" in s
    assert "stale" in c


def test_build_preview_batch():
    s, c = build_preview({
        "action": "batch", "target": "memory",
        "operations": [
            {"action": "add", "content": "x"},
            {"action": "remove", "old_text": "y"},
        ],
    })
    assert "apply 2 op(s)" in s
    assert "x" in c
    assert "y" in c


def test_build_preview_empty_args():
    s, c = build_preview({})
    assert s == ""
    assert c == ""


def test_build_preview_not_dict():
    s, c = build_preview("not dict")  # type: ignore[arg-type]
    assert s == ""
    assert c == ""


def test_build_preview_long_batch():
    """>6 ops should truncate with '... N more'."""
    ops = [{"action": "add", "content": f"item_{i}"} for i in range(10)]
    s, c = build_preview({"action": "batch", "target": "memory", "operations": ops})
    assert "apply 10 op(s)" in s
    assert "... 4 more" in c
    for i in range(6):
        assert f"item_{i}" in c


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _simple_memory_args():
    return {"action": "add", "target": "memory", "content": "test content"}