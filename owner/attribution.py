"""Per-turn attribution helpers (C01 skeleton).

Stamps ``model`` / ``provider`` / ``owner_provider_name`` onto assistant message
dicts for persistence. Billing / credential / outbound strip belong to C02 — not here.

Official glue sites (thin only):
- ``agent.agent_init.init_agent`` → :func:`bind_agent_attribution`
- ``agent.chat_completion_helpers.build_assistant_message`` → :func:`inject_attribution_into_message`
- ``hermes_state_*`` messages DDL / INSERT for the ``owner_provider_name`` column
"""

from __future__ import annotations

from typing import Any, Dict, Optional


def get_current_attribution(agent: Any) -> Optional[str]:
    """Return the current ``owner_provider_name`` (normalized) or None."""
    if agent is None:
        return None
    val = getattr(agent, "owner_provider_name", None)
    if val:
        return str(val).strip().lower() or None
    return None


def bind_agent_attribution(agent: Any, owner_provider_name: Optional[str] = None) -> None:
    """Set ``agent.owner_provider_name`` (explicit arg, else existing attr, else ``agent.provider``)."""
    raw = owner_provider_name
    if raw is None:
        raw = getattr(agent, "owner_provider_name", None)
    normalized = (str(raw).strip().lower() if raw else "") or None
    if not normalized:
        provider = getattr(agent, "provider", None)
        normalized = (str(provider).strip().lower() if provider else None) or None
    agent.owner_provider_name = normalized


def inject_attribution_into_message(agent: Any, msg: Dict[str, Any]) -> None:
    """Stamp per-turn attribution fields onto *msg* (in-place; never raises)."""
    try:
        model = getattr(agent, "model", None)
        provider = getattr(agent, "provider", None)
        if model:
            msg["model"] = model
        if provider:
            msg["provider"] = provider
        name = get_current_attribution(agent)
        if name:
            msg["owner_provider_name"] = name
    except Exception:
        pass
