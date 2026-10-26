"""[owner] C13 — shared coerce / platform helpers for explainers."""

from __future__ import annotations

from typing import Any


def coerce_bool(val: Any, default: bool) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        low = val.strip().lower()
        if low in {"true", "yes", "1", "on"}:
            return True
        if low in {"false", "no", "0", "off"}:
            return False
        return default
    if isinstance(val, int):
        return val != 0
    return default


def coerce_int(val: Any, default: int, minimum: int = 0) -> int:
    try:
        n = int(val)
    except (TypeError, ValueError):
        return default
    return max(minimum, n)


def norm_model_field(val: Any) -> str:
    """provider/model: ``auto`` / empty → '' (call_llm auxiliary auto chain)."""
    s = str(val or "").strip()
    if s.lower() == "auto":
        return ""
    return s


def normalize_platform(platform: Any) -> str:
    """``Platform.FEISHU`` / ``feishu`` / enum → lowercase short name."""
    if platform is None:
        return ""
    if hasattr(platform, "value"):
        platform = getattr(platform, "value", platform)
    p = str(platform or "").strip().lower()
    if "." in p:
        p = p.split(".")[-1]
    return p


def display_language() -> str:
    """``display.language`` short code; default ``zh`` on failure."""
    try:
        from hermes_cli.i18n import get_language

        lang = str(get_language() or "").strip().lower()
        if lang:
            return lang
    except Exception:
        pass
    try:
        from agent.i18n import get_language

        lang = str(get_language() or "").strip().lower()
        if lang:
            return lang
    except Exception:
        pass
    return "zh"


def display_language_is_chinese() -> bool:
    return display_language().startswith("zh")
