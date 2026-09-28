"""[owner T2-9] Egress hardening for ``hermes.tool.progress`` (S2-3).

The progress channel carries the whole tool argument set (up to
``_TOOL_ARGS_MAX_CHARS``) and a result preview (up to ``_TOOL_OUTPUT_MAX``).
Before this item the only masking was ``redact_tool_args_for_display`` —
which handles ``browser_type`` and nothing else — and the result preview was
pure truncation, so command text, file bodies and stdout reached the wire
verbatim. Isolation depended on an unstated property of the code: the queue
is created per request.

Two things are pinned here:

  * **Redaction at the boundary** — args and output are run through the log
    redactor with ``force=True`` before they are clipped, and a redactor that
    cannot be loaded suppresses the free text instead of emitting it raw.
  * **The isolation assertion** — every tool frame is stamped with the owning
    request's token, and a frame bound to a different token is written in its
    stripped name+status form. The mismatch case is exercised end-to-end by
    binding frames to a foreign token, so the guard is proven to bite rather
    than asserted structurally.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import pytest
from aiohttp.test_utils import TestClient, TestServer

from gateway.platforms import api_server
from gateway.platforms.api_server import (
    _bind_tool_frame,
    _clip_tool_args_for_sse,
    _clip_tool_output_for_sse,
    _redact_for_sse,
    _stripped_tool_frame,
    _tool_frame_is_ours,
)
from tests.gateway.test_api_server import _create_app, _make_adapter

# A recognizable credential-shaped value: the redactor masks ``ghp_…`` tokens.
SECRET = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"
SECRET_CMD = f"export TOKEN={SECRET}"


# ---------------------------------------------------------------------------
# Redaction at the boundary
# ---------------------------------------------------------------------------


class TestRedactionAtTheBoundary:

    def test_recognizable_secret_is_masked(self):
        out = _redact_for_sse(SECRET_CMD)
        assert SECRET not in out
        assert "***" in out

    def test_bearer_credential_in_a_command_is_masked(self):
        arg = "curl -H 'Authorization: Bearer sk-abcdefghijklmnopqrstuvwxyz0123456789' x"
        out = _clip_tool_args_for_sse({"command": arg})
        assert "sk-abcdefghijklmnopqrstuvwxyz0123456789" not in json.dumps(out)

    def test_args_redaction_covers_the_slim_fallback_too(self):
        """The >6000-char path rebuilds args from primary keys — still masked."""
        args = {
            "command": SECRET_CMD,
            "filler_a": "x" * 2500,
            "filler_b": "y" * 2500,
            "filler_c": "z" * 2500,
        }
        out = _clip_tool_args_for_sse(args)
        assert set(out) == {"command"}
        assert SECRET not in json.dumps(out)

    def test_redaction_precedes_the_per_value_cut(self):
        """Ordering is load-bearing, but only for the fragment case.

        When the per-value cut lands *inside* a credential, clip-then-redact
        leaves ``…ghp_abc`` — a fragment too short for the pattern set to
        recognize afterwards, so the dict-level backstop cannot recover it.
        Redact-then-clip needs no such recovery. (The full secret is absent
        either way; this test exists to pin the ordering, and it is the only
        property that makes the per-value redaction non-redundant.)
        """
        value = "a" * (api_server._TOOL_ARG_VALUE_MAX - 10) + " " + SECRET
        out = json.dumps(_clip_tool_args_for_sse({"command": value}))
        assert SECRET not in out
        assert "ghp_abc" not in out

    def test_output_redaction_happens_before_truncation(self):
        """A secret straddling the cut must not survive as a half-written key.

        The naive order (clip, then redact) leaks the head of any credential
        that starts just before ``_TOOL_OUTPUT_MAX``.
        """
        pad = "a" * (api_server._TOOL_OUTPUT_MAX - 10)
        out = _clip_tool_output_for_sse(pad + SECRET + "trailing")
        assert SECRET not in out
        assert len(out) <= api_server._TOOL_OUTPUT_MAX

    def test_output_dict_preview_is_masked(self):
        out = _clip_tool_output_for_sse({"stdout": SECRET_CMD})
        assert SECRET not in out

    def test_unavailable_redactor_suppresses_rather_than_leaks(self, monkeypatch):
        """Fail closed: "could not verify" must not mean "emitted raw"."""
        monkeypatch.setattr(
            "agent.redact.redact_sensitive_text",
            lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("no redactor")),
        )
        monkeypatch.setattr(api_server, "_sse_redaction_failed", False)
        assert _redact_for_sse(SECRET_CMD) == api_server._SSE_REDACT_PLACEHOLDER
        # Same suppression through both public clip helpers.
        assert SECRET not in json.dumps(_clip_tool_args_for_sse({"command": SECRET_CMD}))
        assert SECRET not in _clip_tool_output_for_sse({"stdout": SECRET_CMD})

    def test_redactor_failure_is_reported_once(self, monkeypatch, caplog):
        monkeypatch.setattr(
            "agent.redact.redact_sensitive_text",
            lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("no redactor")),
        )
        monkeypatch.setattr(api_server, "_sse_redaction_failed", False)
        with caplog.at_level("ERROR"):
            for _ in range(3):
                _redact_for_sse("anything")
        hits = [r for r in caplog.records if "redaction unavailable" in r.getMessage()]
        assert len(hits) == 1


# ---------------------------------------------------------------------------
# Frame binding
# ---------------------------------------------------------------------------


class TestFrameBinding:

    def test_bound_frame_carries_the_token_out_of_band(self):
        frame = _bind_tool_frame("__tool_progress__", {"tool": "terminal"}, "tok")
        assert frame == ("__tool_progress__", "tok", {"tool": "terminal"})
        # The payload itself is untouched — the token must not reach the wire.
        assert "sseFrameToken" not in frame[2]
        assert frame[2] == {"tool": "terminal"}

    def test_matching_token_is_ours(self):
        assert _tool_frame_is_ours(("t", "tok", {}), "tok") is True

    def test_foreign_token_is_not_ours(self):
        assert _tool_frame_is_ours(("t", "other", {}), "tok") is False

    def test_unbound_two_tuple_is_not_ours(self):
        """A producer that predates the binding is treated as untrusted."""
        assert _tool_frame_is_ours(("t", {}), "tok") is False

    def test_empty_expected_token_never_matches(self):
        assert _tool_frame_is_ours(("t", "", {}), "") is False

    def test_stripped_frame_keeps_only_identity_and_status(self):
        stripped = _stripped_tool_frame(
            {
                "tool": "terminal",
                "toolCallId": "call-1",
                "status": "running",
                "args": {"command": SECRET_CMD},
                "output": SECRET,
                "emoji": "x",
            }
        )
        assert stripped == {
            "tool": "terminal",
            "toolCallId": "call-1",
            "status": "running",
        }


# ---------------------------------------------------------------------------
# End to end through the chat-completions SSE stream
# ---------------------------------------------------------------------------


def _mock_run_agent_emitting_a_secret():
    async def _mock_run_agent(**kwargs):
        ts_cb = kwargs.get("tool_start_callback")
        tc_cb = kwargs.get("tool_complete_callback")
        cb = kwargs.get("stream_delta_callback")
        if ts_cb:
            ts_cb("call_terminal_1", "terminal", {"command": SECRET_CMD})
        if tc_cb:
            tc_cb("call_terminal_1", "terminal", {"command": SECRET_CMD}, f"ok {SECRET}")
        if cb:
            await asyncio.sleep(0.05)
            cb("done.")
        return (
            {"final_response": "done.", "messages": [], "api_calls": 1},
            {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
        )

    return _mock_run_agent


def _progress_payloads(body: str) -> list[dict]:
    payloads: list[dict] = []
    lines = body.splitlines()
    for i, line in enumerate(lines):
        if line.strip() != "event: hermes.tool.progress":
            continue
        for follow in lines[i + 1 : i + 4]:
            if follow.startswith("data: "):
                try:
                    payloads.append(json.loads(follow[len("data: ") :]))
                except json.JSONDecodeError:
                    pass
                break
    return payloads


@pytest.mark.asyncio
async def test_stream_masks_the_secret_in_args_and_output():
    """The bound (normal) path still delivers the payload — minus the secret."""
    adapter = _make_adapter()
    app = _create_app(adapter)
    async with TestClient(TestServer(app)) as cli:
        with patch.object(
            adapter, "_run_agent", side_effect=_mock_run_agent_emitting_a_secret()
        ):
            resp = await cli.post(
                "/v1/chat/completions",
                json={
                    "model": "test",
                    "messages": [{"role": "user", "content": "go"}],
                    "stream": True,
                },
            )
            assert resp.status == 200
            body = await resp.text()

    assert SECRET not in body
    payloads = _progress_payloads(body)
    assert payloads, "expected hermes.tool.progress events"
    running = [p for p in payloads if p.get("status") == "running"]
    completed = [p for p in payloads if p.get("status") == "completed"]
    assert running and completed
    # Shape preserved: the frontend contract must not change.
    assert running[0]["tool"] == "terminal"
    assert running[0]["toolCallId"] == "call_terminal_1"
    assert running[0]["args"]["command"].startswith("export TOKEN=")
    assert completed[0]["output"].startswith("ok ")


@pytest.mark.asyncio
async def test_stream_degrades_a_foreignly_bound_frame():
    """A frame not bound to this request loses args and output on the wire.

    Bound ``_bind_tool_frame`` to a fixed foreign token: the emitting handler
    and the writer then disagree, which is exactly the shape a future
    cross-request fan-out would produce. The event must still arrive (clients
    keep their lifecycle UI) but must no longer carry the rich payload.
    """
    adapter = _make_adapter()
    app = _create_app(adapter)
    real_bind = api_server._bind_tool_frame

    def _bind_foreignly(tag, payload, _token):
        return real_bind(tag, payload, "not-this-streams-token")

    async with TestClient(TestServer(app)) as cli:
        with patch.object(
            adapter, "_run_agent", side_effect=_mock_run_agent_emitting_a_secret()
        ), patch.object(api_server, "_bind_tool_frame", _bind_foreignly):
            resp = await cli.post(
                "/v1/chat/completions",
                json={
                    "model": "test",
                    "messages": [{"role": "user", "content": "go"}],
                    "stream": True,
                },
            )
            assert resp.status == 200
            body = await resp.text()

    assert SECRET not in body
    payloads = _progress_payloads(body)
    assert payloads, "an unbound frame must degrade, never disappear"
    assert all("args" not in p for p in payloads)
    assert all("output" not in p for p in payloads)
    running = [p for p in payloads if p.get("status") == "running"]
    assert running and running[0]["tool"] == "terminal"
    assert running[0]["toolCallId"] == "call_terminal_1"


@pytest.mark.asyncio
async def test_responses_stream_masks_arguments_and_result():
    """The Responses channel echoes tool args/results by spec — and now masks.

    This channel has no length budget of its own, so the rule applied here is
    redaction-only: shapes and field names are preserved (a client parsing
    ``function_call.arguments`` still gets valid JSON), the credential does
    not ride along.
    """
    adapter = _make_adapter()
    app = _create_app(adapter)
    async with TestClient(TestServer(app)) as cli:
        with patch.object(
            adapter, "_run_agent", side_effect=_mock_run_agent_emitting_a_secret()
        ):
            resp = await cli.post(
                "/v1/responses",
                json={"model": "hermes-agent", "input": "go", "stream": True},
            )
            assert resp.status == 200
            body = await resp.text()

    assert SECRET not in body
    assert "function_call" in body
    assert "call_terminal_1" in body


@pytest.mark.asyncio
async def test_nested_secret_one_level_down_is_also_masked():
    """A credential nested inside an arg object must not ride along untouched."""
    adapter = _make_adapter()
    app = _create_app(adapter)

    async def _mock_run_agent(**kwargs):
        ts_cb = kwargs.get("tool_start_callback")
        if ts_cb:
            ts_cb("call_1", "terminal", {"env": {"TOKEN": SECRET}, "args": [SECRET]})
        cb = kwargs.get("stream_delta_callback")
        if cb:
            await asyncio.sleep(0.05)
            cb("done.")
        return (
            {"final_response": "done.", "messages": [], "api_calls": 1},
            {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
        )

    async with TestClient(TestServer(app)) as cli:
        with patch.object(adapter, "_run_agent", side_effect=_mock_run_agent):
            resp = await cli.post(
                "/v1/chat/completions",
                json={
                    "model": "test",
                    "messages": [{"role": "user", "content": "go"}],
                    "stream": True,
                },
            )
            assert resp.status == 200
            body = await resp.text()

    assert SECRET not in body
