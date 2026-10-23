"""Tests for live+curated merge in the generic profile-based provider path.

Guards two contracts:

* #46850 — when a provider's live /v1/models endpoint returns a stale or
  incomplete list, the static curated models from ``_PROVIDER_MODELS`` must
  still appear in the merged result (nothing is dropped).
* #46309 / #49129 — merge *order* is per-provider. Single providers
  (kimi, zai) stay **curated-first** so a deliberately surfaced newest model
  leads even when the live API lags. ``_LIVE_FIRST_PICKER_PROVIDERS``
  (OpenCode Zen / Go) flip to **live-first** because their live API is the
  authoritative catalog and stale curated entries must not lead the picker.
"""

from unittest.mock import MagicMock, patch

from hermes_cli.models import (
    _KIMI_CODING_PLAN_MODELS,
    _LIVE_FIRST_PICKER_PROVIDERS,
    provider_model_ids,
)


class TestGenericProviderLiveCuratedMerge:
    """provider_model_ids merges live + curated for generic api_key providers."""

    def _make_profile(self, models=None):
        """Create a minimal mock provider profile."""
        p = MagicMock()
        p.auth_type = "api_key"
        p.base_url = "https://api.example.com/v1"
        p.fetch_models.return_value = models
        p.fallback_models = None
        return p

    def test_curated_first_for_single_provider(self):
        """Single providers (zai) stay curated-first; live-only appended."""
        assert "zai" not in _LIVE_FIRST_PICKER_PROVIDERS
        curated = ["glm-5.2", "glm-5.1", "glm-5"]  # authoritative-intent order
        # Live API lags AND surfaces a brand-new model not yet curated.
        live = ["glm-5", "glm-6-preview"]
        profile = self._make_profile(live)

        with (
            patch("providers.get_provider_profile", return_value=profile),
            patch(
                "hermes_cli.auth.resolve_api_key_provider_credentials",
                return_value={"api_key": "k", "base_url": ""},
            ),
            patch.dict("hermes_cli.models._PROVIDER_MODELS", {"zai": curated}),
        ):
            result = provider_model_ids("zai")

        # Curated entries lead (commit 658ac1d86, #46309).
        assert result[: len(curated)] == curated
        # Live-only entries (glm-6-preview) still surface, appended afterwards.
        assert "glm-6-preview" in result
        assert result.index("glm-6-preview") >= len(curated)
        # No duplicates for models present in both.
        assert result.count("glm-5") == 1


    def test_no_models_dropped_either_direction(self):
        """Every live AND curated model survives the merge for both modes."""
        live = ["a", "b"]
        # zai = curated-first
        with (
            patch("providers.get_provider_profile", return_value=self._make_profile(live)),
            patch(
                "hermes_cli.auth.resolve_api_key_provider_credentials",
                return_value={"api_key": "k", "base_url": ""},
            ),
            patch.dict("hermes_cli.models._PROVIDER_MODELS", {"zai": ["c", "b"]}),
        ):
            zai_result = set(provider_model_ids("zai"))
        assert {"a", "b", "c"} <= zai_result

        # opencode-zen = live-first
        with (
            patch("providers.get_provider_profile", return_value=self._make_profile(live)),
            patch(
                "hermes_cli.auth.resolve_api_key_provider_credentials",
                return_value={"api_key": "k", "base_url": ""},
            ),
            patch.dict("hermes_cli.models._PROVIDER_MODELS", {"opencode-zen": ["c", "b"]}),
        ):
            zen_result = set(provider_model_ids("opencode-zen"))
        assert {"a", "b", "c"} <= zen_result

    def test_case_insensitive_dedup(self):
        """Dedup is case-insensitive but preserves first occurrence casing."""
        live = ["GLM-5.1", "glm-5"]
        curated = ["glm-5.1", "GLM-5", "glm-4.5"]
        profile = self._make_profile(live)

        with (
            patch("providers.get_provider_profile", return_value=profile),
            patch(
                "hermes_cli.auth.resolve_api_key_provider_credentials",
                return_value={"api_key": "k", "base_url": ""},
            ),
            patch.dict("hermes_cli.models._PROVIDER_MODELS", {"zai": curated}),
        ):
            result = provider_model_ids("zai")

        # zai is curated-first: curated casing wins for models present in both.
        assert result == ["glm-5.1", "GLM-5", "glm-4.5"]


