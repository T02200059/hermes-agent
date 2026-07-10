"""MiMo thinking wire — shared helper + xiaomi/damodel profile contracts.

Official Xiaomi docs: thinking is controlled by
``extra_body.thinking.type`` = enabled|disabled (default enabled).
``reasoning_effort`` is optional/best-effort. damodel routes MiMo to the
same upstream, so both profiles must emit the same shape.
"""

from __future__ import annotations

import pytest

from providers.mimo_thinking import build_mimo_thinking_extras, is_mimo_thinking_model


# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------


class TestIsMimoThinkingModel:
    @pytest.mark.parametrize(
        "model",
        [
            "mimo-v2.5-pro",
            "mimo-v2.5",
            "MIMO-V2.5-PRO",
            "mimo-v2.5-future",
        ],
    )
    def test_chat_models_supported(self, model):
        assert is_mimo_thinking_model(model) is True

    @pytest.mark.parametrize(
        "model",
        [
            None,
            "",
            "   ",
            "deepseek-v4-pro",
            "glm-5.1",
            "qwen3.7-max",
            "mimo-v2.5-tts",
            "mimo-v2.5-tts-voicedesign",
            "mimo-v2.5-tts-voiceclone",
            "mimo-v2.5-asr",
        ],
    )
    def test_non_thinking_models_excluded(self, model):
        assert is_mimo_thinking_model(model) is False


class TestBuildMimoThinkingExtras:
    def test_default_enables_thinking_without_effort(self):
        extra_body, top_level = build_mimo_thinking_extras(
            reasoning_config=None, model="mimo-v2.5-pro"
        )
        assert extra_body == {"thinking": {"type": "enabled"}}
        assert top_level == {}

    def test_explicit_enabled_with_high_effort(self):
        extra_body, top_level = build_mimo_thinking_extras(
            reasoning_config={"enabled": True, "effort": "high"},
            model="mimo-v2.5-pro",
        )
        assert extra_body == {"thinking": {"type": "enabled"}}
        assert top_level == {"reasoning_effort": "high"}

    @pytest.mark.parametrize("effort", ["low", "medium", "high"])
    def test_standard_efforts_pass_through(self, effort):
        _, top_level = build_mimo_thinking_extras(
            reasoning_config={"enabled": True, "effort": effort},
            model="mimo-v2.5",
        )
        assert top_level == {"reasoning_effort": effort}

    @pytest.mark.parametrize("effort", ["xhigh", "max", "MAX", "  Max  "])
    def test_xhigh_and_max_clamp_to_high(self, effort):
        _, top_level = build_mimo_thinking_extras(
            reasoning_config={"enabled": True, "effort": effort},
            model="mimo-v2.5-pro",
        )
        assert top_level == {"reasoning_effort": "high"}

    def test_minimal_clamps_to_low(self):
        _, top_level = build_mimo_thinking_extras(
            reasoning_config={"enabled": True, "effort": "minimal"},
            model="mimo-v2.5-pro",
        )
        assert top_level == {"reasoning_effort": "low"}

    def test_disabled_sends_disabled_marker(self):
        """``enabled=False`` must be *sent* — default is thinking ON."""
        extra_body, top_level = build_mimo_thinking_extras(
            reasoning_config={"enabled": False}, model="mimo-v2.5-pro"
        )
        assert extra_body == {"thinking": {"type": "disabled"}}
        assert top_level == {}

    def test_disabled_drops_effort(self):
        extra_body, top_level = build_mimo_thinking_extras(
            reasoning_config={"enabled": False, "effort": "high"},
            model="mimo-v2.5-pro",
        )
        assert extra_body == {"thinking": {"type": "disabled"}}
        assert top_level == {}

    def test_unknown_effort_omits_top_level(self):
        _, top_level = build_mimo_thinking_extras(
            reasoning_config={"enabled": True, "effort": "garbage"},
            model="mimo-v2.5-pro",
        )
        assert top_level == {}

    def test_empty_or_none_effort_omits_top_level(self):
        for effort in ("", "none", "  "):
            _, top_level = build_mimo_thinking_extras(
                reasoning_config={"enabled": True, "effort": effort},
                model="mimo-v2.5-pro",
            )
            assert top_level == {}

    def test_non_mimo_returns_empty(self):
        extra_body, top_level = build_mimo_thinking_extras(
            reasoning_config={"enabled": True, "effort": "high"},
            model="glm-5.1",
        )
        assert extra_body == {}
        assert top_level == {}


# ---------------------------------------------------------------------------
# Registered profiles must share the same wire shape
# ---------------------------------------------------------------------------


@pytest.fixture(params=["xiaomi", "damodel"])
def mimo_profile(request):
    import model_tools  # noqa: F401 — triggers plugin discovery
    import providers

    profile = providers.get_provider_profile(request.param)
    assert profile is not None, f"{request.param} provider profile must be registered"
    return request.param, profile


class TestXiaomiAndDamodelMimoWireParity:
    """Both entry points emit identical MiMo thinking kwargs."""

    def test_pro_default_enables_thinking(self, mimo_profile):
        _name, profile = mimo_profile
        extra_body, top_level = profile.build_api_kwargs_extras(
            reasoning_config=None, model="mimo-v2.5-pro"
        )
        assert extra_body == {"thinking": {"type": "enabled"}}
        assert top_level == {}

    def test_disable_thinking(self, mimo_profile):
        _name, profile = mimo_profile
        extra_body, top_level = profile.build_api_kwargs_extras(
            reasoning_config={"enabled": False}, model="mimo-v2.5-pro"
        )
        assert extra_body == {"thinking": {"type": "disabled"}}
        assert top_level == {}

    def test_effort_clamp_with_thinking(self, mimo_profile):
        _name, profile = mimo_profile
        extra_body, top_level = profile.build_api_kwargs_extras(
            reasoning_config={"enabled": True, "effort": "xhigh"},
            model="mimo-v2.5-pro",
        )
        assert extra_body == {"thinking": {"type": "enabled"}}
        assert top_level == {"reasoning_effort": "high"}

    def test_tts_model_untouched(self, mimo_profile):
        _name, profile = mimo_profile
        extra_body, top_level = profile.build_api_kwargs_extras(
            reasoning_config={"enabled": True, "effort": "high"},
            model="mimo-v2.5-tts",
        )
        assert extra_body == {}
        assert top_level == {}


class TestDamodelNonMimoUntouched:
    """damodel must not inject MiMo fields for other upstream families."""

    @pytest.fixture
    def damodel_profile(self):
        import model_tools  # noqa: F401
        import providers

        profile = providers.get_provider_profile("damodel")
        assert profile is not None
        return profile

    @pytest.mark.parametrize("model", ["glm-5.1", "deepseek-v4-pro", "qwen3.7-max"])
    def test_non_mimo_empty(self, damodel_profile, model):
        extra_body, top_level = damodel_profile.build_api_kwargs_extras(
            reasoning_config={"enabled": True, "effort": "high"},
            model=model,
        )
        assert extra_body == {}
        assert top_level == {}
