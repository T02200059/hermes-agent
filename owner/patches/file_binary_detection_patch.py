"""[owner] Fix: read_file treats .py files as binary when a multi-byte
UTF-8 character straddles the ``head -c 1000`` sample boundary.

Root cause
----------
``ShellFileOperations.read_file`` / ``read_file_raw`` sample the first
1000 **bytes** with ``head -c 1000``.  The terminal backend decodes
subprocess stdout as UTF-8 with ``errors="replace"``, so when a
multi-byte character (CJK = 3 bytes, emoji = 4 bytes) is split at the
1000-byte boundary, the trailing partial sequence becomes ``U+FFFD``.

Commit 021a07688 (2026-08-01) added a guard that treats *any*
``U+FFFD`` in the first 1000 chars of the sample as proof the file is
binary, to prevent a read->edit->write round-trip from silently
corrupting non-UTF-8 files with mojibake.  That guard cannot
distinguish "the file contains illegal bytes" from "the sampler cut a
legal character in half" -- both produce ``U+FFFD``.  The result is an
**intermittent** false-positive binary classification on legitimate
UTF-8 text files (``.py``, ``.md``, ...) whenever a multi-byte
character happens to land on the byte-1000 boundary.  Denser
multi-byte content (CJK, emoji) raises the hit rate, which explains
the "偶发" pattern.

Fix
---
A truncation artifact from ``head -c`` can **only** appear at the very
last character of the decoded sample (only one byte boundary is cut).
``U+FFFD`` anywhere else in the sample is a genuine illegal byte.  So:

1. If the sample contains no ``U+FFFD``  -> original non-printable ratio check.
2. If ``U+FFFD`` appears only as the last char -> strip it (truncation
   artifact), then re-evaluate.  If no more ``U+FFFD`` remains, treat
   as text (fall through to the ratio check).
3. If ``U+FFFD`` appears in the middle (or remains after stripping the
   tail) -> genuine illegal bytes -> binary (preserves 021a07688's
   mojibake-prevention intent).

Residual risk: a file whose size is ~1000 bytes with a *real* illegal
byte exactly at the last sampled character would be misclassified as
text.  This is astronomically unlikely (the byte must land precisely
at the boundary) and the downstream read->write path carries its own
mojibake guards.  Acceptable trade-off vs. the current intermittent
false-positive on normal UTF-8 files.

No official source file is modified -- the fix is a runtime
monkey-patch on ``ShellFileOperations._is_likely_binary``, applied at
plugin register() time via ``owner/owner-extensions/__init__.py``.

See ``owner/docs/read-file-utf8-boundary-fix.md`` for the full design.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Patch state.
_originals: Dict[str, Any] = {}
_applied: bool = False

# Re-imported here so the patched method body can reference the binary
# extension set without re-importing on every call.
from tools.binary_extensions import BINARY_EXTENSIONS  # noqa: E402


def _patched_is_likely_binary(self, path: str, content_sample: Optional[str] = None) -> bool:
    """Drop-in replacement for ``ShellFileOperations._is_likely_binary``.

    Signature matches the original exactly so the official call sites
    (``read_file``, ``read_file_raw``) need no change.
    """
    ext = os.path.splitext(path)[1].lower()
    if ext in BINARY_EXTENSIONS:
        return True

    if not content_sample:
        return False

    sample = content_sample[:1000]
    if not sample:
        return False

    has_replacement = "\ufffd" in sample

    if has_replacement:
        # A head -c truncation artifact can ONLY be the last char of the
        # decoded sample (one byte boundary cut -> at most one partial
        # sequence -> at most one U+FFFD at the tail).  U+FFFD anywhere
        # else is a genuine illegal byte.
        if sample.endswith("\ufffd"):
            stripped = sample[:-1]
            if "\ufffd" not in stripped:
                # Tail U+FFFD was the only one -> truncation artifact.
                # Strip it and fall through to the ratio check on clean text.
                sample = stripped
                has_replacement = False
        # If U+FFFD remains (middle, or multiple), it's a real illegal byte.
        if has_replacement:
            return True

    # Original non-printable ratio check (unchanged).
    non_printable = sum(1 for c in sample if ord(c) < 32 and c not in '\n\r\t')
    return non_printable / min(len(sample), 1000) > 0.30


def apply_patch() -> None:
    """Patch ``ShellFileOperations._is_likely_binary`` with the boundary fix.

    Idempotent: repeated calls are no-ops once applied.  ``revert_patch``
    restores the original exactly.
    """
    global _applied
    if _applied:
        return
    from tools.file_operations import ShellFileOperations

    _originals["_is_likely_binary"] = ShellFileOperations._is_likely_binary
    ShellFileOperations._is_likely_binary = _patched_is_likely_binary
    _applied = True
    logger.info("file_binary_detection_patch applied")


def revert_patch() -> None:
    """Restore the original ``_is_likely_binary``.

    Idempotent: safe to call even if the patch was never applied.
    """
    global _applied
    orig = _originals.pop("_is_likely_binary", None)
    if orig is not None:
        from tools.file_operations import ShellFileOperations

        ShellFileOperations._is_likely_binary = orig
    _applied = False
    logger.info("file_binary_detection_patch reverted")


__all__ = ["apply_patch", "revert_patch"]
