"""Model-level extra_body injection from patch.yaml.

This is the private owner/ implementation behind the thin `# [owner]` calls
in ``agent/transports/chat_completions.py``. Keeping the logic here keeps the
official transport file as close to upstream as possible.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# WR-02: defense-in-depth allowlist for keys merged into extra_body.
# patch.yaml lives in ~/.hermes/patch.yaml — operator-writable, not
# user-LLM-controllable, but a compromised cron script or mistaken edit
# could put arbitrary keys here. Without an allowlist, a hostile entry
# like `tools: [{...arbitrary tool definition...}]` would be merged
# verbatim into the LLM request. Only keys the owner actually uses
# (today: thinking-mode switches for xfyun/damodel) are permitted.
# Extend this set deliberately when adding new features; do NOT widen
# the merge to "everything in patch.yaml".
_ALLOWED_EXTRA_BODY_KEYS = frozenset({"enable_thinking", "thinking"})

# Nested allowlist for known dict-typed top-level keys. Anything not in
# this set inside an allowed parent is dropped.
_ALLOWED_NESTED_KEYS: Dict[str, frozenset] = {
    "thinking": frozenset({"type", "clear_thinking"}),
}


def _filter_extra_body(additions: Dict[str, Any]) -> Dict[str, Any]:
    """Drop any keys not in the allowlist; recurse one level for nested dicts."""
    filtered: Dict[str, Any] = {}
    for key, value in additions.items():
        if key not in _ALLOWED_EXTRA_BODY_KEYS:
            logger.warning(
                "Model extra_body: dropping non-allowlisted key %r for provider injection",
                key,
            )
            continue
        nested = _ALLOWED_NESTED_KEYS.get(key)
        if nested is not None and isinstance(value, dict):
            value = {
                k: v for k, v in value.items() if k in nested
            }
        filtered[key] = value
    return filtered


def inject_model_extra_body(
    extra_body: Dict[str, Any],
    owner_provider_name: Optional[str],
    model: Optional[str],
) -> None:
    """Merge per-model extra_body from patch.yaml into ``extra_body`` in-place.

    ``owner_provider_name`` is the true provider identity preserved by
    ``owner/attribution.py`` (e.g. ``xfyun``, ``damodel``). For built-in
    providers it falls back to the canonical provider name. This lets the same
    patch.yaml section distinguish multiple custom endpoints that all resolve
    to ``agent.provider == "custom"``.

    Only allowlisted keys are merged; see ``_ALLOWED_EXTRA_BODY_KEYS``.
    """
    if not isinstance(extra_body, dict) or not owner_provider_name or not model:
        return

    try:
        from owner.patch_config import get_model_extra_body

        additions = get_model_extra_body(owner_provider_name, model)
        if additions:
            extra_body.update(_filter_extra_body(additions))
    except Exception as exc:
        # patch.yaml is optional; never let a config read break an API call.
        logger.debug("Model-level extra_body injection skipped: %s", exc)
