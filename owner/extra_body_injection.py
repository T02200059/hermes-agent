"""Model-level extra_body injection from patch.yaml.

This is the private owner/ implementation behind the thin `# [owner]` calls
in ``agent/transports/chat_completions.py``. Keeping the logic here keeps the
official transport file as close to upstream as possible.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


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
    """
    if not isinstance(extra_body, dict) or not owner_provider_name or not model:
        return

    try:
        from owner.patch_config import get_model_extra_body

        additions = get_model_extra_body(owner_provider_name, model)
        if additions:
            extra_body.update(additions)
    except Exception as exc:
        # patch.yaml is optional; never let a config read break an API call.
        logger.debug("Model-level extra_body injection skipped: %s", exc)
