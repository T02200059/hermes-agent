"""Memory proposal approval system.

Provides a user-approval gate for all writes to MEMORY.md / USER.md.
The LLM calls ``memory_propose`` instead of ``memory``; the agent thread
blocks until the user approves or denies the proposal via /approve / /deny
or an interactive card button.
"""

from owner.memory.gateway import (
    _MemoryApprovalEntry,
    clear_memory_proposal,
    get_memory_timeout,
    handle_deny_command,
    handle_approve_command,
    has_memory_proposal,
    register_memory_notify,
    resolve_memory_approval,
    submit_memory_proposal,
    unregister_memory_notify,
    wait_for_memory_approval,
)
from owner.memory.schema import MEMORY_PROPOSE_SCHEMA
from owner.memory.tool import memory_propose_tool

__all__ = [
    "MEMORY_PROPOSE_SCHEMA",
    "_MemoryApprovalEntry",
    "clear_memory_proposal",
    "get_memory_timeout",
    "handle_approve_command",
    "handle_deny_command",
    "has_memory_proposal",
    "memory_propose_tool",
    "register_memory_notify",
    "resolve_memory_approval",
    "submit_memory_proposal",
    "unregister_memory_notify",
    "wait_for_memory_approval",
]
