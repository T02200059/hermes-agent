"""Unified, fail-open loader for ``~/.hermes/patch.yaml``.

Centralizes the duplicated ``_load_patch_owner_config()`` logic that used to
live in several owner/ modules. Official code and other owner/ modules can
import helpers here instead of re-implementing YAML loading.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# 1-minute TTL for patch.yaml reloads (in addition to mtime-based invalidation on file change).
# This ensures periodic refresh even if the file mtime does not change (e.g. network mounts,
# external edits, or safety against stale cache in long-running gateway processes).
_PATCH_TTL_SECONDS = 60

# Cache for patch.yaml (owner section).
_cache: Dict[str, Any] = {"path": None, "mtime": None, "data": None, "last_load": 0}

# Cache for patch_feishu_profile.yaml (top-level dict).
_feishu_profile_cache: Dict[str, Any] = {
    "path": None,
    "mtime": None,
    "data": None,
    "last_load": 0,
}


def load_patch_config(force: bool = False) -> Dict[str, Any]:
    """Public wrapper for :func:`_load_patch_owner_config`.

    Official-code callers (e.g. ``tools/approval.py``) should import this
    instead of the private ``_load_patch_owner_config``.
    """
    return _load_patch_owner_config(force=force)


def _load_yaml_file(
    cache: Dict[str, Any],
    filename: str,
    *,
    owner_section: bool = False,
    force: bool = False,
) -> Dict[str, Any]:
    """Generic fail-open YAML loader with mtime + TTL caching.

    Loads ``~/.hermes/<filename>`` and returns either the top-level dict
    (``owner_section=False``) or the ``owner`` subsection
    (``owner_section=True``).
    """
    try:
        from hermes_constants import get_hermes_home

        path = get_hermes_home() / filename
        path_str = str(path)

        if not path.exists():
            cache["path"] = path_str
            cache["mtime"] = None
            cache["data"] = {}
            return {}

        mtime = path.stat().st_mtime
        now = time.time()
        if (
            not force
            and cache.get("path") == path_str
            and cache.get("mtime") == mtime
            and cache.get("data") is not None
            and now - cache.get("last_load", 0) < _PATCH_TTL_SECONDS
        ):
            return cache["data"]

        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            result: Dict[str, Any] = {}
        elif owner_section:
            result = (
                data["owner"]
                if isinstance(data.get("owner"), dict)
                else {}
            )
        else:
            result = data

        cache["path"] = path_str
        cache["mtime"] = mtime
        cache["data"] = result
        cache["last_load"] = time.time()
        return result
    except Exception as exc:
        logger.debug("Failed to load %s: %s", filename, exc)
        return {}


def _load_patch_owner_config(force: bool = False) -> Dict[str, Any]:
    """Load ``~/.hermes/patch.yaml`` and return the ``owner`` section.

    Fail-open: returns an empty dict if the file is missing or unreadable.
    Caches by file mtime (for immediate reaction to edits) + a 1-minute TTL
    (so long-running processes periodically re-read even without mtime change).
    Use invalidate_patch_owner_config_cache() for immediate forced refresh.
    """
    return _load_yaml_file(
        _cache,
        "patch.yaml",
        owner_section=True,
        force=force,
    )


def invalidate_patch_owner_config_cache() -> None:
    """Force the next loader call to re-read patch.yaml from disk."""
    _cache["mtime"] = None
    _cache["data"] = None
    _cache["last_load"] = 0


def load_patch_feishu_profile_config(force: bool = False) -> Dict[str, Any]:
    """Load ``~/.hermes/patch_feishu_profile.yaml`` and return the top-level dict.

    Fail-open: returns an empty dict if the file is missing or unreadable.
    Caches by file mtime + a 1-minute TTL.
    Use invalidate_patch_feishu_profile_config_cache() for immediate forced refresh.

    This file is dedicated to Feishu multi-profile routing configuration
    (``feishu.user_routing``) so that profile endpoints and route mappings can
    be managed independently of the main ``patch.yaml``.
    """
    return _load_yaml_file(
        _feishu_profile_cache,
        "patch_feishu_profile.yaml",
        owner_section=False,
        force=force,
    )


def invalidate_patch_feishu_profile_config_cache() -> None:
    """Force the next loader call to re-read patch_feishu_profile.yaml from disk."""
    _feishu_profile_cache["mtime"] = None
    _feishu_profile_cache["data"] = None
    _feishu_profile_cache["last_load"] = 0


def get_model_extra_body(
    owner_provider_name: Optional[str], model: Optional[str]
) -> Dict[str, Any]:
    """Return per-model extra_body entries from ``owner.model_extra_body``.

    The expected shape is::

        owner:
          model_extra_body:
            <owner_provider_name>:
              <model>:
                key: value
                ...

    Both ``owner_provider_name`` and ``model`` are normalized to lower case for
    lookup. Returns an empty dict when nothing is configured.
    """
    if not owner_provider_name or not model:
        return {}

    try:
        owner_cfg = _load_patch_owner_config()
        model_extra = owner_cfg.get("model_extra_body")
        if not isinstance(model_extra, dict):
            return {}

        provider_extra = model_extra.get(str(owner_provider_name).strip().lower())
        if not isinstance(provider_extra, dict):
            return {}

        return dict(provider_extra.get(str(model).strip()) or {})
    except Exception as exc:
        logger.debug("Failed to get model_extra_body: %s", exc)
        return {}
