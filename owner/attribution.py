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
    """Inject the current attribution into a message dict (for DB / history).

    This is the single place that decides the key name and value rules.
    Official message-building code should call this instead of doing
    the getattr + assignment themselves.
    """
    name = get_current_attribution(agent)
    if name:
        msg["owner_provider_name"] = name
    # If no attribution, we deliberately do not set the key at all
    # (keeps historical messages cleaner when the feature is not active).
