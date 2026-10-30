"""Scrub session/cron env vars from the gateway process and restart watcher env.

# [owner] C16 thin gap — ContextVar is the cron authority; inherited os.environ
markers must not survive into a live gateway or its restart child, or
``get_session_env``'s os.environ fallback can misclassify chat as cron.
"""

from __future__ import annotations

_VARS_TO_SCRUB = (
    "HERMES_CRON_SESSION",
    "HERMES_SESSION_KEY",
    "HERMES_SESSION_ID",
)


def owner_cron_scrub_watcher_env(watcher_env: dict) -> None:
    """Remove stale HERMES_CRON_SESSION and related session markers.

    The restart watcher inherits os.environ from the dying gateway process.
    Without scrubbing, leaked session markers would propagate into the new
    gateway lifetime.
    """
    for var in _VARS_TO_SCRUB:
        watcher_env.pop(var, None)


def owner_cron_scrub_process_env() -> None:
    """Scrub leaked session/cron markers from the live ``os.environ``.

    Called once at gateway startup. Cron context now lives only in a ContextVar,
    so the gateway process should never carry HERMES_CRON_SESSION in os.environ.
    If a value were inherited from the launching environment,
    ``get_session_env``'s os.environ fallback would misclassify every live
    gateway message (whose context never sets the cron var) as a cron session
    and silently apply cron approval mode process-wide.
    """
    import os

    for var in _VARS_TO_SCRUB:
        os.environ.pop(var, None)
