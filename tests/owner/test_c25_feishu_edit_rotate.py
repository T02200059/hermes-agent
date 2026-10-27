"""Tests for progress-message edit-rotate semantics (C25 / WR-06).

Bug: Feishu caps edits to a single message at ~20 (error 230072 / 230075).
The gateway treated this as a permanent edit failure and set
``can_edit = False`` for the rest of the run — every subsequent tool
progress line landed as its own standalone bubble instead of merging
into one editable message.

Fix introduces a platform-agnostic contract: adapters return
``SendResult(rotate=True)`` when the target bubble is no longer editable
but a fresh bubble can continue. The gateway rotates to a new message
and keeps ``can_edit = True``.
"""

from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from gateway.platforms.base import SendResult
from owner.gateway.turn_helpers import classify_edit_failure


# ---------------------------------------------------------------------------
# 1. SendResult.rotate field contract
# ---------------------------------------------------------------------------

def test_send_result_rotate_defaults_false():
    r = SendResult(success=True, message_id="1")
    assert r.rotate is False


def test_send_result_rotate_can_be_set_true():
    r = SendResult(success=False, error="[230072] edit limit", rotate=True)
    assert r.rotate is True


def test_send_result_rotate_independent_of_retryable():
    r = SendResult(success=False, error="edit limit", rotate=True, retryable=False)
    assert r.rotate is True
    assert r.retryable is False


# ---------------------------------------------------------------------------
# 2. Feishu adapter — 230072 / 230075 edit-limit → rotate=True
# ---------------------------------------------------------------------------

@pytest.fixture
def _feishu_adapter():
    from gateway.config import PlatformConfig
    from plugins.platforms.feishu.adapter import FeishuAdapter
    return FeishuAdapter(PlatformConfig())


def _run_edit_with_response_codes(adapter, codes):
    """Drive edit_message through a sequence of update() responses."""
    calls = {"i": 0}

    class _MessageAPI:
        def update(self, request):
            i = calls["i"]
            calls["i"] += 1
            code = codes[min(i, len(codes) - 1)]
            if code == 0:
                return SimpleNamespace(success=lambda: True, data=SimpleNamespace(message_id="om_ok"))
            return SimpleNamespace(
                success=lambda: False,
                code=code,
                msg=f"failed code={code}",
            )

    adapter._client = SimpleNamespace(
        im=SimpleNamespace(v1=SimpleNamespace(message=_MessageAPI()))
    )

    async def _direct(func, *args, **kwargs):
        return func(*args, **kwargs)

    with patch.object(adapter, "_run_blocking", side_effect=_direct):
        return asyncio.run(
            adapter.edit_message(
                chat_id="oc_chat",
                message_id="om_progress",
                content="```\nls\n```",
            )
        )


@patch.dict(os.environ, {}, clear=True)
def test_feishu_edit_230072_sets_rotate(_feishu_adapter):
    result = _run_edit_with_response_codes(_feishu_adapter, [230072, 230072])
    assert result.success is False
    assert result.rotate is True, "230072 must signal rotate=True"
    assert "230072" in (result.error or "")


@patch.dict(os.environ, {}, clear=True)
def test_feishu_edit_230075_sets_rotate(_feishu_adapter):
    result = _run_edit_with_response_codes(_feishu_adapter, [230075, 230075])
    assert result.success is False
    assert result.rotate is True


@patch.dict(os.environ, {}, clear=True)
def test_feishu_edit_unrelated_error_does_not_rotate(_feishu_adapter):
    result = _run_edit_with_response_codes(_feishu_adapter, [230001, 230001])
    assert result.success is False
    assert result.rotate is False


@patch.dict(os.environ, {}, clear=True)
def test_feishu_edit_success_has_no_rotate(_feishu_adapter):
    result = _run_edit_with_response_codes(_feishu_adapter, [0])
    assert result.success is True
    assert result.rotate is False


# ---------------------------------------------------------------------------
# 3. Gateway progress-loop rotate handling (simulated)
# ---------------------------------------------------------------------------

