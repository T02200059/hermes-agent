"""Damodel (genai.damodel.com) provider profile.

The damodel NewAPI proxy routes to multiple upstream models (MiMo, GLM,
DeepSeek, Qwen, MiniMax, etc.) through a single endpoint.  MiMo traffic is
homologous with the official Xiaomi endpoint — same ``thinking.type`` wire
format — so the mimo branch reuses ``providers.mimo_thinking``.

Model-specific handling
-----------------------
* MiMo chat (mimo-v2.5 / mimo-v2.5-pro, …):
  Emit official ``extra_body.thinking.type`` = enabled|disabled, and clamp
  optional ``reasoning_effort`` to low/medium/high (relays may accept it;
  the official server's main knob is thinking.type).
* Everything else (GLM / DeepSeek / Qwen / MiniMax / Doubao / Kimi):
  Do NOT emit MiMo thinking fields or ``reasoning_effort`` from this profile
  — let each upstream default apply, or owner patch.yaml for model-specific
  extras (e.g. GLM clear_thinking).
"""

from __future__ import annotations

from typing import Any

from providers import register_provider
from providers.base import ProviderProfile
from providers.mimo_thinking import build_mimo_thinking_extras, is_mimo_thinking_model


class DamodelProfile(ProviderProfile):
    """Damodel NewAPI proxy — MiMo thinking wire shared with official Xiaomi."""

    def build_api_kwargs_extras(
        self,
        *,
        reasoning_config: dict | None = None,
        model: str | None = None,
        **context: Any,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if not is_mimo_thinking_model(model):
            # Non-MiMo upstreams: leave wire format alone.
            return {}, {}

        return build_mimo_thinking_extras(
            reasoning_config=reasoning_config,
            model=model,
        )


damodel = DamodelProfile(
    name="damodel",
    aliases=(),
    env_vars=("DAMODEL_API_KEY",),
    base_url="https://genai.damodel.com/v1",
    supports_health_check=True,
    # The damodel proxy fronts multimodel models (mimo-v2.5, qwen-vl-*)
    supports_vision=True,
    # MiMo rejects list-type tool content (400 "text is not set")
    supports_vision_tool_messages=False,
)

register_provider(damodel)
