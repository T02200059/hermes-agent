"""Kimi/Moonshot ``thinking`` contract on the Anthropic Messages-compatible wire.

Contract source (retrieved 2026-10-21, platform.kimi.com):

* ``guide/use-thinking-models`` — the per-model parameter table and the
  tool-calling requirements (``max_tokens>=16000``, stream, and "无需设置
  ``temperature``…请勿显式传入").
* ``guide/claude-code-kimi`` — the Anthropic-compatible endpoint
  (``https://api.moonshot.ai/anthropic``) behaviour table, and its verbatim
  rejection: ``400 invalid thinking: only type=enabled is allowed for this
  model``.
* ``api/messages`` — the request body field list (``output_config``: "reasoning
  effort and structured output") and the response shape, whose reasoning is
  ``{type: "thinking", thinking, signature}`` content blocks.

Documented per-model behaviour on this endpoint:

    kimi-k3                        on by default, CAN be turned off
    kimi-k2.7-code (+ -highspeed)  forced on, CANNOT be turned off
    kimi-k2.6                      optional

Two facts these tests pin, both of which an "Anthropic-shaped" implementation
gets wrong:

1. ``thinking.type`` is a **binary** ``enabled``/``disabled`` switch. Anthropic's
   ``adaptive`` type and its ``display`` field are not part of Kimi's vocabulary.
2. For the forced-on family, **omission is also a 400** — so the parameter must
   be sent unconditionally, including when the caller supplied no
   ``reasoning_config`` and when the user asked for thinking off.

Reasoning strength is ``output_config.effort``, documented for **k3 only**
(``low``/``high``/``max``, server default ``max``); the parameter table marks it
不支持 for k2.7-code and k2.6.
"""

from __future__ import annotations

import pytest

# Endpoints that speak the Anthropic Messages shape for Kimi models.
ANTHROPIC_COMPAT_URLS = (
    "https://api.kimi.com/coding",
    "https://api.kimi.com/coding/v1",
    "https://api.kimi.com/coding/anthropic",
    "https://api.kimi.com/v1",
    "https://api.moonshot.ai/anthropic",
    "https://api.moonshot.cn/anthropic",
    "https://api.moonshot.cn/anthropic/v1",
    # Custom / proxied hosts carrying a Kimi-family model id (#17057).
    "http://my-kimi-proxy.internal",
    "https://llm.example.com/anthropic",
)

ALWAYS_THINKING_MODELS = ("kimi-k2.7-code", "kimi-k2.7-code-highspeed", "moonshotai/kimi-k2.7-code")
TOGGLEABLE_MODELS = ("kimi-k3", "kimi-k3[1m]", "k3", "kimi-k2.6", "kimi-k2.5", "kimi-0714-preview", "moonshot-v1-32k")


def _build(model: str, base_url: str | None, reasoning_config=None) -> dict:
    from agent.anthropic_adapter import build_anthropic_kwargs

    return build_anthropic_kwargs(
        model=model,
        messages=[{"role": "user", "content": "hello"}],
        tools=None,
        max_tokens=4096,
        reasoning_config=reasoning_config,
        base_url=base_url,
    )


class TestForcedOnFamilyAlwaysSendsEnabled:
    """``kimi-k2.7-code``: thinking forced on — omission and ``disabled`` are both 400s."""

    @pytest.mark.parametrize("model", ALWAYS_THINKING_MODELS)
    @pytest.mark.parametrize("base_url", ANTHROPIC_COMPAT_URLS[:3])
    def test_sends_enabled_regardless_of_caller_config(self, model: str, base_url: str) -> None:
        for cfg in (None, {}, {"enabled": True}, {"enabled": True, "effort": "high"}):
            kwargs = _build(model, base_url, cfg)
            assert kwargs["thinking"] == {"type": "enabled"}, (model, base_url, cfg)

    @pytest.mark.parametrize("model", ALWAYS_THINKING_MODELS)
    def test_thinking_off_request_is_not_honoured(self, model: str) -> None:
        """A user asking for thinking off must not brick every turn.

        The endpoint answers ``disabled`` with ``400 invalid thinking: only
        type=enabled is allowed for this model``, so the forced-on family keeps
        ``enabled`` and the request is silently not honoured — a live model
        beats a dead turn.
        """
        kwargs = _build(model, "https://api.moonshot.ai/anthropic", {"enabled": False})
        assert kwargs["thinking"] == {"type": "enabled"}

    @pytest.mark.parametrize("model", ALWAYS_THINKING_MODELS)
    def test_no_effort_knob(self, model: str) -> None:
        """``reasoning_effort`` / ``output_config.effort`` is 不支持 for k2.7-code."""
        kwargs = _build(model, "https://api.moonshot.ai/anthropic", {"enabled": True, "effort": "max"})
        assert "output_config" not in kwargs

    @pytest.mark.parametrize("model", ALWAYS_THINKING_MODELS)
    def test_never_anthropic_proprietary_fields(self, model: str) -> None:
        kwargs = _build(model, "https://api.kimi.com/coding", {"enabled": True, "effort": "high"})
        assert kwargs["thinking"].get("type") != "adaptive"
        assert "display" not in kwargs["thinking"]
        assert "budget_tokens" not in kwargs["thinking"]


