"""
[owner] pool-base-url-override: Config-aware base_url override for credential pool.

When model.provider matches a built-in provider and model.base_url is set,
the credential pool should honour the config override instead of falling back
to the provider's hardcoded default URL.

Fixes: delegate_task 401 on token-plan xiaomi endpoints.
See: owner/docs/v16改动清单.md §pool-base-url-override
"""
from typing import Optional


def config_base_url_override(provider: str, current_url: str) -> Optional[str]:
    """If model.base_url in config.yaml overrides the provider default, return it.

    Returns the override URL when ALL conditions are met:
    1. provider is a known built-in (in PROVIDER_REGISTRY)
    2. current_url matches the provider's hardcoded default (not already overridden by env var)
    3. model.provider in config.yaml matches this provider
    4. model.base_url in config.yaml is set and doesn't contain ${VAR} templates

    Returns None when no override is needed (caller keeps current_url unchanged).

    Priority: env var > config model.base_url > hardcoded default
    """
    try:
        from hermes_cli.auth import PROVIDER_REGISTRY
        from hermes_cli.runtime_provider import _get_model_config
    except ImportError:
        return None

    pconfig = PROVIDER_REGISTRY.get(provider)
    if not pconfig or not current_url:
        return None
    if current_url.rstrip("/") != pconfig.inference_base_url.rstrip("/"):
        return None  # URL already overridden by env var or explicit param — don't touch
    model_cfg = _get_model_config()
    configured_provider = str(model_cfg.get("provider") or "").strip().lower()
    if configured_provider != provider:
        return None  # config provider doesn't match this runtime provider
    cfg_base_url = str(model_cfg.get("base_url") or "").strip().rstrip("/")
    if cfg_base_url and "${" not in cfg_base_url:
        return cfg_base_url
    return None
