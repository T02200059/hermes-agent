"""Gateway raw-text platform allowlist (CR-004 / upstream #39293).

Upstream lets four surfaces keep *un-redacted* raw status and error text:

    {"local", "api_server", "webhook", "msgraph_webhook"}

``api_server`` / ``webhook`` / ``msgraph_webhook`` accept **external traffic**,
so an attacker can deliberately trigger an error to elicit un-redacted
credentials in the reply. Owner therefore tightens the allowlist to the local
diagnostic surface only:

    {"local"}

This widens upstream's Telegram-only filter (#28533) to every chat gateway.
The rationale lives here rather than in ``gateway/run.py`` so that the official
file carries only a thin delegate and stops churning on upstream diffs.

Called from ``gateway/run.py`` as a thin ``# [owner]`` delegate.

Fail-closed by construction: this module exposes the *tight* set, so a missing
or broken delegate must fall back to ``{"local"}`` — never to upstream's wider
set. Callers must honour that (see the ``except`` branch in ``gateway/run.py``).
"""

from __future__ import annotations

from typing import FrozenSet

# Upstream's set — recorded for reference and for tests that assert the
# tightening is real.
UPSTREAM_RAW_TEXT_PLATFORMS: FrozenSet[str] = frozenset(
    {"local", "api_server", "webhook", "msgraph_webhook"}
)

# Owner's tightened set: local CLI/TUI diagnostics only.
OWNER_RAW_TEXT_PLATFORMS: FrozenSet[str] = frozenset({"local"})


def owner_raw_text_platforms() -> FrozenSet[str]:
    """Return the tightened allowlist for ``_GATEWAY_RAW_TEXT_PLATFORMS``."""
    return OWNER_RAW_TEXT_PLATFORMS


__all__ = [
    "OWNER_RAW_TEXT_PLATFORMS",
    "UPSTREAM_RAW_TEXT_PLATFORMS",
    "owner_raw_text_platforms",
]
