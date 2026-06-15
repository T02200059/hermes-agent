"""DashScope image generation plugin.

Thin registration wrapper; the provider implementation lives in
``owner.image_gen.dashscope_provider`` so the core logic stays in the
``owner/`` namespace per the owner-v16 development guidelines.
"""

from __future__ import annotations

from typing import Any

# [owner] dashscope image-gen: core provider lives in owner/
from owner.image_gen.dashscope_provider import DashScopeImageGenProvider


def register(ctx: Any) -> None:
    """Register the DashScope image generation provider."""
    ctx.register_image_gen_provider(DashScopeImageGenProvider())
