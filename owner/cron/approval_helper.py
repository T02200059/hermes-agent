"""Approval-system helper for detecting cron sessions."""

from gateway.session_context import get_session_env

from owner.cron.session_context import _CRON_SESSION  # registers _VAR_MAP entry


def owner_cron_is_active() -> bool:
    """Return True if the current context is a cron session.

    Prefers the ContextVar set by run_job(); falls back to os.environ for
    CLI/test compatibility and legacy callers.
    """
    return bool(get_session_env("HERMES_CRON_SESSION", ""))
