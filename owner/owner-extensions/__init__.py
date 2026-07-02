"""[owner] Hermes plugin entry: registers owner-specific runtime patches.

All owner monkey-patches are applied at plugin register() time, which
runs during discover_plugins() -- guaranteed before any agent turn or
MemoryManager call (see gateway/run.py and model_tools.py).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def register(ctx) -> None:
    """Apply all owner runtime patches. Idempotent per-patch."""
    # §9.3 memory synthetic guard
    # Skip MemoryManager prefetch/sync/on_turn_start for synthetic system
    # messages (async delegation, bg process, watch match, CLI handoff).
    # See owner/patches/memory_synthetic_guard_patch.py
    try:
        from owner.patches.memory_synthetic_guard_patch import apply_patch
        apply_patch()
        logger.debug("owner: memory_synthetic_guard_patch applied via plugin register")
    except Exception:
        logger.warning("owner: memory_synthetic_guard_patch failed", exc_info=True)

    # §2.3 runtime schema patches
    # Mutate built-in tool schema dicts after tool registration so owner-only
    # parameters (image_generate.model, legacy send_message.card) are visible
    # without editing upstream tool modules.
    try:
        import owner.tools.schema_patches  # noqa: F401
        logger.debug("owner: schema_patches applied via plugin register")
    except Exception:
        logger.warning("owner: schema_patches failed", exc_info=True)

    # §7.3 OpenViking recall owner extensions
    # Advisory wording, peer-mirror dedup, recall card (Feishu/QQ).
    # See owner/patches/openviking_owner_recall_patch.py
    try:
        from owner.patches.openviking_owner_recall_patch import apply_patch
        apply_patch()
        logger.debug("owner: openviking_owner_recall_patch applied via plugin register")
    except Exception:
        logger.warning("owner: openviking_owner_recall_patch failed", exc_info=True)
