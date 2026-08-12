"""[owner] Hermes plugin entry: registers owner-specific runtime patches.

All owner monkey-patches are applied at plugin register() time, which
runs during discover_plugins() -- guaranteed before any agent turn or
MemoryManager call (see gateway/run.py and model_tools.py).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _wrap_providers_command(handler):
    async def _providers_command(_raw_args: str, *, hermes_ctx):
        return await handler(
            adapters=getattr(hermes_ctx, "adapters", {}) or {},
            event=getattr(hermes_ctx, "event", None),
        )

    return _providers_command


def _wrap_feishu_guide_command(handler):
    async def _feishu_guide_command(_raw_args: str, *, hermes_ctx):
        return await handler(
            adapters=getattr(hermes_ctx, "adapters", {}) or {},
            event=getattr(hermes_ctx, "event", None),
        )

    return _feishu_guide_command


def register(ctx) -> None:
    """Apply all owner runtime patches. Idempotent per-patch."""
    # §2.5 /providers plugin slash command
    # Uses PluginCommandContext (hermes_ctx) so Feishu can keep its interactive
    # provider picker card via gateway adapters/event, while CLI falls back to text.
    try:
        from owner.commands.providers import handle_providers_command
        ctx.register_command(
            "providers",
            _wrap_providers_command(handle_providers_command),
            description="List configured providers",
        )
        logger.debug("owner: /providers registered via plugin command")
    except Exception:
        logger.warning("owner: /providers registration failed", exc_info=True)

    # §2.6 /feishu_guide plugin slash command
    # Feishu-only interactive card for /queue, /steer, /goal, /subgoal, /background.
    # See owner/feishu/steer_card.py for card building + callback handling.
    try:
        from owner.commands.feishu_guide import handle_feishu_guide_command
        ctx.register_command(
            "feishu-guide",
            _wrap_feishu_guide_command(handle_feishu_guide_command),
            description="Feishu interactive guide card (queue/steer/goal/subgoal/background)",
        )
        logger.debug("owner: /feishu_guide registered via plugin command")
    except Exception:
        logger.warning("owner: /feishu_guide registration failed", exc_info=True)

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

    # §7.4 Feishu memory write-approval interactive card
    # Auto-popup approval card when memory tool stages a write on Feishu.
    # See owner/owner-extensions/memory_feishu_bridge/
    try:
        from .memory_feishu_bridge import register_hooks
        register_hooks(ctx)
        logger.debug("owner: memory-feishu-bridge hooks registered via owner-extensions")
    except Exception:
        logger.warning("owner: memory-feishu-bridge hooks registration failed", exc_info=True)

    # § skill_manage Feishu write approval (profile whitelist + 24h wait)
    # See owner/approval/skill_manage_gate.py + skill_manage_bridge/
    try:
        from .skill_manage_bridge import register_hooks as _register_skill_manage_hooks
        _register_skill_manage_hooks(ctx)
        logger.debug("owner: skill_manage-bridge hooks registered via owner-extensions")
    except Exception:
        logger.warning("owner: skill_manage-bridge hooks registration failed", exc_info=True)

    # §4.11 Feishu queue lifecycle card (cancel / process_now / freeze)
    # + guide-card morph to status card. Feishu-only; other platforms keep text ack.
    # See owner/patches/queue_cancel_patch.py + owner/feishu/queue_card.py.
    try:
        from owner.patches.queue_cancel_patch import apply_patch
        apply_patch()
        logger.debug("owner: queue_cancel_patch applied via plugin register")
    except Exception:
        logger.warning("owner: queue_cancel_patch failed", exc_info=True)

    # §8.5 read_file UTF-8 boundary false-positive fix
    # head -c 1000 splits multi-byte chars at the boundary -> U+FFFD -> 误判 binary.
    # See owner/patches/file_binary_detection_patch.py + owner/docs/read-file-utf8-boundary-fix.md
    try:
        from owner.patches.file_binary_detection_patch import apply_patch
        apply_patch()
        logger.debug("owner: file_binary_detection_patch applied via plugin register")
    except Exception:
        logger.warning("owner: file_binary_detection_patch failed", exc_info=True)
