"""Feishu WS reconnect guard — hung SDK ladder + capped supervisor rebuilds.

Root cause (2026-11-02, local gateway): keepalive ping timeout → SDK logs
"trying to reconnect for the 1st time" then stalls inside sync
``requests.post`` in ``Client._get_conn_url`` (no timeout). The WS thread
stays alive, so ``_supervise_websocket_thread`` never rebuilds; the process
looks healthy while Feishu inbound is deaf until a whole gateway restart.

Policy (user): do **not** restart the gateway process; ~10 min between
supervisor rebuilds; single in-flight rebuild; finite SDK ladder; cap
consecutive failures then degrade to alert + stop auto-retry (no multi-day
empty spin leaking tasks/FDs).

Core lives here; ``plugins/platforms/feishu/adapter.py`` only thin ``# [owner]`` glue.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Process-wide requests.post shim: per-thread timeout via TLS (safe under multiplex).
_POST_SHIM_LOCK = threading.Lock()
_POST_SHIM_INSTALLED = False
_post_timeout_tls = threading.local()


@dataclass(frozen=True)
class WsReconnectPolicy:
    """Tunables; overlay ``feishu.ws_reconnect_guard`` overrides DEFAULTS."""

    enabled: bool = True
    # Force finite SDK ladder so a failed reconnect exits the receive loop and
    # hands off to the supervisor (server ClientConfig can otherwise leave -1).
    sdk_reconnect_count: int = 2
    # Bound the hung ``_get_conn_url`` / first ``_try_connect``.
    conn_url_timeout_s: float = 30.0
    # Supervisor waits after a dead WS thread (first rebuild can be faster).
    first_supervisor_retry_s: float = 30.0
    supervisor_retry_interval_s: float = 600.0  # ~10 min
    # After this many consecutive rebuild cycles without ``_ws_link_up``, stop.
    max_failures: int = 18  # ~3h at 10 min, then alert + stop


_DEFAULT_POLICY = WsReconnectPolicy()


@dataclass
class _GuardState:
    failures: int = 0
    stopped: bool = False
    rebuild_inflight: bool = False


# Keyed by id(adapter): FeishuAdapter is long-lived; tests call clear_states().
# (SimpleNamespace stubs are not weakref-able.)
_states: dict[int, _GuardState] = {}


def _state_for(adapter: Any) -> _GuardState:
    key = id(adapter)
    st = _states.get(key)
    if st is None:
        st = _GuardState()
        _states[key] = st
    return st


def clear_states() -> None:
    """Test helper / disconnect hygiene."""
    _states.clear()


def drop_state(adapter: Any) -> None:
    _states.pop(id(adapter), None)


def load_policy() -> WsReconnectPolicy:
    """Fail-open load from overlay ``feishu.ws_reconnect_guard``."""
    try:
        from owner.patch_config import load_patch_config

        raw = (load_patch_config() or {}).get("feishu", {}) or {}
        section = raw.get("ws_reconnect_guard") or {}
        if not isinstance(section, dict):
            return _DEFAULT_POLICY
        base = _DEFAULT_POLICY
        return WsReconnectPolicy(
            enabled=bool(section.get("enabled", base.enabled)),
            sdk_reconnect_count=int(
                section.get("sdk_reconnect_count", base.sdk_reconnect_count)
            ),
            conn_url_timeout_s=float(
                section.get("conn_url_timeout_s", base.conn_url_timeout_s)
            ),
            first_supervisor_retry_s=float(
                section.get("first_supervisor_retry_s", base.first_supervisor_retry_s)
            ),
            supervisor_retry_interval_s=float(
                section.get(
                    "supervisor_retry_interval_s", base.supervisor_retry_interval_s
                )
            ),
            max_failures=int(section.get("max_failures", base.max_failures)),
        )
    except Exception as exc:  # pragma: no cover - fail-open
        logger.debug("[Feishu] ws_reconnect_guard policy load failed: %s", exc)
        return _DEFAULT_POLICY


def supervisor_wait_s(failures_before_wait: int, policy: WsReconnectPolicy) -> float:
    """Seconds to sleep before the next supervisor rebuild attempt."""
    if failures_before_wait <= 0:
        return max(0.0, policy.first_supervisor_retry_s)
    return max(0.0, policy.supervisor_retry_interval_s)


def should_stop_auto_retry(failures: int, policy: WsReconnectPolicy) -> bool:
    return failures >= max(1, policy.max_failures)


def note_link_up(adapter: Any) -> None:
    """Successful handshake — clear failure streak / stop latch."""
    st = _state_for(adapter)
    st.failures = 0
    st.stopped = False


def note_retrying(adapter: Any) -> None:
    """SDK ladder started; no counter change (hung attempt still in-flight)."""
    _state_for(adapter)  # ensure state exists


def _ensure_requests_post_shim() -> None:
    global _POST_SHIM_INSTALLED
    with _POST_SHIM_LOCK:
        if _POST_SHIM_INSTALLED:
            return
        import requests

        real_post = requests.post

        def _post_with_optional_timeout(*args: Any, **kwargs: Any) -> Any:
            timeout = getattr(_post_timeout_tls, "value", None)
            if timeout is not None:
                kwargs.setdefault("timeout", timeout)
            return real_post(*args, **kwargs)

        requests.post = _post_with_optional_timeout  # type: ignore[assignment]
        _POST_SHIM_INSTALLED = True


def _wrap_get_conn_url(ws_client: Any, timeout_s: float) -> None:
    """Ensure ``Client._get_conn_url`` cannot block the WS loop forever."""
    if getattr(ws_client, "_owner_conn_url_wrapped", False):
        return
    _ensure_requests_post_shim()
    original = ws_client._get_conn_url

    def _guarded() -> str:
        _post_timeout_tls.value = timeout_s
        try:
            return original()
        finally:
            _post_timeout_tls.value = None

    ws_client._get_conn_url = _guarded
    ws_client._owner_conn_url_wrapped = True


def apply_ws_client_overrides(ws_client: Any, adapter: Any) -> None:
    """Force finite SDK reconnect count + conn-url timeout on this client.

    Called from ``_apply_runtime_ws_overrides`` (also re-entered after server
    ``_configure``, which would otherwise overwrite ``_reconnect_count``).
    """
    policy = load_policy()
    if not policy.enabled:
        return
    try:
        # Positive finite ladder; never leave -1 (infinite) after our override.
        count = max(1, int(policy.sdk_reconnect_count))
        ws_client._reconnect_count = count
        _wrap_get_conn_url(ws_client, max(1.0, float(policy.conn_url_timeout_s)))
    except Exception as exc:  # pragma: no cover
        logger.debug("[Feishu] apply_ws_client_overrides failed: %s", exc)


async def supervise_websocket_thread(adapter: Any) -> None:
    """Capped ~10min rebuild loop; single in-flight; stop after max_failures.

    Replaces the adapter's open-ended exponential backoff (capped at 60s) which
    never helped when the SDK ladder hung inside the still-alive thread, and
    which would spin forever if the thread kept dying.
    """
    policy = load_policy()
    if not policy.enabled:
        await _legacy_supervise(adapter)
        return

    st = _state_for(adapter)
    last_dead: Optional[asyncio.Future] = None

    while getattr(adapter, "_running", False):
        ws_future = getattr(adapter, "_ws_future", None)
        if ws_future is None:
            return
        try:
            await asyncio.shield(ws_future)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass

        if not getattr(adapter, "_running", False) or getattr(adapter, "_ws_client", None) is None:
            return

        if st.stopped:
            # Cap reached: park (infrequent wake) until note_link_up clears latch
            # or disconnect. No rebuild — avoids multi-day empty spin.
            await asyncio.sleep(min(60.0, policy.supervisor_retry_interval_s))
            continue

        if ws_future is not last_dead:
            # A prior supervised thread died without note_link_up → count failure.
            if last_dead is not None:
                st.failures += 1
                if should_stop_auto_retry(st.failures, policy):
                    _trip_stop(
                        adapter, st, policy, reason="repeated ws thread exit"
                    )
                    last_dead = ws_future
                    continue
            last_dead = ws_future
            wait_s = supervisor_wait_s(st.failures, policy)
            logger.error(
                "[Feishu] WebSocket client thread exited unexpectedly; "
                "supervisor rebuild in %.0fs (failures=%d/%d)",
                wait_s,
                st.failures,
                policy.max_failures,
            )
            write = getattr(adapter, "_write_runtime_status_safe", None)
            if callable(write):
                write(
                    "ws_link_lost",
                    platform_state="retrying",
                    error_code=None,
                    error_message="Feishu websocket link lost; rebuilding",
                )
            await asyncio.sleep(wait_s)
        else:
            # Same dead future after a failed rebuild — interval cadence.
            await asyncio.sleep(supervisor_wait_s(max(1, st.failures), policy))

        if not getattr(adapter, "_running", False) or st.stopped:
            continue
        if st.rebuild_inflight:
            continue
        st.rebuild_inflight = True
        try:
            connect = getattr(adapter, "_connect_websocket", None)
            if connect is None:
                return
            await connect()
        except Exception as exc:
            st.failures += 1
            logger.warning(
                "[Feishu] WebSocket restart failed (%d/%d): %s",
                st.failures,
                policy.max_failures,
                exc,
            )
            if should_stop_auto_retry(st.failures, policy):
                _trip_stop(adapter, st, policy, reason=str(exc))
        finally:
            st.rebuild_inflight = False


def _trip_stop(
    adapter: Any, st: _GuardState, policy: WsReconnectPolicy, *, reason: str
) -> None:
    st.stopped = True
    logger.error(
        "[Feishu] WS reconnect guard: stopping auto-retry after %d failures "
        "(max=%d); reason=%s. Fix network/credentials then restart the Feishu "
        "platform or gateway; will not spin for days.",
        st.failures,
        policy.max_failures,
        reason,
    )
    write = getattr(adapter, "_write_runtime_status_safe", None)
    if callable(write):
        write(
            "ws_reconnect_cap",
            platform_state="disconnected",
            error_code="ws_reconnect_cap",
            error_message=(
                f"Feishu WS auto-reconnect stopped after {st.failures} failures"
            ),
        )


async def _legacy_supervise(adapter: Any) -> None:
    """Pre-guard exponential backoff (used when policy.enabled is false)."""
    backoff = initial_backoff = float(getattr(adapter, "_ws_restart_backoff", 5.0))
    last_dead: Optional[asyncio.Future] = None
    while getattr(adapter, "_running", False):
        ws_future = getattr(adapter, "_ws_future", None)
        if ws_future is None:
            return
        try:
            await asyncio.shield(ws_future)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        if not getattr(adapter, "_running", False) or getattr(adapter, "_ws_client", None) is None:
            return
        if ws_future is not last_dead:
            logger.error(
                "[Feishu] WebSocket client thread exited unexpectedly; restarting in %.0fs",
                backoff,
            )
            last_dead = ws_future
            write = getattr(adapter, "_write_runtime_status_safe", None)
            if callable(write):
                write(
                    "ws_link_lost",
                    platform_state="retrying",
                    error_code=None,
                    error_message="Feishu websocket link lost; rebuilding",
                )
        await asyncio.sleep(backoff)
        if not getattr(adapter, "_running", False):
            return
        try:
            await adapter._connect_websocket()
            backoff = initial_backoff
        except Exception as exc:
            logger.warning("[Feishu] WebSocket restart failed (retrying): %s", exc)
            backoff = min(backoff * 2, 60.0)
