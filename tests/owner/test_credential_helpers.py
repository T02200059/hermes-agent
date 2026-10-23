"""C02: owner credential helpers — prefix merge + expiry."""

from __future__ import annotations


def test_has_valid_env_credential_fail_open_without_prefixes():
    from owner.providers.credential_helpers import has_valid_env_credential

    env = {"SOME_KEY": "plain-value"}
    assert has_valid_env_credential(("SOME_KEY",), "unknown-provider", read_env=env.get) is True
    assert has_valid_env_credential(("MISSING",), "unknown-provider", read_env=env.get) is False


def test_has_valid_env_credential_respects_owner_copilot_prefixes():
    from owner.providers.credential_helpers import has_valid_env_credential

    # classic ghp_ intentionally rejected
    env_bad = {"GH_TOKEN": "ghp_classic_should_fail"}
    assert has_valid_env_credential(("GH_TOKEN",), "copilot", read_env=env_bad.get) is False

    env_ok = {"GH_TOKEN": "gho_oauth_ok"}
    assert has_valid_env_credential(("GH_TOKEN",), "copilot", read_env=env_ok.get) is True


def test_merged_prefixes_include_official_openrouter():
    from owner.providers.credential_helpers import _merged_prefix_map

    merged = _merged_prefix_map()
    # official openrouter should appear when hermes_cli.auth is importable
    assert "openrouter" in merged
    assert merged["openrouter"]  # non-empty
    assert "copilot" in merged
    assert "gho_" in merged["copilot"]
    assert "ghp_" not in merged["copilot"]


def test_is_token_expired_fail_open():
    from owner.providers.credential_helpers import is_token_expired

    assert is_token_expired(None) is False
    assert is_token_expired("not-a-date") is False
    assert is_token_expired("2000-01-01T00:00:00+00:00") is True
    assert is_token_expired("2999-01-01T00:00:00+00:00") is False
