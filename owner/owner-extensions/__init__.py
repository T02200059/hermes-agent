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
