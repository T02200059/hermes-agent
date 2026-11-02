"""英文回复启发式判定（对齐 viking_memory_lib.detect_non_chinese 的语气词思路）。

目标：区分「中文里夹英文术语」vs「整段变成英文」。
实现刻意保持小而自包含，不依赖 owner/scripts 扫描工具链。
"""

from __future__ import annotations

import re
from typing import Any, Optional

_CODE_FENCE_RE = re.compile(r"```[\s\S]*?```", re.MULTILINE)
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
_LATIN_WORD_RE = re.compile(r"[a-z\u00c0-\u024f]+", re.IGNORECASE)
_ZH_RE = re.compile(r"[\u4e00-\u9fff]")
_LATIN_CHAR_RE = re.compile(r"[A-Za-z\u00c0-\u024f]")

# Lightweight English function words (语气词/虚词) — 引用术语通常凑不齐密度。
_EN_STOPWORDS = set(
    "the a an and or but if then else when while for with without from to "
    "of in on at by as is are was were be been being this that these those "
    "it its they them their we our you your not no yes can could should "
    "would will just also more most other into about over after before "
    "have has had do does did so than too very only such same here there "
    "what which who whom how why where".split()
)

MIN_CHARS = 24
MIN_LATIN_CHARS = 40
MIN_EN_HITS = 5
MIN_EN_DENSITY = 0.10
MAX_ZH_RATIO = 0.30


def _strip_code(text: str) -> str:
    s = _CODE_FENCE_RE.sub(" ", text or "")
    s = _INLINE_CODE_RE.sub(" ", s)
    return s


def looks_like_english_reply(text: str) -> Optional[dict[str, Any]]:
    """若整段更像英文回复（而非中文夹术语），返回检测细节；否则 None。"""
    raw = (text or "").strip()
    if len(raw) < MIN_CHARS:
        return None
    sample = _strip_code(raw)
    if len(sample.strip()) < MIN_CHARS:
        return None

    words = _LATIN_WORD_RE.findall(sample.lower())
    zh_chars = len(_ZH_RE.findall(sample))
    latin_chars = len(_LATIN_CHAR_RE.findall(sample))
    total = zh_chars + latin_chars
    if total == 0:
        return None

    zh_ratio = zh_chars / total
    if zh_ratio > MAX_ZH_RATIO:
        return None
    if latin_chars < MIN_LATIN_CHARS:
        return None

    en_hits = sum(1 for w in words if w in _EN_STOPWORDS)
    en_density = en_hits / max(len(words), 1)
    if en_hits < MIN_EN_HITS or en_density < MIN_EN_DENSITY:
        # 低中文 + 大量拉丁但仍不足语气词 → 可能是专名/命令堆砌，不触发
        return None

    return {
        "language": "en",
        "stopword_hits": int(en_hits),
        "density": round(en_density, 3),
        "zh_ratio": round(zh_ratio, 3),
        "latin_chars": latin_chars,
        "zh_chars": zh_chars,
        "word_count": len(words),
        "reason": "english_heavy",
    }


# Short narration floor (progress/approval often < MIN_LATIN_CHARS of the long-form detector).
_SHORT_MIN_CHARS = 12
_SHORT_MIN_LATIN = 18
_SHORT_MAX_ZH_RATIO = 0.35


def looks_like_non_chinese_output(text: str) -> Optional[dict[str, Any]]:
    """Explainer-output gate: True-ish dict when the reply looks non-Chinese-primary.

    Reuses ``looks_like_english_reply`` (long English prose), then a short-latin
    fallback for brief narrations that never reach the long-form latin floor.
    Returns None when Chinese-primary, mixed-with-terms, or too little signal.
    """
    hit = looks_like_english_reply(text)
    if hit is not None:
        return hit

    raw = (text or "").strip()
    if len(raw) < _SHORT_MIN_CHARS:
        return None
    sample = _strip_code(raw)
    if len(sample.strip()) < _SHORT_MIN_CHARS:
        return None

    zh_chars = len(_ZH_RE.findall(sample))
    latin_chars = len(_LATIN_CHAR_RE.findall(sample))
    total = zh_chars + latin_chars
    if total == 0:
        return None
    zh_ratio = zh_chars / total
    # Enough Chinese already → accept (术语夹杂 OK).
    if zh_ratio >= 0.45 or zh_chars >= 8:
        return None
    if latin_chars < _SHORT_MIN_LATIN or zh_ratio > _SHORT_MAX_ZH_RATIO:
        return None
    return {
        "language": "en",
        "stopword_hits": 0,
        "density": 0.0,
        "zh_ratio": round(zh_ratio, 3),
        "latin_chars": latin_chars,
        "zh_chars": zh_chars,
        "word_count": len(_LATIN_WORD_RE.findall(sample.lower())),
        "reason": "short_latin_heavy",
    }

