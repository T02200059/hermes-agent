"""C06c live LDAP E2E — opt-in via HERMES_LDAP_E2E=1.

Pytest sandboxes ``HERMES_HOME``, so this module does **not** read the live
overlay.yaml. Connection fields come from ``HERMES_LDAP_*`` env (defaults below
match the company directory topology already documented in overlay comments).

Negative bind does **not** need a real user password. Positive bind needs
``HERMES_LDAP_E2E_PASSWORD`` (+ optional ``HERMES_LDAP_E2E_LOGIN``).
"""

from __future__ import annotations

import asyncio
import os
import socket

import pytest

from owner.gateway import ldap_auth as la

_RUN = os.environ.get("HERMES_LDAP_E2E", "").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
pytestmark = pytest.mark.skipif(
    not _RUN, reason="set HERMES_LDAP_E2E=1 to run live LDAP E2E"
)

# Non-secret defaults (same topology as owner/config/overlay.yaml ldap:).
_DEFAULT_HOST = "10.10.100.150"
_DEFAULT_PORT = "389"
_DEFAULT_TEMPLATE = "cn={login},cn=people,dc=westhpc,dc=com"


@pytest.fixture(autouse=True)
def _reset():
    la.reset_for_tests()
    yield
    la.reset_for_tests()


def _tcp(host: str, port: int, timeout: float = 3.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@pytest.fixture
def live_cfg(monkeypatch):
    """Wire gate via env only (sandbox-proof); never touch production home."""
    host = os.environ.get("HERMES_LDAP_HOST", _DEFAULT_HOST).strip() or _DEFAULT_HOST
    port = os.environ.get("HERMES_LDAP_PORT", _DEFAULT_PORT).strip() or _DEFAULT_PORT
    template = (
        os.environ.get("HERMES_LDAP_USER_DN_TEMPLATE", _DEFAULT_TEMPLATE).strip()
        or _DEFAULT_TEMPLATE
    )
    monkeypatch.setenv("HERMES_LDAP_ENABLED", "1")
    monkeypatch.setenv("HERMES_LDAP_HOST", host)
    monkeypatch.setenv("HERMES_LDAP_PORT", port)
    monkeypatch.setenv("HERMES_LDAP_USER_DN_TEMPLATE", template)
    monkeypatch.setenv("HERMES_LDAP_ENFORCE", "always")
    monkeypatch.setenv("HERMES_LDAP_FAIL_OPEN_ON_ERROR", "0")

    # Empty yaml loaders so only env supplies the section.
    import owner.patch_config as pc

    monkeypatch.setattr(pc, "load_owner_config", lambda force=False: {})
    monkeypatch.setattr(
        pc, "load_patch_feishu_profile_config", lambda force=False: {}
    )
    monkeypatch.setattr(la, "_ldap_config_broken_reason", lambda: None)

    cfg = la._load_ldap_config()
    if not str(cfg.get("host") or "").strip():
        pytest.skip("no ldap.host after env wiring")
    try:
        port_i = int(cfg.get("port", 389))
    except (TypeError, ValueError):
        port_i = 389
    if not _tcp(str(cfg["host"]), port_i):
        pytest.skip(f"LDAP TCP unreachable: {cfg['host']}:{port_i}")
    import importlib.util

    if importlib.util.find_spec("ldap3") is None:
        pytest.skip("ldap3 not installed (optional extra 'ldap')")
    return cfg


def test_e2e_tcp_and_negative_bind(live_cfg, monkeypatch, tmp_path):
    monkeypatch.setattr(la, "_state_file_path", lambda: str(tmp_path / "c.json"))
    login = os.environ.get("HERMES_LDAP_E2E_LOGIN", "c06c-no-such-user").strip()
    verdict = asyncio.run(la.ldap_gate(login, "c06c-definitely-wrong-password"))
    assert verdict == la.DENY_BAD_CREDENTIALS


def test_e2e_positive_bind_optional(live_cfg, monkeypatch, tmp_path):
    password = os.environ.get("HERMES_LDAP_E2E_PASSWORD")
    if not password:
        pytest.skip("HERMES_LDAP_E2E_PASSWORD not set")
    login = os.environ.get("HERMES_LDAP_E2E_LOGIN", "yangtb").strip()
    monkeypatch.setattr(la, "_state_file_path", lambda: str(tmp_path / "c.json"))
    verdict = asyncio.run(la.ldap_gate(login, password))
    assert verdict == la.ALLOW
    assert asyncio.run(la.ldap_gate(login, None)) == la.ALLOW
