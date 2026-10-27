"""Permanent ("Always") approval policy + overlay.yaml allowlist merge (C01).

Hard constraint for Feishu / QQ (and policy-wide when configured):
- ``config.owner.approvals.allow_permanent`` defaults to **False**
- UI must not offer Always / 始终允许 when the gate is off
- ``command_allowlist`` from overlay.yaml is still **unioned into memory** so
  operator-curated patterns keep working; the UI just cannot mint new permanent
  grants via the Always button

Official ``tools/approval.py`` only calls the thin helpers here.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable, Set

logger = logging.getLogger(__name__)


def get_allow_permanent() -> bool:
    """Return whether permanent ("Always") approval may be offered.

    Reads ``config.owner.approvals.allow_permanent`` (from overlay.yaml via apply_owner_overlay).
    Fail-open default: **False** (safer — must opt in explicitly).
    """
    try:
        from hermes_cli.config import load_config_readonly

        owner = load_config_readonly().get("owner") or {}
        approvals = owner.get("approvals") if isinstance(owner, dict) else None
        if not isinstance(approvals, dict):
            return False
        return bool(approvals.get("allow_permanent", False))
    except Exception as exc:
        logger.debug("get_allow_permanent failed: %s", exc)
        return False


def gate_allow_permanent(flag: bool) -> bool:
    """AND *flag* with :func:`get_allow_permanent` (never raise)."""
    if not flag:
        return False
    try:
        return bool(get_allow_permanent())
    except Exception:
        return False


def owner_command_allowlist() -> Set[str]:
    """``config.owner.approvals.command_allowlist`` as a set of strings (fail-open ``set()``)."""
    try:
        from hermes_cli.config import load_config_readonly

        owner = load_config_readonly().get("owner") or {}
        approvals = owner.get("approvals") if isinstance(owner, dict) else None
        if not isinstance(approvals, dict):
            return set()
        raw = approvals.get("command_allowlist") or []
        if not isinstance(raw, list):
            return set()
        return {str(item) for item in raw if isinstance(item, str) and item.strip()}
    except Exception as exc:
        logger.debug("owner_command_allowlist failed: %s", exc)
        return set()


def merge_owner_command_allowlist(patterns: Iterable[str]) -> Set[str]:
    """Union *patterns* with :func:`owner_command_allowlist`."""
    merged = set(patterns or ())
    merged.update(owner_command_allowlist())
    return merged


def sanitize_permanent_choice(choice: str) -> str:
    """When permanent is disabled, degrade ``always`` → ``session`` (no disk write of Always).

    Keeps the command approved for the current session so an old Always click
    still unblocks the turn without minting a permanent grant.
    """
    if choice != "always":
        return choice
    try:
        if get_allow_permanent():
            return choice
    except Exception:
        pass
    return "session"
