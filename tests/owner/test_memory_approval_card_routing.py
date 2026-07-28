"""Tests for owner.feishu.memory_approval card + plugin bridge."""

import importlib.util
import json
import sys
from pathlib import Path
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
# Load owner-extensions/memory_feishu_bridge as hermes_plugins.owner_extensions.memory_feishu_bridge
# (mirrors PluginManager._load_directory_module) so the bridge module is
# importable in tests without running full plugin discovery.
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BRIDGE_DIR = _REPO_ROOT / "owner" / "owner-extensions" / "memory_feishu_bridge"
_BRIDGE_MODNAME = "hermes_plugins.owner_extensions.memory_feishu_bridge"


@pytest.fixture(scope="module", autouse=True)
def _bridge_module():
    if _BRIDGE_MODNAME in sys.modules:
        return sys.modules[_BRIDGE_MODNAME]
    # Ensure the parent namespace package exists
    import types as _types
    if "hermes_plugins" not in sys.modules:
        ns = _types.ModuleType("hermes_plugins")
        ns.__path__ = []  # type: ignore[attr-defined]
        sys.modules["hermes_plugins"] = ns
    spec = importlib.util.spec_from_file_location(
        _BRIDGE_MODNAME,
        _BRIDGE_DIR / "__init__.py",
        submodule_search_locations=[str(_BRIDGE_DIR)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[_BRIDGE_MODNAME] = module
    spec.loader.exec_module(module)
    return module


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
    # Title is i18n-driven; just verify it's non-empty.
    assert card["header"]["title"]["content"]

    elements = card["elements"]
    md = elements[0]
    assert md["tag"] == "markdown"
    assert "a1b2c3d4" in md["content"]
    assert "add to memory" in md["content"]
    assert "new content here" in md["content"]

    actions = elements[1]["actions"]
    assert len(actions) == 2
    assert actions[0]["value"]["hermes_action"] == ACTION_KEY
    assert actions[0]["value"]["choice"] == "approve"
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
    assert card["header"]["title"]["content"]  # i18n-driven label
    assert len(card["elements"]) == 1
    assert card["elements"][0]["tag"] == "markdown"
    assert "**ID**" in card["elements"][0]["content"]


def test_build_resolved_denied_card():
    card = build_resolved_card(choice="deny")
    assert card["header"]["template"] == "red"
    assert "🟥" in card["header"]["title"]["content"]
    assert card["header"]["title"]["content"]  # i18n-driven label
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
# Plugin bridge tests — bridge loaded as hermes_plugins.owner_extensions.memory_feishu_bridge
# ---------------------------------------------------------------------------

def _get_bridge():
    """Return the bridge module (loaded by the module fixture)."""
    return sys.modules[_BRIDGE_MODNAME]


def test_plugin_post_tool_non_memory_tool():
    bridge = _get_bridge()
    _on_post_tool_call = bridge._on_post_tool_call

    adapter = MagicMock()
    with patch.object(bridge, "_FEISHU_ADAPTER", adapter):
        _on_post_tool_call(tool_name="write_file", result="some text")
    adapter._submit_on_loop.assert_not_called()


def test_plugin_post_tool_non_staged_result():
    bridge = _get_bridge()
    _on_post_tool_call = bridge._on_post_tool_call

    adapter = MagicMock()
    with patch.object(bridge, "_FEISHU_ADAPTER", adapter):
        _on_post_tool_call(
            tool_name="memory",
            args=_simple_memory_args(),
            result=json.dumps({"success": True}),
            session_id="agent:main:feishu:dm:oc_test",
        )
    adapter._submit_on_loop.assert_not_called()


def test_plugin_post_tool_invalid_json():
    bridge = _get_bridge()
    _on_post_tool_call = bridge._on_post_tool_call

    with patch.object(bridge, "_FEISHU_ADAPTER", MagicMock()):
        _on_post_tool_call(
            tool_name="memory",
            args=_simple_memory_args(),
            result="not json at all",
            session_id="agent:main:feishu:dm:oc_test",
        )


def test_plugin_post_tool_no_feishu_adapter():
    bridge = _get_bridge()
    _on_post_tool_call = bridge._on_post_tool_call

    with patch.object(bridge, "_FEISHU_ADAPTER", None):
        _on_post_tool_call(
            tool_name="memory",
            args=_simple_memory_args(),
            result=json.dumps({"staged": True, "pending_id": "abc123"}),
            session_id="agent:main:feishu:dm:oc_test",
        )


def test_plugin_post_tool_non_feishu_session():
    bridge = _get_bridge()
    _on_post_tool_call = bridge._on_post_tool_call

    adapter = MagicMock()
    with patch.object(bridge, "_FEISHU_ADAPTER", adapter):
        _on_post_tool_call(
            tool_name="memory",
            args=_simple_memory_args(),
            result=json.dumps({"staged": True, "pending_id": "abc123"}),
            session_id="agent:main:telegram:dm:12345",
        )
    adapter._submit_on_loop.assert_not_called()


def test_plugin_pre_gateway_dispatch():
    bridge = _get_bridge()
    _on_pre_gateway_dispatch = bridge._on_pre_gateway_dispatch
    from gateway.config import Platform

    adapter = MagicMock()
    gateway = SimpleNamespace(adapters={Platform.FEISHU: adapter})

    bridge._FEISHU_ADAPTER = None  # clean state

    _on_pre_gateway_dispatch(gateway=gateway)
    assert bridge._FEISHU_ADAPTER is adapter
    assert bridge._GATEWAY_REF is gateway


# ---------------------------------------------------------------------------
# build_preview (owner/feishu/memory_approval.py)
# ---------------------------------------------------------------------------

def test_build_preview_add():
    s, c = build_preview({"action": "add", "target": "memory", "content": "hello"})
    assert s  # i18n-driven summary
    assert "hello" in c


def test_build_preview_replace():
    s, c = build_preview({
        "action": "replace", "target": "user",
        "old_text": "before", "content": "after",
    })
    assert s  # i18n-driven summary
    assert "before" in c
    assert "after" in c


def test_build_preview_remove():
    s, c = build_preview({"action": "remove", "target": "memory", "old_text": "stale"})
    assert s  # i18n-driven summary
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


# ---------------------------------------------------------------------------
# gateway_session_key plumbing — direction A fix
# ---------------------------------------------------------------------------

class _CapturingSubmit:
    def __init__(self):
        self.calls = []

    def __call__(self, loop, coro):
        self.calls.append((loop, coro))
        # Close the unawaited coroutine to avoid RuntimeWarning
        coro.close()


def _make_live_loop():
    """A fake loop object that reports as not-closed."""
    return SimpleNamespace(is_closed=lambda: False)


def test_gateway_session_key_preferred_over_session_id():
    """When both are present, gateway_session_key decides the chat_id.

    The bridge should ignore the bare timestamp-shaped agent.session_id and
    pull chat_id from the gateway session_key (agent:main:feishu:dm:<chat_id>).

    Also verifies the production path writes the pending_id to _SENT_CARD_IDS
    once a dispatch is submitted (the transform no longer reads this set, but it
    remains an observational dispatch log that P1 tests must cover).
    """
    bridge = _get_bridge()
    bridge._SENT_CARD_IDS.clear()
    adapter = SimpleNamespace(
        _loop=_make_live_loop(),
        _submit_on_loop=_CapturingSubmit(),
    )
    with patch.object(bridge, "_FEISHU_ADAPTER", adapter):
        bridge._on_post_tool_call(
            tool_name="memory",
            args=_simple_memory_args(),
            result=json.dumps({"staged": True, "pending_id": "abc123"}),
            # session_id is a bare timestamp id — extract_feishu_chat_id("") returns ""
            session_id="20260703_191525_0fce5a47",
            gateway_session_key="agent:main:feishu:dm:oc_correct_chat",
        )
    assert len(adapter._submit_on_loop.calls) == 1
    # Production path populated the dispatch log.
    assert "abc123" in bridge._SENT_CARD_IDS


def test_dispatch_failure_does_not_mark_sent():
    """When scheduling the card send raises, _SENT_CARD_IDS must NOT be
    populated — the mark means \"a dispatch was submitted\", so a failed
    submit must leave it empty (otherwise the observational log would lie
    about a dispatch that never reached the loop)."""
    bridge = _get_bridge()
    bridge._SENT_CARD_IDS.clear()

    class _BoomSubmit:
        def __call__(self, loop, coro):
            coro.close()  # avoid RuntimeWarning for unawaited coroutine
            raise RuntimeError("loop gone away")

    adapter = SimpleNamespace(
        _loop=_make_live_loop(),
        _submit_on_loop=_BoomSubmit(),
    )
    with patch.object(bridge, "_FEISHU_ADAPTER", adapter):
        bridge._on_post_tool_call(
            tool_name="memory",
            args=_simple_memory_args(),
            result=json.dumps({"staged": True, "pending_id": "fail_1"}),
            session_id="agent:main:feishu:dm:oc_fail_chat",
        )
    # Dispatch raised before the mark → set stays empty.
    assert "fail_1" not in bridge._SENT_CARD_IDS


def test_submit_returns_false_does_not_mark_sent_when_fallback_also_fails():
    """_submit_on_loop returning False used to be ignored (card silently
    dropped but _SENT_CARD_IDS still marked). When both submit and the
    run_coroutine_threadsafe fallback fail, the set must stay empty."""
    bridge = _get_bridge()
    bridge._SENT_CARD_IDS.clear()

    class _FalseSubmit:
        def __call__(self, loop, coro):
            coro.close()
            return False

    adapter = SimpleNamespace(
        _loop=_make_live_loop(),
        _submit_on_loop=_FalseSubmit(),
    )
    with patch.object(bridge, "_FEISHU_ADAPTER", adapter), \
         patch("asyncio.run_coroutine_threadsafe", side_effect=RuntimeError("no loop")):
        bridge._on_post_tool_call(
            tool_name="memory",
            args=_simple_memory_args(),
            result=json.dumps({"staged": True, "pending_id": "false_submit"}),
            session_id="agent:main:feishu:dm:oc_false",
        )
    assert "false_submit" not in bridge._SENT_CARD_IDS


def test_chat_id_hint_fallback_when_session_keys_unparseable():
    """When session keys lack Feishu shape, agent-level chat_id + platform
    still schedules the card (2026-07-28 regression: silent skip)."""
    bridge = _get_bridge()
    bridge._SENT_CARD_IDS.clear()
    adapter = SimpleNamespace(
        _loop=_make_live_loop(),
        _submit_on_loop=_CapturingSubmit(),
    )
    with patch.object(bridge, "_FEISHU_ADAPTER", adapter):
        bridge._on_post_tool_call(
            tool_name="memory",
            args=_simple_memory_args(),
            result=json.dumps({"staged": True, "pending_id": "hint_1"}),
            session_id="20260728_184040_0e88da8d",  # bare timestamp
            gateway_session_key="",
            platform="feishu",
            chat_id="oc_from_agent_chat_id",
        )
    assert len(adapter._submit_on_loop.calls) == 1
    assert "hint_1" in bridge._SENT_CARD_IDS


def test_empty_args_still_sends_card_with_fallback_summary():
    """Empty/unknown tool args used to abort on empty build_preview summary.
    Staged writes must still produce a card."""
    bridge = _get_bridge()
    bridge._SENT_CARD_IDS.clear()
    adapter = SimpleNamespace(
        _loop=_make_live_loop(),
        _submit_on_loop=_CapturingSubmit(),
    )
    with patch.object(bridge, "_FEISHU_ADAPTER", adapter):
        bridge._on_post_tool_call(
            tool_name="memory",
            args={},  # no action/content
            result=json.dumps({"staged": True, "pending_id": "empty_args"}),
            gateway_session_key="agent:main:feishu:dm:oc_empty_args",
        )
    assert len(adapter._submit_on_loop.calls) == 1
    assert "empty_args" in bridge._SENT_CARD_IDS


def test_staged_memory_invokes_send_approval_card():
    """End-to-end: staged memory result → scheduled coroutine calls
    owner.feishu.memory_approval.send_approval_card (the actual Feishu
    card send). Mocks send_approval_card so we assert the call without
    hitting the network."""
    import asyncio

    bridge = _get_bridge()
    bridge._SENT_CARD_IDS.clear()
    captured = {}

    async def _fake_send(adapter, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(success=True, message_id="om_test")

    class _RunSubmit:
        """Run the scheduled coroutine on a temporary event loop."""

        def __call__(self, loop, coro):
            # Drive the coroutine to completion so send_approval_card runs.
            asyncio.get_event_loop_policy().new_event_loop()
            tmp = asyncio.new_event_loop()
            try:
                tmp.run_until_complete(coro)
            finally:
                tmp.close()
            return True

    adapter = SimpleNamespace(
        _loop=_make_live_loop(),
        _submit_on_loop=_RunSubmit(),
    )
    with patch.object(bridge, "_FEISHU_ADAPTER", adapter), \
         patch(
             "owner.feishu.memory_approval.send_approval_card",
             side_effect=_fake_send,
         ):
        bridge._on_post_tool_call(
            tool_name="memory",
            args={
                "action": "batch",
                "target": "memory",
                "operations": [
                    {"action": "remove", "old_text": "entry one"},
                    {"action": "remove", "old_text": "entry two"},
                ],
            },
            result=json.dumps({
                "success": True,
                "staged": True,
                "pending_id": "7bdca1a2",
                "message": "Staged for approval",
            }),
            session_id="20260728_184040_0e88da8d",
            gateway_session_key="agent:main:feishu:dm:oc_1918df05db4fc0d7044d13e599721dc8",
        )

    assert captured.get("pending_id") == "7bdca1a2"
    assert captured.get("chat_id") == "oc_1918df05db4fc0d7044d13e599721dc8"
    assert "7bdca1a2" in bridge._SENT_CARD_IDS
    # Preview should mention the batch removes.
    assert "entry one" in (captured.get("content_preview") or "")


def test_gateway_session_key_empty_falls_back_to_session_id():
    """When gateway_session_key is missing, fall back to session_id (legacy path)."""
    bridge = _get_bridge()
    adapter = SimpleNamespace(
        _loop=_make_live_loop(),
        _submit_on_loop=_CapturingSubmit(),
    )
    with patch.object(bridge, "_FEISHU_ADAPTER", adapter):
        bridge._on_post_tool_call(
            tool_name="memory",
            args=_simple_memory_args(),
            result=json.dumps({"staged": True, "pending_id": "abc123"}),
            # No gateway_session_key — session_id carries the gateway shape.
            session_id="agent:main:feishu:dm:oc_legacy_chat",
        )
    assert len(adapter._submit_on_loop.calls) == 1


def test_gateway_session_key_with_wrong_platform_falls_back():
    """If gateway_session_key is non-feishu (e.g. telegram), the bridge should
    try session_id next rather than aborting."""
    bridge = _get_bridge()
    adapter = SimpleNamespace(
        _loop=_make_live_loop(),
        _submit_on_loop=_CapturingSubmit(),
    )
    with patch.object(bridge, "_FEISHU_ADAPTER", adapter):
        bridge._on_post_tool_call(
            tool_name="memory",
            args=_simple_memory_args(),
            result=json.dumps({"staged": True, "pending_id": "abc123"}),
            session_id="agent:main:feishu:dm:oc_via_session_id",
            gateway_session_key="agent:main:telegram:dm:12345",
        )
    # session_id has feishu shape → falls back successfully → card scheduled.
    assert len(adapter._submit_on_loop.calls) == 1


def test_both_keys_unparseable_skips_card():
    """When neither key parses to a feishu chat, the card is skipped."""
    bridge = _get_bridge()
    adapter = SimpleNamespace(
        _loop=_make_live_loop(),
        _submit_on_loop=_CapturingSubmit(),
    )
    with patch.object(bridge, "_FEISHU_ADAPTER", adapter):
        bridge._on_post_tool_call(
            tool_name="memory",
            args=_simple_memory_args(),
            result=json.dumps({"staged": True, "pending_id": "abc123"}),
            session_id="20260703_191525_0fce5a47",
            gateway_session_key="agent:main:telegram:dm:12345",
        )
    assert len(adapter._submit_on_loop.calls) == 0


# ---------------------------------------------------------------------------
# _emit_post_tool_call_hook forwards gateway_session_key to the hook kwargs
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# transform_tool_result - message rewrite on Feishu
# ---------------------------------------------------------------------------

def test_transform_non_memory_tool_returns_none():
    bridge = _get_bridge()
    result = json.dumps({"staged": True, "pending_id": "xyz"})
    out = bridge._on_transform_tool_result(
        tool_name="terminal", result=result,
        gateway_session_key="agent:main:feishu:dm:oc_1",
    )
    assert out is None


def test_transform_non_staged_result_returns_none():
    bridge = _get_bridge()
    result = json.dumps({"success": True})
    out = bridge._on_transform_tool_result(
        tool_name="memory", result=result,
        gateway_session_key="agent:main:feishu:dm:oc_1",
    )
    assert out is None


def test_transform_non_feishu_session_returns_none():
    """A non-Feishu session (no derivable Feishu chat id) is not transformed —
    the upstream CLI-oriented message is left untouched."""
    bridge = _get_bridge()
    bridge._SENT_CARD_IDS.clear()
    result = json.dumps({"staged": True, "pending_id": "never_sent", "message": "orig"})
    out = bridge._on_transform_tool_result(
        tool_name="memory", result=result,
        gateway_session_key="agent:main:telegram:dm:12345",
    )
    assert out is None


def test_transform_feishu_session_rewrites_message():
    """On a Feishu session, a staged memory write is rewritten to mention the
    approval card being sent. Detection keys on the session, NOT on
    _SENT_CARD_IDS (the async dispatch may fail in flight)."""
    bridge = _get_bridge()
    bridge._SENT_CARD_IDS.clear()  # intentionally empty — transform must not depend on it

    result = json.dumps({
        "success": True, "staged": True,
        "pending_id": "pid_feishu_1",
        "message": "Staged for approval (memory.write_approval is on). Not yet saved - review with /memory pending.",
    })
    out = bridge._on_transform_tool_result(
        tool_name="memory", result=result,
        gateway_session_key="agent:main:feishu:dm:oc_chat_1",
    )
    assert out is not None
    parsed = json.loads(out)
    # Progressive tense — accurate whether or not the in-flight card delivers.
    assert "Approval card being sent" in parsed["message"]
    assert "/memory pending" not in parsed["message"]


def test_transform_feishu_session_via_session_id_fallback():
    """When gateway_session_key is absent, session_id with the Feishu gateway
    shape still triggers the rewrite (back-compat with older callers)."""
    bridge = _get_bridge()
    bridge._SENT_CARD_IDS.clear()
    result = json.dumps({
        "success": True, "staged": True,
        "pending_id": "pid_feishu_2", "message": "old",
    })
    out = bridge._on_transform_tool_result(
        tool_name="memory", result=result,
        session_id="agent:main:feishu:dm:oc_chat_2",
    )
    assert out is not None
    parsed = json.loads(out)
    assert "Approval card being sent" in parsed["message"]


def test_transform_preserves_other_fields():
    """success / staged / pending_id must be preserved; only message changes."""
    bridge = _get_bridge()
    bridge._SENT_CARD_IDS.clear()

    result = json.dumps({
        "success": True, "staged": True,
        "pending_id": "pid_42",
        "message": "old",
    })
    out = bridge._on_transform_tool_result(
        tool_name="memory", result=result,
        gateway_session_key="agent:main:feishu:dm:oc_42",
    )
    parsed = json.loads(out)
    assert parsed["success"] is True
    assert parsed["staged"] is True
    assert parsed["pending_id"] == "pid_42"
    assert parsed["message"] != "old"


def test_transform_invalid_json_returns_none():
    bridge = _get_bridge()
    out = bridge._on_transform_tool_result(
        tool_name="memory", result="not json",
        gateway_session_key="agent:main:feishu:dm:oc_1",
    )
    assert out is None


def test_emit_post_tool_call_hook_forwards_gateway_session_key():
    """model_tools._emit_post_tool_call_hook must pass gateway_session_key
    through to invoke_hook so plugin callbacks see it in their kwargs."""
    from model_tools import _emit_post_tool_call_hook

    captured: dict = {}

    def _capture(hook_name, **kwargs):
        captured.update(kwargs)

    with patch("hermes_cli.plugins.has_hook", lambda name: True), \
         patch("hermes_cli.plugins.invoke_hook", _capture):
        _emit_post_tool_call_hook(
            function_name="memory",
            function_args={"action": "add"},
            result=json.dumps({"staged": True}),
            session_id="20260703_191525_0fce5a47",
            gateway_session_key="agent:main:feishu:dm:oc_forwarded",
        )

    assert captured.get("gateway_session_key") == "agent:main:feishu:dm:oc_forwarded"
    # session_id is still forwarded unchanged.
    assert captured.get("session_id") == "20260703_191525_0fce5a47"


def test_emit_post_tool_call_hook_default_gateway_session_key_blank():
    """When gateway_session_key is not supplied, it defaults to '' (back-compat)."""
    from model_tools import _emit_post_tool_call_hook

    captured: dict = {}

    def _capture(hook_name, **kwargs):
        captured.update(kwargs)

    with patch("hermes_cli.plugins.has_hook", lambda name: True), \
         patch("hermes_cli.plugins.invoke_hook", _capture):
        _emit_post_tool_call_hook(
            function_name="memory",
            function_args={},
            result="{}",
        )

    assert captured.get("gateway_session_key") == ""


def test_handle_function_call_accepts_gateway_session_key():
    """handle_function_call must accept the new keyword without breaking
    the existing call shape (backward-compat signature)."""
    import inspect
    from model_tools import handle_function_call

    sig = inspect.signature(handle_function_call)
    assert "gateway_session_key" in sig.parameters
    param = sig.parameters["gateway_session_key"]
    # Must have a default so existing callers don't break.
    assert param.default is None


def test_emit_post_tool_call_hook_accepts_gateway_session_key():
    """_emit_post_tool_call_hook must accept the new keyword arg."""
    import inspect
    from model_tools import _emit_post_tool_call_hook

    sig = inspect.signature(_emit_post_tool_call_hook)
    assert "gateway_session_key" in sig.parameters
    param = sig.parameters["gateway_session_key"]
    assert param.default is None


def test_transform_tool_result_hook_receives_gateway_session_key():
    """handle_function_call forwards gateway_session_key to the
    transform_tool_result hook (parity with post_tool_call) so plugins can
    detect the Feishu session when rewriting staged-memory results.

    Uses a stubbed registry (pattern from tests/test_dispatch_session_id.py) so
    the real tool dispatch is bypassed and the transform-hook seam is reached
    without depending on a concrete tool implementation. Uses a generic tool
    name (web_search) because agent-loop tools (memory/todo/etc.) are intercepted
    before the registry dispatch — the transform seam is tool-agnostic."""
    from unittest.mock import MagicMock
    captured: dict = {}

    registry = MagicMock()

    def _dispatch(name, args, **kwargs):
        return json.dumps({"ok": True})

    registry.dispatch.side_effect = _dispatch

    def _capture_invoke(hook_name, **kwargs):
        if hook_name == "transform_tool_result":
            captured.update(kwargs)
        return []

    with patch("model_tools.registry", registry), \
         patch("hermes_cli.plugins.has_hook", lambda name: name == "transform_tool_result"), \
         patch("hermes_cli.plugins.invoke_hook", _capture_invoke), \
         patch("hermes_cli.middleware.run_tool_execution_middleware",
               lambda fn, args, dispatch, **kw: dispatch(args)):
        from model_tools import handle_function_call
        handle_function_call(
            "web_search",
            {"query": "feishu"},
            task_id="t1",
            session_id="20260703_191525_0fce5a47",
            gateway_session_key="agent:main:feishu:dm:oc_transformed",
            skip_pre_tool_call_hook=True,
        )

    assert captured.get("gateway_session_key") == "agent:main:feishu:dm:oc_transformed"
    assert captured.get("tool_name") == "web_search"
    assert captured.get("session_id") == "20260703_191525_0fce5a47"