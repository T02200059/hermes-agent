"""Private per-turn attribution helpers (owner_provider_name + related).

This module exists because the fork needs reliable per-turn provider identity
for custom / private providers (xfyun, damodel, specific DashScope instances, etc.)
across multi-profile Feishu deployments, billing, audit, and recall.

Per 二次开发规范:
- 核心逻辑放在 owner/ 下
- 官方代码通过薄调用接入，尽量减少官方文件中的永久改动面积
- 便于未来从上游 pull 时冲突最小

Usage in official code:
    from owner.attribution import inject_attribution_into_message, get_current_attribution

    # when building an assistant message for persistence
    inject_attribution_into_message(agent, msg_dict)

    # when you just need the value
    name = get_current_attribution(agent)
"""

from __future__ import annotations

from typing import Any, Dict, Optional


def get_current_attribution(agent: Any) -> Optional[str]:
    """Return the current owner_provider_name (or None).

    Safe to call from anywhere that has an agent-like object.
    """
    if agent is None:
        return None
    val = getattr(agent, "owner_provider_name", None)
    if val:
        return str(val).strip().lower() or None
    return None


def inject_attribution_into_message(agent: Any, msg: Dict[str, Any]) -> None:
    """Inject per-turn attribution into a message dict (for DB / history).

    Stamps three fields for every assistant message:
    - ``model`` — the active model name (e.g. "deepseek-v4-flash")
    - ``provider`` — the active provider name (e.g. "deepseek")
    - ``owner_provider_name`` — custom provider alias (if configured)

    This is the single place that decides the key names and value rules.
    Official message-building code should call this instead of doing
    the getattr + assignment themselves.
    """
    # Standard model/provider: always available on the agent
    model = getattr(agent, "model", None)
    provider = getattr(agent, "provider", None)
    if model:
        msg["model"] = model
    if provider:
        msg["provider"] = provider

    # Custom provider name (optional, for billing / audit)
    name = get_current_attribution(agent)
    if name:
        msg["owner_provider_name"] = name
