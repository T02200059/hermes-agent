"""
Session-scoped context variables for the Hermes gateway.

Replaces the previous ``os.environ``-based session state
(``HERMES_SESSION_PLATFORM``, ``HERMES_SESSION_CHAT_ID``, etc.) with
Python's ``contextvars.ContextVar``.

**Why this matters**

The gateway processes messages concurrently via ``asyncio``.  When two
messages arrive at the same time the old code did:

    os.environ["HERMES_SESSION_THREAD_ID"] = str(context.source.thread_id)

Because ``os.environ`` is *process-global*, Message A's value was
silently overwritten by Message B before Message A's agent finished
running.  Background-task notifications and tool calls therefore routed
to the wrong thread.

``contextvars.ContextVar`` values are *task-local*: each ``asyncio``
task (and any ``run_in_executor`` thread it spawns) gets its own copy,
so concurrent messages never interfere.

**Backward compatibility**

The public helper ``get_session_env(name, default="")`` mirrors the old
``os.getenv("HERMES_SESSION_*", ...)`` calls.  Existing tool code only
needs to replace the import + call site:

    # before
    import os
    platform = os.getenv("HERMES_SESSION_PLATFORM", "")

    # after
    from gateway.session_context import get_session_env
    platform = get_session_env("HERMES_SESSION_PLATFORM", "")
"""

import os  # [owner] A4-2: upstream get_session_env falls back to os.environ
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

# Sentinel to distinguish "never set in this context" from "explicitly set to empty".
# When a contextvar holds _UNSET, we fall back to os.environ (CLI/cron compat).
# When it holds "" (after clear_session_vars resets it), we return "" — no fallback.
_UNSET: Any = object()

# Process-level flag: has any code in this process bound a session via
# set_session_vars()? Concurrent multi-session hosts (the messaging gateway, the
# ACP adapter, the API server, the TUI, cron) all do; a pure single-process
# CLI/one-shot that never engages the session-context system does not.
#
# The subprocess-env bridge (tools/environments/local.py) reads this to choose
# its leak policy: when engaged, the ContextVars are authoritative and an _UNSET
# var means "no session bound in THIS task" — so a process-global os.environ
# mirror (written last-writer-wins by whatever concurrent session ran most
# recently) must NOT be inherited into a child process. When never engaged, the
# os.environ fallback is preserved (no concurrency to leak across). Monotonic
# latch — once any host binds a session, the process stays engaged for life.
_session_context_engaged: bool = False


_SESSION_VARS = (
    _SESSION_PLATFORM, _SESSION_SOURCE, _SESSION_CHAT_ID, _SESSION_CHAT_TYPE,
    _SESSION_CHAT_NAME, _SESSION_THREAD_ID, _SESSION_USER_ID, _SESSION_USER_ID_ALT,
    _SESSION_USER_NAME, _SESSION_SCOPE_ID, _SESSION_KEY, _SESSION_ID,
    _SESSION_UI_SESSION_ID, _SESSION_MESSAGE_ID, _SESSION_PROFILE,
    _BROWSER_CONTROL_PRINCIPAL, _BROWSER_CONTROL_TRANSPORT_FAMILY, _CRON_SESSION, _SESSION_PARENT_CHAT_ID,
) = tuple(ContextVar(name, default=_UNSET) for name in (
    "HERMES_SESSION_PLATFORM", "HERMES_SESSION_SOURCE", "HERMES_SESSION_CHAT_ID",
    "HERMES_SESSION_CHAT_TYPE", "HERMES_SESSION_CHAT_NAME", "HERMES_SESSION_THREAD_ID",
    "HERMES_SESSION_USER_ID", "HERMES_SESSION_USER_ID_ALT", "HERMES_SESSION_USER_NAME",
    "HERMES_SESSION_SCOPE_ID", "HERMES_SESSION_KEY", "HERMES_SESSION_ID",
    "HERMES_UI_SESSION_ID", "HERMES_SESSION_MESSAGE_ID", "HERMES_SESSION_PROFILE",
    "HERMES_BROWSER_CONTROL_PRINCIPAL", "HERMES_BROWSER_CONTROL_TRANSPORT_FAMILY",
    "HERMES_CRON_SESSION", "HERMES_SESSION_PARENT_CHAT_ID",
))
# [owner] A4-2: removed duplicate definition — the unpacked tuple above binds this name.


