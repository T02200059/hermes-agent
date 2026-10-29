"""C06c: HERMES_LDAP_* env overrides on ldap config loader."""

from __future__ import annotations

import asyncio

import pytest

from owner.gateway import ldap_auth as la


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    la.reset_for_tests()
    # clear ldap env between tests
    for key in list(__import__("os").environ):
        if key.startswith("HERMES_LDAP_"):
            monkeypatch.delenv(key, raising=False)
    yield
    la.reset_for_tests()


def test_env_enabled_and_host_override(monkeypatch):
    # stub yaml loaders via patching the helpers used inside _load_ldap_config
    monkeypatch.setenv("HERMES_LDAP_ENABLED", "1")
    monkeypatch.setenv("HERMES_LDAP_HOST", "ldap.env.test")
    monkeypatch.setenv("HERMES_LDAP_PORT", "636")
    monkeypatch.setenv("HERMES_LDAP_USE_SSL", "true")
    monkeypatch.setenv(
        "HERMES_LDAP_USER_DN_TEMPLATE", "uid={login},dc=env,dc=test"
    )
    monkeypatch.setenv("HERMES_LDAP_ENFORCE", "off")
    monkeypatch.setenv("HERMES_LDAP_FAIL_OPEN_ON_ERROR", "1")

    # Force empty yaml so only env matters
    import owner.patch_config as pc

    monkeypatch.setattr(pc, "load_owner_config", lambda force=False: {})
    monkeypatch.setattr(
        pc, "load_patch_feishu_profile_config", lambda force=False: {}
    )

    cfg = la._load_ldap_config()
    assert cfg["enabled"] is True
    assert cfg["host"] == "ldap.env.test"
    assert cfg["port"] == 636
    assert cfg["use_ssl"] is True
    assert cfg["user_dn_template"] == "uid={login},dc=env,dc=test"
    assert cfg["enforce"] == "off"
    assert cfg["fail_open_on_error"] is True


def test_env_overrides_yaml_host(monkeypatch):
    import owner.patch_config as pc

    monkeypatch.setattr(
        pc,
        "load_owner_config",
        lambda force=False: {
            "ldap": {
                "enabled": False,
                "host": "yaml.local",
                "port": 389,
                "user_dn_template": "cn={login},dc=yaml",
            }
        },
    )
    monkeypatch.setattr(
        pc, "load_patch_feishu_profile_config", lambda force=False: {}
    )
    monkeypatch.setenv("HERMES_LDAP_HOST", "from.env")
    monkeypatch.setenv("HERMES_LDAP_ENABLED", "true")

    cfg = la._load_ldap_config()
    assert cfg["host"] == "from.env"
    assert cfg["enabled"] is True
    assert cfg["user_dn_template"] == "cn={login},dc=yaml"


def test_gate_respects_env_enabled_with_mock_bind(monkeypatch):
    import owner.patch_config as pc

    monkeypatch.setattr(
        pc,
        "load_owner_config",
        lambda force=False: {
            "ldap": {
                "enabled": False,
                "host": "ldap.test.local",
                "user_dn_template": "cn={login},dc=t",
                "enforce": "always",
            }
        },
    )
    monkeypatch.setattr(
        pc, "load_patch_feishu_profile_config", lambda force=False: {}
    )
    monkeypatch.setattr(la, "_ldap_config_broken_reason", lambda: None)
    # yaml says disabled → allow without bind
    assert asyncio.run(la.ldap_gate("alice", None)) == la.ALLOW

    monkeypatch.setenv("HERMES_LDAP_ENABLED", "1")
    la._bind_sync_impl = lambda *a, **k: False
    assert asyncio.run(la.ldap_gate("alice", "x")) == la.DENY_BAD_CREDENTIALS
