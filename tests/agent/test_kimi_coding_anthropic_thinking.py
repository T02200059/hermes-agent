"""Kimi / Moonshot thinking behavior on the Anthropic-Messages wire.

Contract:

- Kimi-family endpoints use server-default thinking. Hermes omits an enable
  payload, sends explicit disable only for pre-k2.7 models, and never disables
  the always-thinking k2.7-code family.

- ``convert_messages_to_anthropic`` still preserves unsigned
  reasoning_content-derived thinking blocks on replay for this family, so
  multi-turn tool-call history round-trips.

Kimi on the chat_completions route handles ``thinking`` via ``extra_body``
in ``ChatCompletionsTransport`` (#13503).
"""

from __future__ import annotations

import pytest


class TestKimiCodingAnthropicThinking:
    """Kimi-family thinking on the Anthropic wire (incl. /coding)."""

    @pytest.mark.parametrize(
        "base_url",
        [
            "https://api.kimi.com/coding",
            "https://api.kimi.com/coding/v1",
            "https://api.kimi.com/coding/anthropic",
            "https://api.kimi.com/coding/",
        ],
    )
    def test_kimi_coding_endpoint_omits_thinking(self, base_url: str) -> None:
        from agent.anthropic_adapter import build_anthropic_kwargs

        kwargs = build_anthropic_kwargs(
            model="kimi-k2.5",
            messages=[{"role": "user", "content": "hello"}],
            tools=None,
            max_tokens=4096,
            reasoning_config={"enabled": True, "effort": "medium"},
            base_url=base_url,
        )
        assert "thinking" not in kwargs, (
            "Anthropic thinking must not be sent to Kimi /coding — "
            "endpoint requires reasoning_content on history we don't preserve."
        )
        assert "output_config" not in kwargs

    def test_kimi_coding_with_explicit_disabled_sends_disabled(self) -> None:
        """Builtin thinking is on by default; only explicit disable is wired.

        Pre-k2.7 models (k2.5/k2.6) still accept ``thinking: {type: disabled}``
        when the user sets ``reasoning_effort: none``.
        """
        from agent.anthropic_adapter import build_anthropic_kwargs

        kwargs = build_anthropic_kwargs(
            model="kimi-k2.5",
            messages=[{"role": "user", "content": "hello"}],
            tools=None,
            max_tokens=4096,
            reasoning_config={"enabled": False},
            base_url="https://api.kimi.com/coding",
        )
        assert kwargs.get("thinking") == {"type": "disabled"}
        assert "output_config" not in kwargs

    def test_kimi_k27_code_refuses_thinking_disabled(self) -> None:
        """k2.7-code always-on thinking — never send type=disabled (API 400)."""
        from agent.anthropic_adapter import build_anthropic_kwargs

        for model in ("kimi-k2.7-code", "kimi-k2.7-code-highspeed"):
            kwargs = build_anthropic_kwargs(
                model=model,
                messages=[{"role": "user", "content": "hello"}],
                tools=None,
                max_tokens=4096,
                reasoning_config={"enabled": False},
                base_url="https://api.moonshot.ai/v1",
            )
            assert "thinking" not in kwargs, model
            assert "output_config" not in kwargs

    def test_kimi_for_coding_model_default_omits_thinking_enable(self) -> None:
        """Default/enabled configs must not send Anthropic thinking.enabled."""
        from agent.anthropic_adapter import build_anthropic_kwargs

        for cfg in (None, {"enabled": True, "effort": "high"}):
            kwargs = build_anthropic_kwargs(
                model="kimi-for-coding",
                messages=[{"role": "user", "content": "hello"}],
                tools=None,
                max_tokens=4096,
                reasoning_config=cfg,
                base_url="https://api.kimi.com/coding",
            )
            assert "thinking" not in kwargs
            assert "output_config" not in kwargs

    def test_non_kimi_third_party_still_gets_thinking(self) -> None:
        """MiniMax and other third-party Anthropic endpoints must retain thinking."""
        from agent.anthropic_adapter import build_anthropic_kwargs

        kwargs = build_anthropic_kwargs(
            model="MiniMax-M2.7",
            messages=[{"role": "user", "content": "hello"}],
            tools=None,
            max_tokens=4096,
            reasoning_config={"enabled": True, "effort": "medium"},
            base_url="https://api.minimax.io/anthropic",
        )
        assert "thinking" in kwargs
        assert kwargs["thinking"]["type"] == "enabled"

    def test_native_anthropic_still_gets_thinking(self) -> None:
        from agent.anthropic_adapter import build_anthropic_kwargs

        kwargs = build_anthropic_kwargs(
            model="claude-sonnet-4-20250514",
            messages=[{"role": "user", "content": "hello"}],
            tools=None,
            max_tokens=4096,
            reasoning_config={"enabled": True, "effort": "medium"},
            base_url=None,
        )
        assert "thinking" in kwargs


