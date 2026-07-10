"""Yangtb (personal Ollama proxy) provider profile.

Extends the custom/Ollama profile with one addition: clamp reasoning_effort
to the values Ollama actually accepts (high / medium / low / none).  Hermes
core may emit extended values like ``xhigh`` from OpenRouter conventions;
Ollama rejects them with HTTP 400.
"""

from __future__ import annotations

from typing import Any

from providers import register_provider
from providers.base import ProviderProfile

# Ollama accepts exactly these four values (case-insensitive).
_VALID_EFFORTS = {"high", "medium", "low", "none"}

# Mapping from extended / non-standard values to the closest Ollama-valid one.
_EFFORT_CLAMP: dict[str, str] = {
    "xhigh": "high",
    "max": "high",
    "xlow": "low",
    "min": "low",
}

# Models known to support Ollama's thinking/reasoning API.
# Other models get NO thinking parameters at all (Ollama 400s on unsupported models).
_THINKING_MODELS = {"gpt-oss", "deepseek-r1", "qwq", "marco-o1"}


def _model_supports_thinking(model_name: str) -> bool:
    """Check if model supports thinking by prefix match against known models."""
    _name = model_name.lower().split(":")[0]  # strip tag (e.g. ":30b")
    return any(_name == m or _name.startswith(m + "-") for m in _THINKING_MODELS)


class YangtbProfile(ProviderProfile):
    """Personal Ollama proxy — clamps reasoning_effort to Ollama-valid values."""

    def build_api_kwargs_extras(
        self,
        *,
        reasoning_config: dict | None = None,
        ollama_num_ctx: int | None = None,
        model: str = "",
        **ctx: Any,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        extra_body: dict[str, Any] = {}
        top_level: dict[str, Any] = {}

        # Ollama context window
        if ollama_num_ctx:
            options = extra_body.get("options", {})
            options["num_ctx"] = ollama_num_ctx
            extra_body["options"] = options

        # Skip thinking/reasoning entirely for models that don't support it.
        if not _model_supports_thinking(model):
            return extra_body, top_level

        # Reasoning / thinking control — same logic as custom provider,
        # plus clamping non-standard effort values to Ollama-valid ones.
        if reasoning_config and isinstance(reasoning_config, dict):
            _effort = (reasoning_config.get("effort") or "").strip().lower()
            _enabled = reasoning_config.get("enabled", True)
            if _effort == "none" or _enabled is False:
                extra_body["think"] = False
            elif _effort:
                # Clamp non-standard values (xhigh, max, …) to high.
                if _effort not in _VALID_EFFORTS:
                    _effort = _EFFORT_CLAMP.get(_effort, "high")
                top_level["reasoning_effort"] = _effort

        return extra_body, top_level

    def fetch_models(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 8.0,
    ) -> list[str] | None:
        """Yangtb/Ollama: base_url is user-configured; fetch if set."""
        if not (base_url or self.base_url):
            return None
        return super().fetch_models(api_key=api_key, base_url=base_url, timeout=timeout)


yangtb = YangtbProfile(
    name="yangtb",
    aliases=(),
    env_vars=(),  # No fixed key — custom endpoint with extra_headers auth
    base_url="",  # User-configured in config.yaml
    default_max_tokens=65536,
)

register_provider(yangtb)
