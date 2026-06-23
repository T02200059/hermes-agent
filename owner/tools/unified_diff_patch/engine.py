"""Apply engine for parsed unified-diff FilePatch objects.

This module is independent of the tool handler; it can be used by tests and
other callers that already have a FileOperations object.
"""

from __future__ import annotations

import difflib
import os
from typing import List, Optional, Tuple

from tools.file_operations import (
    FileOperations,
    PatchResult,
    _detect_line_ending,
    _normalize_line_endings,
)

from .parser import FilePatch, Hunk


def _find_context_matches(
    lines: List[str],
    hunk_old_lines: List[str],
    old_count: int,
) -> List[int]:
    """Return 1-based line numbers of every full match of the hunk context.

    R4 / P0-A: helper for the ambiguous-context error path. Tries both an
    exact match and a trailing-whitespace-tolerant match at each sliding
    window, mirroring the resolution logic in _resolve_hunk_start.
    """
    if old_count == 0:
        return []
    stripped_expected = [ln.rstrip() for ln in hunk_old_lines]
    matches: List[int] = []
    limit = max(0, len(lines) - old_count + 1)
    for idx in range(limit):
        candidate = lines[idx : idx + old_count]
        if candidate == hunk_old_lines or [ln.rstrip() for ln in candidate] == stripped_expected:
            matches.append(idx + 1)
    return matches


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
            # R4 / P0-A: list every candidate location with a short preview so
            # the user can pick the right Host block instead of guessing.
            matches = _find_context_matches(lines, hunk_old_lines, old_count)
            preview_limit = 10
            preview_lines: List[str] = []
            for loc in matches[:preview_limit]:
                preview_start = max(0, loc - 2)
                snippet_end = loc + old_count
                snippet = lines[preview_start:snippet_end]
                joined = " | ".join(snippet)
                preview_lines.append(f"  - line {loc}: {joined}")
            if len(matches) > preview_limit:
                preview_lines.append(f"  ... and {len(matches) - preview_limit} more")
            hint = (
                f"Context is ambiguous — found at {len(matches)} file locations.\n"
                f"Candidate locations:\n"
                + "\n".join(preview_lines)
                + "\nAdd more context lines to make the hunk unique."
            )
            return None, hint

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
            return False, (
                f"Cannot read file for deletion: {read_result.error}\n"
                f"  Resolved target: {path}\n"
                f"  Process CWD: {os.getcwd()}"
            ), None
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
        # Concatenate every hunk's added lines — a new-file diff is normally a
        # single hunk, but a multi-hunk new file must not silently drop the
        # 2nd+ hunks (which using ``hunks[0]`` alone would do).
        new_file_lines = [ln for h in fp.hunks for ln in h.new_lines]
        content = '\n'.join(new_file_lines)
        if not dry_run:
            write_result = file_ops.write_file(path, content)
            if write_result.error:
                return False, write_result.error, None
            lsp = getattr(write_result, "lsp_diagnostics", None)
        else:
            lsp = None
        diff = f"--- /dev/null\n+++ b/{path}\n"
        diff += '\n'.join(f"+{ln}" for ln in new_file_lines)
        return True, diff, lsp

    # UPDATE
    read_result = file_ops.read_file_raw(path)
    if read_result.error:
        return False, (
            f"Cannot read file: {read_result.error}\n"
            f"  Resolved target: {path}\n"
            f"  Process CWD: {os.getcwd()}"
        ), None

    original = read_result.content
    line_ending = _detect_line_ending(original)
    # Normalize to LF for matching, then restore the original line ending later.
    original_lf = original.replace('\r\n', '\n').replace('\r', '\n')
    has_trailing_nl = original_lf.endswith('\n')
    file_lines = original_lf.split('\n')
    if file_lines and file_lines[-1] == '':
        file_lines.pop()

    # Pass 1 — resolve every hunk's start index against the ORIGINAL file.
    # Resolving against the immutable original (rather than a progressively
    # mutated buffer) lets us derive the apply order from the RESOLVED
    # positions: auto_fix_start may relocate a hunk far from its declared @@
    # line, and sorting by the declared old_start (as we used to) would then
    # splice relocated hunks out of order and corrupt the file.
    # Each entry: (resolved_idx, old_count, new_lines, original_hunk_index).
    resolved_hunks: List[Tuple[int, int, List[str], int]] = []
    for hi, hunk in enumerate(fp.hunks):
        start_idx = hunk.old_start - 1
        if start_idx < 0:
            if hunk.old_count == 0:
                start_idx = 0
            else:
                return False, (
                    f"{path}: hunk {hi + 1} invalid old_start {hunk.old_start}"
                ), None

        resolved_idx, hint = _resolve_hunk_start(
            file_lines, hunk.old_lines, start_idx, hunk.old_count, auto_fix_start
        )
        if resolved_idx is None:
            # R4 / P0-B: bounds check moved here so alt_loc / Did-you-mean hint
            # can ride along on the "exceeds file bounds" error too. Previously
            # the bounds branch at L182-187 returned early and short-circuited
            # the existing alt_loc scan in _resolve_hunk_start.
            end_idx = start_idx + hunk.old_count
            if end_idx > len(file_lines) and not auto_fix_start:
                bounds_hint = (
                    f"\nHint: {hint}" if hint else ""
                )
                return False, (
                    f"{path}: hunk {hi + 1} exceeds file bounds "
                    f"(needs lines {start_idx + 1}-{end_idx}, file has {len(file_lines)})"
                    f"{bounds_hint}"
                ), None

            declared_actual = file_lines[start_idx:end_idx]
            # R4 / P1-D: show the full expected vs actual block so the user
            # can spot the offset at a glance, instead of just the first
            # mismatching line.
            first_bad_line: Optional[int] = None
            for offset, (actual, expected) in enumerate(zip(declared_actual, hunk.old_lines)):
                if actual.rstrip() != expected.rstrip():
                    first_bad_line = start_idx + offset + 1
                    break
            if first_bad_line is not None:
                expected_display = "\n".join(
                    f"    {start_idx + i + 1}|{line}"
                    for i, line in enumerate(hunk.old_lines)
                )
                actual_display = "\n".join(
                    f"    {start_idx + i + 1}|{line}"
                    for i, line in enumerate(declared_actual)
                )
                return False, (
                    f"{path}: context mismatch in hunk {hi + 1} "
                    f"at declared position (first difference at line {first_bad_line}).\n"
                    f"Expected old lines:\n{expected_display}\n"
                    f"Actual old lines:\n{actual_display}\n"
                    f"Hint: {hint}"
                ), None
            return False, (
                f"{path}: line count mismatch in hunk {hi + 1} "
                f"(expected {len(hunk.old_lines)} lines, found {len(declared_actual)})\n"
                f"Hint: {hint}"
            ), None

        resolved_hunks.append((resolved_idx, hunk.old_count, hunk.new_lines, hi))

    # Detect overlapping hunks — possible once auto_fix_start relocates a hunk
    # onto a region another hunk also claims. Splicing overlapping ranges would
    # silently corrupt the file, so fail loudly instead. A pure insertion
    # (old_count == 0) touching the boundary is not an overlap.
    by_position = sorted(resolved_hunks, key=lambda r: (r[0], r[1]))
    for (s1, c1, _n1, hi1), (s2, _c2, _n2, hi2) in zip(by_position, by_position[1:]):
        if c1 > 0 and s1 + c1 > s2:
            return False, (
                f"{path}: hunks {hi1 + 1} and {hi2 + 1} overlap after position "
                f"resolution (lines {s1 + 1}-{s1 + c1} vs starting {s2 + 1}). "
                "Combine them into one hunk or add disambiguating context."
            ), None

    # Pass 2 — apply bottom-to-top by RESOLVED start so earlier (higher-line)
    # hunks do not shift the indices of later (lower-line) ones.
    new_lines = list(file_lines)
    for start_idx, old_count, hunk_new_lines, _hi in sorted(
        resolved_hunks, key=lambda r: r[0], reverse=True
    ):
        end_idx = start_idx + old_count
        new_lines = new_lines[:start_idx] + hunk_new_lines + new_lines[end_idx:]

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