# Whether the current session's delivery channel can route an ASYNC completion
# back to the agent AFTER the current turn ends (i.e. wake a fresh turn).
#
# True  — long-lived CLI sessions (in-process completion_queue drain) and the
#         real gateway platforms (Telegram/Discord/Slack/...), which hold a
#         persistent outbound channel and run the watcher/drain loops.
# False — finite runtimes that can end before a detached completion returns:
#         stateless API-server requests and dispatcher-spawned Kanban workers.
#
# Tools that promise async delivery (terminal notify_on_complete /
# watch_patterns, delegate_task background=True) read this via
# ``async_delivery_supported()`` and refuse to hand out a promise the channel
# can't keep — turning a silent no-op into an explicit contract.
#
# Default _UNSET => treated as supported, so CLI (which never sets a platform)
# and any contextvar-unaware path keep working. Stateless adapters opt OUT by
# setting ``supports_async_delivery = False`` on the adapter class; the gateway
# propagates that into this contextvar at session-bind time.
_SESSION_ASYNC_DELIVERY: ContextVar = ContextVar("HERMES_SESSION_ASYNC_DELIVERY", default=_UNSET)

# [owner] A4-2: forward-ported — session_history_delivery / wake authority proof.
_SESSION_HISTORY_DELIVERY: ContextVar = ContextVar("HERMES_SESSION_HISTORY_DELIVERY", default=_UNSET)

# [owner] A4-2: upstream form — single _VAR_MAP over the unpacked _SESSION_VARS
# Cron auto-delivery vars, set per-job in run_job() so concurrent jobs don't clobber.
_CRON_AUTO_DELIVER_PLATFORM = ContextVar("HERMES_CRON_AUTO_DELIVER_PLATFORM", default=_UNSET)
_CRON_AUTO_DELIVER_CHAT_ID = ContextVar("HERMES_CRON_AUTO_DELIVER_CHAT_ID", default=_UNSET)
_CRON_AUTO_DELIVER_THREAD_ID = ContextVar("HERMES_CRON_AUTO_DELIVER_THREAD_ID", default=_UNSET)

# Legacy env-var name -> ContextVar for get_session_env (_SESSION_ASYNC_DELIVERY deliberately
# absent: it is a bool capability, read via async_delivery_supported).
_VAR_MAP = {var.name: var for var in (
    *_SESSION_VARS, _CRON_AUTO_DELIVER_PLATFORM, _CRON_AUTO_DELIVER_CHAT_ID,
    _CRON_AUTO_DELIVER_THREAD_ID,
)}



def set_current_session_id(session_id: str) -> None:
    """Synchronize ``HERMES_SESSION_ID`` across ContextVar and ``os.environ``.

    Long-lived single-process entrypoints like the CLI can rotate sessions via
    ``/new``, ``/resume``, ``/branch``, or compression splits without
    reconstructing the entire agent. Tools still consult
    ``get_session_env("HERMES_SESSION_ID")`` with an ``os.environ`` fallback,
    so both storage paths must move together when the active session changes.

    Delegated subagent children are the exception: they are constructed inside
    the parent process within ``delegated_child_context()``, and their
    ``AIAgent.__init__`` calls this same helper. Writing a child's internal
    session id to ``os.environ`` (process-global) would clobber the parent's
    ``HERMES_SESSION_ID`` for the rest of the process — leaking the child id
    into parent tools and subprocesses spawned after the child was built. The
    ContextVar write below is task-local and safe for concurrent children; only
    the process-global ``os.environ`` mirror is suppressed for delegated
    children. Root agents (CLI, gateway, cron) keep both paths.
    """
    import os

    _SESSION_ID.set(session_id)

    # Skip the process-global os.environ write for delegated children. The
    # child's own tools and subprocesses still resolve their id through the
    # ContextVar (task-local), while the parent's process-wide env keeps the
    # parent's session identity. See HermesPRDelegationSessionContext task.
    try:
        from agent.delegation_context import is_delegated_child_context

        if is_delegated_child_context():
            return
    except Exception:
        pass

    os.environ["HERMES_SESSION_ID"] = session_id


