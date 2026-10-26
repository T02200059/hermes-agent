"""[owner] Plugin entry: registers owner slash commands (and future runtime patches)."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def register(ctx) -> None:
    """Register owner plugin commands. Idempotent per discovery load."""
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
