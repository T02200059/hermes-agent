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


def test_is_damodel_route_by_provider_and_host():
    from owner.providers.damodel import is_damodel_route

    assert is_damodel_route("damodel", None) is True
    assert is_damodel_route("Damodel", "https://example.com/v1") is True
    assert is_damodel_route("openai", "https://genai.damodel.com/v1") is True
    assert is_damodel_route("openai", "https://api.openai.com/v1") is False
    assert is_damodel_route(None, None) is False


def test_anthropic_prompt_cache_policy_grants_damodel():
    """C03+ — damodel must get envelope cache_control (should_cache=True, native=False)."""
    from types import SimpleNamespace

    from agent.agent_runtime_helpers import anthropic_prompt_cache_policy

    agent = SimpleNamespace(
        _cache_disabled=False,
        provider="damodel",
        base_url="https://genai.damodel.com/v1",
        api_mode="chat_completions",
        model="qwen3.6-27b",
        _custom_providers=None,
    )
    should_cache, native = anthropic_prompt_cache_policy(agent)
    assert should_cache is True
    assert native is False
