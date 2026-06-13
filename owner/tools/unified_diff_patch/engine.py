"""Apply engine for parsed unified-diff FilePatch objects.

This module is independent of the tool handler; it can be used by tests and
other callers that already have a FileOperations object.
"""

from __future__ import annotations

import difflib
from typing import List, Optional, Tuple

from tools.file_operations import (
    FileOperations,
    PatchResult,
    _detect_line_ending,
    _normalize_line_endings,
)

from .parser import FilePatch, Hunk


def _resolve_hunk_start(
    lines: List[str],
    hunk_old_lines: List[str],
    declared_idx: int,
    old_count: int,
    auto_fix_start: bool,
) -> Tuple[Optional[int], Optional[str]]:
    """Resolve the correct 0-based start index for a hunk.

    Tries three strategies in order:
    1. Exact match at the declared position.
    2. Trailing-whitespace-tolerant match at the declared position.
    3. Full-file context search requiring a *unique* match (only when
       ``auto_fix_start`` is True).

    Returns ``(resolved_idx, hint)``.  ``resolved_idx`` is None on failure;
    ``hint`` is only set on failure.
    """
    if old_count == 0:
        return declared_idx, None

    candidate = lines[declared_idx : declared_idx + old_count]
    stripped_expected = [l.rstrip() for l in hunk_old_lines]

    if candidate == hunk_old_lines:
        return declared_idx, None

    if [l.rstrip() for l in candidate] == stripped_expected:
        return declared_idx, None

    if auto_fix_start:
        found_at: Optional[int] = None
        ambiguous = False
        limit = max(0, len(lines) - old_count + 1)
        for try_idx in range(limit):
            if try_idx == declared_idx:
                continue
            c = lines[try_idx : try_idx + old_count]
            if c == hunk_old_lines or [l.rstrip() for l in c] == stripped_expected:
                if found_at is not None:
                    ambiguous = True
                    break
                found_at = try_idx
        if not ambiguous and found_at is not None:
            return found_at, None
        if ambiguous:
            return None, (
                "Context is ambiguous — found at multiple file locations. "
                "Add more context lines to make the hunk unique."
            )

    # Build a location hint by scanning the file for the expected context.
    alt_loc: Optional[int] = None
    limit = max(0, len(lines) - old_count + 1)
    for search_idx in range(limit):
        c = lines[search_idx : search_idx + old_count]
        if c == hunk_old_lines or [l.rstrip() for l in c] == stripped_expected:
            alt_loc = search_idx + 1  # 1-based for display
            break

    if alt_loc is not None:
        hint = (
            f"Context found at line {alt_loc}, not {declared_idx + 1}. "
            f"Did you mean @@ -{alt_loc} @@?"
        )
    else:
        hint = (
            "Context not found anywhere in file — verify the file content "
            "matches what you read before writing this patch."
        )
    return None, hint


