"""Credential validation helpers for /providers command.

Filter classic GitHub PATs (ghp_*) rejected by Copilot API,
check OAuth token expiration, and related utilities.

可移除性：删除此文件后，/providers 的 credential checks
回退到基本的 any(os.environ.get(...)) 检查，不过滤过期 token。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Union

logger = logging.getLogger(__name__)


def has_valid_github_token(env_vars: Union[tuple, list]) -> bool:
    """Check if any env var has a valid (non-classic-pat) GitHub token.

    Classic PATs (ghp_*) are not accepted by the Copilot API.
    Fine-grained PATs (github_pat_*) and device-code tokens (gho_*) are valid.
    Returns True on the first valid, non-empty, non-ghp_ token found.
    """
    import os as _os

    for ev in env_vars:
        val = _os.environ.get(ev, "")
        if not val:
            continue
        if ev == "GITHUB_TOKEN" and val.startswith("ghp_"):
            logger.debug(
                "Skipping ghp_* GITHUB_TOKEN (classic PAT not supported by Copilot API)"
            )
            continue
        return True
    return False


def is_token_expired(expires_at: str | None) -> bool:
    """Check if a token's expires_at timestamp is in the past.

    Accepts ISO 8601 strings (e.g. ``"2026-06-10T15:04:38+00:00"``).
    Returns True if expired, False if valid, missing, or unparseable
    (fail-open: unparseable dates are treated as "not expired").
    """
    if not expires_at:
        return False
    try:
        exp_dt = datetime.fromisoformat(expires_at)
        return datetime.now(timezone.utc) > exp_dt
    except Exception:
        return False
