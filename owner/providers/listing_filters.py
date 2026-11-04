"""Owner picker-row filters for /providers and model-switch listing (C26).

Keeps discovery usable while matching deployment preferences:
- drop Alibaba Coding Plan variants (pay-as-you-go only)
- collapse Alibaba pay-as-you-go duplicates to one preferred slug
- safety net for rows that slipped past prefix-aware credential checks

Removability: delete this module and stop calling ``filter_authenticated_provider_rows``;
listing falls back to the official unfiltered inventory.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

# Coding-plan / dedicated coding-tier slugs (not pay-as-you-go).
_ALIBABA_CODING_SLUGS = frozenset({
    "alibaba-coding-plan",
    "alibaba-coding-plan-cn",
    "alibaba-coding-cn",
    "alibaba_coding",
    "alibaba-coding",
    "dashscope-coding",
    "dashscope-coding-cn",
})

# Pay-as-you-go DashScope family. Prefer China endpoint for this deployment.
_ALIBABA_PAYGO_PREFERENCE = (
    "alibaba-cn",
    "dashscope-cn",
    "alibaba-cloud-cn",
    "alibaba",
    "dashscope",
)

_ALIBABA_PAYGO_SLUGS = frozenset({
    *_ALIBABA_PAYGO_PREFERENCE,
    "alibaba-cloud",
    "qwen-dashscope",
    "aliyun",
})


def _slug(row: dict[str, Any]) -> str:
    return str(row.get("slug") or "").strip().lower()


def filter_authenticated_provider_rows(
    rows: Iterable[dict[str, Any]],
    *,
    current_provider: str = "",
) -> list[dict[str, Any]]:
    """Return *rows* after owner listing preferences.

    Always keeps the current provider even when it would otherwise be dropped,
    so a saved selection never disappears from the picker.
    """
    current = str(current_provider or "").strip().lower()
    material = list(rows or [])

    kept: list[dict[str, Any]] = []
    paygo_candidates: list[dict[str, Any]] = []
    first_paygo_at: Optional[int] = None

    for row in material:
        slug = _slug(row)
        if not slug:
            continue
        if slug in _ALIBABA_CODING_SLUGS and slug != current:
            continue
        if slug in _ALIBABA_PAYGO_SLUGS:
            if first_paygo_at is None:
                first_paygo_at = len(kept)
            paygo_candidates.append(row)
            continue
        kept.append(row)

    preferred = _pick_alibaba_paygo(paygo_candidates, current=current)
    if preferred is not None:
        idx = 0 if first_paygo_at is None else first_paygo_at
        kept.insert(min(idx, len(kept)), preferred)

    return kept


def _pick_alibaba_paygo(
    candidates: list[dict[str, Any]],
    *,
    current: str,
) -> Optional[dict[str, Any]]:
    if not candidates:
        return None
    by_slug = {_slug(r): r for r in candidates}
    if current in by_slug:
        return by_slug[current]
    for pref in _ALIBABA_PAYGO_PREFERENCE:
        if pref in by_slug:
            return by_slug[pref]
    return candidates[0]


def allow_ambient_anthropic_listing() -> bool:
    """Ambient Claude Code keychain must not surface ``anthropic`` in pickers.

    Explicit ``ANTHROPIC_API_KEY`` / Hermes OAuth / pool entries are handled by
    the normal credential ladder before the ambient branch runs.
    """
    return False
