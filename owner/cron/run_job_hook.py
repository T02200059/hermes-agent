"""Set/reset the HERMES_CRON_SESSION ContextVar around run_job()."""

import os
from contextvars import Token
from typing import Optional

from owner.cron.session_context import _CRON_SESSION


def owner_cron_session_enter() -> Token:
    """Mark the current context as a cron session.

    Replaces the legacy ``os.environ["HERMES_CRON_SESSION"] = "1"`` write
    that leaked across scheduler worker threads.
    """
    return _CRON_SESSION.set("1")


def owner_cron_session_exit(token: Optional[Token] = None) -> None:
    """Reset the cron ContextVar and defensively scrub os.environ."""
    if token is not None:
        try:
            _CRON_SESSION.reset(token)
        except Exception:
            pass
    os.environ.pop("HERMES_CRON_SESSION", None)
