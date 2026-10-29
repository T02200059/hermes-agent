"""C06a: LDAP gate unit tests (mock bind; no live directory)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from owner.gateway import ldap_auth as la


@pytest.fixture(autouse=True)
def _reset():
    la.reset_for_tests()
    yield
    la.reset_for_tests()


def _cfg(**overrides):
    base = {
        "enabled": True,
        "host": "ldap.test.local",
        "port": 389,
        "use_ssl": False,
        "timeout_seconds": 2,
        "user_dn_template": "cn={login},cn=people,dc=example,dc=com",
        "enforce": "always",
        "cache_ttl_hours": 1,
        "negative_cache_seconds": 10,
        "fail_open_on_error": False,
    }
    base.update(overrides)
    return base


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def load_cfg(monkeypatch):
    state = {"cfg": _cfg()}

    def _loader():
        return dict(state["cfg"])

    monkeypatch.setattr(la, "_load_ldap_config", _loader)
    monkeypatch.setattr(la, "_ldap_config_broken_reason", lambda: None)
    return state


def test_disabled_gate_allows(load_cfg):
    load_cfg["cfg"] = _cfg(enabled=False)
    assert _run(la.ldap_gate("alice", None)) == la.ALLOW


def test_invalid_login_chars(load_cfg):
    assert _run(la.ldap_gate("alice;drop", "x")) == la.DENY_INVALID_LOGIN


def test_empty_password_rejected_before_bind(load_cfg):
    called = []

    def boom(*a, **k):
        called.append(1)
        return True

    la._bind_sync_impl = boom
    assert _run(la.ldap_gate("alice", "   ")) == la.DENY_EMPTY_PASSWORD
    assert called == []


def test_good_password_caches_and_reauth_free(load_cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(la, "_state_file_path", lambda: str(tmp_path / "cache.json"))
    la._bind_sync_impl = lambda *a, **k: True
    assert _run(la.ldap_gate("Alice", "secret")) == la.ALLOW
    # casefold cache hit — no bind
    la._bind_sync_impl = lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not bind"))
    assert _run(la.ldap_gate("alice", None)) == la.ALLOW


def test_bad_password_denies_and_requires_reauth(load_cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(la, "_state_file_path", lambda: str(tmp_path / "cache.json"))
    la._bind_sync_impl = lambda *a, **k: False
    assert _run(la.ldap_gate("bob", "wrong")) == la.DENY_BAD_CREDENTIALS
    assert _run(la.ldap_gate("bob", None)) == la.DENY_REAUTH_REQUIRED


def test_enforce_off_allows_without_password(load_cfg):
    load_cfg["cfg"] = _cfg(enforce="off")
    assert _run(la.ldap_gate("carol", None)) == la.ALLOW


def test_enforce_seen_is_always_alias(load_cfg):
    load_cfg["cfg"] = _cfg(enforce="seen")
    assert _run(la.ldap_gate("dave", None)) == la.DENY_REAUTH_REQUIRED


def test_enforce_typo_fail_closed(load_cfg):
    load_cfg["cfg"] = _cfg(enforce="alway")
    assert _run(la.ldap_gate("erin", None)) == la.DENY_REAUTH_REQUIRED


def test_transport_error_default_fail_closed(load_cfg):
    def boom(*a, **k):
        raise OSError("down")

    la._bind_sync_impl = boom
    assert _run(la.ldap_gate("frank", "pw")) == la.DENY_BACKEND_UNAVAILABLE


def test_transport_error_fail_open_opt_in(load_cfg):
    load_cfg["cfg"] = _cfg(fail_open_on_error=True)

    def boom(*a, **k):
        raise OSError("down")

    la._bind_sync_impl = boom
    assert _run(la.ldap_gate("frank", "pw")) == la.ALLOW


def test_no_host_is_config_error_ignores_fail_open(load_cfg):
    load_cfg["cfg"] = _cfg(host="", fail_open_on_error=True)
    assert _run(la.ldap_gate("gina", "pw")) == la.DENY_BACKEND_UNAVAILABLE


def test_dn_injection_escaped(load_cfg):
    # login charset already rejects comma; escape still covers edge values via helper
    assert la._rfc4514_escape('a,b') == "a\\2Cb"
    assert "cn=alice," in (la._build_user_dn(
        "cn={login},cn=people,dc=example,dc=com", "alice"
    ) or "")


def test_broken_config_fail_closed_when_disabled_loader_empty(monkeypatch):
    monkeypatch.setattr(la, "_load_ldap_config", dict)
    monkeypatch.setattr(la, "_ldap_config_broken_reason", lambda: "YAML parse error: x")
    assert _run(la.ldap_gate("harry", None)) == la.DENY_BACKEND_UNAVAILABLE


def test_normalize_login_casefold():
    assert la._normalize_login(" Alice ") == "alice"


def test_state_file_bad_mac_ignored(tmp_path, monkeypatch, load_cfg):
    monkeypatch.setattr(la, "_state_file_path", lambda: str(tmp_path / "cache.json"))
    la._bind_sync_impl = lambda *a, **k: True
    assert _run(la.ldap_gate("ivy", "ok")) == la.ALLOW
    # forge unsigned far-future entry
    path = Path(tmp_path / "cache.json")
    path.write_text(
        '{"version":3,"entries":{"ivy":9999999999},"seen":["ivy"],"mac":"deadbeef"}',
        encoding="utf-8",
    )
    la.reset_for_tests()
    monkeypatch.setattr(la, "_state_file_path", lambda: str(path))
    # after reset, new HMAC key; forged file ignored → no cache → reauth required
    load_cfg["cfg"] = _cfg()
    monkeypatch.setattr(la, "_load_ldap_config", lambda: _cfg())
    monkeypatch.setattr(la, "_ldap_config_broken_reason", lambda: None)
    assert _run(la.ldap_gate("ivy", None)) == la.DENY_REAUTH_REQUIRED
