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

# 5-minute TTL for patch.yaml reloads (in addition to mtime-based invalidation on file change).
# This ensures periodic refresh even if the file mtime does not change (e.g. network mounts,
# external edits, or safety against stale cache in long-running gateway processes).
_PATCH_TTL_SECONDS = 300

_cache: Dict[str, Any] = {"path": None, "mtime": None, "data": None, "last_load": 0}


def _load_patch_owner_config(force: bool = False) -> Dict[str, Any]:
    """Load ``~/.hermes/patch.yaml`` and return the ``owner`` section.

    Fail-open: returns an empty dict if the file is missing or unreadable.
    Caches by file mtime (for immediate reaction to edits) + a 5-minute TTL
    (so long-running processes periodically re-read even without mtime change).
    Use invalidate_patch_owner_config_cache() for immediate forced refresh.
    """
    try:
        from hermes_constants import get_hermes_home

        path = get_hermes_home() / "patch.yaml"
        path_str = str(path)

        if not path.exists():
            _cache["path"] = path_str
            _cache["mtime"] = None
            _cache["data"] = {}
            return {}

        mtime = path.stat().st_mtime
        now = time.time()
        if (
            not force
            and _cache["path"] == path_str
            and _cache["mtime"] == mtime
            and _cache["data"] is not None
            and now - _cache.get("last_load", 0) < _PATCH_TTL_SECONDS
        ):
            return _cache["data"]

        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        owner_cfg = (
            data["owner"]
            if isinstance(data, dict) and isinstance(data.get("owner"), dict)
            else {}
        )

        _cache["path"] = path_str
        _cache["mtime"] = mtime
        _cache["data"] = owner_cfg
        _cache["last_load"] = time.time()
        return owner_cfg
    except Exception as exc:
        logger.debug("Failed to load patch.yaml owner config: %s", exc)
        return {}


def invalidate_patch_owner_config_cache() -> None:
    """Force the next loader call to re-read patch.yaml from disk."""
    _cache["mtime"] = None
    _cache["data"] = None
    _cache["last_load"] = 0


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
