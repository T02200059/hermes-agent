"""C10 · ``localized(key, en_text, **kw)`` — English source stays in code.

When the active language is English, format and return ``en_text`` without
reading the catalog (so an upstream rewording in code propagates). For any
other language, prefer the catalog entry for ``key``, falling back to
``en_text`` on a total miss (never raise, never show a bare key to the user).

Used by write-guard messages in ``tools/file_tools_write_guards.py``. The
EN constants live next to the call sites (and are mirrored in
:data:`GUARD_EN_TEXTS`) so the drift test can compare code ↔ ``locales/en.yaml``.
"""

from __future__ import annotations

from typing import Any

from agent.i18n import DEFAULT_LANGUAGE, get_language, t

# Populated by tools.file_tools_write_guards on import (single source of
# constants). Drift tests read this table.
GUARD_EN_TEXTS: dict[str, str] = {}


def localized(key: str, en_text: str, **kwargs: Any) -> str:
    """Render with code English as the source of truth for ``en``."""
    if get_language() == DEFAULT_LANGUAGE:
        return en_text.format(**kwargs) if kwargs else en_text
    rendered = t(key, **kwargs)
    if rendered != key:
        return rendered
    return en_text.format(**kwargs) if kwargs else en_text


def register_guard_en_texts(mapping: dict[str, str]) -> None:
    """Replace :data:`GUARD_EN_TEXTS` (called from write_guards module load)."""
    GUARD_EN_TEXTS.clear()
    GUARD_EN_TEXTS.update(mapping)


__all__ = ["GUARD_EN_TEXTS", "localized", "register_guard_en_texts"]