class TestKimiCodingPlanModelIds:
    """sk-kimi-* / api.kimi.com/coding must expose only the Coding Plan catalog.

    The Subscription's catalog IS the curated ``kimi-coding`` row (it carries
    ``kimi-for-coding``, which the Moonshot open-API row does not), so that row is
    the allow-list. Live ids are folded in only when the row already names them —
    an open-API-only model must never leak into a Coding Plan picker.
    """

    def test_sk_kimi_key_exposes_only_the_plan_catalog(self):
        """A Coding Plan key must not surface Moonshot-open-API-only models."""
        live = ["kimi-for-coding", "kimi-for-coding-highspeed", "moonshot-v1-128k"]
        profile = MagicMock()
        profile.auth_type = "api_key"
        profile.base_url = "https://api.moonshot.ai/v1"
        profile.fetch_models.return_value = live
        profile.fallback_models = None

        with (
            patch("providers.get_provider_profile", return_value=profile),
            patch(
                "hermes_cli.auth.resolve_api_key_provider_credentials",
                return_value={
                    "api_key": "sk-kimi-plan-key",
                    "base_url": "https://api.kimi.com/coding",
                },
            ),
        ):
            result = provider_model_ids("kimi-coding")

        # Curated row leads (it carries k3 and the k2.x coding models)…
        assert "kimi-k3" in result
        assert "kimi-for-coding" in result
        # …and an open-API-only id from the live catalog is filtered out.
        assert "moonshot-v1-128k" not in result

    def test_sk_kimi_key_filters_live_to_the_plan_catalog(self):
        """Live /v1/models is folded in only where the plan catalog already names it."""
        profile = MagicMock()
        profile.auth_type = "api_key"
        profile.base_url = "https://api.moonshot.ai/v1"
        profile.fetch_models.return_value = [
            "kimi-for-coding",
            "kimi-k2.7-code",
            "moonshot-v1-32k",
        ]
        profile.fallback_models = None

        with (
            patch("providers.get_provider_profile", return_value=profile),
            patch(
                "hermes_cli.auth.resolve_api_key_provider_credentials",
                return_value={
                    "api_key": "sk-kimi-plan-key",
                    "base_url": "https://api.kimi.com/coding",
                },
            ),
        ):
            result = provider_model_ids("kimi-coding")

        assert result == list(_KIMI_CODING_PLAN_MODELS)
        assert "moonshot-v1-32k" not in result

    def test_sk_kimi_fallback_when_live_empty(self):
        profile = MagicMock()
        profile.auth_type = "api_key"
        profile.base_url = "https://api.moonshot.ai/v1"
        profile.fetch_models.return_value = None
        profile.fallback_models = None

        with (
            patch("providers.get_provider_profile", return_value=profile),
            patch(
                "hermes_cli.auth.resolve_api_key_provider_credentials",
                return_value={
                    "api_key": "sk-kimi-plan-key",
                    "base_url": "https://api.kimi.com/coding",
                },
            ),
        ):
            result = provider_model_ids("kimi-coding")

        assert result == list(_KIMI_CODING_PLAN_MODELS)

    def test_legacy_moonshot_key_still_merges_curated(self):
        """Non-sk-kimi keys on moonshot.ai keep curated-first merge."""
        live = ["kimi-k2.6"]
        profile = MagicMock()
        profile.auth_type = "api_key"
        profile.base_url = "https://api.moonshot.ai/v1"
        profile.fetch_models.return_value = live
        profile.fallback_models = None
        curated = ["kimi-k2.7-code", "kimi-k2.6", "kimi-for-coding"]

        with (
            patch("providers.get_provider_profile", return_value=profile),
            patch(
                "hermes_cli.auth.resolve_api_key_provider_credentials",
                return_value={
                    "api_key": "sk-legacy-moonshot",
                    "base_url": "https://api.moonshot.ai/v1",
                },
            ),
            patch.dict(
                "hermes_cli.models._PROVIDER_MODELS",
                {"kimi-coding": curated},
            ),
        ):
            result = provider_model_ids("kimi-coding")

        assert result[: len(curated)] == curated
        assert "kimi-for-coding" in result
