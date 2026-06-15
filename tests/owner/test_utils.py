"""Tests for owner/utils.py."""

from owner.utils import normalize_bare_domain_base_url


def test_normalize_bare_domain_appends_v1():
    assert normalize_bare_domain_base_url("https://api.example.com") == "https://api.example.com/v1"


def test_normalize_bare_domain_preserves_existing_path():
    assert (
        normalize_bare_domain_base_url("https://api.ppinfra.com/v3/openai")
        == "https://api.ppinfra.com/v3/openai"
    )


def test_normalize_bare_domain_empty_passthrough():
    assert normalize_bare_domain_base_url("") == ""
    assert normalize_bare_domain_base_url("   ") == ""