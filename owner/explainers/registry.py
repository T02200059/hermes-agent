"""[owner] C13 — explainer kind registry (built-ins + future kinds).

Register a new kind::

    from owner.explainers.registry import register_kind
    register_kind("summary", task_name="summary_explainer", defaults={"enabled": False})

Then add ``explainers.summary:`` in patch.yaml and a package under
``owner/explainers/summary/`` that calls ``call_explainer_llm("summary", ...)``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class KindSpec:
    name: str
    task_name: str
    defaults: Dict[str, Any] = field(default_factory=dict)


_KINDS: Dict[str, KindSpec] = {}


def register_kind(
    name: str,
    *,
    task_name: Optional[str] = None,
    defaults: Optional[Dict[str, Any]] = None,
) -> KindSpec:
    """Register or replace a kind. ``task_name`` defaults to ``{name}_explainer``."""
    key = str(name or "").strip()
    if not key:
        raise ValueError("explainer kind name required")
    spec = KindSpec(
        name=key,
        task_name=str(task_name or f"{key}_explainer"),
        defaults=dict(defaults or {}),
    )
    _KINDS[key] = spec
    return spec


def get_kind(name: str) -> Optional[KindSpec]:
    return _KINDS.get(str(name or "").strip())


def known_kinds() -> tuple[str, ...]:
    return tuple(sorted(_KINDS))


def task_name_for(kind: str) -> str:
    spec = get_kind(kind)
    if spec is not None:
        return spec.task_name
    k = str(kind or "").strip()
    return f"{k}_explainer" if k else "explainer"


def _ensure_builtins() -> None:
    """Register built-in kinds; skip ones already present (hot-reload safe)."""
    if "progress" not in _KINDS:
        register_kind(
            "progress",
            defaults={
                "enabled": False,
                "silence_seconds": 60,
                "stall_seconds": 120,
                "min_interval_seconds": 120,
                "max_per_turn": 5,
                "tick_seconds": 5,
                "events_in_digest": 8,
                "chars_per_event": 200,
                "reasoning_tail_chars": 1500,
                "cleanup_progress": False,
                "platforms": {},
                "chats": {},
            },
        )
    if "approval" not in _KINDS:
        register_kind(
            "approval",
            defaults={
                "enabled": False,
                "description_max_chars": 500,
                "cache_ttl_seconds": 600,
                "cache_max_entries": 128,
                "platforms": {},
                "chats": {},
            },
        )
    if "english" not in _KINDS:
        register_kind(
            "english",
            defaults={
                "enabled": False,
                "platforms": {},
                "chats": {},
            },
        )
    if "recap" not in _KINDS:
        register_kind(
            "recap",
            defaults={
                "enabled": False,
                "max_output_chars": 500,
                "platforms": {},
                "chats": {},
            },
        )


_ensure_builtins()
