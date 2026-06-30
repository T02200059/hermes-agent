"""Runtime patches for core tool schemas (private extensions).

This module applies owner-specific additions to tool schemas *after* the
official tool modules have defined their base SCHEMA.

Why post-patch:
- Keeps the official tool/*.py files' schema *literals* identical to upstream.
- Reduces permanent diff surface in core files when pulling from official.
- The LLM still sees the extended schema (with "model", "card" etc.) because
  the patch mutates the dict in place before any agent uses the tools.

Usage:
  import owner.tools.schema_patches   # do this early, before first tool use

All logic here is private customization. See owner/docs/ for details.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def apply_image_generate_schema_patch() -> None:
    """Add 'model' param to image_generate tool (for DashScope preset switching etc.)."""
    try:
        from tools.image_generation_tool import IMAGE_GENERATE_SCHEMA
    except Exception as exc:
        logger.debug("image_generate schema patch skipped: %s", exc)
        return

    # Only add if not already present (idempotent)
    props = IMAGE_GENERATE_SCHEMA.setdefault("parameters", {}).setdefault("properties", {})
    if "model" not in props:
        props["model"] = {
            "type": "string",
            "description": (
                "Optional model name or alias. Overrides the active "
                "preset's model. Use aliases like 'wan' or 'qwen' to "
                "switch presets entirely."
            ),
        }
        # Also update description to mention the capability (for the LLM)
        desc = IMAGE_GENERATE_SCHEMA.get("description", "")
        if "model" not in desc:
            IMAGE_GENERATE_SCHEMA["description"] = (
                desc.rstrip() +
                " The agent may pass 'model' to override the active preset's model or switch presets via alias."
            )
        logger.debug("Applied owner image_generate schema patch (model param)")


def apply_send_message_schema_patch() -> None:
    """Add 'card' param to send_message tool (for Feishu interactive cards etc.)."""
    try:
        from tools.send_message_tool import SEND_MESSAGE_SCHEMA
    except Exception as exc:
        logger.debug("send_message schema patch skipped: %s", exc)
        return

    props = SEND_MESSAGE_SCHEMA.setdefault("parameters", {}).setdefault("properties", {})
    if "card" not in props:
        props["card"] = {
            "type": "object",
            "description": (
                "Feishu interactive card payload (JSON object with config + header + elements). "
                "When set, sends as an interactive card instead of plain text. Only supported on feishu platform."
            ),
        }
        logger.debug("Applied owner send_message schema patch (card param)")


# Auto-apply on import (early enough if this module is imported before agent run)
apply_image_generate_schema_patch()
apply_send_message_schema_patch()
