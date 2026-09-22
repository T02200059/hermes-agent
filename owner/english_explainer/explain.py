"""调辅助 LLM 生成英文回复的中文解说（永不抛）。

侧路：agent.auxiliary_client.call_llm(task="english_explainer")，
语义对齐 progress_explainer / approval_explainer：
patch.yaml provider/model 空或 auto → 传 None → auxiliary auto 链；
显式值直连。任何异常 / 超时 → None。
"""

from __future__ import annotations

import logging
from typing import Optional

from owner.english_explainer import prompt as prompt_mod

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_MS = 30000


def _extract_content(response: object) -> Optional[str]:
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


def _clean_output(text: str, max_chars: int) -> Optional[str]:
    s = (text or "").strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("\"", "'", "“", "‘", "`"):
        s = s[1:-1].strip()
    s = "\n".join(line.strip() for line in s.splitlines() if line.strip())
    if not s:
        return None
    if max_chars > 0 and len(s) > max_chars:
        s = s[:max_chars].rstrip() + "…"
    return s


def explain_sync(source: str, cfg: dict) -> Optional[str]:
    """同步生成中文解说。永不抛：失败返回 None。"""
    try:
        if not isinstance(cfg, dict):
            return None
        src = str(source or "").strip()
        if not src:
            return None
        max_src = int(cfg.get("max_source_chars") or 4000)
        if max_src > 0 and len(src) > max_src:
            src = src[:max_src].rstrip() + "…"

        timeout_ms = _DEFAULT_TIMEOUT_MS
        try:
            timeout_ms = int(cfg.get("explainer_timeout_ms", _DEFAULT_TIMEOUT_MS))
        except (TypeError, ValueError):
            pass
        if timeout_ms <= 0:
            timeout_ms = _DEFAULT_TIMEOUT_MS
        timeout_s = max(0.5, timeout_ms / 1000.0)

        max_out = int(cfg.get("max_output_chars") or 1200)
        messages = prompt_mod.build_messages(src)

        _provider = str(cfg.get("provider", "") or "").strip() or None
        _model = str(cfg.get("model", "") or "").strip() or None
        if _model and _model.lower() == "auto":
            _model = None

        from agent.auxiliary_client import call_llm

        response = call_llm(
            task="english_explainer",
            messages=messages,
            temperature=0,
            max_tokens=min(800, max(120, max_out // 2)),
            timeout=timeout_s,
            provider=_provider,
            model=_model,
        )
        content = _extract_content(response)
        if not content:
            return None
        return _clean_output(content, max_out)
    except Exception as exc:
        logger.debug("english_explainer explain failed: %s", exc)
        return None
