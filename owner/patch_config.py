"""Unified fail-open loader for ``~/.hermes/patch.yaml`` (owner customization layer).

v2 shape (hard constraint):
- The YAML file has **no outer shell** (no top-level ``owner:`` / ``patch:`` wrapper).
  First-level keys are the sections themselves (``approvals``, ``feishu_card``, …).
- Code knows this file is the owner layer. After fuse with the official runtime
  config it hangs under ``config.owner.xxx`` (see :func:`apply_owner_overlay`).

Hot-reload: mtime invalidation + 60s TTL (same idea as the source-tree loader).
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_PATCH_TTL_SECONDS = 60

_cache: Dict[str, Any] = {"path": None, "mtime": None, "data": None, "last_load": 0}
_feishu_profile_cache: Dict[str, Any] = {
    "path": None,
    "mtime": None,
    "data": None,
    "last_load": 0,
}


def _load_yaml_file(
    cache: Dict[str, Any],
    filename: str,
    *,
    force: bool = False,
) -> Dict[str, Any]:
    """Fail-open YAML loader with mtime + TTL caching.

    Returns the **top-level dict** of ``~/.hermes/<filename>`` (no subsection peel).
    """
    try:
        from hermes_constants import get_hermes_home

        path = get_hermes_home() / filename
        path_str = str(path)

        if not path.exists():
            cache["path"] = path_str
            cache["mtime"] = None
            cache["data"] = {}
            cache["last_load"] = time.time()
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
        result: Dict[str, Any] = data if isinstance(data, dict) else {}

        cache["path"] = path_str
        cache["mtime"] = mtime
        cache["data"] = result
        cache["last_load"] = time.time()
        return result
    except Exception as exc:
        logger.debug("Failed to load %s: %s", filename, exc)
        return {}


def load_owner_config(force: bool = False) -> Dict[str, Any]:
    """Load ``~/.hermes/patch.yaml`` as the owner-layer dict (file first level = sections).

    Fail-open: missing/unreadable → ``{}``.
    """
    return _load_yaml_file(_cache, "patch.yaml", force=force)


def load_patch_config(force: bool = False) -> Dict[str, Any]:
    """Alias of :func:`load_owner_config` (callers historically named it patch)."""
    return load_owner_config(force=force)


def invalidate_owner_config_cache() -> None:
    """Force the next loader call to re-read patch.yaml from disk."""
    _cache["mtime"] = None
    _cache["data"] = None
    _cache["last_load"] = 0


def invalidate_patch_owner_config_cache() -> None:
    """Back-compat alias for :func:`invalidate_owner_config_cache`."""
    invalidate_owner_config_cache()


def load_patch_feishu_profile_config(force: bool = False) -> Dict[str, Any]:
    """Load ``~/.hermes/patch_feishu_profile.yaml`` (top-level dict; used later by C05/C06)."""
    return _load_yaml_file(
        _feishu_profile_cache,
        "patch_feishu_profile.yaml",
        force=force,
    )


def invalidate_patch_feishu_profile_config_cache() -> None:
    """Force the next loader call to re-read patch_feishu_profile.yaml from disk."""
    _feishu_profile_cache["mtime"] = None
    _feishu_profile_cache["data"] = None
    _feishu_profile_cache["last_load"] = 0


def apply_owner_overlay(config: Dict[str, Any]) -> Dict[str, Any]:
    """Hang the owner-layer YAML under ``config['owner']`` (in-place).

    Deep-merge strategy:
    - Start from any existing ``config['owner']`` dict (e.g. accidental key in
      ``config.yaml``), then overlay ``patch.yaml`` on top (patch wins per key).
    - ``patch.yaml`` is the source of truth for owner customization; missing file
      leaves ``config['owner']`` as ``{}`` (or the shallow leftover from config.yaml).

    Official ``load_config`` / ``load_config_readonly`` call this via thin glue so
    callers can use ``config['owner']['approvals']`` etc.
    """
    if not isinstance(config, dict):
        return config
    try:
        base = config.get("owner")
        base_dict: Dict[str, Any] = dict(base) if isinstance(base, dict) else {}
        overlay = load_owner_config()
        if overlay:
            # Shallow section merge: each first-level key from patch replaces the same
            # key from config.yaml's owner (sections are owned by patch.yaml).
            merged = dict(base_dict)
            merged.update(overlay)
            config["owner"] = merged
        else:
            config["owner"] = base_dict
    except Exception as exc:
        logger.debug("apply_owner_overlay failed: %s", exc)
        config.setdefault("owner", {})
    return config


def get_model_extra_body(
    owner_provider_name: Optional[str], model: Optional[str]
) -> Dict[str, Any]:
    """Return per-model ``extra_body`` entries from ``owner.model_extra_body`` (C03+).

    Expected shape (file first level, no shell)::

        model_extra_body:
          <owner_provider_name>:
            <model>:
              key: value
    """
    if not owner_provider_name or not model:
        return {}
    try:
        owner_cfg = load_owner_config()
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
