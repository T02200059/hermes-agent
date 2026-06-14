"""OpenAI function-calling schema for memory_propose."""

from __future__ import annotations


MEMORY_PROPOSE_SCHEMA = {
    "name": "memory_propose",
    "description": (
        "Propose to update the persistent memory files (MEMORY.md / USER.md). "
        "This tool BLOCKS until the user approves or denies. "
        "Use this instead of directly writing memory files whenever you want to "
        "persist new information about the user's preferences, environment facts, "
        "or learned patterns.\n"
        "Args:\n"
        "  action: 'add' (append), 'replace' (find+replace), or 'remove'\n"
        "  target: 'memory' (agent notes) or 'user' (user profile)\n"
        "  old_text: substring to identify the entry being replaced/removed\n"
        "  new_content: the new content (for add/replace)\n"
        "Presentation:\n"
        "  The approval card already shows action, target, and new content. "
        "  Do NOT repeat 'old_text' or 'existing content' in your message — "
        "  it adds no value and clutters the chat.\n"
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
                "description": "The type of update: add (append), replace (find+replace), or remove.",
            },
            "target": {
                "type": "string",
                "enum": ["memory", "user"],
                "description": "Which memory file to update: 'memory' (agent notes) or 'user' (user profile).",
            },
            "old_text": {
                "type": "string",
                "description": (
                    "Substring that uniquely identifies the entry to replace or remove. "
                    "Used for 'replace' and 'remove' actions. For 'add', pass an empty string."
                ),
            },
            "new_content": {
                "type": "string",
                "description": (
                    "The new content for 'add' or 'replace' actions. "
                    "For 'remove', pass an empty string."
                ),
            },
        },
        "required": ["action", "target", "old_text", "new_content"],
    },
}