class TestToggleableFamily:
    """``kimi-k3`` / ``kimi-k2.6``: ``enabled`` by default, explicit ``disabled`` to turn off."""

    @pytest.mark.parametrize("model", TOGGLEABLE_MODELS)
    @pytest.mark.parametrize("base_url", ANTHROPIC_COMPAT_URLS)
    def test_enabled_by_default(self, model: str, base_url: str) -> None:
        kwargs = _build(model, base_url, {"enabled": True})
        assert kwargs["thinking"] == {"type": "enabled"}, (model, base_url)

    @pytest.mark.parametrize("model", TOGGLEABLE_MODELS)
    @pytest.mark.parametrize("base_url", ANTHROPIC_COMPAT_URLS)
    def test_no_config_still_enables(self, model: str, base_url: str) -> None:
        """Server default is thinking-on; state it rather than rely on the default."""
        kwargs = _build(model, base_url, None)
        assert kwargs["thinking"] == {"type": "enabled"}, (model, base_url)

    @pytest.mark.parametrize("model", TOGGLEABLE_MODELS)
    def test_disabled_is_explicit(self, model: str) -> None:
        """Omitting the parameter would leave the server default ON — send the disable."""
        kwargs = _build(model, "https://api.moonshot.cn/anthropic/v1", {"enabled": False})
        assert kwargs["thinking"] == {"type": "disabled"}
        assert "output_config" not in kwargs

    @pytest.mark.parametrize("model", TOGGLEABLE_MODELS)
    def test_sampling_and_budget_params_absent(self, model: str) -> None:
        """``temperature`` 不可修改 (docs: 请勿显式传入); ``budget_tokens`` is Anthropic-only."""
        kwargs = _build(model, "https://api.moonshot.ai/anthropic", {"enabled": True, "effort": "high"})
        assert "temperature" not in kwargs
        assert "top_p" not in kwargs
        assert "top_k" not in kwargs
        assert "budget_tokens" not in str(kwargs.get("thinking"))
        assert kwargs["max_tokens"] == 4096


class TestK3EffortVocabulary:
    """``output_config.effort`` — k3 only, clamped to the documented low/high/max."""

    @pytest.mark.parametrize(
        "hermes_effort,wire_effort",
        [
            ("minimal", "low"),
            ("low", "low"),
            ("medium", "high"),   # documented K3 rounding: high is its positional middle
            ("high", "high"),
            ("xhigh", "max"),     # documented K3 override
            ("max", "max"),
            ("ultra", "max"),
        ],
    )
    def test_k3_effort_is_clamped_to_kimi_vocabulary(self, hermes_effort: str, wire_effort: str) -> None:
        kwargs = _build("kimi-k3", "https://api.moonshot.ai/anthropic",
                        {"enabled": True, "effort": hermes_effort})
        assert kwargs["thinking"] == {"type": "enabled"}
        assert kwargs["output_config"] == {"effort": wire_effort}

    @pytest.mark.parametrize("model", ["kimi-k3", "kimi-k3[1m]", "k3"])
    def test_k3_without_explicit_effort_uses_server_default(self, model: str) -> None:
        """Docs: k3's ``reasoning_effort`` defaults to ``max`` — don't pin it."""
        kwargs = _build(model, "https://api.moonshot.ai/anthropic", {"enabled": True})
        assert "output_config" not in kwargs

    @pytest.mark.parametrize("model", ["kimi-k2.6", "kimi-k2.5", "kimi-0714-preview", "moonshot-v1-32k"])
    def test_pre_k3_models_get_no_effort(self, model: str) -> None:
        """``reasoning_effort`` is k3-only; K2-era models must not receive output_config."""
        kwargs = _build(model, "https://api.moonshot.cn/anthropic/v1", {"enabled": True, "effort": "high"})
        assert kwargs["thinking"] == {"type": "enabled"}
        assert "output_config" not in kwargs


