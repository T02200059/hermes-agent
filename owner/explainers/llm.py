"""[owner] C13 — shared explainer LLM entry (resolve + call).

Priority (provider/model):
  1. patch explainers.<kind>.provider|model (non-empty, non-auto)
  2. patch explainers.provider|model
  3. call_llm(task="<kind>_explainer") → config.yaml auxiliary.<task>
  4. main chat model (call_llm auto chain)

Never raise to callers: call_explainer_llm returns None on any failure.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from owner.explainers.config import load_kind_config, resolve_model, resolve_timeout_s
from owner.explainers.registry import task_name_for

logger = logging.getLogger(__name__)

_MAX_OUTPUT_CHARS_DEFAULT = 700


def resolve_explainer_call(kind: str, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Return ``{task, provider, model, timeout_s, cfg}`` for a kind."""
    merged = cfg if isinstance(cfg, dict) else load_kind_config(kind)
    provider, model = resolve_model(merged)
    return {
        "task": task_name_for(kind),
        "provider": provider,
        "model": model,
        "timeout_s": resolve_timeout_s(merged),
        "cfg": merged,
    }


def extract_content(response: object) -> Optional[str]:
    if isinstance(response, str):
        return response or None
    if response is None:
        return None
    content: object = None
    try:
        choices = getattr(response, "choices", None)
        if choices:
            content = getattr(getattr(choices[0], "message", None), "content", None)
    except Exception:
        content = None
    if not content or not isinstance(content, str):
        return None
    return content


def clean_output(text: str, *, max_chars: int = _MAX_OUTPUT_CHARS_DEFAULT) -> Optional[str]:
    s = (text or "").strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("\"", "'", "“", "‘", "`"):
        s = s[1:-1].strip()
    s = "\n".join(line.strip() for line in s.splitlines() if line.strip())
    if not s:
        return None
    if max_chars > 0 and len(s) > max_chars:
        s = s[:max_chars].rstrip() + "…"
    return s


def call_explainer_llm(
    kind: str,
    messages: List[Dict[str, str]],
    *,
    cfg: Optional[Dict[str, Any]] = None,
    temperature: float = 0,
    max_tokens: int = 250,
    max_output_chars: int = _MAX_OUTPUT_CHARS_DEFAULT,
) -> Optional[str]:
    """Sync call; returns cleaned text or None. Never raises."""
    try:
        resolved = resolve_explainer_call(kind, cfg)
        from agent.auxiliary_client import call_llm

        response = call_llm(
            task=resolved["task"],
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=resolved["timeout_s"],
            provider=resolved["provider"],
            model=resolved["model"],
        )
        content = extract_content(response)
        if not content:
            return None
        return clean_output(content, max_chars=max_output_chars)
    except Exception as exc:
        logger.debug("explainer llm kind=%s failed: %s", kind, exc)
        return None


async def call_explainer_llm_async(
    kind: str,
    messages: List[Dict[str, str]],
    *,
    cfg: Optional[Dict[str, Any]] = None,
    temperature: float = 0,
    max_tokens: int = 250,
    max_output_chars: int = _MAX_OUTPUT_CHARS_DEFAULT,
) -> Optional[str]:
    """Async wrapper with hard timeout (to_thread + wait_for). Never raises."""
    import asyncio

    try:
        resolved = resolve_explainer_call(kind, cfg)
        timeout_s = resolved["timeout_s"]

        def _call() -> Optional[str]:
            return call_explainer_llm(
                kind,
                messages,
                cfg=resolved["cfg"],
                temperature=temperature,
                max_tokens=max_tokens,
                max_output_chars=max_output_chars,
            )

        return await asyncio.wait_for(asyncio.to_thread(_call), timeout=timeout_s)
    except Exception as exc:
        logger.debug("explainer llm async kind=%s failed: %s", kind, exc)
        return None
