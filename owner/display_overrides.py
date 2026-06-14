"""Per-chat display overrides from patch.yaml.

This module provides the private implementation behind the thin
``# [owner]`` calls in ``gateway/display_config.py``.  Keeping the merge
and per-chat resolution logic here keeps the official resolver as close
to upstream as possible.

Also re-exports invalidate_per_chat_display_cache (wrapper around
owner.patch_config.invalidate_patch_owner_config_cache) for users who need
immediate effect after editing patch.yaml.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


def merge_owner_display_config(display_cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Deep-merge ``owner.display`` from patch.yaml into ``display_cfg``.

    Top-level keys in patch.yaml's ``owner.display`` win over config.yaml's
    ``display`` section.  When both sides have a dict value, the dicts are
    shallow-merged with patch.yaml values taking precedence.

    Fail-open: if patch.yaml cannot be loaded, ``display_cfg`` is returned
    unchanged.
    """
    try:
        from owner.patch_config import _load_patch_owner_config

        patch = _load_patch_owner_config()
        patch_display = patch.get("display")
        if not isinstance(patch_display, dict):
            return display_cfg

        merged = dict(display_cfg)
        for key, value in patch_display.items():
            if (
                key in merged
                and isinstance(merged[key], dict)
                and isinstance(value, dict)
            ):
                merged[key] = {**merged[key], **value}
            else:
                merged[key] = value
        return merged
    except Exception:
        return display_cfg


def resolve_per_chat_override(
    display_cfg: Dict[str, Any],
    platform_key: str,
    chat_id: Optional[str],
    setting: str,
) -> Any:
    """Return a per-chat display override if one is defined.

    Looks up ``display.per_chat.<platform_key>.<chat_id>.<setting>``.
    Returns ``None`` when no override exists so the caller can fall through
    to the normal resolution tiers.
    """
    if not chat_id:
        return None

    per_chat = display_cfg.get("per_chat") or {}
    if not isinstance(per_chat, dict):
        return None

    plat_per_chat = per_chat.get(platform_key)
    if not isinstance(plat_per_chat, dict):
        return None

    chat_overrides = plat_per_chat.get(chat_id)
    if not isinstance(chat_overrides, dict):
        return None

    return chat_overrides.get(setting)


# [owner] expose cache invalidation for patch.yaml owner.display changes.
# Call this (or owner.patch_config.invalidate_patch_owner_config_cache directly)
# after programmatically editing ~/.hermes/patch.yaml if you need the next
# resolve_display_setting to pick up fresh per_chat / owner.display values
# without waiting for mtime change.
from owner.patch_config import invalidate_patch_owner_config_cache as invalidate_per_chat_display_cache

__all__ = [
    "merge_owner_display_config",
    "resolve_per_chat_override",
    "invalidate_per_chat_display_cache",
]
