"""Overlay presets and optional ``image_generate`` parameters for Image Hub."""

from __future__ import annotations

from typing import Any, Iterable


def tool_parameter_overrides(aliases: Iterable[str] = ()) -> dict[str, dict[str, Any]]:
    """Expose the preset alias previously lost in the dynamic-schema rebuild.

    An arbitrary model id remains supported: this is intentionally not an enum.
    The choices come from overlay, so changing presets needs no second list.
    """
    choices = ", ".join(sorted({str(alias) for alias in aliases if alias}))
    detail = (f" Available preset names/aliases: {choices}." if choices
              else " See overlay.yaml image_gen.presets for configured aliases.")
    return {
        "model": {
            "type": "string",
            "description": (
                "Optional model id or Image Hub preset name/alias. A preset "
                "alias switches preset; any other value overrides the active "
                "preset's model id." + detail
            ),
        },
    }


def dispatch_model(provider: Any, requested: Any, configured: Any) -> Any:
    """Pass a call-level model only to providers that advertise ``model``."""
    if isinstance(requested, str) and requested.strip():
        if "model" in getattr(provider, "tool_parameter_overrides", dict)():
            return requested.strip()
    return configured
