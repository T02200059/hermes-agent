"""[owner] C13 — progress explainer LLM call (never raises)."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from owner.explainers import llm as llm_mod
from owner.explainers.progress import prompt as prompt_mod

logger = logging.getLogger(__name__)

_MAX_OUTPUT_CHARS = 900
_MAX_TOKENS = 400


async def explain(
    state: dict,
    cfg: dict,
    user_message: str,
    language: str,
) -> Optional[str]:
    """Generate progress narration (no PREFIX). Fail → None."""
    try:
        if not isinstance(state, dict) or not isinstance(cfg, dict):
            return None
        digest = str(state.get("digest") or "")
        raw_hard = state.get("hard_facts")
        hard_facts = raw_hard if isinstance(raw_hard, dict) else {}
        messages = prompt_mod.build_messages(user_message, digest, hard_facts, language)
        out_cap = int(cfg.get("max_output_chars") or _MAX_OUTPUT_CHARS)
        return await llm_mod.call_explainer_llm_async(
            "progress",
            messages,
            cfg=cfg,
            max_tokens=_MAX_TOKENS,
            max_output_chars=max(80, out_cap),
        )
    except Exception as exc:
        logger.debug("progress explain failed: %s", exc)
        return None
