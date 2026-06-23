"""OpenAI function-calling schema for memory_propose."""

from __future__ import annotations


MEMORY_PROPOSE_SCHEMA = {
    "name": "memory_propose",
    "description": (
        "Propose to update the persistent memory files (MEMORY.md / USER.md) and "
        "BLOCK until the user approves or denies. Use this instead of directly "
        "writing memory files whenever you want to persist new information about "
        "the user's preferences, environment facts, or learned patterns.\n\n"
        "HOW: make ALL your changes in ONE call via the 'operations' array (each "
        "item: {action, content?, old_text?}). The batch is applied atomically and "
        "the char limit is checked only on the FINAL result — so a single call can "
        "remove/replace stale entries to free room AND add new ones, even when an "
        "add alone would overflow. The user reviews all ops on ONE approval card "
        "and approves/denies the whole batch. Use the single-op shape "
        "(action/old_text/new_content) only for a lone one-off change.\n\n"
        "IF FULL: reissue as ONE batch that removes or shortens enough stale "
        "entries and adds the new one together.\n\n"
        "TARGETS: 'user' = who the user is (name, role, preferences, style). "
        "'memory' = your notes (environment, conventions, tool quirks, lessons).\n\n"
        "Presentation:\n"
        "  The approval card already shows every op's action + content preview. "
        "  Do NOT repeat 'old_text' or 'existing content' in your message — it "
        "  adds no value and clutters the chat.\n"
        "Returns:\n"
        "  approved=true + the memory was updated, OR\n"
        "  approved=false + reason (denied_by_user / timeout)"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["add", "replace", "remove"],
                "description": (
                    "Single-op shape: the type of update — add (append), replace "
                    "(find+replace), or remove. Omit when using 'operations'."
                ),
            },
            "target": {
                "type": "string",
                "enum": ["memory", "user"],
                "description": "Which memory file to update: 'memory' (agent notes) or 'user' (user profile).",
            },
            "old_text": {
                "type": "string",
                "description": (
                    "Single-op shape: substring that uniquely identifies the entry to "
                    "replace or remove. Ignored when using 'operations'."
                ),
            },
            "new_content": {
                "type": "string",
                "description": (
                    "Single-op shape: the new content for 'add' or 'replace'. "
                    "Ignored when using 'operations' (each op carries its own 'content')."
                ),
            },
            "operations": {
                "type": "array",
                "description": (
                    "Batch shape (preferred for multiple changes): a list of operations "
                    "applied atomically in one call against the final char budget. The "
                    "user reviews all ops on ONE approval card. Each item is "
                    "{action, content?, old_text?}."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["add", "replace", "remove"],
                            "description": "The action for this op: add, replace, or remove.",
                        },
                        "content": {
                            "type": "string",
                            "description": "Entry content for add/replace (this op).",
                        },
                        "old_text": {
                            "type": "string",
                            "description": "Substring identifying the entry for replace/remove (this op).",
                        },
                    },
                    "required": ["action"],
                },
            },
        },
        "required": ["target"],
    },
}