class TestKimiFamilyUsesServerDefaultThinking:
    """Kimi-family endpoints rely on their server-default thinking mode."""

    @pytest.mark.parametrize(
        "base_url,model",
        [
            # Official Kimi / Moonshot hosts (all URL shapes)
            ("https://api.kimi.com/coding", "kimi-k2.5"),
            ("https://api.kimi.com/coding/v1", "kimi-k2.5"),
            ("https://api.kimi.com/coding/anthropic", "kimi-k2.5"),
            ("https://api.kimi.com/v1", "kimi-k2.5"),
            ("https://api.moonshot.ai/anthropic", "moonshot-v1-32k"),
            ("https://api.moonshot.cn/anthropic", "moonshot-v1-32k"),
            ("https://api.moonshot.cn/anthropic/v1", "kimi-0714-preview"),
            # Custom / proxied hosts with a Kimi-family model (#17057)
            ("http://my-kimi-proxy.internal", "kimi-2.6"),
            ("https://llm.example.com/anthropic", "moonshotai/kimi-k2.5"),
        ],
    )
    def test_kimi_family_endpoint_omits_thinking_enable(
        self, base_url: str, model: str
    ) -> None:
        from agent.anthropic_adapter import build_anthropic_kwargs

        kwargs = build_anthropic_kwargs(
            model=model,
            messages=[{"role": "user", "content": "hello"}],
            tools=None,
            max_tokens=4096,
            reasoning_config={"enabled": True, "effort": "high"},
            base_url=base_url,
        )
        assert "thinking" not in kwargs, (base_url, model, kwargs.get("thinking"))
        assert "output_config" not in kwargs
        assert "temperature" not in kwargs
        assert kwargs["max_tokens"] == 4096

    @pytest.mark.parametrize(
        "hermes_effort,wire_effort",
        [
            ("minimal", "low"),
            ("low", "low"),
            ("medium", "medium"),
            ("high", "high"),
            ("xhigh", "xhigh"),
            ("max", "max"),
            ("ultra", "max"),
        ],
    )
    def test_kimi_effort_does_not_override_server_default(
        self, hermes_effort: str, wire_effort: str
    ) -> None:
        from agent.anthropic_adapter import build_anthropic_kwargs

        kwargs = build_anthropic_kwargs(
            model="kimi-0714-preview",
            messages=[{"role": "user", "content": "hello"}],
            tools=None,
            max_tokens=4096,
            reasoning_config={"enabled": True, "effort": hermes_effort},
            base_url="https://api.moonshot.cn/anthropic/v1",
        )
        assert "thinking" not in kwargs
        assert "output_config" not in kwargs

    def test_kimi_thinking_disabled_is_explicit_for_pre_k27(self) -> None:
        from agent.anthropic_adapter import build_anthropic_kwargs

        kwargs = build_anthropic_kwargs(
            model="kimi-0714-preview",
            messages=[{"role": "user", "content": "hello"}],
            tools=None,
            max_tokens=4096,
            reasoning_config={"enabled": False},
            base_url="https://api.moonshot.cn/anthropic/v1",
        )
        assert kwargs["thinking"] == {"type": "disabled"}
        assert "output_config" not in kwargs

    def test_custom_endpoint_non_kimi_model_keeps_thinking(self) -> None:
        """Custom endpoint with a non-Kimi model must keep thinking intact.

        Guards against over-broad model-family matching — only model names
        starting with a Kimi/Moonshot prefix should route to adaptive.
        """
        from agent.anthropic_adapter import build_anthropic_kwargs

        kwargs = build_anthropic_kwargs(
            model="MiniMax-M2.7",
            messages=[{"role": "user", "content": "hello"}],
            tools=None,
            max_tokens=4096,
            reasoning_config={"enabled": True, "effort": "medium"},
            base_url="https://my-llm-proxy.example.com/anthropic",
        )
        assert "thinking" in kwargs
        assert kwargs["thinking"]["type"] == "enabled"

    def test_kimi_family_replay_preserves_unsigned_thinking(self) -> None:
        """On a custom Kimi endpoint, unsigned reasoning_content thinking
        blocks must survive the third-party signature-stripping pass so
        the upstream's message-history validation passes.
        """
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
        # The assistant message still carries the unsigned thinking block
        # synthesised from reasoning_content (required by Kimi's history
        # validation).  A plain third-party endpoint would have stripped it.
        assistant_msg = next(m for m in converted if m["role"] == "assistant")
        assistant_blocks = assistant_msg["content"]
        thinking_blocks = [
            b for b in assistant_blocks
            if isinstance(b, dict) and b.get("type") == "thinking"
        ]
        assert len(thinking_blocks) == 1
        assert thinking_blocks[0]["thinking"] == "planning the tool call"
