"""[owner] C13 — shared explainer LLM entry (resolve + call).

Priority (provider/model):
  1. patch explainers.<kind>.provider|model (non-empty, non-auto)
  2. patch explainers.provider|model
  3. call_llm(task="<kind>_explainer") → config.yaml auxiliary.<task>
  4. main chat model (call_llm auto chain)

Never raise to callers: call_explainer_llm returns None on any failure.

Chinese gate (C13 language retry):
  When the UI / kind expects Simplified Chinese, a non-Chinese-looking output
  triggers one corrective regenerate (assistant+user nudge). Still non-Chinese
  → fail-open with the last text (same as other explainer soft failures).
  english kind: only the *旁白译文* is gated; the English source body is never rewritten here.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from owner.explainers.config import load_kind_config, resolve_model, resolve_timeout_s
from owner.explainers.registry import task_name_for

logger = logging.getLogger(__name__)

_MAX_OUTPUT_CHARS_DEFAULT = 1000

# One corrective turn only — avoid token/latency burn on sticky English models.
_CHINESE_RETRY_MAX = 1
_CHINESE_RETRY_NUDGE = (
    "上一段输出不是简体中文。请用简体中文完整重写全部内容；"
    "不要用英文正文，专有名词可保留原文。"
)


def resolve_explainer_call(kind: str, cfg: Optional[dict[str, Any]] = None) -> dict[str, Any]:
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


def _should_enforce_chinese(kind: str, cfg: Optional[dict[str, Any]]) -> bool:
    """english/recap always want 中文旁白; progress/approval follow display.language."""
    merged = cfg if isinstance(cfg, dict) else {}
    if "require_chinese" in merged:
        from owner.explainers.common import coerce_bool

        return coerce_bool(merged.get("require_chinese"), True)
    if kind in ("english", "recap"):
        return True
    try:
        from owner.explainers.common import display_language_is_chinese

        return display_language_is_chinese()
    except Exception:
        return True


def _non_chinese_hit(text: str) -> Optional[dict[str, Any]]:
    try:
        from owner.explainers.english.detect import looks_like_non_chinese_output

        return looks_like_non_chinese_output(text)
    except Exception:
        return None


def _invoke_llm(
    *,
    kind: str,
    messages: list[dict[str, str]],
    resolved: dict[str, Any],
    temperature: float,
    max_tokens: int,
    max_output_chars: int,
    route_info: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    from agent.auxiliary_client import call_llm

    response = call_llm(
        task=resolved["task"],
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=resolved["timeout_s"],
        provider=resolved["provider"],
        model=resolved["model"],
        route_info=route_info,
    )
    content = extract_content(response)
    if not content:
        return None
    return clean_output(content, max_chars=max_output_chars)


def call_explainer_llm(
    kind: str,
    messages: list[dict[str, str]],
    *,
    cfg: Optional[dict[str, Any]] = None,
    temperature: float = 0,
    max_tokens: int = 400,
    max_output_chars: int = _MAX_OUTPUT_CHARS_DEFAULT,
    route_info: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    """Sync call; returns cleaned text or None. Never raises.

    Optional *route_info* dict is filled with the resolved provider/model from
    ``call_llm`` (for notice persist attribution).
    """
    try:
        resolved = resolve_explainer_call(kind, cfg)
        # Seed with config intent so persist still has a channel if call_llm
        # never writes route_info (e.g. mocked tests).
        if route_info is not None:
            if resolved.get("provider"):
                route_info.setdefault("provider", resolved["provider"])
            if resolved.get("model"):
                route_info.setdefault("model", resolved["model"])
            route_info.setdefault("task", resolved.get("task"))
        text = _invoke_llm(
            kind=kind,
            messages=messages,
            resolved=resolved,
            temperature=temperature,
            max_tokens=max_tokens,
            max_output_chars=max_output_chars,
            route_info=route_info,
        )
        if not text:
            return None
        if not _should_enforce_chinese(kind, resolved.get("cfg")):
            return text
        hit = _non_chinese_hit(text)
        if hit is None:
            return text

        last = text
        retry_messages = list(messages)
        for attempt in range(1, _CHINESE_RETRY_MAX + 1):
            logger.info(
                "explainer kind=%s non-chinese output (reason=%s zh_ratio=%s); "
                "chinese retry %s/%s",
                kind,
                hit.get("reason"),
                hit.get("zh_ratio"),
                attempt,
                _CHINESE_RETRY_MAX,
            )
            retry_messages = retry_messages + [
                {"role": "assistant", "content": last},
                {"role": "user", "content": _CHINESE_RETRY_NUDGE},
            ]
            retry = _invoke_llm(
                kind=kind,
                messages=retry_messages,
                resolved=resolved,
                temperature=temperature,
                max_tokens=max_tokens,
                max_output_chars=max_output_chars,
                route_info=route_info,
            )
            if not retry:
                break
            last = retry
            hit = _non_chinese_hit(retry)
            if hit is None:
                return retry

        logger.warning(
            "explainer kind=%s still non-chinese after retry; fail-open keep text",
            kind,
        )
        return last
    except Exception as exc:
        logger.debug("explainer llm kind=%s failed: %s", kind, exc)
        return None


async def call_explainer_llm_async(
    kind: str,
    messages: list[dict[str, str]],
    *,
    cfg: Optional[dict[str, Any]] = None,
    temperature: float = 0,
    max_tokens: int = 400,
    max_output_chars: int = _MAX_OUTPUT_CHARS_DEFAULT,
    route_info: Optional[dict[str, Any]] = None,
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
                route_info=route_info,
            )

        return await asyncio.wait_for(asyncio.to_thread(_call), timeout=timeout_s)
    except Exception as exc:
        logger.debug("explainer llm async kind=%s failed: %s", kind, exc)
        return None
