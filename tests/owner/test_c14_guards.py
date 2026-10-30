"""C14 — output_guard + stream_guard (offline; no network)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from owner.output_guard import (
    _on_transform_llm_output,
    analyze,
    register_hooks as register_output_guard,
)
from owner.stream_guard import (
    evaluate_window,
    observe,
    register_hooks as register_stream_guard,
    reset_state,
    snapshot,
)


# ── output_guard ─────────────────────────────────────────────────────────────


def test_output_guard_repeat_folds():
    text = ("要推 origin + gitlab 吗？需要就说一声。确认就推。默认不推 upstream。\n\n" * 100)
    assert analyze(text)["verdict"] == "repeat"
    out = _on_transform_llm_output(text, session_id="t", model="m", platform="cli")
    assert out is not None
    assert "[output-guard]" in out
    assert len(out) < len(text) / 5


def test_output_guard_short_ok():
    assert analyze("短回复正常。")["verdict"] == "ok"
    assert _on_transform_llm_output("短回复正常。") is None


def test_output_guard_mojibake():
    text = "正常前缀\n\n" + ("\ufffd" * 50) + "\n\n尾巴"
    assert analyze(text)["verdict"] == "mojibake"
    out = _on_transform_llm_output(text, model="m")
    assert out is not None and "[output-guard]" in out


def test_output_guard_reasoning_only_note(monkeypatch):
    # Healthy short body + long degenerate reasoning → keep body, append note
    body = "正文正常回答。"
    reasoning = ("END OF THINKING\n" * 500) + ("要推吗？确认就推。\n\n" * 400)
    assert analyze(body)["verdict"] == "ok"
    out = _on_transform_llm_output(
        body, reasoning_text=reasoning, session_id="t", model="m", interrupted=False,
    )
    assert out is not None
    assert out.startswith(body)
    assert "思考通道" in out


def test_output_guard_enabled_false(monkeypatch):
    monkeypatch.setattr(
        "owner.patch_config.load_patch_config",
        lambda: {"output_guard": {"enabled": False}},
    )
    text = ("要推 origin + gitlab 吗？需要就说一声。确认就推。默认不推 upstream。\n\n" * 100)
    assert _on_transform_llm_output(text, model="m") is None


def test_output_guard_interrupted_still_folds():
    text = ("要推 origin + gitlab 吗？需要就说一声。确认就推。默认不推 upstream。\n\n" * 100)
    out = _on_transform_llm_output(text, interrupted=True, model="m")
    assert out is not None and "[output-guard]" in out


def test_output_guard_register_hooks():
    ctx = MagicMock()
    register_output_guard(ctx)
    ctx.register_hook.assert_called_once()
    assert ctx.register_hook.call_args[0][0] == "transform_llm_output"


# ── stream_guard signals ─────────────────────────────────────────────────────


def _cfg(**over):
    from owner.stream_guard import DEFAULTS
    c = dict(DEFAULTS)
    c["signature_tokens"] = tuple(c.get("signature_tokens") or ("ฅ",))
    c.update(over)
    return c


def test_stream_guard_s1_s2_boundary_loop():
    # Dense markers + signature tokens → vote trip
    chunk = "END OF THINKING\nWRITING RESPONSE\nฅ now outputting ฅ\n思考结束\n"
    buf = chunk * 80  # well over 4KB window worth of density
    sig = evaluate_window(buf[-4096:], _cfg())
    assert sig["trip"] is True
    assert sig["votes"] >= 2
    assert sig["s1_marker_rate"] >= 3.0


def test_stream_guard_s3_solo_pure_repeat():
    unit = "abcdefghijklmnopqrstuvwxyz012345 "
    buf = unit * 200  # pure repeat dominated
    sig = evaluate_window(buf, _cfg(s3_solo=True))
    assert sig["s3_no_progress"] == 1
    assert sig["trip"] is True
    assert sig["s3_solo_trip"] is True


def test_stream_guard_clean_long_text_no_trip():
    # Varied paragraphs, no markers, no signature flood
    paras = [f"段落{i}：今天讨论了 hermes 的 stream_guard 设计与标定结果。\n" for i in range(200)]
    buf = "".join(paras)
    sig = evaluate_window(buf[-4096:], _cfg())
    assert sig["trip"] is False


def test_stream_guard_observe_interrupt(monkeypatch):
    reset_state()
    stops = []

    class Agent:
        def __init__(self):
            self._interrupt_requested = False
            self._current_turn_id = "turn-1"
            self.warnings = []

        def _request_stream_stop(self, reason="", turn_id=""):
            self._interrupt_requested = True
            stops.append((reason, turn_id))
            return True

        def _emit_warning(self, message):
            self.warnings.append(message)

    agent = Agent()
    # Force interrupt action + tiny grace/min so one big feed trips
    monkeypatch.setattr(
        "owner.stream_guard.config",
        lambda: _cfg(
            action="interrupt",
            grace_seconds=0,
            min_stream_chars=100,
            eval_interval_chars=50,
            window_chars=4096,
        ),
    )
    chunk = "END OF THINKING\nWRITING RESPONSE\nฅ (stop)\n思考结束\n"
    blob = chunk * 100
    # Feed in steps so evaluated_at advances
    step = 200
    for i in range(0, len(blob), step):
        observe(
            blob[i : i + step],
            kind="text",
            session_id="s1",
            turn_id="turn-1",
            iteration=1,
            model="m",
            request_stop=agent._request_stream_stop,
        )
    assert stops, "request_stop should have been called"
    assert agent._interrupt_requested is True
    snap = snapshot(session_id="s1", turn_id="turn-1")
    assert snap["tripped"] is True
    reset_state()


def test_stream_guard_warn_only_no_stop(monkeypatch):
    reset_state()
    called = []

    def stop(**kw):
        called.append(kw)
        return True

    monkeypatch.setattr(
        "owner.stream_guard.config",
        lambda: _cfg(
            action="warn_only",
            grace_seconds=0,
            min_stream_chars=100,
            eval_interval_chars=50,
        ),
    )
    chunk = "END OF THINKING\nWRITING RESPONSE\nฅ (stop)\n"
    blob = chunk * 100
    for i in range(0, len(blob), 200):
        observe(
            blob[i : i + 200],
            kind="text",
            session_id="s2",
            turn_id="t2",
            iteration=0,
            model="m",
            request_stop=stop,
        )
    assert called == []  # warn_only must not call request_stop
    assert snapshot(session_id="s2", turn_id="t2")["tripped"] is True
    reset_state()


def test_stream_guard_register_hooks():
    ctx = MagicMock()
    register_stream_guard(ctx)
    ctx.register_hook.assert_called_once()
    assert ctx.register_hook.call_args[0][0] == "on_stream_delta"


def test_request_stop_mixin_latch():
    from agent.stream_delivery import StreamDeliveryMixin

    class Agent(StreamDeliveryMixin):
        def __init__(self):
            self._interrupt_requested = False
            self._current_turn_id = "t"
            self.log_prefix = ""
            self._stream_needs_break = False
            self.session_id = "s"
            self.model = "m"
            self.provider = "p"
            self.platform = "cli"
            self._api_call_count = 1
            self._vprint = lambda *a, **k: None

    a = Agent()
    payload = a._stream_hook_base_payload()
    assert callable(payload["request_stop"])
    assert a._request_stream_stop(reason="test", turn_id="t") is True
    assert a._interrupt_requested is True
    assert a._stream_stop_requested is True
    # Wrong turn rejected
    a._current_turn_id = "other"
    a._stream_stop_requested = False
    a._interrupt_requested = False
    assert a._request_stream_stop(reason="x", turn_id="t") is False


def test_stream_guard_defaults_action_interrupt():
    """H03: code DEFAULTS must match overlay full default (interrupt), not warn_only."""
    from owner.stream_guard import DEFAULTS
    assert DEFAULTS["action"] == "interrupt"

