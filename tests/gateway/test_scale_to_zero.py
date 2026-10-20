"""Unit tests for the scale-to-zero idle-detection pure logic (Phase 0).

Behaviour-contract tests (AGENTS.md): each conjunct of the idle predicate and
each clause of the arm-gate is exercised independently, not frozen against a
snapshot. The pure helpers in gateway/scale_to_zero.py take plain inputs so they
test without a live gateway.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from gateway.scale_to_zero import (
    DEFAULT_IDLE_TIMEOUT_MINUTES,
    SCALE_TO_ZERO_ENV,
    is_idle,
    messaging_is_relay_only_or_absent,
    parse_idle_timeout_seconds,
    scale_to_zero_enabled,
    should_arm,
)


# ── scale_to_zero_enabled (the Labs HERMES_SCALE_TO_ZERO stamp, D11/Q8=A) ────


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", " On "])
def test_enabled_truthy_values(value):
    assert scale_to_zero_enabled({SCALE_TO_ZERO_ENV: value}) is True


# ── parse_idle_timeout_seconds (config.yaml, D2) ─────────────────────────────


def test_timeout_parses_minutes_to_seconds():
    assert parse_idle_timeout_seconds(5) == 300.0
    assert parse_idle_timeout_seconds(10) == 600.0
    assert parse_idle_timeout_seconds("5") == 300.0


def test_timeout_invalid_values_degrade_to_default():
    # Behavior contract: bad config falls back to the module default (whatever
    # its current value), never to zero/negative — an instant-dormant gateway
    # is never the intent.
    for bad in (None, "", "nope", 0, -3):
        assert parse_idle_timeout_seconds(bad) == DEFAULT_IDLE_TIMEOUT_MINUTES * 60.0


# ── messaging_is_relay_only_or_absent (F6/D1) ────────────────────────────────


class _P:
    """Stand-in for a Platform enum member with a ``.value``."""

    def __init__(self, value):
        self.value = value


def test_relay_only_is_true():
    assert messaging_is_relay_only_or_absent([_P("relay")]) is True


def test_no_platform_is_true():
    # A Chronos-only / no-messaging-platform agent can scale to zero.
    assert messaging_is_relay_only_or_absent([]) is True


# ── should_arm (D1/D11/§3.4(1)) ──────────────────────────────────────────────


def test_arm_blocked_without_wake_url():
    # A suspended instance with no wake target is a black hole (§3.4(1)).
    assert should_arm(enabled=True, relay_only_or_absent=True, wake_url=None) is False
    assert should_arm(enabled=True, relay_only_or_absent=True, wake_url="") is False


# ── is_idle (D2/D3/F7) — each conjunct flips the result ──────────────────────


def _idle_kwargs(**over):
    base = dict(
        active_work_count=0,
        seconds_since_last_inbound=600.0,
        idle_timeout_seconds=300.0,
        has_live_background_work=False,
    )
    base.update(over)
    return base


def test_not_idle_with_running_agent():
    assert is_idle(**_idle_kwargs(active_work_count=1)) is False


def test_idle_exactly_at_threshold():
    # >= timeout is idle (boundary).
    assert is_idle(**_idle_kwargs(seconds_since_last_inbound=300.0)) is True




# ── suspend_self / self_suspend_available (the gateway-owned suspend call) ───
#
# Fly Proxy autostop is inbound-only and job-blind (and since mid-2026 no longer
# counts outbound sockets as activity), so the gateway suspends its own machine
# via the local flaps unix socket strictly after the idle predicate + dormant
# quiesce. These exercise the wire call against a real unix-socket fake flaps.


import os
import socket as _socket
import threading


from gateway.scale_to_zero import (  # noqa: E402 - grouped with their section
    FLY_APP_NAME_ENV,
    FLY_MACHINE_ID_ENV,
    self_suspend_available,
    suspend_self,
)

_FLY_ENV = {FLY_APP_NAME_ENV: "hermes-agent-stg-test", FLY_MACHINE_ID_ENV: "d891234f"}


# [owner] T2-21: restored from upstream — the owner prune replaced this fixture
# with bare tmp_path, but pytest's tmp_path nests deep enough on macOS that
# binding an AF_UNIX socket under it fails with "path too long" (sun_path is
# 104 bytes on Darwin). Production uses the fixed /.fly/api so this only
# affects the fake flaps server.
_SUN_PATH_MAX = 100


@pytest.fixture()
def short_sock_dir():
    """A directory short enough that ``<dir>/fly-api.sock`` fits in sun_path."""
    import shutil
    import tempfile

    candidates = [tempfile.gettempdir(), "/tmp"]
    for base in candidates:
        try:
            path = Path(tempfile.mkdtemp(prefix="s2z-", dir=base))
        except OSError:
            continue
        if len(str(path / "fly-api.sock").encode()) <= _SUN_PATH_MAX:
            break
        shutil.rmtree(path, ignore_errors=True)
    else:
        pytest.skip(f"no temp dir short enough for an AF_UNIX socket (tried {candidates})")
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _fake_flaps(tmp_path, status_line, capture):
    """One-shot unix-socket HTTP server standing in for flaps."""
    sock_path = str(tmp_path / "fly-api.sock")
    server = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
    server.bind(sock_path)
    server.listen(1)

    def serve():
        conn, _ = server.accept()
        with conn:
            conn.settimeout(5)
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
            capture.append(data)
            conn.sendall(
                f"HTTP/1.1 {status_line}\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{{}}".encode()
            )
        server.close()

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    return sock_path, t


def test_suspend_self_posts_suspend_for_this_machine(short_sock_dir):
    captured: list[bytes] = []
    sock_path, t = _fake_flaps(short_sock_dir, "200 OK", captured)
    assert suspend_self(_FLY_ENV, socket_path=sock_path) is True
    t.join(timeout=5)
    request = captured[0].decode()
    # The request must target THIS machine's suspend endpoint, per the Fly
    # Machines API (POST /v1/apps/{app}/machines/{id}/suspend on /.fly/api).
    assert request.startswith(
        "POST /v1/apps/hermes-agent-stg-test/machines/d891234f/suspend HTTP/1.1\r\n"
    )
    assert "Host: flaps\r\n" in request


def test_suspend_self_non_2xx_is_false_not_raise(short_sock_dir):
    captured: list[bytes] = []
    sock_path, t = _fake_flaps(short_sock_dir, "412 Precondition Failed", captured)
    assert suspend_self(_FLY_ENV, socket_path=sock_path) is False
    t.join(timeout=5)


def test_suspend_self_missing_socket_is_false_not_raise(tmp_path):
    # Fail-awake: a dead/absent flaps socket must never raise out of the watcher.
    assert suspend_self(_FLY_ENV, socket_path=str(tmp_path / "nope.sock")) is False


def test_suspend_self_requires_machine_identity(tmp_path):
    assert suspend_self({}, socket_path=str(tmp_path / "unused.sock")) is False


def test_self_suspend_available_needs_identity_and_socket():
    # No socket at /.fly/api in a test environment -> unavailable even with env.
    if not os.path.exists("/.fly/api"):
        assert self_suspend_available(_FLY_ENV) is False
    # Missing identity -> unavailable regardless of socket.
    assert self_suspend_available({}) is False


# ---------------------------------------------------------------------------
# [owner] T2-21: brokered_sleep_url's module-level symbols were dropped by the
# A4-2 forward-port (SLEEP_URL_ENV / _malformed_sleep_url_logged / urllib.parse
# import) — every call raised NameError, silently killing the NAS-brokered
# suspend lever (the watcher's except-swallow made it look like "no lever").
# Restored; these pin the function end-to-end without mocking it.
# ---------------------------------------------------------------------------


def test_brokered_sleep_url_symbols_are_defined():
    from gateway import scale_to_zero as stz

    assert stz.SLEEP_URL_ENV == "GATEWAY_RELAY_SLEEP_URL"
    assert stz._malformed_sleep_url_logged is False


def test_brokered_sleep_url_accepts_valid_https(caplog):
    from gateway.scale_to_zero import brokered_sleep_url

    url = "https://nas.internal/sleep?sig=abc"
    assert brokered_sleep_url({"GATEWAY_RELAY_SLEEP_URL": url}) == url


def test_brokered_sleep_url_rejects_missing_and_malformed(caplog):
    from gateway.scale_to_zero import brokered_sleep_url

    assert brokered_sleep_url({}) is None
    # non-https must be rejected with a single latched warning
    assert brokered_sleep_url({"GATEWAY_RELAY_SLEEP_URL": "ftp://nas/sleep"}) is None
    assert "malformed" in caplog.text.lower()


def test_suspend_available_with_brokered_url(monkeypatch):
    """A stamped broker URL is a suspend lever even without Fly sockets."""
    from gateway import scale_to_zero as stz

    monkeypatch.setenv("GATEWAY_RELAY_SLEEP_URL", "https://nas.internal/sleep?sig=x")
    monkeypatch.delenv("FLY_APP_NAME", raising=False)
    monkeypatch.delenv("FLY_MACHINE_ID", raising=False)
    assert stz.suspend_available() is True
