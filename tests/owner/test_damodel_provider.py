"""C03: damodel provider/proxy registration."""

from __future__ import annotations


def test_damodel_profile_constants():
    from owner.providers.damodel import DAMODEL_BASE_URL, damodel

    assert damodel.name == "damodel"
    assert damodel.base_url == DAMODEL_BASE_URL
    assert DAMODEL_BASE_URL == "https://genai.damodel.com/v1"
    assert damodel.env_vars == ("DAMODEL_API_KEY",)
    assert damodel.supports_vision is True
    assert damodel.supports_vision_tool_messages is False


def test_damodel_discovered_via_bundled_plugin():
    from providers import get_provider_profile

    profile = get_provider_profile("damodel")
    assert profile is not None
    assert profile.name == "damodel"
    assert profile.base_url == "https://genai.damodel.com/v1"
    assert "DAMODEL_API_KEY" in profile.env_vars