class TestNonKimiRoutesUnaffected:
    """The Kimi branch must not leak into other Anthropic-compatible providers."""

    def test_minimax_keeps_manual_thinking(self) -> None:
        kwargs = _build("MiniMax-M2.7", "https://api.minimax.io/anthropic",
                        {"enabled": True, "effort": "medium"})
        assert "thinking" in kwargs
        assert kwargs["thinking"]["type"] == "enabled"

    def test_custom_endpoint_non_kimi_model_keeps_thinking(self) -> None:
        """Guards against over-broad model-family matching."""
        kwargs = _build("MiniMax-M2.7", "https://my-llm-proxy.example.com/anthropic",
                        {"enabled": True, "effort": "medium"})
        assert kwargs["thinking"]["type"] == "enabled"

    @pytest.mark.parametrize("model", ["claude-sonnet-4-6", "claude-opus-4-7"])
    def test_native_anthropic_still_adaptive(self, model: str) -> None:
        """Claude 4.6+ keeps Anthropic's own adaptive contract — untouched by the Kimi branch."""
        kwargs = _build(model, None, {"enabled": True, "effort": "medium"})
        assert kwargs["thinking"]["type"] == "adaptive"
        assert kwargs["thinking"]["display"] == "summarized"
        assert kwargs["output_config"]["effort"] == "medium"

    @pytest.mark.parametrize("model", ["claude-sonnet-4-6", "claude-opus-4-7"])
    def test_native_anthropic_disable_still_explicit(self, model: str) -> None:
        kwargs = _build(model, None, {"enabled": False})
        assert kwargs["thinking"] == {"type": "disabled"}

    def test_legacy_manual_thinking_claude_keeps_budget_tokens(self) -> None:
        """Pre-4.6 Claude keeps manual budget-based thinking (and its temperature=1 pairing)."""
        kwargs = _build("claude-sonnet-4-20250514", None, {"enabled": True, "effort": "medium"})
        assert kwargs["thinking"]["type"] == "enabled"
        assert kwargs["thinking"]["budget_tokens"] > 0
        assert kwargs["temperature"] == 1

    def test_kimi_family_detection_does_not_capture_claude(self) -> None:
        from agent.anthropic_endpoints import _model_name_is_kimi_family

        assert _model_name_is_kimi_family("claude-sonnet-4-20250514") is False
        assert _model_name_is_kimi_family("kimi-k2.7-code") is True


class TestReplayPreservesReasoning:
    """Preserved thinking: history must carry the reasoning back verbatim.

    The Messages endpoint returns reasoning as ``{type: "thinking", thinking,
    signature}`` content blocks; on a third-party Kimi proxy the block arrives
    unsigned (synthesised from ``reasoning_content``) and must survive the
    signature-stripping pass, or the upstream's history validation rejects the
    request.  Docs: "必须把 API 返回的完整 assistant message 原样回传到
    ``messages``（包括 ``reasoning_content``）"; for k2.7-code preserved
    thinking is always on, so this is mandatory rather than optional.
    """

    def test_unsigned_thinking_survives_third_party_stripping(self) -> None:
        from agent.anthropic_adapter import convert_messages_to_anthropic

        messages = [
            {"role": "user", "content": "hi"},
            {
                "role": "assistant",
                "reasoning_content": "planning the tool call",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "skill_view", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "ok"},
        ]
        _, converted = convert_messages_to_anthropic(
            messages,
            base_url="http://my-kimi-proxy.internal",
            model="kimi-2.6",
        )
        assistant_msg = next(m for m in converted if m["role"] == "assistant")
        thinking_blocks = [
            b for b in assistant_msg["content"]
            if isinstance(b, dict) and b.get("type") == "thinking"
        ]
        assert len(thinking_blocks) == 1
        assert thinking_blocks[0]["thinking"] == "planning the tool call"
