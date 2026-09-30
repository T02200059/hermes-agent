"""Gateway lifecycle display copy — profile tag + translation.

Owner-side home for the ``{profile_tag}`` injection (改动清单 §7.14): a named
profile, or a non-default ``HERMES_HOME`` (→ ``custom``), shows ``" [<name>]"``
in lifecycle / busy-drain messages so one-process-per-tenant fleets can tell
which process is shutting down or coming back online. The default profile stays
untagged, so single-profile installs keep the original wording.

Why the implementation lives here rather than in ``gateway/run.py``: upstream
split that file into ``gateway/run_*.py`` and defines neither helper, while the
split modules must stay self-sufficient. ``gateway/run.py`` keeps thin
delegations only while the monolith is still in use.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def profile_tag() -> str:
    """Return a display tag for lifecycle messages, e.g. ``" [coder]"``.

    Resolution order:

    1. ``HERMES_LIFECYCLE_LABEL`` env var — free-form display label for
       lifecycle / busy-drain messages only (Chinese, spaces, etc. allowed).
       Intended for one-process-per-tenant fleets that keep a stable
       ``HERMES_PROFILE`` id for routing while showing a human nickname.
    2. ``HERMES_PROFILE`` env var (set by ``-p`` / profile selection).
    3. ``get_active_profile_name()`` (inferred from ``HERMES_HOME`` path).

    ``HERMES_LIFECYCLE_LABEL`` is display-only: it is not validated as a profile
    id and is not used for routing, auth, or bot identity.

    Any resolution failure also returns ``""`` (falling back to the original
    message shape) and logs a warning — lifecycle notifications must never crash
    the shutdown/startup path over a missing profile id.
    """
    try:
        # Display override first — free-form, no profile-id constraints.
        label = (os.environ.get("HERMES_LIFECYCLE_LABEL") or "").strip()
        if label:
            return f" [{label}]"

        name = (os.environ.get("HERMES_PROFILE") or "").strip()
        if not name:
            from hermes_cli.profiles import get_active_profile_name

            name = get_active_profile_name()
    except Exception as exc:
        logger.warning(
            "Could not resolve active profile name for lifecycle messages; "
            "using untagged gateway text: %s",
            exc,
        )
        return ""

    if not isinstance(name, str) or not name.strip():
        logger.warning(
            "Active profile name is empty/invalid (%r); using untagged gateway text",
            name,
        )
        return ""

    name = name.strip()
    if name == "default":
        return ""
    return f" [{name}]"


def lifecycle_msg(key: str, **format_kwargs: Any) -> str:
    """Translate a gateway lifecycle key with an optional ``{profile_tag}``.

    Extra ``format_kwargs`` (e.g. ``count``, ``action``, ``boot_rev``) are
    forwarded to :func:`agent.i18n.t` alongside the resolved profile tag.
    """
    from agent.i18n import t

    return t(key, profile_tag=profile_tag(), **format_kwargs)
