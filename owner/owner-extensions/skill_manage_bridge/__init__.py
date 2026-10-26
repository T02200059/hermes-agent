"""Feishu skill_manage write-approval bridge.

Hooks:
  pre_gateway_dispatch — cache gateway for agent activity/interrupt resolution
  pre_tool_call        — escalate skill_manage writes on Feishu whitelist profiles

Patches (applied at register):
  - tools.approval._get_approval_timeout override (24h skill waits)
  - AIAgent._spawn_background_review skill suppress when gate active
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def register_hooks(ctx: Any) -> None:
    try:
        from owner.approval.skill_manage_gate import apply_all_patches

        apply_all_patches()
    except Exception:
        logger.warning(
            "skill_manage_bridge: apply_all_patches failed", exc_info=True,
        )

    ctx.register_hook("pre_gateway_dispatch", _on_pre_gateway_dispatch)
    ctx.register_hook("pre_tool_call", _on_pre_tool_call)
    logger.debug("skill_manage_bridge: hooks registered")


def _on_pre_gateway_dispatch(**kwargs: Any) -> None:
    gateway = kwargs.get("gateway")
    if gateway is None:
        return
    try:
        from owner.approval.skill_manage_gate import cache_gateway, ensure_patches

        ensure_patches()
        cache_gateway(gateway)
    except Exception:
        logger.debug("skill_manage_bridge: cache_gateway failed", exc_info=True)


def _on_pre_tool_call(
    tool_name: str = "",
    args: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Optional[Dict[str, Any]]:
    """Return block directive or None. Runs the full human gate when needed."""
    try:
        from owner.approval.skill_manage_gate import ensure_patches, run_gate

        ensure_patches()
        return run_gate(tool_name or "", args if isinstance(args, dict) else {})
    except Exception as exc:
        logger.exception("skill_manage_bridge: run_gate crashed")
        # Fail closed for skill_manage only
        if (tool_name or "") == "skill_manage":
            return {
                "action": "block",
                "message": (
                    f"BLOCKED: skill_manage approval gate failed ({exc}). "
                    "Do NOT retry."
                ),
            }
        return None
