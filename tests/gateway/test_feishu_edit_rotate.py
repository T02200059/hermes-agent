"""Tests for progress-message edit-rotate semantics.

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
import json
import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from gateway.platforms.base import SendResult
from gateway.run import _classify_edit_failure


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
    # rotate is a distinct signal: not "retry same op" (retryable),
    # but "open a new editable bubble" (rotate).
    r = SendResult(success=False, error="edit limit", rotate=True, retryable=False)
    assert r.rotate is True
    assert r.retryable is False


# ---------------------------------------------------------------------------
# 2. Feishu adapter — 230072 / 230075 edit-limit → rotate=True
# ---------------------------------------------------------------------------

@pytest.fixture
def _feishu_adapter():
    from gateway.config import PlatformConfig
    from gateway.platforms.feishu import FeishuAdapter
    return FeishuAdapter(PlatformConfig())


def _run_edit_with_response_codes(adapter, codes):
    """Drive edit_message through a sequence of update() responses.

    Each code in ``codes`` produces a failed response with that Feishu
    error code; a trailing 0 means success. Returns the final SendResult.
    """
    calls = {"i": 0}

    class _MessageAPI:
        def update(self, request):
            i = calls["i"]
            calls["i"] += 1
            code = codes[min(i, len(codes) - 1)]
            if code == 0:
                return SimpleNamespace(success=lambda: True)
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

    with patch("gateway.platforms.feishu.asyncio.to_thread", side_effect=_direct):
        return asyncio.run(
            adapter.edit_message(
                chat_id="oc_chat",
                message_id="om_progress",
                content="```\nls\n```",
            )
        )


@patch.dict(os.environ, {}, clear=True)
def test_feishu_edit_230072_sets_rotate(_feishu_adapter):
    """230072 = too many edits on this message → rotate to a fresh bubble."""
    result = _run_edit_with_response_codes(_feishu_adapter, [230072, 230072])
    assert result.success is False
    assert result.rotate is True, "230072 must signal rotate=True"
    assert "230072" in (result.error or "")


@patch.dict(os.environ, {}, clear=True)
def test_feishu_edit_230075_sets_rotate(_feishu_adapter):
    """230075 is the sibling edit-cap error code."""
    result = _run_edit_with_response_codes(_feishu_adapter, [230075, 230075])
    assert result.success is False
    assert result.rotate is True


@patch.dict(os.environ, {}, clear=True)
def test_feishu_edit_unrelated_error_does_not_rotate(_feishu_adapter):
    """A non-edit-cap error (e.g. 230001 format error that survives the
    post→text fallback) must NOT set rotate=True."""
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

    ``edit_results``: sequence of SendResult returned by edit_message.
    ``send_results``: sequence of SendResult returned by send (new bubble).

    Returns dict with final state: can_edit, progress_msg_id rotations,
    number of standalone sends, and whether any edit was attempted after
    a rotate.

    The per-result DECISION is delegated to the production classifier
    ``_classify_edit_failure`` (WR-06) — only the loop bookkeeping around it is
    simulated here, so a regression in the real decision logic fails these
    tests.
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
        action = _classify_edit_failure(result)
        if action == "retryable":
            continue
        if action == "rotate":
            # Rotate: clear msg id, keep can_edit, send new bubble.
            progress_msg_id = None
            rotations += 1
            new = send_results[min(send_i, len(send_results) - 1)]
            send_i += 1
            if new.success and new.message_id:
                progress_msg_id = new.message_id
                edit_after_rotate += 1  # next edit will target the new bubble
            continue
        if action == "flood":
            # Flood control: keep editing, just back off — no standalone bubble.
            continue
        # action == "disable": permanent failure (old behavior)
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
    """230072 on bubble A → rotate → bubble B continues editing."""
    edit_results = [
        SendResult(success=True),                                   # edit on A ok
        SendResult(success=True),                                   # edit on A ok
        SendResult(success=False, error="[230072] edit limit", rotate=True),  # A capped
        SendResult(success=True),                                   # edit on B ok
    ]
    send_results = [SendResult(success=True, message_id="om_bubble_b")]
    state = _simulate_progress_loop_with_rotate(edit_results, send_results)
    assert state["can_edit"] is True, "rotate must NOT disable can_edit"
    assert state["rotations"] == 1
    assert state["progress_msg_id"] == "om_bubble_b", "new bubble id captured"
    assert state["standalone_sends"] == 0, "must not fall through to standalone"


def test_multiple_rotates_chain_through_bubbles():
    """When bubble B also hits the cap, rotate again to bubble C."""
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
    """If retryable=False but rotate=True, the loop rotates; only a bare
    permanent failure (no retryable, no rotate) disables can_edit."""
    edit_results = [
        SendResult(success=False, error="[230072]", rotate=True, retryable=False),
    ]
    send_results = [SendResult(success=True, message_id="om_new")]
    state = _simulate_progress_loop_with_rotate(edit_results, send_results)
    assert state["can_edit"] is True


def test_bare_permanent_failure_still_disables_can_edit():
    """Existing behavior preserved: a non-retryable, non-rotate failure
    (e.g. permissions, message-not-found) still sets can_edit=False."""
    edit_results = [
        SendResult(success=False, error="message to edit not found"),
    ]
    state = _simulate_progress_loop_with_rotate(edit_results, [])
    assert state["can_edit"] is False
    assert state["standalone_sends"] == 1


# ---------------------------------------------------------------------------
# 4. _classify_edit_failure — production decision function (WR-06)
# ---------------------------------------------------------------------------

class TestClassifyEditFailure:
    """Direct unit tests for the extracted decision function in gateway/run.py.

    The progress-loop simulation above delegates to this same function, so the
    rotate/flood/disable decision is now exercised against production code
    rather than a hand-written re-implementation.
    """

    def test_retryable_takes_precedence(self):
        # retryable wins even if rotate is also set.
        r = SendResult(success=False, error="connect timeout", retryable=True, rotate=True)
        assert _classify_edit_failure(r) == "retryable"

    def test_rotate_when_not_retryable(self):
        r = SendResult(success=False, error="[230072] edit limit", rotate=True)
        assert _classify_edit_failure(r) == "rotate"

    def test_flood_from_error_text(self):
        assert _classify_edit_failure(SendResult(success=False, error="flood control")) == "flood"
        assert _classify_edit_failure(SendResult(success=False, error="Please retry after 5s")) == "flood"

    def test_disable_for_bare_permanent_failure(self):
        r = SendResult(success=False, error="message to edit not found")
        assert _classify_edit_failure(r) == "disable"

    def test_disable_when_error_missing(self):
        # No error attribute set / empty → permanent disable, not a crash.
        assert _classify_edit_failure(SendResult(success=False)) == "disable"