@contextmanager
def scoped_current_session_id(session_id: str | None = None) -> Iterator[None]:
    """Bind a task-local session id and restore the prior value on exit.

    With ``session_id=None`` this acts as a save/restore boundary around code
    that may call :func:`set_current_session_id` itself (notably delegated
    ``AIAgent`` construction).  It intentionally never mutates ``os.environ``.
    """
    previous = _SESSION_ID.get()
    if session_id is not None:
        _SESSION_ID.set(session_id)
    try:
        yield
    finally:
        _SESSION_ID.set(previous)


# [owner] A4-2: upstream form (parent_chat_id + session_history_delivery params)
def set_session_vars(
    platform: str = "", source: str = "", chat_id: str = "", chat_type: str = "",
    chat_name: str = "", thread_id: str = "", user_id: str = "", user_id_alt: str = "",
    user_name: str = "", scope_id: str = "", session_key: str = "", session_id: str = "",
    message_id: str = "", profile: str = "", browser_control_principal: str = "",
    browser_control_transport_family: str = "", cwd: str = "", async_delivery: bool = True,
    ui_session_id: str = "", cron_session: Any = _UNSET, parent_chat_id: str = "",
    session_history_delivery: str | None = None,
) -> list:
    """Set all session context variables and return reset tokens.  Call
    ``clear_session_vars(tokens)`` in a ``finally``; not nestable, clearing resets every var
    to ``""`` rather than restoring prior values (tokens are accepted only for API compat).

    ``session_history_delivery`` declares whether the bound chat id is one the client can address again:
    ``"1"`` (audited producers — explicit session-id header, native API sessions, /v1/runs) or
    ``""`` / omitted (default-deny, #98619).  ``None`` leaves the var at ``_UNSET`` ("never
    declared"), which ``session_history_delivery_supported()`` treats as NOT capable — an omitted declaration
    cannot grant wake authority."""
    global _session_context_engaged
    _session_context_engaged = True
    values = (
        platform, source, chat_id, chat_type, chat_name, thread_id, user_id, user_id_alt,
        user_name, scope_id, session_key, session_id, ui_session_id, message_id, profile,
        browser_control_principal, browser_control_transport_family, cron_session, parent_chat_id,
    )
    tokens = [var.set(value) for var, value in zip(_SESSION_VARS, values)]
    tokens.append(_SESSION_ASYNC_DELIVERY.set(bool(async_delivery)))
    tokens.append(_SESSION_HISTORY_DELIVERY.set(_UNSET if session_history_delivery is None else session_history_delivery))
    _runtime_cwd("set_session_cwd", cwd)
    return tokens


# [owner] A4-2: upstream form (cron_session tri-state + async-delivery sentinel semantics)
def clear_session_vars(tokens: list) -> None:
    """Mark session context variables as explicitly cleared (``""``, not ``_UNSET``), so
    ``get_session_env`` returns empty instead of stale ``os.environ`` values.  Async-delivery
    goes back to ``_UNSET``: a cleared context is default-supported, not opted-out.  Wake
    capability goes back to ``_UNSET`` too — but for the opposite reason: a cleared context has
    declared nothing, and an undeclared capability FAILS CLOSED (#98619)."""
    for var in _SESSION_VARS:
        var.set("")
    _SESSION_ASYNC_DELIVERY.set(_UNSET)
    _SESSION_HISTORY_DELIVERY.set(_UNSET)
    _runtime_cwd("clear_session_cwd")


