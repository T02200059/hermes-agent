# [owner] memory_propose tool: registration glue + runtime toolset patch.
# Core implementation lives in owner/memory/.
from __future__ import annotations
from typing import Any

# Force legacy memory tool registration so we can deregister it reliably.
import tools.memory_tool  # noqa: F401

# Runtime patch: replace memory toolset with memory_propose and remove legacy
# memory from core tool lists. Must happen before tool discovery finishes.
import owner.memory.setup  # noqa: F401

from owner.memory import MEMORY_PROPOSE_SCHEMA, memory_propose_tool
from tools.registry import registry

__all__ = ["memory_propose_tool"]


def _handle_memory_propose(args: dict, **kw: Any) -> str:
    return memory_propose_tool(
        action=args.get("action", ""),
        target=args.get("target", ""),
        old_text=args.get("old_text", ""),
        new_content=args.get("new_content", ""),
        store=kw.get("store"),
    )


registry.register(
    name="memory_propose",
    toolset="memory",
    schema=MEMORY_PROPOSE_SCHEMA,
    handler=_handle_memory_propose,
    check_fn=lambda: True,
    emoji="💾",
)
