"""[owner] C13 — unified ``owner.explainers`` config (overlay.yaml).

Schema::

    explainers:
      provider: auto
      model: auto
      timeout_ms: 30000
      max_input_chars: 64000   # shared; designed for ≥256k-context models
      progress: { enabled: false, ... }
      approval: { enabled: false, ... }
      english:  { enabled: false, ... }
      recap:    { enabled: false, ... }

Shared provider/model/timeout_ms/max_input_chars apply to every kind unless the kind overrides.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from owner.explainers.common import (
    DEFAULT_MAX_INPUT_CHARS,
    coerce_bool,
    coerce_int,
    norm_model_field,
    normalize_platform,
)
from owner.explainers.registry import get_kind, known_kinds

_SHARED_DEFAULTS: dict[str, Any] = {
    "provider": "",
    "model": "",
    "timeout_ms": 30000,
    "max_input_chars": DEFAULT_MAX_INPUT_CHARS,
}

_INT_SHARED = ("timeout_ms",)


def _patch_root() -> dict[str, Any]:
    """Return the owner-layer dict (flat v2, or peel legacy ``owner:`` wrapper)."""
    try:
        from owner.patch_config import load_patch_config

        raw = load_patch_config() or {}
        if not isinstance(raw, dict):
            return {}
        # Legacy live file (old hermes-agent symlink) wrapped everything in owner:
        if (
            "explainers" not in raw
            and "stream_guard" not in raw
            and isinstance(raw.get("owner"), dict)
        ):
            return raw["owner"]
        return raw
    except Exception:
        return {}


def _legacy_kind_block(root: dict[str, Any], kind: str) -> dict[str, Any]:
    """Map old top-level ``{kind}_explainer`` into a kind sub-dict."""
    legacy = root.get(f"{kind}_explainer")
    if not isinstance(legacy, dict):
        return {}
    out = dict(legacy)
    # Normalize timeout key
    if "timeout_ms" not in out and "explainer_timeout_ms" in out:
        out["timeout_ms"] = out.get("explainer_timeout_ms")
    return out


def _raw_explainers() -> dict[str, Any]:
    """Unified ``explainers:`` block, with legacy flat-key synthesis.

    Prefer ``explainers:`` when present. Otherwise synthesize from old
    ``progress_explainer`` / ``approval_explainer`` / ``english_explainer``
    top-level sections (pre-C13 live files).
    """
    try:
        root = _patch_root()
        block = root.get("explainers")
        if isinstance(block, dict) and block:
            return block
        # Synthesize so a still-old symlink keeps working until retargeted.
        synthesized: dict[str, Any] = {
            "provider": "",
            "model": "",
            "timeout_ms": 30000,
            "max_input_chars": DEFAULT_MAX_INPUT_CHARS,
        }
        found = False
        for kind in ("progress", "approval", "english"):
            legacy = _legacy_kind_block(root, kind)
            if legacy:
                synthesized[kind] = legacy
                # Promote first non-empty provider/model to shared if unset
                if not synthesized["provider"] and legacy.get("provider"):
                    synthesized["provider"] = legacy.get("provider") or ""
                if not synthesized["model"] and legacy.get("model"):
                    synthesized["model"] = legacy.get("model") or ""
                if legacy.get("timeout_ms") or legacy.get("explainer_timeout_ms"):
                    try:
                        synthesized["timeout_ms"] = int(
                            legacy.get("timeout_ms")
                            or legacy.get("explainer_timeout_ms")
                            or 30000
                        )
                    except (TypeError, ValueError):
                        pass
                found = True
        return synthesized if found else {}
    except Exception:
        return {}


def load_shared() -> dict[str, Any]:
    raw = _raw_explainers()
    cfg = {
        "provider": norm_model_field(raw.get("provider", _SHARED_DEFAULTS["provider"])),
        "model": norm_model_field(raw.get("model", _SHARED_DEFAULTS["model"])),
        "timeout_ms": coerce_int(
            raw.get("timeout_ms", _SHARED_DEFAULTS["timeout_ms"]),
            _SHARED_DEFAULTS["timeout_ms"],
            minimum=1,
        ),
        "max_input_chars": coerce_int(
            raw.get("max_input_chars", _SHARED_DEFAULTS["max_input_chars"]),
            _SHARED_DEFAULTS["max_input_chars"],
            minimum=0,
        ),
    }
    return cfg


def load_kind_config(kind: str) -> dict[str, Any]:
    """Merged config for one kind: kind defaults ← shared ← kind overrides.

    Always includes ``provider`` / ``model`` / ``timeout_ms`` (resolved).
    Kind-only keys come from registry defaults + kind yaml.
    """
    shared = load_shared()
    spec = get_kind(kind)
    defaults = dict(spec.defaults) if spec else {"enabled": False, "platforms": {}, "chats": {}}
    raw_root = _raw_explainers()
    raw_kind = raw_root.get(kind)
    if not isinstance(raw_kind, dict):
        raw_kind = {}

    cfg: dict[str, Any] = dict(defaults)
    cfg["enabled"] = coerce_bool(raw_kind.get("enabled", defaults.get("enabled", False)), False)

    # kind-specific ints
    for key, default in list(defaults.items()):
        if key in {"enabled", "platforms", "chats", "provider", "model"}:
            continue
        if isinstance(default, bool):
            cfg[key] = coerce_bool(raw_kind.get(key, default), default)
        elif isinstance(default, int):
            minimum = 1 if key == "tick_seconds" else 0
            cfg[key] = coerce_int(raw_kind.get(key, default), default, minimum=minimum)
        elif isinstance(default, str):
            cfg[key] = str(raw_kind.get(key, default) or default)
        elif isinstance(default, dict):
            # Nested blocks (e.g. recap.auto): defaults ← overlay shallow-merge
            merged = dict(default)
            raw_block = raw_kind.get(key)
            if isinstance(raw_block, dict):
                merged.update(raw_block)
            cfg[key] = merged
        elif key not in raw_kind:
            pass
        else:
            cfg[key] = raw_kind[key]

    platforms = raw_kind.get("platforms", defaults.get("platforms", {}))
    cfg["platforms"] = platforms if isinstance(platforms, dict) else {}
    chats = raw_kind.get("chats", defaults.get("chats", {}))
    cfg["chats"] = chats if isinstance(chats, dict) else {}

    # model resolve: kind override > shared
    kind_provider = norm_model_field(raw_kind.get("provider", ""))
    kind_model = norm_model_field(raw_kind.get("model", ""))
    cfg["provider"] = kind_provider or shared["provider"]
    cfg["model"] = kind_model or shared["model"]

    # timeout: kind > shared; accept legacy explainer_timeout_ms on kind
    if "timeout_ms" in raw_kind:
        cfg["timeout_ms"] = coerce_int(raw_kind.get("timeout_ms"), shared["timeout_ms"], minimum=1)
    elif "explainer_timeout_ms" in raw_kind:
        cfg["timeout_ms"] = coerce_int(
            raw_kind.get("explainer_timeout_ms"), shared["timeout_ms"], minimum=1
        )
    else:
        cfg["timeout_ms"] = shared["timeout_ms"]

    # keep legacy alias for progress explain path that still checks explainer_timeout_ms
    cfg["explainer_timeout_ms"] = cfg["timeout_ms"]

    # max_input_chars: kind > shared > 64000 (designed for ≥256k-context models)
    if "max_input_chars" in raw_kind:
        cfg["max_input_chars"] = coerce_int(
            raw_kind.get("max_input_chars"), shared["max_input_chars"], minimum=0
        )
    else:
        cfg["max_input_chars"] = shared["max_input_chars"]

    cfg["_kind"] = kind
    return cfg


def resolve_enabled(kind: str, platform: str = "", chat_id: Any = None) -> bool:
    """chats.<platform>.<chat_id> → platforms.<platform> → enabled."""
    cfg = load_kind_config(kind)
    p = normalize_platform(platform)
    fallback = bool(cfg.get("enabled", False))

    per_chat = cfg.get("chats") or {}
    if isinstance(per_chat, dict) and chat_id is not None:
        bucket = per_chat.get(p)
        if isinstance(bucket, dict) and str(chat_id) in bucket:
            return coerce_bool(bucket[str(chat_id)], fallback)

    per_platform = cfg.get("platforms") or {}
    if isinstance(per_platform, dict) and p in per_platform:
        return coerce_bool(per_platform[p], fallback)

    return fallback


def resolve_model(cfg: dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
    provider = str((cfg or {}).get("provider", "") or "").strip() or None
    model = str((cfg or {}).get("model", "") or "").strip() or None
    if model and model.lower() == "auto":
        model = None
    if provider and provider.lower() == "auto":
        provider = None
    return provider, model


def resolve_timeout_s(cfg: dict[str, Any], default_ms: int = 30000) -> float:
    try:
        ms = int(cfg.get("timeout_ms") or cfg.get("explainer_timeout_ms") or default_ms)
    except (TypeError, ValueError):
        ms = default_ms
    if ms <= 0:
        ms = default_ms
    return max(0.5, ms / 1000.0)


def list_configured_kinds() -> tuple[str, ...]:
    """Built-ins plus any extra mapping keys under explainers: that look like kinds."""
    raw = _raw_explainers()
    extras = [
        k
        for k, v in raw.items()
        if k not in {"provider", "model", "timeout_ms", "max_input_chars"} and isinstance(v, dict)
    ]
    return tuple(sorted(set(known_kinds()) | set(extras)))
