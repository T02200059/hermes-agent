"""Unified-diff parser used by the owner unified_diff_patch tool.

Kept separate from the apply engine so the parser can be unit-tested without
spinning up file operations or terminal environments.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class Hunk:
    """One @@ hunk from a unified diff."""

    old_start: int          # 1-based line number in original file
    old_count: int          # number of lines consumed from original
    new_start: int          # 1-based line number in new file
    new_count: int          # number of lines produced in new file
    old_lines: List[str] = field(default_factory=list)   # ' ' + '-' lines
    new_lines: List[str] = field(default_factory=list)   # ' ' + '+' lines


@dataclass
class FilePatch:
    """A single file's worth of hunks."""

    old_path: str
    new_path: str
    hunks: List[Hunk] = field(default_factory=list)
    is_new: bool = False
    is_deleted: bool = False


_HUNK_HEADER_RE = re.compile(
    r'^@@\s+-(?P<old_start>\d+)(?:,(?P<old_count>\d+))?'
    r'\s+\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))?\s+@@'
)


def _normalize_diff_path(path: str) -> str:
    """Strip an optional git a/b prefix from diff paths.

    Relative paths may be written as ``a/relative/path`` or simply
    ``relative/path``.  Absolute paths may be written directly as
    ``/absolute/path``; the leading slash is preserved.
    """
    path = path.strip()
    if path.startswith('a/') or path.startswith('b/'):
        return path[2:]
    return path


def parse_unified_diff(
    patch_content: str,
    *,
    strict: bool = False,
    auto_fix_header: bool = True,
) -> Tuple[List[FilePatch], Optional[str], Optional[str]]:
    """Parse a standard unified diff into structured FilePatch/Hunk objects.

    Args:
        patch_content: The unified diff text.
        strict: When True, reject blank lines and bare lines inside hunk
            bodies with a precise error.  Recommended for hand-written diffs.
        auto_fix_header: When True (default), silently correct ``@@`` header
            line counts that do not match the parsed body.  This removes the
            most common source of failures for weaker models.
    """
    # Normalize CRLF/CR to LF so prefix detection and context matching work.
    # \r\n must be replaced BEFORE lone \r to avoid double newlines.
    lines = patch_content.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    if lines and lines[-1] == '':
        lines.pop()

    strict_errors: List[str] = []
    strict_warnings: List[str] = []
    file_patches: List[FilePatch] = []
    current: Optional[FilePatch] = None
    current_hunk: Optional[Hunk] = None
    hunk_body_line = 0

    i = 0
    while i < len(lines):
        line = lines[i]

        if line.startswith('--- '):
            # Flush previous state before starting a new file patch.
            if current_hunk and current:
                current.hunks.append(current_hunk)
                current_hunk = None
            if current:
                file_patches.append(current)

            old_path_raw = line[4:].strip()
            new_path_raw = ''
            if i + 1 < len(lines) and lines[i + 1].startswith('+++ '):
                new_path_raw = lines[i + 1][4:].strip()
                i += 1  # consume the +++ line

            old_path = _normalize_diff_path(old_path_raw)
            new_path = _normalize_diff_path(new_path_raw)

            is_new = old_path == '/dev/null'
            is_deleted = new_path == '/dev/null'
            target = new_path if not is_deleted else old_path

            current = FilePatch(
                old_path=old_path,
                new_path=target,
                is_new=is_new,
                is_deleted=is_deleted,
            )
            current_hunk = None

        elif line.startswith('@@') and current is not None:
            if current_hunk:
                current.hunks.append(current_hunk)

            m = _HUNK_HEADER_RE.match(line)
            if not m:
                return [], f"Invalid hunk header: {line!r}", None

            current_hunk = Hunk(
                old_start=int(m.group('old_start')),
                old_count=int(m.group('old_count') or '1'),
                new_start=int(m.group('new_start')),
                new_count=int(m.group('new_count') or '1'),
            )
            hunk_body_line = 0

        elif current_hunk is not None:
            hunk_body_line += 1
            if line.startswith('\\'):
                # "\ No newline at end of file" — metadata marker, skip.
                pass
            elif line.startswith(' '):
                content = line[1:]
                current_hunk.old_lines.append(content)
                current_hunk.new_lines.append(content)
            elif line.startswith('-'):
                current_hunk.old_lines.append(line[1:])
            elif line.startswith('+'):
                current_hunk.new_lines.append(line[1:])
            elif line == '':
                if strict:
                    strict_errors.append(
                        f"{current.new_path}: hunk {len(current.hunks) + 1} "
                        f"line {hunk_body_line} is an empty line without a "
                        "leading space. In strict mode every hunk body line "
                        "must start with ' ', '+', '-', or '\\'."
                    )
                current_hunk.old_lines.append('')
                current_hunk.new_lines.append('')
            else:
                if strict:
                    strict_errors.append(
                        f"{current.new_path}: hunk {len(current.hunks) + 1} "
                        f"line {hunk_body_line} is a bare line {line!r} "
                        "(no leading space, '+', '-', or '\\'). "
                        "In strict mode hunk body lines must use the standard prefix."
                    )
                current_hunk.old_lines.append(line)
                current_hunk.new_lines.append(line)

        i += 1

    if current_hunk and current:
        current.hunks.append(current_hunk)
    if current:
        file_patches.append(current)

    if not file_patches:
        return [], "No file patches found in diff", None

    # Strict format errors are root causes; report them before count mismatches.
    if strict and strict_errors:
        return [], "Strict parse error: " + "; ".join(strict_errors), None

    errors: List[str] = []
    for fp in file_patches:
        for hi, h in enumerate(fp.hunks):
            actual_old = len(h.old_lines)
            actual_new = len(h.new_lines)
            if strict and auto_fix_header and (
                actual_old != h.old_count or actual_new != h.new_count
            ):
                strict_warnings.append(
                    f"{fp.new_path}: hunk {hi + 1} header count mismatch "
                    f"(old header {h.old_count} vs {actual_old} body lines, "
                    f"new header {h.new_count} vs {actual_new} body lines). "
                    "Tip: count context + removed/added lines before writing the header. "
                    "Auto-corrected because auto_fix_header=True (default)."
                )
            if actual_old != h.old_count:
                if auto_fix_header:
                    h.old_count = actual_old
                else:
                    errors.append(
                        f"{fp.new_path}: hunk {hi + 1} old line count mismatch "
                        f"(header says {h.old_count}, parsed {actual_old}). "
                        "Tip: count context + removed lines, or set auto_fix_header=true."
                    )
            if actual_new != h.new_count:
                if auto_fix_header:
                    h.new_count = actual_new
                else:
                    errors.append(
                        f"{fp.new_path}: hunk {hi + 1} new line count mismatch "
                        f"(header says {h.new_count}, parsed {actual_new}). "
                        "Tip: count context + added lines, or set auto_fix_header=true."
                    )

    if errors:
        return [], "Parse error: " + "; ".join(errors), None

    return (
        file_patches,
        None,
        "\n".join(strict_warnings) if strict_warnings else None,
    )
