"""Register the HERMES_CRON_SESSION ContextVar in gateway.session_context.

This module is imported early (via owner.cron) so that
``gateway.session_context._VAR_MAP`` contains ``HERMES_CRON_SESSION`` before
any cron/scheduler or approval code reads it.

Must be imported before any code accesses
``_VAR_MAP["HERMES_CRON_SESSION"]`` or
``get_session_env("HERMES_CRON_SESSION", ...)``.

Why this import deliberately stays **hard** (unlike the other official-private
dependencies listed in owner/docs/owner改动清单.md §16.13)
----------------------------------------------------------------------------
``_VAR_MAP`` / ``_UNSET`` are official **private** symbols, and this module's
entire purpose is to inject into them. Two properties make a soft fallback the
*wrong* choice here:

1. There is nothing to fall back **to**. If ``_VAR_MAP`` is gone the
   registration cannot happen at all, so ``get_session_env`` would stop seeing
   the cron session — cron jobs would silently lose their session context
   instead of the feature failing to start. A silent partial feature is worse
   than a loud startup error.
2. ``_UNSET`` **is** the sentinel. It is used as the ContextVar's ``default``
   and compared by identity somewhere upstream, so substituting a local
   placeholder would change those comparisons rather than degrade them.

So a rename upstream must fail loudly here, and
``tests/owner/test_upstream_private_symbol_deps.py`` pins both symbols plus the
registration having actually landed, so the breakage names itself in CI instead
of appearing as "cron jobs lost their session".
"""

from contextvars import ContextVar

from gateway.session_context import _UNSET, _VAR_MAP

_CRON_SESSION: ContextVar = ContextVar("HERMES_CRON_SESSION", default=_UNSET)

_VAR_MAP["HERMES_CRON_SESSION"] = _CRON_SESSION
