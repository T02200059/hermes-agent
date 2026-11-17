"""[owner] C13 recap — LLM call (never raises; never writes session)."""

from __future__ import annotations

import logging
from typing import Any, Optional

from owner.explainers import llm as llm_mod
from owner.explainers.common import DEFAULT_MAX_INPUT_CHARS
from owner.explainers.config import load_kind_config
from owner.explainers.recap import hybrid as hybrid_mod
from owner.explainers.recap import prompt as prompt_mod

logger = logging.getLogger(__name__)

_MAX_TOKENS = 260


def _plan_and_messages(
    messages: list[Any],
    *,
    cfg: Optional[dict[str, Any]],
    route_info: Optional[dict[str, Any]],
    session_id: Optional[str],
    db: Any,
    prior_notices: Any,
) -> Optional[tuple[dict[str, Any], list[dict[str, str]]]]:
    merged = cfg if isinstance(cfg, dict) else load_kind_config("recap")
    budget = int(merged.get("max_input_chars") or DEFAULT_MAX_INPUT_CHARS)
    plan = hybrid_mod.plan_recap_input(
        messages,
        max_input_chars=budget,
        session_id=session_id,
        db=db,
        prior_notices=prior_notices,
    )
    if not plan.dialogue.strip():
        return None
    if isinstance(route_info, dict):
        route_info["recap_input"] = plan.extra_meta()
    return merged, prompt_mod.build_messages(plan.dialogue, prior_recap=plan.prior_recap)


def explain_from_messages(
    messages: list[Any],
    *,
    cfg: Optional[dict[str, Any]] = None,
    route_info: Optional[dict[str, Any]] = None,
    session_id: Optional[str] = None,
    db: Any = None,
    prior_notices: Optional[list] = None,
) -> Optional[str]:
    """Flatten ``messages`` then call the shared explainer LLM. Returns cleaned text or None."""
    try:
        planned = _plan_and_messages(
            messages,
            cfg=cfg,
            route_info=route_info,
            session_id=session_id,
            db=db,
            prior_notices=prior_notices,
        )
        if planned is None:
            return None
        merged, llm_messages = planned
        out_cap = int(merged.get("max_output_chars") or 350)
        return llm_mod.call_explainer_llm(
            "recap",
            llm_messages,
            cfg=merged,
            max_tokens=_MAX_TOKENS,
            max_output_chars=max(80, out_cap),
            route_info=route_info,
        )
    except Exception as exc:
        logger.debug("recap explain_from_messages failed: %s", exc)
        return None


async def explain_from_messages_async(
    messages: list[Any],
    *,
    cfg: Optional[dict[str, Any]] = None,
    route_info: Optional[dict[str, Any]] = None,
    session_id: Optional[str] = None,
    db: Any = None,
    prior_notices: Optional[list] = None,
) -> Optional[str]:
    try:
        planned = _plan_and_messages(
            messages,
            cfg=cfg,
            route_info=route_info,
            session_id=session_id,
            db=db,
            prior_notices=prior_notices,
        )
        if planned is None:
            return None
        merged, llm_messages = planned
        out_cap = int(merged.get("max_output_chars") or 350)
        return await llm_mod.call_explainer_llm_async(
            "recap",
            llm_messages,
            cfg=merged,
            max_tokens=_MAX_TOKENS,
            max_output_chars=max(80, out_cap),
            route_info=route_info,
        )
    except Exception as exc:
        logger.debug("recap explain_from_messages_async failed: %s", exc)
        return None
