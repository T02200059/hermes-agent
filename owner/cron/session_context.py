"""Register the HERMES_CRON_SESSION ContextVar in gateway.session_context.

This module is imported early (via owner.cron) so that
``gateway.session_context._VAR_MAP`` contains ``HERMES_CRON_SESSION`` before
any cron/scheduler or approval code reads it.

Must be imported before any code accesses
``_VAR_MAP["HERMES_CRON_SESSION"]`` or
``get_session_env("HERMES_CRON_SESSION", ...)``.
"""

from contextvars import ContextVar

from gateway.session_context import _UNSET, _VAR_MAP

_CRON_SESSION: ContextVar = ContextVar("HERMES_CRON_SESSION", default=_UNSET)

_VAR_MAP["HERMES_CRON_SESSION"] = _CRON_SESSION
