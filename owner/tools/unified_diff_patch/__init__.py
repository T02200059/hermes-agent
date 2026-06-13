"""Owner's unified-diff patch tool.

Core implementation lives here; the official ``tools/unified_diff_patch_tool.py``
file is a thin registration glue only.
"""

from .engine import apply_unified_diff
from .interface import (
    UNIFIED_DIFF_PATCH_SCHEMA,
    _check_file_reqs,
    _handle_unified_diff_patch,
    unified_diff_patch_tool,
)
from .parser import FilePatch, Hunk, parse_unified_diff

__all__ = [
    "apply_unified_diff",
    "FilePatch",
    "Hunk",
    "parse_unified_diff",
    "UNIFIED_DIFF_PATCH_SCHEMA",
    "unified_diff_patch_tool",
    "_check_file_reqs",
    "_handle_unified_diff_patch",
]
