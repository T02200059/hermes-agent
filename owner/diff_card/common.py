"""Shared helpers for the diff-card feature.

Nothing here depends on platform-specific SDKs.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional, Tuple

from agent.display import LocalEditSnapshot

# Tools whose successful results should trigger a diff card.
DIFF_CARD_TOOLS: frozenset[str] = frozenset({"patch", "write_file", "skill_manage", "unified_diff_patch"})

# Max visible diff lines per tool type.
_DIFF_CARD_MAX_LINES: Dict[str, int] = {
    "patch": 60,
    "write_file": 10,
    "skill_manage": 10,
    "unified_diff_patch": 60,
}

_TOOL_EMOJI: Dict[str, str] = {
    "patch": "🔧",
    "write_file": "✍️",
    "skill_manage": "📚",
    "unified_diff_patch": "🧩",
}

# Default TTL for cached diff card state (used for Feishu callback actions).
DIFF_CACHE_TTL_SECONDS: float = 3 * 60 * 60  # 3 hours


def diff_card_max_lines(tool_name: str) -> int:
    """Return the per-tool diff line budget."""
    return _DIFF_CARD_MAX_LINES.get(tool_name, 10)


def diff_card_emoji(tool_name: str) -> str:
    """Return the emoji prefix for a tool in card headers."""
    return _TOOL_EMOJI.get(tool_name, "📝")


def count_diff_changes(diff: str) -> Tuple[int, int]:
    """Count added (+) and removed (-) lines in a unified diff.

    Header lines (---/+++/@@) are not counted.
    """
    added = removed = 0
    for raw in diff.splitlines():
        if raw.startswith("+") and not raw.startswith("+++"):
            added += 1
        elif raw.startswith("-") and not raw.startswith("---"):
            removed += 1
    return added, removed


def display_file_path(tool_name: str, function_args: Dict[str, Any],
                      snapshot: Optional[LocalEditSnapshot],
                      result_data: Optional[Dict[str, Any]]) -> str:
    """Pick the best file-path label for a diff card.

    Priority:
    1. For write_file / patch: the explicit `path` argument.
    2. For skill_manage: the actual path captured in the snapshot.
    3. Fallback to files_modified in the result.
    4. Finally file_path argument (skill_manage supporting file).
    """
    if tool_name in ("write_file", "patch"):
        path = function_args.get("path")
        if path:
            return str(path)

    if snapshot is not None and snapshot.paths:
        return str(snapshot.paths[0])

    if isinstance(result_data, dict):
        files = result_data.get("files_modified") or result_data.get("files_created") or []
        if files:
            return ", ".join(str(f) for f in files)

    if tool_name == "skill_manage":
        path = function_args.get("file_path")
        if path:
            return str(path)

    return ""


def basename_for_display(path: str) -> str:
    """Return the basename of a path, or 'file' if empty."""
    return os.path.basename(path) if path else "file"


def cache_put(cache: Dict[str, Dict[str, Any]], key: str, value: Dict[str, Any],
              ttl: float = DIFF_CACHE_TTL_SECONDS) -> None:
    """Store a value with timestamp and evict expired entries."""
    now = time.time()
    expired = [
        k for k, v in cache.items()
        if now - v.get("_ts", 0) > v.get("_ttl", DIFF_CACHE_TTL_SECONDS)
    ]
    for k in expired:
        del cache[k]
    value["_ts"] = now
    value["_ttl"] = ttl
    cache[key] = value


def cache_get(cache: Dict[str, Dict[str, Any]], key: str,
              ttl: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """Retrieve a cached entry, returning None if missing or expired.

    ``ttl`` is optional; when omitted the entry's own stored TTL is used.
    """
    entry = cache.get(key)
    if entry is None:
        return None
    effective_ttl = ttl if ttl is not None else entry.get("_ttl", DIFF_CACHE_TTL_SECONDS)
    if time.time() - entry.get("_ts", 0) > effective_ttl:
        del cache[key]
        return None
    return entry
