"""Memory proposal tool implementation.

The LLM calls ``memory_propose`` instead of directly writing memory files.
The tool submits the proposal to the approval queue, notifies the user, and
blocks until approval/denial or timeout.

Two shapes are supported (mirrors the dual shape in tools/memory_tool.py):

- **Single-op**: ``action`` + ``old_text`` + ``new_content`` for one change.
- **Batch**: ``operations`` = list of ``{action, content?, old_text?}`` dicts
  applied atomically via ``MemoryStore.apply_batch`` on approval. Preferred
  when making multiple changes — the user reviews all ops on ONE card and the
  char budget is checked only on the FINAL result.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from owner.memory.gateway import (
    _get_session_key,
    get_memory_timeout,
    submit_memory_proposal,
    wait_for_memory_approval,
    _notify,
)

logger = logging.getLogger(__name__)


_VALID_ACTIONS = ("add", "replace", "remove")
_VALID_TARGETS = ("memory", "user")


def _validate_operations(operations: Any) -> Optional[str]:
    """Return a human-readable error reason if ``operations`` is malformed, else None.

    Each item must be a dict with an ``action`` in {add, replace, remove} AND the
    fields that action requires, mirroring ``MemoryStore.apply_batch``:
      - add     → non-empty ``content``
      - replace → non-empty ``old_text`` AND non-empty ``content``
      - remove  → non-empty ``old_text``

    Validating shape here (pre-approval) means the model gets an immediate
    ``invalid_operations`` error instead of rendering an empty/partial approval
    card the user wastes a decision on, only for ``apply_batch`` to reject it
    after approval. This matches the single-op path, which validates early.
    """
    if not isinstance(operations, list) or not operations:
        return "operations must be a non-empty array."
    for i, op in enumerate(operations):
        pos = f"operation {i + 1}"
        if not isinstance(op, dict):
            return f"{pos}: each operation must be an object."
        act = op.get("action")
        if act not in _VALID_ACTIONS:
            return f"{pos}: action must be one of add, replace, remove (got {act!r})."
        content = (op.get("content") or "").strip()
        old_text = (op.get("old_text") or "").strip()
        if act in ("add", "replace") and not content:
            return f"{pos}: action {act!r} requires non-empty 'content'."
        if act in ("replace", "remove") and not old_text:
            return f"{pos}: action {act!r} requires non-empty 'old_text'."
    return None


def memory_propose_tool(
    action: str = "",
    target: str = "",
    old_text: str = "",
    new_content: str = "",
    operations: Optional[List[Dict[str, Any]]] = None,
    store: Optional[Any] = None,
) -> str:
    """Propose a memory update and wait for user approval.

    Args:
        action: "add", "replace", or "remove" (single-op shape only)
        target: "memory" or "user" (required for both shapes)
        old_text: substring to identify the entry (single-op shape, replace/remove)
        new_content: new entry content (single-op shape, add/replace)
        operations: batch shape — list of {action, content?, old_text?} dicts
            applied atomically. Preferred for multiple changes.
        store: MemoryStore instance (injected by tool_executor)

    Returns:
        JSON string with the result.
    """
    # ---- target is required for both shapes --------------------------------
    if target not in _VALID_TARGETS:
        return json.dumps({
            "approved": False,
            "reason": "invalid_target",
            "message": f"target must be one of: memory, user. Got: {target!r}",
        }, ensure_ascii=False)

    # ---- shape selection: single-op XOR batch ------------------------------
    has_single = bool(action)
    has_batch = bool(operations)

    if has_single and has_batch:
        # Mutually exclusive — the model picked both shapes at once.
        return json.dumps({
            "approved": False,
            "reason": "conflicting_shape",
            "message": (
                "Provide either the single-op fields (action/old_text/new_content) "
                "OR the 'operations' array — not both."
            ),
        }, ensure_ascii=False)

    if has_batch:
        # Validate the operations list structure. Per-op content/old_text
        # constraints are enforced at write time by store.apply_batch.
        bad = _validate_operations(operations)
        if bad is not None:
            return json.dumps({
                "approved": False,
                "reason": "invalid_operations",
                "message": (
                    f"{bad} Each item must be "
                    "{action: add|replace|remove, content?, old_text?} with the "
                    "fields that action requires."
                ),
            }, ensure_ascii=False)
    else:
        # Single-op shape: validate the single action.
        if action not in _VALID_ACTIONS:
            return json.dumps({
                "approved": False,
                "reason": "invalid_action",
                "message": f"action must be one of: add, replace, remove. Got: {action!r}",
            }, ensure_ascii=False)

    session_key = _get_session_key()
    timeout = get_memory_timeout()

    entry = submit_memory_proposal(
        action=action,
        target=target,
        old_text=old_text,
        new_content=new_content,
        operations=operations,
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
            _do_memory_write(
                store, target,
                action=action, old_text=old_text, new_content=new_content,
                operations=operations,
            )
            if operations:
                return json.dumps({
                    "approved": True,
                    "target": target,
                    "operations": len(operations),
                    "applied": "batch",
                }, ensure_ascii=False)
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
    target: str,
    *,
    action: str = "",
    old_text: str = "",
    new_content: str = "",
    operations: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """Perform the actual memory write via MemoryStore.

    - Batch shape (``operations`` set): one atomic ``store.apply_batch(target,
      operations)`` call. All-or-nothing — if any op is malformed, doesn't
      match, or the net result would exceed the char limit, NOTHING is written
      and the resulting RuntimeError surfaces the live state.
    - Single-op shape: legacy ``store.add/replace/remove`` path.

    Raises RuntimeError when the store reports failure.
    """
    if operations:
        # Atomic batch — MemoryStore.apply_batch validates every op against the
        # FINAL budget and returns current_entries/usage on failure.
        result = store.apply_batch(target, operations)
    elif action == "remove":
        result = store.remove(target, old_text)
    elif action == "replace":
        result = store.replace(target, old_text, new_content)
    else:  # add
        result = store.add(target, new_content)

    if not result.get("success"):
        raise RuntimeError(result.get("error", "Unknown error"))
