"""[owner] C13 — english explainer LLM call (never raises; never rewrites body)."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from owner.explainers import llm as llm_mod
from owner.explainers.common import DEFAULT_MAX_INPUT_CHARS, clip_input
from owner.explainers.config import load_kind_config
from owner.explainers.english import prompt as prompt_mod

logger = logging.getLogger(__name__)

_MAX_OUTPUT_CHARS = 1000
_MAX_TOKENS = 450


def explain(english_text: str, *, cfg: Optional[Dict[str, Any]] = None) -> Optional[str]:
    try:
        text = (english_text or "").strip()
        if not text:
            return None
        merged = cfg if isinstance(cfg, dict) else load_kind_config("english")
        text = clip_input(text, int(merged.get("max_input_chars") or DEFAULT_MAX_INPUT_CHARS))
        messages = prompt_mod.build_messages(text)
        return llm_mod.call_explainer_llm(
            "english",
            messages,
            cfg=merged,
            max_tokens=_MAX_TOKENS,
            max_output_chars=_MAX_OUTPUT_CHARS,
        )
    except Exception as exc:
        logger.debug("english explain failed: %s", exc)
        return None


async def explain_async(english_text: str, *, cfg: Optional[Dict[str, Any]] = None) -> Optional[str]:
    try:
        text = (english_text or "").strip()
        if not text:
            return None
        merged = cfg if isinstance(cfg, dict) else load_kind_config("english")
        text = clip_input(text, int(merged.get("max_input_chars") or DEFAULT_MAX_INPUT_CHARS))
        messages = prompt_mod.build_messages(text)
        return await llm_mod.call_explainer_llm_async(
            "english",
            messages,
            cfg=merged,
            max_tokens=_MAX_TOKENS,
            max_output_chars=_MAX_OUTPUT_CHARS,
        )
    except Exception as exc:
        logger.debug("english explain_async failed: %s", exc)
        return None
