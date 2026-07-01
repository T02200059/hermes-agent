"""
Choice display helpers for gateway adapters.
"""

from typing import Any


def get_choice_display(c: Any) -> str:
    """Return the user-facing label for a choice item.

    Accepts the normalized ``{"display", "key"}`` dict shape produced by
    ``owner.clarify.choice_normalizer`` and returns ``c["display"]``.
    Falls back to ``str(c)`` for legacy callers that still pass strings,
    so the platform layer can be written once and not crash on either
    shape.
    """
    if isinstance(c, dict):
        display = c.get("display")
        if isinstance(display, str) and display:
            return display
    return str(c)


def get_choice_key(c: Any) -> str:
    """Return the stable identifier for a choice item (or empty string).

    For normalized dicts: returns ``c["key"]`` (which may be ``None`` →
    empty string).
    For legacy strings: returns the string itself (so the value sent back
    to the model is the same as the user saw).
    """
    if isinstance(c, dict):
        key = c.get("key")
        if isinstance(key, str):
            return key
        return ""
    return str(c)
