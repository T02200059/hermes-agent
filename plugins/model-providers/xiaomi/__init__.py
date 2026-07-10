"""Xiaomi MiMo provider profile.

Official OpenAI-compatible endpoint. Deep thinking is controlled by
``extra_body.thinking.type`` (see ``providers.mimo_thinking``); multi-turn
tool calls must echo ``reasoning_content`` (agent runtime).
"""

from __future__ import annotations

from typing import Any

from providers import register_provider
from providers.base import ProviderProfile
from providers.mimo_thinking import build_mimo_thinking_extras


class XiaomiProfile(ProviderProfile):
    """Xiaomi MiMo — explicit thinking on/off + optional effort clamp."""

    def build_api_kwargs_extras(
        self,
        *,
        reasoning_config: dict | None = None,
        model: str | None = None,
        **context: Any,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return build_mimo_thinking_extras(
            reasoning_config=reasoning_config,
            model=model,
        )


xiaomi = XiaomiProfile(
    name="xiaomi",
    aliases=("mimo", "xiaomi-mimo"),
    env_vars=("XIAOMI_API_KEY",),
    base_url="https://api.xiaomimimo.com/v1",
    supports_health_check=False,  # /v1/models returns 401 even with valid key
    supports_vision=True,  # mimo-v2.5 is vision-capable (omni-modal)
    supports_vision_tool_messages=False,  # rejects list-type tool content (400 "text is not set")
)

register_provider(xiaomi)