def _apply_file_patch(
    fp: FilePatch,
    file_ops: FileOperations,
    *,
    auto_fix_start: bool = True,
    dry_run: bool = False,
) -> Tuple[bool, str, Optional[str]]:
    """Apply (or preview) a single FilePatch.

    Returns ``(success, diff_or_error, lsp_diagnostics)``.
    """
    path = fp.new_path

    if fp.is_deleted:
        read_result = file_ops.read_file_raw(path)
        if read_result.error:
            return False, f"Cannot read file for deletion: {read_result.error}", None
        removed = read_result.content.splitlines(keepends=True)
        if not dry_run:
            delete_result = file_ops.delete_file(path)
            if delete_result.error:
                return False, delete_result.error, None
        diff = ''.join(difflib.unified_diff(
            removed, [],
            fromfile=f"a/{path}",
            tofile="/dev/null",
        ))
        return True, diff or f"# {'Would delete' if dry_run else 'Deleted'}: {path}", None

    if fp.is_new:
        content = '\n'.join(fp.hunks[0].new_lines) if fp.hunks else ''
        if not dry_run:
            write_result = file_ops.write_file(path, content)
            if write_result.error:
                return False, write_result.error, None
            lsp = getattr(write_result, "lsp_diagnostics", None)
        else:
            lsp = None
        diff = f"--- /dev/null\n+++ b/{path}\n"
        diff += '\n'.join(f"+{ln}" for ln in (fp.hunks[0].new_lines if fp.hunks else []))
        return True, diff, lsp

    # UPDATE
    read_result = file_ops.read_file_raw(path)
    if read_result.error:
        return False, f"Cannot read file: {read_result.error}", None

    original = read_result.content
    line_ending = _detect_line_ending(original)
    # Normalize to LF for matching, then restore the original line ending later.
    original_lf = original.replace('\r\n', '\n').replace('\r', '\n')
    has_trailing_nl = original_lf.endswith('\n')
    file_lines = original_lf.split('\n')
    if file_lines and file_lines[-1] == '':
        file_lines.pop()

    # Apply from bottom to top so later hunks do not shift earlier ones.
    sorted_hunks = sorted(fp.hunks, key=lambda h: h.old_start, reverse=True)
    new_lines = list(file_lines)

    for hi, hunk in enumerate(sorted_hunks):
        start_idx = hunk.old_start - 1
        if start_idx < 0:
            if hunk.old_count == 0:
                start_idx = 0
            else:
                return False, (
                    f"{path}: hunk {hi + 1} invalid old_start {hunk.old_start}"
                ), None

        end_idx = start_idx + hunk.old_count
        if end_idx > len(new_lines) and not auto_fix_start:
            return False, (
                f"{path}: hunk {hi + 1} exceeds file bounds "
                f"(needs lines {start_idx + 1}-{end_idx}, file has {len(new_lines)})"
            ), None

        resolved_idx, hint = _resolve_hunk_start(
            new_lines, hunk.old_lines, start_idx, hunk.old_count, auto_fix_start
        )
        if resolved_idx is None:
            declared_actual = new_lines[start_idx:end_idx]
            for offset, (actual, expected) in enumerate(zip(declared_actual, hunk.old_lines)):
                if actual.rstrip() != expected.rstrip():
                    line_no = start_idx + offset + 1
                    return False, (
                        f"{path}: context mismatch at line {line_no} in hunk {hi + 1}. "
                        f"Expected {expected!r}, got {actual!r}\n"
                        f"Hint: {hint}"
                    ), None
            return False, (
                f"{path}: line count mismatch in hunk {hi + 1} "
                f"(expected {len(hunk.old_lines)} lines, found {len(declared_actual)})\n"
                f"Hint: {hint}"
            ), None

        start_idx = resolved_idx
        end_idx = start_idx + hunk.old_count
        new_lines = new_lines[:start_idx] + hunk.new_lines + new_lines[end_idx:]

    new_content_lf = '\n'.join(new_lines)
    if has_trailing_nl:
        new_content_lf += '\n'
    new_content = (
        _normalize_line_endings(new_content_lf, line_ending)
        if line_ending
        else new_content_lf
    )

    if not dry_run:
        write_result = file_ops.write_file(path, new_content)
        if write_result.error:
            return False, write_result.error, None
        lsp = getattr(write_result, "lsp_diagnostics", None)
    else:
        lsp = None

    diff = ''.join(difflib.unified_diff(
        original.splitlines(keepends=True),
        new_content.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
    ))

    return True, diff, lsp


def apply_unified_diff(
    file_patches: List[FilePatch],
    file_ops: FileOperations,
    *,
    auto_fix_start: bool = True,
    dry_run: bool = False,
) -> PatchResult:
    """Apply unified diff patches file by file.  Aborts on first error."""
    files_modified: List[str] = []
    files_created: List[str] = []
    files_deleted: List[str] = []
    all_diffs: List[str] = []
    lsp_blocks: List[str] = []
    errors: List[str] = []

    for fp in file_patches:
        try:
            ok, diff_or_err, lsp = _apply_file_patch(
                fp, file_ops,
                auto_fix_start=auto_fix_start,
                dry_run=dry_run,
            )
            if ok:
                if fp.is_new:
                    files_created.append(fp.new_path)
                elif fp.is_deleted:
                    files_deleted.append(fp.new_path)
                else:
                    files_modified.append(fp.new_path)
                all_diffs.append(diff_or_err)
                if lsp:
                    lsp_blocks.append(lsp)
            else:
                errors.append(diff_or_err)
                break
        except Exception as exc:
            errors.append(f"{fp.new_path}: {exc}")
            break

    combined_diff = '\n'.join(all_diffs)

    if errors:
        return PatchResult(
            success=False,
            diff=combined_diff,
            files_modified=files_modified,
            files_created=files_created,
            files_deleted=files_deleted,
            lsp_diagnostics="\n\n".join(lsp_blocks) if lsp_blocks else None,
            error="Patch failed (no further files modified):\n"
                  + "\n".join(f"  • {e}" for e in errors),
        )

    lint_results = {}
    if not dry_run:
        for f in files_modified + files_created:
            if hasattr(file_ops, '_check_lint'):
                lint_result = file_ops._check_lint(f)
                lint_results[f] = lint_result.to_dict()

    return PatchResult(
        success=True,
        diff=combined_diff,
        files_modified=files_modified,
        files_created=files_created,
        files_deleted=files_deleted,
        lint=lint_results if lint_results else None,
        lsp_diagnostics="\n\n".join(lsp_blocks) if lsp_blocks else None,
    )
