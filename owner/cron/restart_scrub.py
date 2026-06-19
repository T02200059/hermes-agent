"""Scrub session/cron env vars from the gateway restart watcher env."""


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
