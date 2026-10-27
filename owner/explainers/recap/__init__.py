"""[owner] C13 — recap explainer (on-demand /recap + idle auto; notice bypass)."""

from __future__ import annotations

from owner.explainers.recap.auto import register_hooks
from owner.explainers.recap.command import handle_recap_command
from owner.explainers.recap.explain import explain_from_messages, explain_from_messages_async
from owner.explainers.recap.flatten import flatten_messages
from owner.explainers.recap.prompt import PREFIX, format_delivery

__all__ = [
    "PREFIX",
    "explain_from_messages",
    "explain_from_messages_async",
    "flatten_messages",
    "format_delivery",
    "handle_recap_command",
    "register_hooks",
]