# [owner] A4-2: upstream form (cron_session tri-state + async-delivery sentinel semantics)
def reset_session_vars() -> None:
    """Reset every session var to ``_UNSET`` ("never bound here") for THIS context.  Call at
    the top of a fresh task *before* it binds: ``create_task`` snapshots the context, so B's
    task inherits A's already-set vars and a subprocess spawned before B binds would read A's
    identity.  ``_SESSION_ASYNC_DELIVERY`` and ``_SESSION_HISTORY_DELIVERY`` (outside ``_VAR_MAP``)
    are reset explicitly too."""
    for var in _VAR_MAP.values():
        var.set(_UNSET)
    _SESSION_ASYNC_DELIVERY.set(_UNSET)
    _SESSION_HISTORY_DELIVERY.set(_UNSET)
    _runtime_cwd("clear_session_cwd")


# [owner] A4-2: upstream form (walrus + explicit _UNSET semantics)
def get_session_env(name: str, default: str = "") -> str:
    """Read a session var by legacy ``HERMES_SESSION_*`` name; drop-in for os.getenv.  The
    ContextVar wins if ever set here (even to ``""``); else ``os.environ``; else *default*."""
    var = _VAR_MAP.get(name)
    if var is not None and (value := var.get()) is not _UNSET:
        return value
    return os.getenv(name, default)


# Surfaces that are not a human chat channel. The gateway binds a platform
# value (``telegram``) to HERMES_SESSION_PLATFORM, while the CLI, TUI, and
# desktop bind HERMES_SESSION_SOURCE (``cli``, ``tui``, ``desktop``) and leave
# the platform empty — so both have to be consulted. ``local``, ``api_server``,
# ``webhook``, and ``msgraph_webhook`` are real Platform values that reach
# HERMES_SESSION_PLATFORM but have no attachment channel behind them.
# Default-deny: an unrecognized identity counts as messaging so a newly added
# chat platform is never treated as a private surface before this set is
# updated. Mirrors LOCAL_SESSION_SOURCE_IDS in
# apps/desktop/src/lib/session-source.ts; keep roughly in sync when adding a
# local or programmatic surface.
NON_MESSAGING_SESSION_SURFACES = frozenset(
    {
        "",
        "api_server",
        "cli",
        "codex",
        "desktop",
        "gateway",
        "kanban",
        "local",
        "msgraph_webhook",
        "tool",
        "tui",
        "webhook",
    }
)


def session_is_messaging_surface() -> bool:
    """Whether this turn is delivered over a human messaging channel.

    Callers use this to decide anything that differs between "the user is
    reading a chat message" and "the user is at a machine they own": whether
    to emit a delivery tag, whether a file has to land somewhere the gateway
    is allowed to send from, whether narration would read as chat noise.

    Resolves ``HERMES_PLATFORM``, then the session platform, then the session
    source, and reports messaging when any of them names a surface outside
    :data:`NON_MESSAGING_SESSION_SURFACES`.
    """
    import os

    platform = os.getenv("HERMES_PLATFORM") or get_session_env("HERMES_SESSION_PLATFORM", "")
    source = get_session_env("HERMES_SESSION_SOURCE", "")
    for identity in (platform, source):
        identity = str(identity or "").strip().lower()
        if identity and identity not in NON_MESSAGING_SESSION_SURFACES:
            return True
    return False


