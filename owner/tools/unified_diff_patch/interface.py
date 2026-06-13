"""Tool handler and public API for unified_diff_patch."""

from __future__ import annotations

import json
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Dict, List, Optional

from tools import check_file_requirements
from tools.path_security import has_traversal_component
from tools.registry import tool_error

from .engine import apply_unified_diff
from .parser import parse_unified_diff
from .schema import UNIFIED_DIFF_PATCH_SCHEMA


def _check_file_reqs() -> bool:
    """Availability check delegated to the official file tools gate."""
    return check_file_requirements()


def _resolve_and_guard_paths(
    file_patches,
    *,
    task_id: str,
    cross_profile: bool,
) -> Optional[str]:
    """Run traversal / sensitive / cross-profile checks. Return error or None."""
    # Import lazily to avoid circular imports at module load.
    from tools.file_tools import (
        _check_cross_profile_path,
        _check_sensitive_path,
    )

    for fp in file_patches:
        target = fp.new_path if not fp.is_deleted else fp.old_path
        if target == '/dev/null':
            continue

        if has_traversal_component(target):
            return (
                f"Patch path contains '..' traversal: {target!r}. "
                "Use absolute paths or cwd-relative paths without '..'."
            )

        sensitive_err = _check_sensitive_path(target, task_id)
        if sensitive_err:
            return sensitive_err

        if not cross_profile:
            cross_warn = _check_cross_profile_path(target, task_id)
            if cross_warn:
                return cross_warn

    return None


def _resolve_local_target_path(target: str, task_id: str) -> Optional[Path]:
    """Resolve a patch target path to a local absolute path for dry-run preview."""
    from tools.file_tools import _resolve_path_for_task

    try:
        return _resolve_path_for_task(target, task_id)
    except Exception:
        return None


def _build_dry_run_result(
    file_patches,
    *,
    task_id: str,
    auto_fix_start: bool,
) -> Dict[str, Any]:
    """Preview a patch by reading local files directly; no locks, no writes."""
    from tools.file_operations import FileOperations, ReadResult

    # Minimal in-memory FileOperations that reads from the local filesystem.
    # This avoids creating terminal environments just for a preview, while still
    # resolving paths through the task's cwd.
    class _LocalFileOperations(FileOperations):
        def read_file(self, path: str, offset: int = 1, limit: int = 500) -> ReadResult:
            raise NotImplementedError

        def read_file_raw(self, path: str) -> ReadResult:
            resolved = _resolve_local_target_path(path, task_id)
            if resolved is None:
                return ReadResult(error=f"Cannot resolve path: {path!r}")
            try:
                with open(resolved, "r", encoding="utf-8") as f:
                    return ReadResult(content=f.read())
            except OSError as exc:
                return ReadResult(error=f"Cannot read file: {exc}")

        def write_file(self, path: str, content: str):
            raise NotImplementedError

        def patch_replace(self, path: str, old_string: str, new_string: str, replace_all: bool = False):
            raise NotImplementedError

        def patch_v4a(self, patch_content: str):
            raise NotImplementedError

        def delete_file(self, path: str):
            raise NotImplementedError

        def move_file(self, src: str, dst: str):
            raise NotImplementedError

        def search(self, pattern: str, path: str = ".", target: str = "content",
                   file_glob: Optional[str] = None, limit: int = 50, offset: int = 0,
                   output_mode: str = "content", context: int = 0):
            raise NotImplementedError

    file_ops = _LocalFileOperations()
    result = apply_unified_diff(
        file_patches,
        file_ops,
        auto_fix_start=auto_fix_start,
        dry_run=True,
    )
    result_dict = result.to_dict()
    result_dict["_dry_run"] = True
    result_dict["files_modified"] = []
    result_dict["files_created"] = []
    result_dict["files_deleted"] = []
    return result_dict


def unified_diff_patch_tool(
    patch: str,
    cross_profile: bool = False,
    task_id: str = "default",
    strict: bool = False,
    dry_run: bool = False,
    auto_fix_header: bool = True,
    auto_fix_start: bool = True,
) -> str:
    """Apply (or preview) a unified diff patch."""
    if not patch or not patch.strip():
        return tool_error("patch content is required")

    file_patches, parse_err = parse_unified_diff(
        patch,
        strict=strict,
        auto_fix_header=auto_fix_header,
    )
    if parse_err:
        return tool_error(parse_err)

    guard_err = _resolve_and_guard_paths(
        file_patches,
        task_id=task_id,
        cross_profile=cross_profile,
    )
    if guard_err:
        return tool_error(guard_err)

    if dry_run:
        result_dict = _build_dry_run_result(
            file_patches,
            task_id=task_id,
            auto_fix_start=auto_fix_start,
        )
        return json.dumps(result_dict, ensure_ascii=False)

    # Real apply: resolve paths, lock, check staleness, write, update timestamps.
    from tools import file_state
    from tools.file_tools import (
        _check_file_staleness,
        _get_file_ops,
        _resolve_path_for_task,
        _update_read_timestamp,
    )

    resolved_paths: List[str] = []
    seen: set = set()
    for fp in file_patches:
        target = fp.new_path if not fp.is_deleted else fp.old_path
        if target == '/dev/null':
            continue
        try:
            r = str(_resolve_path_for_task(target, task_id))
        except Exception:
            r = None
        if r and r not in seen:
            resolved_paths.append(r)
            seen.add(r)

    resolved_paths.sort()

    try:
        with ExitStack() as locks:
            for r in resolved_paths:
                locks.enter_context(file_state.lock_path(r))

            stale_warnings: List[str] = []
            for fp in file_patches:
                target = fp.new_path if not fp.is_deleted else fp.old_path
                if target == '/dev/null':
                    continue
                try:
                    r = str(_resolve_path_for_task(target, task_id))
                except Exception:
                    r = None
                cross = file_state.check_stale(task_id, r) if r else None
                # Filter partial-read warnings — they are misleading for a
                # line-by-line patch tool.
                if cross and ("partial view" in cross or "offset/limit" in cross):
                    cross = None
                sw = cross or _check_file_staleness(target, task_id)
                if sw:
                    stale_warnings.append(sw)

            file_ops = _get_file_ops(task_id)
            result = apply_unified_diff(
                file_patches,
                file_ops,
                auto_fix_start=auto_fix_start,
                dry_run=False,
            )
            result_dict = result.to_dict()

            if stale_warnings:
                result_dict["_warning"] = (
                    stale_warnings[0]
                    if len(stale_warnings) == 1
                    else " | ".join(stale_warnings)
                )

            if not result_dict.get("error"):
                for fp in file_patches:
                    target = fp.new_path if not fp.is_deleted else fp.old_path
                    if target == '/dev/null':
                        continue
                    _update_read_timestamp(target, task_id)
                    try:
                        r = str(_resolve_path_for_task(target, task_id))
                        file_state.note_write(task_id, r)
                    except Exception:
                        pass

        return json.dumps(result_dict, ensure_ascii=False)
    except Exception as e:
        return tool_error(str(e))


def _handle_unified_diff_patch(args: Dict[str, Any], **kw: Any) -> str:
    """Registry handler adapter."""
    return unified_diff_patch_tool(
        patch=args.get("patch", ""),
        cross_profile=bool(args.get("cross_profile", False)),
        task_id=kw.get("task_id") or "default",
        strict=bool(args.get("strict", False)),
        dry_run=bool(args.get("dry_run", False)),
        auto_fix_header=bool(args.get("auto_fix_header", True)),
        auto_fix_start=bool(args.get("auto_fix_start", True)),
    )
