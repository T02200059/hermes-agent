"""Owner-specific utility helpers (kept out of official utils.py for sync hygiene)."""

from __future__ import annotations

from urllib.parse import urlparse


def normalize_bare_domain_base_url(base_url: str) -> str:
    """Auto-append ``/v1`` for bare-domain base URLs that have no path component.

    See owner/docs/v16改动清单.md P30 for rationale.
    """
    candidate = str(base_url or "").strip()
    if not candidate:
        return candidate
    try:
        parsed = urlparse(candidate)
        if parsed.scheme in ("http", "https") and not parsed.path.strip("/"):
            return candidate.rstrip("/") + "/v1"
    except Exception:
        pass
    return candidate