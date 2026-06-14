"""Memory proposal tool implementation.

The LLM calls ``memory_propose`` instead of directly writing memory files.
The tool submits the proposal to the approval queue, notifies the user, and
blocks until approval/denial or timeout.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from owner.memory.gateway import (
    _get_session_key,
    get_memory_timeout,
    submit_memory_proposal,
    wait_for_memory_approval,
    _notify,
)

logger = logging.getLogger(__name__)


def memory_propose_tool(
    action: str,
    target: str,
    old_text: str,
    new_content: str,
    store: Optional[Any] = None,
) -> str:
    """Propose a memory update and wait for user approval.

    Args:
        action: "add", "replace", or "remove"
        target: "memory" or "user"
        old_text: substring to identify the entry (for replace/remove)
        new_content: new entry content (for add/replace)
        store: MemoryStore instance (injected by tool_executor)

    Returns:
        JSON string with the result.
    """
    if action not in ("add", "replace", "remove"):
        return json.dumps({
            "approved": False,
            "reason": "invalid_action",
            "message": f"action must be one of: add, replace, remove. Got: {action}",
        }, ensure_ascii=False)

    if target not in ("memory", "user"):
        return json.dumps({
            "approved": False,
            "reason": "invalid_target",
            "message": f"target must be one of: memory, user. Got: {target}",
        }, ensure_ascii=False)

    session_key = _get_session_key()
    timeout = get_memory_timeout()

    entry = submit_memory_proposal(
        action=action,
        target=target,
        old_text=old_text,
        new_content=new_content,
        session_key=session_key,
    )

    # Notify the user via the gateway-registered callback, then block.
    _notify(session_key, entry)

    result = wait_for_memory_approval(entry, timeout=float(timeout))

    if result == "approve":
        if store is None:
            return json.dumps({
                "approved": False,
                "reason": "no_store",
                "message": "MemoryStore not available in this context.",
            }, ensure_ascii=False)
        try:
            _do_memory_write(store, action, target, old_text, new_content)
            return json.dumps({
                "approved": True,
                "action": action,
                "target": target,
                "content": new_content,
            }, ensure_ascii=False)
        except Exception as exc:
            logger.error("Failed to write memory: %s", exc)
            return json.dumps({
                "approved": False,
                "reason": "write_error",
                "message": f"Failed to update memory: {exc}",
            }, ensure_ascii=False)

    if result == "deny":
        return json.dumps({
            "approved": False,
            "reason": "denied_by_user",
        }, ensure_ascii=False)

    return json.dumps({
        "approved": False,
        "reason": "timeout",
    }, ensure_ascii=False)


def _do_memory_write(
    store: Any,
    action: str,
    target: str,
    old_text: str,
    new_content: str,
) -> None:
    """Perform the actual memory write via MemoryStore."""
    if action == "remove":
        result = store.remove(target, old_text)
    elif action == "replace":
        result = store.replace(target, old_text, new_content)
    else:  # add
        result = store.add(target, new_content)

    if not result.get("success"):
        raise RuntimeError(result.get("error", "Unknown error"))
