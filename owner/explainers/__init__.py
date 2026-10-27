"""[owner] C13 — unified explainers (shared config / LLM / registry).

Kinds: progress | approval | english | recap
Extend: ``register_kind("name", task="name_explainer")`` then
``explainers.<name>: {enabled: true, ...}`` in overlay.yaml.
"""

from owner.explainers.config import (
    load_kind_config,
    load_shared,
    resolve_enabled,
    resolve_model,
    resolve_timeout_s,
)
from owner.explainers.llm import call_explainer_llm, call_explainer_llm_async
from owner.explainers.registry import known_kinds, register_kind, task_name_for

__all__ = [
    "load_shared",
    "load_kind_config",
    "resolve_enabled",
    "resolve_model",
    "resolve_timeout_s",
    "call_explainer_llm",
    "call_explainer_llm_async",
    "register_kind",
    "known_kinds",
    "task_name_for",
]
