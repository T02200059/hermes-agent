"""Configuration loader for OpenViking owner recall extensions.

Reads ``owner.openviking_sync_recall`` and ``owner.openviking_recall_card``
from ``~/.hermes/patch.yaml`` (fail-open to DEFAULTS). Falls back to
legacy ``OPENVIKING_*`` environment variables for backwards compatibility.

Only the owner-specific extensions are configured here:
- advisory memory-context wording
- peer-mirror URI canonical deduplication
- recall card visualization (Feishu / QQ Bot)

The official synchronous prefetch, queue_prefetch no-op, limit,
context_type, and session-search fallback are provided by the official
OpenViking plugin and are NOT duplicated in this patch.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from owner.patch_config import _load_patch_owner_config

logger = logging.getLogger("openviking_recall")

# Sync recall owner-extension defaults.
SYNC_RECALL_DEFAULTS: dict[str, Any] = {
    "advisory": True,   # advisory wording — replaces OPENVIKING_ADVISORY_MEMORY
    "dedup": True,      # collapse peer-mirror URIs
    "top_n": 6,         # recall card hit limit
}

# Recall visualization defaults.
RECALL_CARD_DEFAULTS: dict[str, Any] = {
    "enabled": True,    # replaces OPENVIKING_RECALL_DISPLAY
    "feishu_card": True,  # replaces OPENVIKING_RECALL_FEISHU_CARD
    "qqbot_text": True,   # replaces OPENVIKING_RECALL_QQBOT_TEXT
}


def _env_bool(name: str, default: bool) -> bool:
    """Legacy env-var fallback. Empty = use default."""
    value = os.environ.get(name, "")
    if value == "":
        return default
    return value.lower() not in ("0", "false", "no", "off")


def load_sync_recall_config() -> dict[str, Any]:
    """Resolve ``owner.openviking_sync_recall`` extension keys from patch.yaml.

    Priority: patch.yaml > legacy env > defaults.
    """
    cfg = _load_patch_owner_config().get("openviking_sync_recall", {}) or {}
    return {
        "advisory": cfg.get("advisory", _env_bool("OPENVIKING_ADVISORY_MEMORY", SYNC_RECALL_DEFAULTS["advisory"])),
        "dedup": cfg.get("dedup", SYNC_RECALL_DEFAULTS["dedup"]),
        "top_n": int(cfg.get("top_n", SYNC_RECALL_DEFAULTS["top_n"])),
    }


def load_recall_card_config() -> dict[str, Any]:
    """Resolve ``owner.openviking_recall_card`` from patch.yaml.

    Priority: patch.yaml > legacy env > defaults.
    """
    cfg = _load_patch_owner_config().get("openviking_recall_card", {}) or {}
    return {
        "enabled": cfg.get("enabled", _env_bool("OPENVIKING_RECALL_DISPLAY", RECALL_CARD_DEFAULTS["enabled"])),
        "feishu_card": cfg.get("feishu_card", _env_bool("OPENVIKING_RECALL_FEISHU_CARD", RECALL_CARD_DEFAULTS["feishu_card"])),
        "qqbot_text": cfg.get("qqbot_text", _env_bool("OPENVIKING_RECALL_QQBOT_TEXT", RECALL_CARD_DEFAULTS["qqbot_text"])),
    }
