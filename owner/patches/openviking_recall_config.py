"""Configuration loader for OpenViking sync recall + visualization patches.

Reads ``owner.openviking_sync_recall`` and ``owner.openviking_recall_card``
from ``~/.hermes/patch.yaml`` (fail-open to DEFAULTS). Falls back to
``OPENVIKING_*`` environment variables for backwards compatibility with
deployments that haven't migrated, but patch.yaml wins over env.

Mirrors the qdrant-memory-recall hook loader pattern (owner/<feature>/
recall_config.py + ``owner.<group>.<feature>`` section in patch.yaml).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger("openviking_recall")

# ── Sync recall defaults ────────────────────────────────────────────────────
# Patch applies these post-registration: synchronous HTTP recall + advisory
# memory-context wording + visualization (Feishu card / QQ Bot text).
SYNC_RECALL_DEFAULTS: dict[str, Any] = {
    "enabled": True,        # master switch — replaces OPENVIKING_SYNC_RECALL
    "advisory": True,       # advisory wording — replaces OPENVIKING_ADVISORY_MEMORY
    "search_timeout": 10,   # seconds — replaces OPENVIKING_SEARCH_TIMEOUT
}

# ── Recall visualization defaults ───────────────────────────────────────────
# Wraps prefetch() to send user-visible feedback after the sync recall.
RECALL_CARD_DEFAULTS: dict[str, Any] = {
    "enabled": True,        # replaces OPENVIKING_RECALL_DISPLAY
    "feishu_card": True,    # replaces OPENVIKING_RECALL_FEISHU_CARD
    "qqbot_text": True,     # replaces OPENVIKING_RECALL_QQBOT_TEXT
}


def _read_patch_yaml() -> dict[str, Any]:
    """Return raw contents of ~/.hermes/patch.yaml, or empty dict on failure."""
    try:
        from hermes_constants import get_hermes_home

        patch_path = get_hermes_home() / "patch.yaml"
        if not patch_path.exists():
            return {}
        with patch_path.open(encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as exc:
        logger.warning("patch.yaml load failed: %s", exc)
        return {}


def _env_bool(name: str, default: bool) -> bool:
    """Legacy OPENVIKING_* env var fallback. Empty = use default."""
    value = os.environ.get(name, "")
    if value == "":
        return default
    return value.lower() not in ("0", "false", "no", "off")


def _env_float(name: str, default: float) -> float:
    """Legacy OPENVIKING_SEARCH_TIMEOUT env var fallback. Empty = use default."""
    raw = os.environ.get(name, "")
    if raw == "":
        return default
    try:
        return float(raw)
    except Exception:
        return default


def load_sync_recall_config() -> dict[str, Any]:
    """Resolve ``owner.openviking_sync_recall`` from patch.yaml.

    Priority order:
    1. patch.yaml ``owner.openviking_sync_recall.*``
    2. ``OPENVIKING_SYNC_RECALL`` / ``_ADVISORY_MEMORY`` / ``_SEARCH_TIMEOUT`` env (legacy)
    3. ``SYNC_RECALL_DEFAULTS`` (True / True / 10)
    """
    cfg = _read_patch_yaml().get("owner", {}).get("openviking_sync_recall", {}) or {}
    return {
        "enabled": cfg.get("enabled", _env_bool("OPENVIKING_SYNC_RECALL", SYNC_RECALL_DEFAULTS["enabled"])),
        "advisory": cfg.get("advisory", _env_bool("OPENVIKING_ADVISORY_MEMORY", SYNC_RECALL_DEFAULTS["advisory"])),
        "search_timeout": cfg.get("search_timeout", _env_float("OPENVIKING_SEARCH_TIMEOUT", SYNC_RECALL_DEFAULTS["search_timeout"])),
    }


def load_recall_card_config() -> dict[str, Any]:
    """Resolve ``owner.openviking_recall_card`` from patch.yaml.

    Priority order:
    1. patch.yaml ``owner.openviking_recall_card.*``
    2. ``OPENVIKING_RECALL_DISPLAY`` / ``_FEISHU_CARD`` / ``_QQBOT_TEXT`` env (legacy)
    3. ``RECALL_CARD_DEFAULTS`` (all True)
    """
    cfg = _read_patch_yaml().get("owner", {}).get("openviking_recall_card", {}) or {}
    return {
        "enabled": cfg.get("enabled", _env_bool("OPENVIKING_RECALL_DISPLAY", RECALL_CARD_DEFAULTS["enabled"])),
        "feishu_card": cfg.get("feishu_card", _env_bool("OPENVIKING_RECALL_FEISHU_CARD", RECALL_CARD_DEFAULTS["feishu_card"])),
        "qqbot_text": cfg.get("qqbot_text", _env_bool("OPENVIKING_RECALL_QQBOT_TEXT", RECALL_CARD_DEFAULTS["qqbot_text"])),
    }


def reset_caches_for_tests() -> None:
    """Test hook: clear any cached state (none yet, but reserved for future)."""
    # Currently load_config reads patch.yaml on every call (cheap yaml.safe_load).
    # If we add module-level caching later, clear it here.
    return None