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
