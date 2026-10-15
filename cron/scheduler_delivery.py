"""[owner] forward-ported minimal slice from upstream cron/scheduler_delivery (BASE 之后新增).

Upstream run.py imports _resolve_home_env_var from here at call time (home-target
env resolution for /sethome and restart notifications). The full upstream module
(2067 lines) is the cron delivery lane; only the env-var resolution slice is
consumed by the swapped run.py — the rest arrives with the cron lane (A4-2+).
"""
from __future__ import annotations

import contextlib

_HOME_TARGET_ENV_VARS = {
    "matrix": "MATRIX_HOME_ROOM",
    "telegram": "TELEGRAM_HOME_CHANNEL",
    "discord": "DISCORD_HOME_CHANNEL",
    "slack": "SLACK_HOME_CHANNEL",
    "signal": "SIGNAL_HOME_CHANNEL",
    "mattermost": "MATTERMOST_HOME_CHANNEL",
    "sms": "SMS_HOME_CHANNEL",
    "email": "EMAIL_HOME_ADDRESS",
    "dingtalk": "DINGTALK_HOME_CHANNEL",
    "feishu": "FEISHU_HOME_CHANNEL",
    "wecom": "WECOM_HOME_CHANNEL",
    "weixin": "WEIXIN_HOME_CHANNEL",
    "bluebubbles": "BLUEBUBBLES_HOME_CHANNEL",
    "qqbot": "QQBOT_HOME_CHANNEL",
    "whatsapp": "WHATSAPP_HOME_CHANNEL",
    "whatsapp_cloud": "WHATSAPP_CLOUD_HOME_CHANNEL"}

# Back-compat: primary env var -> previous name, consulted when the primary is unset.
_LEGACY_HOME_TARGET_ENV_VARS = {"QQBOT_HOME_CHANNEL": "QQ_HOME_CHANNEL"}


def _plugin_cron_env_var(platform_name: str) -> str:
    """Cron home-channel env var registered by a plugin ``PlatformEntry.cron_deliver_env_var``."""
    with contextlib.suppress(Exception):
        from hermes_cli.plugins import discover_plugins
        discover_plugins()  # idempotent
        from gateway.platform_registry import platform_registry
        entry = platform_registry.get(platform_name.lower())
        if entry and entry.cron_deliver_env_var:
            return entry.cron_deliver_env_var
    return ""


def _resolve_home_env_var(platform_name: str) -> str:
    name = (platform_name or "").strip().lower()
    return _HOME_TARGET_ENV_VARS.get(name) or _plugin_cron_env_var(name)
