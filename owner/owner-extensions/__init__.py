"""[owner] Plugin entry: registers owner slash commands and runtime hooks."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def register(ctx) -> None:
    """Register owner plugin commands and hooks. Idempotent per discovery load."""
    try:
        from owner.commands.providers import handle_providers_command

        ctx.register_command(
            "providers",
            handle_providers_command,
            description="List configured providers",
        )
        logger.debug("owner: /providers registered via plugin command")
    except Exception:
        logger.warning("owner: /providers registration failed", exc_info=True)

    try:
        from owner.explainers.recap import handle_recap_command

        ctx.register_command(
            "recap",
            handle_recap_command,
            description="Summarize this chat (notice card; not written to agent history)",
        )
        logger.debug("owner: /recap registered via plugin command")
    except Exception:
        logger.warning("owner: /recap registration failed", exc_info=True)

    # [owner] C14: output_guard + stream_guard
    try:
        from owner.output_guard import register_hooks as _register_output_guard

        _register_output_guard(ctx)
    except Exception:
        logger.warning("owner: output_guard registration failed", exc_info=True)
    try:
        from owner.stream_guard import register_hooks as _register_stream_guard

        _register_stream_guard(ctx)
    except Exception:
        logger.warning("owner: stream_guard registration failed", exc_info=True)

    # [owner] C13: progress + english + recap explainers
    try:
        from owner.explainers.progress import register_hooks as _register_progress_explainer

        _register_progress_explainer(ctx)
    except Exception:
        logger.warning("owner: progress_explainer registration failed", exc_info=True)
    try:
        from owner.explainers.english import register_hooks as _register_english_explainer

        _register_english_explainer(ctx)
    except Exception:
        logger.warning("owner: english_explainer registration failed", exc_info=True)

    # [owner] C09: skill_manage Feishu write-approval gate
    try:
        from .skill_manage_bridge import register_hooks as _register_skill_manage_hooks

        _register_skill_manage_hooks(ctx)
        logger.debug("owner: skill_manage-bridge hooks registered via owner-extensions")
    except Exception:
        logger.warning("owner: skill_manage-bridge hooks registration failed", exc_info=True)