def declare_stateless_channel() -> None:
    """Declare that this session cannot receive an async background completion.

    Binds only the delivery capability, leaving every other session var unset.
    Use this instead of ``set_session_vars(async_delivery=False)`` on a pure
    single-process runner: ``set_session_vars`` also latches
    ``_session_context_engaged`` (see above), which switches the subprocess
    env bridge from "os.environ fallback" to "ContextVar-authoritative, strip on
    _UNSET" in ``tools/environments/local.py``. A one-shot CLI that never engages
    the session-context system must not flip that latch as a side effect of
    declaring a capability.

    Callers that already build a full session context (cron's ``run_job``) get
    the same state by passing ``async_delivery=False`` to ``set_session_vars``.

    A session that cannot take a late completion makes ``delegate_task`` fall
    through to its existing inline/synchronous path, so subagent results are
    returned within the turn instead of being dispatched to a channel that will
    never deliver them.

    See NousResearch/hermes-agent#53027 and #63142.
    """
    _SESSION_ASYNC_DELIVERY.set(False)


def async_delivery_supported() -> bool:
    """Whether the current session can deliver a background completion later.

    Returns ``False`` for finite runtimes that can end before a detached result
    is delivered: sessions explicitly bound by a stateless channel — an adapter
    that cannot route a notification back after the turn ends (the API server),
    or a one-shot runner that exits after its final response (``hermes -z``,
    cron — see :func:`declare_stateless_channel`) — and dispatcher-spawned
    Kanban workers (identified by ``HERMES_KANBAN_TASK``), which are one-shot
    ``chat -q`` subprocesses. The real gateway platforms, the interactive CLI,
    and any other path that never bound the contextvar return ``True``.

    Tools that promise async delivery (``terminal`` notify_on_complete /
    watch_patterns, ``delegate_task`` background=True) consult this before
    registering a watcher / dispatching a detached child, so they can refuse a
    promise the channel can't keep instead of silently no-op'ing.
    """
    import os

    # A Kanban worker is a one-shot subprocess. Its parent session and process
    # disappear after the quiet turn returns, so a completion queued later has
    # no durable consumer even though an ordinary CLI session can drain that
    # queue. Force tools onto their existing synchronous/polling fallbacks.
    if os.environ.get("HERMES_KANBAN_TASK"):
        return False

    value = _SESSION_ASYNC_DELIVERY.get()
    if value is _UNSET:
        return True
    return bool(value)


# [owner] cron: register HERMES_CRON_SESSION ContextVar (see owner/cron/session_context.py)
try:
    import owner.cron.session_context  # noqa: F401
except Exception:
    # Fail loud (but non-fatally): if registration is skipped, _VAR_MAP has no
    # HERMES_CRON_SESSION entry, so get_session_env() silently falls back to
    # os.environ and cron approval mode is never detected. A swallowed failure
    # here would hide that safety-relevant gap.
    import logging as _logging

    _logging.getLogger(__name__).warning(
        "owner.cron.session_context import failed; HERMES_CRON_SESSION ContextVar "
        "not registered — cron approval mode may not be detected",
        exc_info=True,
    )


# [owner] forward-ported from upstream (BASE 之后新增): run_busy's busy-ack reply chain
# (and other swapped hosts) resolve route metadata / session-id helpers through these.

def _runtime_cwd(func: str, *args: Any) -> None:
    """Best-effort call of ``agent.runtime_cwd.<func>``; import/runtime failures are ignored."""
    try:
        from agent import runtime_cwd
        getattr(runtime_cwd, func)(*args)
    except Exception:
        pass

def source_route_metadata(source: Any, metadata: dict | None) -> dict | None:
    """Keep inbound route anchors for durable deliveries after the source is gone."""
    anchors = {key: str(value) for key in ("scope_id", "parent_chat_id")
               if (value := getattr(source, key, None))}
    return {**(metadata or {}), **anchors} if anchors else metadata

def session_history_delivery_supported() -> bool:
    """Whether this request declares a server-history consumer for detached results.

    Fail closed on omitted bindings; never borrow authority from the environment."""
    return _SESSION_HISTORY_DELIVERY.get() == "1"
