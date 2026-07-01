"""Regression tests for Feishu progress-message edit-limit rotation (§11.9)."""

from __future__ import annotations

import asyncio

import pytest
from types import SimpleNamespace

from gateway.platforms.base import SendResult
from gateway.run import _classify_edit_failure


class TestSendResultRotate:
    """``rotate`` is independent from ``retryable`` and defaults to False."""

    def test_rotate_defaults_to_false(self):
        result = SendResult(success=False, error="boom")
        assert result.rotate is False

    def test_rotate_can_be_set_true(self):
        result = SendResult(success=False, error="limit", rotate=True)
        assert result.rotate is True

    def test_rotate_independent_from_retryable(self):
        result = SendResult(success=False, error="limit", rotate=True, retryable=True)
        assert result.rotate is True
        assert result.retryable is True


class TestClassifyEditFailure:
    """``_classify_edit_failure`` must follow precedence retryable > rotate > flood > disable."""

    def test_retryable_wins_over_rotate(self):
        result = SendResult(success=False, error="[230072] limit", retryable=True, rotate=True)
        assert _classify_edit_failure(result) == "retryable"

    def test_rotate_wins_over_flood(self):
        result = SendResult(success=False, error="flood control", rotate=True)
        assert _classify_edit_failure(result) == "rotate"

    @pytest.mark.parametrize("err", ["flood control", "Flood wait", "Retry after 10"])
    def test_flood_detected(self, err):
        result = SendResult(success=False, error=err)
        assert _classify_edit_failure(result) == "flood"

    def test_disable_for_permanent_failure(self):
        result = SendResult(success=False, error="message not found")
        assert _classify_edit_failure(result) == "disable"


class TestFeishuAdapterEditRotate:
    """Feishu ``edit_message`` sets ``rotate=True`` on edit-limit codes 230072/230075."""

    @pytest.fixture
    def adapter(self):
        from plugins.platforms.feishu.adapter import FeishuAdapter

        adapter = object.__new__(FeishuAdapter)
        adapter._client = SimpleNamespace(
            im=SimpleNamespace(v1=SimpleNamespace(message=SimpleNamespace(update=None)))
        )
        return adapter

    def _run_edit(self, adapter, *, code: str, msg: str = "edit limit"):
        async def _run_blocking(_fn, _req):
            # Lark response objects expose ``success`` as a method.
            return SimpleNamespace(success=lambda: False, code=code, msg=msg)

        adapter._run_blocking = _run_blocking
        return asyncio.get_event_loop().run_until_complete(
            adapter.edit_message("oc_chat", "om_msg", "hello")
        )

    def test_230072_returns_rotate_true(self, adapter):
        result = self._run_edit(adapter, code="230072")
        assert result.success is False
        assert result.rotate is True
        assert "230072" in (result.error or "")

    def test_230075_returns_rotate_true(self, adapter):
        result = self._run_edit(adapter, code="230075")
        assert result.success is False
        assert result.rotate is True
        assert "230075" in (result.error or "")

    def test_other_error_does_not_rotate(self, adapter):
        result = self._run_edit(adapter, code="230011")
        assert result.success is False
        assert result.rotate is False


class TestGatewayRotateSimulation:
    """Gateway failure branch uses production ``_classify_edit_failure`` directly."""

    def test_rotate_result_maps_to_rotate_action(self):
        result = SendResult(success=False, error="[230072] limit", rotate=True)
        assert _classify_edit_failure(result) == "rotate"

    def test_simulated_progress_edit_failure_branch(self):
        """Mirror the decision the gateway progress loop would make for a rotate."""
        failed_edit = SendResult(success=False, error="[230075] edit limit reached", rotate=True)
        action = _classify_edit_failure(failed_edit)
        assert action == "rotate"
        # rotate must keep can_edit semantics (the gateway does this; here we assert
        # the classifier never returns disable for a rotate result).
        assert action != "disable"
