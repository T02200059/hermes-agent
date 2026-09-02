"""Outbound message_id logging in the Feishu adapter.

Every outbound Feishu path — plain text/post, edit, card, image, file, exec
approval, update prompt — funnels through ``_finalize_send_result``. That makes
it the single place that can record the platform-assigned message id for all of
them at once.

Before this logging existed the id was extracted into the ``SendResult`` and
then thrown away everywhere except the card path (which had its own success
log). Text, edits and file sends were therefore delivered with no durable trace
of what was actually sent: the message could not be recalled, edited or reacted
to afterward even though the API had returned an id all along.

These tests drive the choke point directly — no network, no lark client — by
constructing minimal stand-ins for the SDK response object.
"""

import logging

import pytest

from plugins.platforms.feishu.adapter import FeishuAdapter


class _Data:
    """Stand-in for the lark ``response.data`` payload."""

    def __init__(self, message_id="om_TESTMESSAGEID001", chat_id="oc_frombody"):
        self.message_id = message_id
        self.chat_id = chat_id


class _OkResponse:
    code = 0
    msg = "ok"

    def __init__(self, data=None):
        self.data = data if data is not None else _Data()

    def success(self):
        return True


class _ErrorResponse:
    code = 230002
    msg = "bot is not in the chat"
    data = None

    def success(self):
        return False


@pytest.fixture
def log_capture():
    """Capture records emitted by the adapter's logger."""
    records = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    logger = logging.getLogger("plugins.platforms.feishu.adapter")
    handler = _Capture()
    previous_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        yield records
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)


@pytest.fixture
def adapter():
    """Bare instance: bypass ``__init__`` (it builds a lark client)."""
    return FeishuAdapter.__new__(FeishuAdapter)


class TestFinalizeSendResultLogging:
    def test_success_logs_chat_id_and_message_id(self, adapter, log_capture):
        result = adapter._finalize_send_result(
            _OkResponse(), "send failed", chat_id="oc_explicit"
        )

        assert result.success is True
        assert result.message_id == "om_TESTMESSAGEID001"

        joined = "\n".join(log_capture)
        assert "[Feishu] Sent" in joined
        assert "chat_id=oc_explicit" in joined
        assert "message_id=om_TESTMESSAGEID001" in joined

    def test_explicit_chat_id_wins_over_response_body(self, adapter, log_capture):
        adapter._finalize_send_result(
            _OkResponse(), "send failed", chat_id="oc_callerknowsbest"
        )
        assert "chat_id=oc_callerknowsbest" in "\n".join(log_capture)

    def test_chat_id_falls_back_to_the_response_body(self, adapter, log_capture):
        """Call sites that don't thread chat_id through still get a usable log.

        im/v1/messages replies echo chat_id, so the fallback keeps the line
        useful without forcing every caller to be updated.
        """
        adapter._finalize_send_result(_OkResponse(), "send failed")
        assert "chat_id=oc_frombody" in "\n".join(log_capture)

    def test_missing_ids_render_as_none_not_empty(self, adapter, log_capture):
        """A blank id must look like "(none)", never like an id was logged."""
        adapter._finalize_send_result(
            _OkResponse(data=_Data(message_id=None, chat_id=None)),
            "send failed",
        )
        joined = "\n".join(log_capture)
        assert "message_id=(none)" in joined
        assert "chat_id=(none)" in joined

    def test_failure_logs_no_success_line(self, adapter, log_capture):
        """A rejected send must never emit a '[Feishu] Sent' line."""
        result = adapter._finalize_send_result(
            _ErrorResponse(), "send failed", chat_id="oc_explicit"
        )

        assert result.success is False
        assert result.message_id is None
        assert "[Feishu] Sent" not in "\n".join(log_capture)

    @pytest.mark.parametrize(
        "default_message",
        [
            "send failed",
            "update failed",
            "card send failed",
            "image send failed",
            "file send failed",
            "send_exec_approval failed",
            "send_update_prompt failed",
        ],
    )
    def test_every_outbound_path_logs(self, adapter, log_capture, default_message):
        """The choke point is shared by all paths; each must log identically."""
        adapter._finalize_send_result(
            _OkResponse(), default_message, chat_id="oc_any"
        )
        joined = "\n".join(log_capture)
        assert "message_id=om_TESTMESSAGEID001" in joined
