"""[owner] C13 — approval explainer LLM call (never raises; never advises)."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from owner.explainers import llm as llm_mod
from owner.explainers.approval import prompt as prompt_mod

logger = logging.getLogger(__name__)

_MAX_OUTPUT_CHARS = 500
_MAX_TOKENS = 220


def explain(
    command: str,
    *,
    cfg: Optional[Dict[str, Any]] = None,
    language: str = "zh",
    reason: str = "",
    tool_name: str = "terminal",
) -> Optional[str]:
    """Return 2–3 sentence risk summary or None. Fail-open."""
    try:
        cmd = (command or "").strip()
        if not cmd:
            return None
        desc_max = 500
        if isinstance(cfg, dict):
            try:
                desc_max = int(cfg.get("description_max_chars") or 500)
            except (TypeError, ValueError):
                desc_max = 500
        messages = prompt_mod.build_messages(
            cmd,
            reason or "",
            language,
            description_max_chars=desc_max,
        )
        return llm_mod.call_explainer_llm(
            "approval",
            messages,
            cfg=cfg,
            max_tokens=_MAX_TOKENS,
            max_output_chars=_MAX_OUTPUT_CHARS,
        )
    except Exception as exc:
        logger.debug("approval explain failed: %s", exc)
        return None


async def explain_async(
    command: str,
    *,
    cfg: Optional[Dict[str, Any]] = None,
    language: str = "zh",
    reason: str = "",
    tool_name: str = "terminal",
) -> Optional[str]:
    try:
        cmd = (command or "").strip()
        if not cmd:
            return None
        desc_max = 500
        if isinstance(cfg, dict):
            try:
                desc_max = int(cfg.get("description_max_chars") or 500)
            except (TypeError, ValueError):
                desc_max = 500
        messages = prompt_mod.build_messages(
            cmd,
            reason or "",
            language,
            description_max_chars=desc_max,
        )
        return await llm_mod.call_explainer_llm_async(
            "approval",
            messages,
            cfg=cfg,
            max_tokens=_MAX_TOKENS,
            max_output_chars=_MAX_OUTPUT_CHARS,
        )
    except Exception as exc:
        logger.debug("approval explain_async failed: %s", exc)
        return None
