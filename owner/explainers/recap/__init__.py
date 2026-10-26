"""[owner] C13 — recap explainer (on-demand /recap; notice bypass)."""

from __future__ import annotations

from owner.explainers.recap.command import handle_recap_command
from owner.explainers.recap.explain import explain_from_messages, explain_from_messages_async
from owner.explainers.recap.flatten import flatten_messages
from owner.explainers.recap.prompt import PREFIX, format_delivery

__all__ = [
    "PREFIX",
    "flatten_messages",
    "format_delivery",
    "explain_from_messages",
    "explain_from_messages_async",
    "handle_recap_command",
]
