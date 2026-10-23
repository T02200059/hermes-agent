"""Credential validation helpers for /providers listing (C02).

Merges with official ``hermes_cli.auth.KNOWN_PROVIDER_KEY_PREFIXES`` (do not
duplicate openrouter here). Owner extras cover Copilot GitHub token shapes and
alibaba-coding-plan ``sk-sp`` keys.

Removability: delete this module and listing falls back to any(non-empty env).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Callable, Optional, Union

logger = logging.getLogger(__name__)

# Owner-only extras. Official prefixes live in hermes_cli.auth.KNOWN_PROVIDER_KEY_PREFIXES.
_OWNER_EXTRA_PREFIXES: dict[str, tuple[str, ...]] = {
    # Classic PATs (ghp_*) are rejected by the Copilot API — omit them intentionally.
    "copilot": ("gho_", "github_pat_", "ghu_"),
    "alibaba-coding-plan": ("sk-sp",),
}


def _merged_prefix_map() -> dict[str, tuple[str, ...]]:
    """Official prefixes first, then owner extras (union on overlap)."""
    merged: dict[str, tuple[str, ...]] = {}
    try:
        from hermes_cli.auth import KNOWN_PROVIDER_KEY_PREFIXES

        for key, prefixes in (KNOWN_PROVIDER_KEY_PREFIXES or {}).items():
            merged[str(key)] = tuple(prefixes or ())
    except Exception:
        pass
    for key, prefixes in _OWNER_EXTRA_PREFIXES.items():
        if key in merged:
            merged[key] = tuple(dict.fromkeys([*merged[key], *prefixes]))
        else:
            merged[key] = tuple(prefixes)
    return merged


def has_valid_github_token(env_vars: Union[tuple, list], read_env: Optional[Callable] = None) -> bool:
    """Backward-compatible Copilot GitHub token check (non-classic PAT)."""
    return has_valid_env_credential(env_vars, "copilot", read_env=read_env)


def has_valid_env_credential(
    env_vars: Union[tuple, list],
    provider: str = "",
    read_env: Optional[Callable] = None,
) -> bool:
    """True when any env var holds a usable key for *provider*.

    When *provider* declares prefixes (official ∪ owner), only matching values
    count. Providers with no declared prefix stay fail-open (any non-empty).
    """
    getter = read_env or os.environ.get
    prefixes = _merged_prefix_map().get(str(provider or "").strip().lower(), ())
    for ev in env_vars or ():
        val = getter(ev) or ""
        if not val:
            continue
        if prefixes and not str(val).startswith(prefixes):
            logger.debug(
                "Skipping %s=%s... (prefix does not match %s for provider %s)",
                ev, str(val)[:8], prefixes, provider,
            )
            continue
        return True
    return False


def is_token_expired(expires_at: str | None) -> bool:
    """True when *expires_at* (ISO 8601) is in the past.

    Missing / unparseable timestamps fail open (treated as not expired).
    """
    if not expires_at:
        return False
    try:
        exp_dt = datetime.fromisoformat(expires_at)
        return datetime.now(timezone.utc) > exp_dt
    except Exception:
        return False
