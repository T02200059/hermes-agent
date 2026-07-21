"""Kimi / Moonshot provider profiles.

Kimi has dual endpoints:
  - sk-kimi-* keys → api.kimi.com/coding (Anthropic Messages API)
  - legacy keys → api.moonshot.ai/v1 (OpenAI chat completions)

This module covers the chat_completions path (/v1 endpoint).
"""

from typing import Any
from urllib.parse import urlparse

from providers import register_provider
from providers.base import OMIT_TEMPERATURE, ProviderProfile


def _is_confirmed_kimi_coding_url(base_url: str) -> bool:
    """Return True only for Kimi Code's canonical HTTPS API surfaces."""
    try:
        parsed = urlparse(base_url)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme.lower() == "https"
        and (parsed.hostname or "").lower() == "api.kimi.com"
        and port in (None, 443)
        and parsed.username is None
        and parsed.password is None
        and parsed.path.rstrip("/") in {"/coding", "/coding/v1"}
        and not parsed.query
        and not parsed.fragment
    )


class KimiProfile(ProviderProfile):
    """Kimi/Moonshot — temperature omitted, thinking xor reasoning_effort."""

    def fetch_models(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 8.0,
    ) -> list[str] | None:
        """Fetch live model IDs, with Coding Plan catalog path handling.

        Inference base for ``sk-kimi-*`` is ``https://api.kimi.com/coding``
        (no ``/v1`` — Anthropic Messages appends ``/v1/messages``). The
        OpenAI-compat model list lives at ``.../coding/v1/models``, so a
        naive ``base + /models`` probe 404s and the picker falls back to the
        full Moonshot curated catalog. Try the ``/v1`` catalog base first
        when the coding plan endpoint is in use.
        """
        effective_base = (base_url or self.base_url or "").rstrip("/")
        confirmed_coding_endpoint = _is_confirmed_kimi_coding_url(effective_base)
        if confirmed_coding_endpoint and urlparse(effective_base).path.rstrip("/") == "/coding":
            effective_base += "/v1"
        models = super().fetch_models(
            api_key=api_key,
            base_url=effective_base or None,
            timeout=timeout,
        )
        if models is None or confirmed_coding_endpoint:
            return models
        return [model for model in models if model.strip().lower() != "k3"]

    def build_api_kwargs_extras(
        self, *, reasoning_config: dict | None = None, **context
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Kimi reasoning controls.

        Moonshot's wire shape treats ``extra_body.thinking`` (a binary toggle)
        and a top-level ``reasoning_effort`` as mutually exclusive — sending
        both is at best redundant and risks "cannot specify both 'thinking' and
        'reasoning_effort'" (HTTP 400). This mirrors the kimi-k2 handling on the
        opencode-go relay: send effort when one is requested, otherwise fall
        back to ``extra_body.thinking`` — never both.

        ``kimi-k2.7-code`` (and highspeed): thinking + Preserved Thinking are
        always on. Official docs say do not pass the ``thinking`` parameter
        (and ``type: disabled`` errors). For that family we omit the toggle
        entirely and only optionally send ``reasoning_effort``.
        """
        extra_body: dict[str, Any] = {}
        top_level: dict[str, Any] = {}

        model = context.get("model")
        try:
            from agent.anthropic_adapter import _kimi_model_always_thinking

            always_thinking = _kimi_model_always_thinking(model)
        except Exception:
            always_thinking = False

        if not reasoning_config or not isinstance(reasoning_config, dict):
            if always_thinking:
                # Server default is on; do not send thinking param.
                return extra_body, top_level
            # No config → thinking enabled, let the server pick the depth.
            # (Previously also sent reasoning_effort="medium", which paired
            # thinking + effort on every default call.)
            extra_body["thinking"] = {"type": "enabled"}
            return extra_body, top_level

        enabled = reasoning_config.get("enabled", True)
        if enabled is False:
            if always_thinking:
                # k2.7-code rejects disabled — omit rather than 400.
                return extra_body, top_level
            extra_body["thinking"] = {"type": "disabled"}
            return extra_body, top_level

        # Enabled: prefer an explicit effort; only fall back to extra_body
        # thinking when no recognized effort is requested.
        effort = (reasoning_config.get("effort") or "").strip().lower()
        if effort in {"low", "medium", "high"}:
            top_level["reasoning_effort"] = effort
        elif always_thinking:
            # k2.7-code: leave thinking param off (always-on server-side).
            pass
        else:
            extra_body["thinking"] = {"type": "enabled"}

        return extra_body, top_level


kimi = KimiProfile(
    name="kimi-coding",
    aliases=("kimi", "moonshot", "kimi-for-coding"),
    env_vars=("KIMI_API_KEY", "KIMI_CODING_API_KEY"),
    base_url="https://api.moonshot.ai/v1",
    fixed_temperature=OMIT_TEMPERATURE,
    default_max_tokens=32000,
    default_headers={"User-Agent": "hermes-agent/1.0"},
    default_aux_model="kimi-k2-turbo-preview",
    supports_vision=True,
)

kimi_cn = KimiProfile(
    name="kimi-coding-cn",
    aliases=("kimi-cn", "moonshot-cn"),
    env_vars=("KIMI_CN_API_KEY",),
    base_url="https://api.moonshot.cn/v1",
    fixed_temperature=OMIT_TEMPERATURE,
    default_max_tokens=32000,
    default_headers={"User-Agent": "hermes-agent/1.0"},
    default_aux_model="kimi-k2-turbo-preview",
    supports_vision=True,
)

register_provider(kimi)
register_provider(kimi_cn)