def _simulate_progress_loop_with_rotate(edit_results, send_results):
    """Mirror the gateway progress-loop decision under the rotate fix.

    The per-result DECISION is delegated to the production classifier
    ``classify_edit_failure`` (WR-06).
    """
    can_edit = True
    progress_msg_id = "om_initial"
    rotations = 0
    standalone_sends = 0
    edit_after_rotate = 0
    send_i = 0

    for result in edit_results:
        if result.success:
            continue
        action = classify_edit_failure(result)
        if action == "retryable":
            continue
        if action == "rotate":
            progress_msg_id = None
            rotations += 1
            new = send_results[min(send_i, len(send_results) - 1)]
            send_i += 1
            if new.success and new.message_id:
                progress_msg_id = new.message_id
                edit_after_rotate += 1
            continue
        if action == "flood":
            continue
        can_edit = False
        standalone_sends += 1
        break

    return {
        "can_edit": can_edit,
        "progress_msg_id": progress_msg_id,
        "rotations": rotations,
        "standalone_sends": standalone_sends,
        "edit_after_rotate": edit_after_rotate,
    }


def test_rotate_keeps_can_edit_true_and_starts_new_bubble():
    edit_results = [
        SendResult(success=True),
        SendResult(success=True),
        SendResult(success=False, error="[230072] edit limit", rotate=True),
        SendResult(success=True),
    ]
    send_results = [SendResult(success=True, message_id="om_bubble_b")]
    state = _simulate_progress_loop_with_rotate(edit_results, send_results)
    assert state["can_edit"] is True
    assert state["rotations"] == 1
    assert state["progress_msg_id"] == "om_bubble_b"
    assert state["standalone_sends"] == 0


def test_multiple_rotates_chain_through_bubbles():
    edit_results = [
        SendResult(success=False, error="[230072]", rotate=True),
        SendResult(success=False, error="[230072]", rotate=True),
        SendResult(success=True),
    ]
    send_results = [
        SendResult(success=True, message_id="om_b"),
        SendResult(success=True, message_id="om_c"),
    ]
    state = _simulate_progress_loop_with_rotate(edit_results, send_results)
    assert state["can_edit"] is True
    assert state["rotations"] == 2
    assert state["progress_msg_id"] == "om_c"


def test_rotate_takes_precedence_over_permanent_disable():
    edit_results = [
        SendResult(success=False, error="[230072]", rotate=True, retryable=False),
    ]
    send_results = [SendResult(success=True, message_id="om_new")]
    state = _simulate_progress_loop_with_rotate(edit_results, send_results)
    assert state["can_edit"] is True


def test_bare_permanent_failure_still_disables_can_edit():
    edit_results = [
        SendResult(success=False, error="message to edit not found"),
    ]
    state = _simulate_progress_loop_with_rotate(edit_results, [])
    assert state["can_edit"] is False
    assert state["standalone_sends"] == 1


# ---------------------------------------------------------------------------
# 4. classify_edit_failure — production decision function (WR-06)
# ---------------------------------------------------------------------------

class TestClassifyEditFailure:
    def test_retryable_takes_precedence(self):
        r = SendResult(success=False, error="connect timeout", retryable=True, rotate=True)
        assert classify_edit_failure(r) == "retryable"

    def test_rotate_when_not_retryable(self):
        r = SendResult(success=False, error="[230072] edit limit", rotate=True)
        assert classify_edit_failure(r) == "rotate"

    def test_flood_from_error_text(self):
        assert classify_edit_failure(SendResult(success=False, error="flood control")) == "flood"
        assert classify_edit_failure(SendResult(success=False, error="Please retry after 5s")) == "flood"

    def test_disable_for_bare_permanent_failure(self):
        r = SendResult(success=False, error="message to edit not found")
        assert classify_edit_failure(r) == "disable"

    def test_disable_when_error_missing(self):
        assert classify_edit_failure(SendResult(success=False)) == "disable"
