"""[owner] C13 recap — LLM call (never raises; never writes session)."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from owner.explainers import llm as llm_mod
from owner.explainers.common import DEFAULT_MAX_INPUT_CHARS
from owner.explainers.config import load_kind_config
from owner.explainers.recap import flatten as flatten_mod
from owner.explainers.recap import prompt as prompt_mod

logger = logging.getLogger(__name__)

_MAX_TOKENS = 220


def explain_from_messages(
    messages: List[Any],
    *,
    cfg: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Flatten ``messages`` then call the shared explainer LLM. Returns cleaned text or None."""
    try:
        merged = cfg if isinstance(cfg, dict) else load_kind_config("recap")
        budget = int(merged.get("max_input_chars") or DEFAULT_MAX_INPUT_CHARS)
        dialogue = flatten_mod.flatten_messages(messages, max_input_chars=budget)
        if not dialogue.strip():
            return None
        out_cap = int(merged.get("max_output_chars") or 500)
        return llm_mod.call_explainer_llm(
            "recap",
            prompt_mod.build_messages(dialogue),
            cfg=merged,
            max_tokens=_MAX_TOKENS,
            max_output_chars=max(80, out_cap),
        )
    except Exception as exc:
        logger.debug("recap explain_from_messages failed: %s", exc)
        return None


async def explain_from_messages_async(
    messages: List[Any],
    *,
    cfg: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    try:
        merged = cfg if isinstance(cfg, dict) else load_kind_config("recap")
        budget = int(merged.get("max_input_chars") or DEFAULT_MAX_INPUT_CHARS)
        dialogue = flatten_mod.flatten_messages(messages, max_input_chars=budget)
        if not dialogue.strip():
            return None
        out_cap = int(merged.get("max_output_chars") or 500)
        return await llm_mod.call_explainer_llm_async(
            "recap",
            prompt_mod.build_messages(dialogue),
            cfg=merged,
            max_tokens=_MAX_TOKENS,
            max_output_chars=max(80, out_cap),
        )
    except Exception as exc:
        logger.debug("recap explain_from_messages_async failed: %s", exc)
        return None
