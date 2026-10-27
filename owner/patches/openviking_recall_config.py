"""[owner] C15 — OpenViking owner-extension config (advisory / dedup; no recall card).

Reads ``openviking:`` from ``overlay.yaml`` (v2 flat sections). Falls back to
legacy ``openviking_sync_recall`` key and ``OPENVIKING_*`` env vars.

Recall-card visualization is intentionally **not** configured here (user
decision: no Feishu/QQ recall cards).
"""

from __future__ import annotations

import logging
import os
from typing import Any

from owner.patch_config import load_owner_config

logger = logging.getLogger("openviking_recall")

SYNC_RECALL_DEFAULTS: dict[str, Any] = {
    "advisory": True,
    "dedup": True,
}


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name, "")
    if value == "":
        return default
    return value.lower() not in ("0", "false", "no", "off")


def _section() -> dict[str, Any]:
    """Resolve the openviking section from overlay (new or legacy key)."""
    cfg = load_owner_config() or {}
    # Preferred v2 consolidated key; legacy keys kept for one-release compat.
    section = cfg.get("openviking")
    if isinstance(section, dict):
        return section
    legacy = cfg.get("openviking_sync_recall")
    if isinstance(legacy, dict):
        return legacy
    return {}


def load_sync_recall_config() -> dict[str, Any]:
    """Resolve advisory/dedup switches.

    Priority: overlay.yaml > legacy env > defaults.
    """
    cfg = _section()
    return {
        "advisory": cfg.get(
            "advisory",
            _env_bool("OPENVIKING_ADVISORY_MEMORY", SYNC_RECALL_DEFAULTS["advisory"]),
        ),
        "dedup": cfg.get("dedup", SYNC_RECALL_DEFAULTS["dedup"]),
    }
