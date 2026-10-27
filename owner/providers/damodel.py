"""Damodel (genai.damodel.com) — NewAPI proxy provider profile.

Registered via the bundled ``plugins/model-providers/damodel/`` glue so the
official model-provider discovery path surfaces ``provider=damodel``.
"""

from __future__ import annotations

from providers.base import ProviderProfile

DAMODEL_BASE_URL = "https://genai.damodel.com/v1"

damodel = ProviderProfile(
    name="damodel",
    aliases=(),
    env_vars=("DAMODEL_API_KEY",),
    base_url=DAMODEL_BASE_URL,
    display_name="Damodel",
    description="Damodel NewAPI proxy (genai.damodel.com)",
    supports_health_check=True,
    # Proxy fronts multimodel catalogs (vision-capable upstreams included).
    supports_vision=True,
    # Some upstreams behind the proxy reject list-type tool content.
    supports_vision_tool_messages=False,
)


def is_damodel_route(provider: str | None, base_url: str | None = None) -> bool:
    """True when the active route is damodel (by provider name or genai host).

    Used by the thin ``# [owner]`` branch in
    ``agent.agent_runtime_helpers.anthropic_prompt_cache_policy`` so OpenAI-wire
    Anthropic-style ``cache_control`` markers are injected; without them
    damodel reports 0% cached tokens and re-bills the full prompt every turn.
    """
    provider_lower = (provider or "").strip().lower()
    if provider_lower == "damodel":
        return True
    try:
        from utils import base_url_host_matches

        return base_url_host_matches(base_url or "", "genai.damodel.com")
    except Exception:
        return "genai.damodel.com" in (base_url or "").lower()

