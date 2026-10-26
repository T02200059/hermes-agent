"""[owner] C13 — approval explainer (embed on approval card; never advise)."""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from typing import Any, Dict, Optional, Tuple

from owner.explainers.approval.explain import explain, explain_async
from owner.explainers.common import display_language, normalize_platform
from owner.explainers.config import load_kind_config, resolve_enabled

logger = logging.getLogger(__name__)

SECTION_LABEL_ZH = "命令说明"
SECTION_LABEL_EN = "What this does"

_CACHE: Dict[str, Tuple[float, str]] = {}
_CACHE_LOCK = threading.Lock()


def _cache_key(command: str, language: str, reason: str) -> str:
    raw = f"{language}\0{reason}\0{command}"
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()


def _cache_get(key: str, ttl: int) -> Optional[str]:
    now = time.time()
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if not hit:
            return None
        ts, val = hit
        if now - ts > max(1, ttl):
            _CACHE.pop(key, None)
            return None
        return val


def _cache_put(key: str, val: str, max_entries: int) -> None:
    with _CACHE_LOCK:
        if len(_CACHE) >= max(1, max_entries):
            # drop oldest
            oldest = min(_CACHE.items(), key=lambda kv: kv[1][0])[0]
            _CACHE.pop(oldest, None)
        _CACHE[key] = (time.time(), val)


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


def maybe_explain_command(
    command: str,
    *,
    platform: str = "",
    chat_id: str = "",
    reason: str = "",
    tool_name: str = "terminal",
    language: Optional[str] = None,
) -> Optional[str]:
    """Sync helper for glue: None if disabled / empty / fail."""
    try:
        plat = normalize_platform(platform)
        if not resolve_enabled("approval", plat, chat_id):
            return None
        cfg = load_kind_config("approval")
        lang = language or display_language()
        key = _cache_key(command or "", lang, reason or "")
        cached = _cache_get(key, int(cfg.get("cache_ttl_seconds") or 600))
        if cached is not None:
            return cached
        text = explain(
            command,
            cfg=cfg,
            language=lang,
            reason=reason,
            tool_name=tool_name,
        )
        if text:
            _cache_put(key, text, int(cfg.get("cache_max_entries") or 128))
        return text
    except Exception as exc:
        logger.debug("maybe_explain_command failed: %s", exc)
        return None


async def explain_command(
    command: str,
    *,
    platform: str = "",
    chat_id: str = "",
    reason: str = "",
    tool_name: str = "terminal",
    language: Optional[str] = None,
) -> str:
    """Async entry used by Feishu adapter glue. Returns '' on skip/fail (fail-open)."""
    try:
        plat = normalize_platform(platform)
        if not resolve_enabled("approval", plat, chat_id):
            return ""
        cfg = load_kind_config("approval")
        lang = language or display_language()
        key = _cache_key(command or "", lang, reason or "")
        cached = _cache_get(key, int(cfg.get("cache_ttl_seconds") or 600))
        if cached is not None:
            return cached
        text = await explain_async(
            command,
            cfg=cfg,
            language=lang,
            reason=reason,
            tool_name=tool_name,
        )
        if text:
            _cache_put(key, text, int(cfg.get("cache_max_entries") or 128))
            return text
        return ""
    except Exception as exc:
        logger.debug("explain_command failed: %s", exc)
        return ""


def format_card_appendix(text: str, *, language: str = "zh") -> str:
    """Markdown appendix appended under the approval prompt body."""
    body = (text or "").strip()
    if not body:
        return ""
    label = SECTION_LABEL_ZH if (language or "zh").lower().startswith("zh") else SECTION_LABEL_EN
    return f"\n\n**{label}**\n{body}"


__all__ = [
    "explain",
    "explain_async",
    "explain_command",
    "maybe_explain_command",
    "format_card_appendix",
    "clear_cache",
    "SECTION_LABEL_ZH",
    "SECTION_LABEL_EN",
]
