"""Tool handler and public API for unified_diff_patch."""

from __future__ import annotations

import json
import os
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


def _materialize_patch_paths(
    file_patches,
    *,
    task_id: str,
) -> None:
    """将 diff header 中的相对路径解析为绝对路径并写回 FilePatch。"""
    from tools.file_tools import _resolve_path_for_task

    for fp in file_patches:
        target = fp.new_path if not fp.is_deleted else fp.old_path
        if target == '/dev/null':
            continue
        resolved = str(_resolve_path_for_task(target, task_id))
        fp.new_path = resolved
        if not fp.is_new:
            fp.old_path = resolved


def _suggest_path(original: str, resolved: str, base_dir: Path) -> str:
    """如果相对路径在工作区根的某个子目录下存在同名文件，给出建议。"""
    if Path(original).expanduser().is_absolute():
        return ""
    rel = Path(original)
    suggestions = []
    try:
        for child in base_dir.iterdir():
            if child.is_dir():
                candidate = child / rel
                if candidate.exists():
                    suggestions.append(str(candidate.resolve()))
    except Exception:
        pass
    if suggestions:
        return f"\n    Did you mean: {suggestions[0]!r}?"
    return ""


def _prevalidate_patch_paths(
    file_patches,
    *,
    task_id: str,
) -> Optional[str]:
    """在真正 apply 前一次性检查所有非新建文件是否可读。

    返回 None 表示全部可读；否则返回聚合错误字符串，包含每个缺失文件的
    原始路径、解析后的绝对路径、工作区根以及可能的建议路径。
    """
    from tools.file_tools import (
        _get_file_ops,
        _resolve_base_dir,
        _resolve_path_for_task,
    )

    base_dir = _resolve_base_dir(task_id)
    file_ops = _get_file_ops(task_id)

    missing = []
    for fp in file_patches:
        target = fp.new_path if not fp.is_deleted else fp.old_path
        if target == '/dev/null' or fp.is_new:
            continue
        resolved = str(_resolve_path_for_task(target, task_id))
        rr = file_ops.read_file_raw(resolved)
        if rr.error:
            missing.append((target, resolved, rr.similar_files or []))

    if not missing:
        return None

    lines = [
        f"The following patch target(s) cannot be read "
        f"(workspace root: {base_dir}, process CWD: {os.getcwd()}):"
    ]
    for original, resolved, similar in missing:
        suggestion = _suggest_path(original, resolved, base_dir)
        similar_hint = ""
        if similar:
            similar_hint = f"\n    Similar files: {', '.join(repr(s) for s in similar[:3])}"
        lines.append(
            f"  • {original!r} resolved to {resolved!r}{suggestion}{similar_hint}"
        )
    lines.append(
        "Hint: use absolute paths, cd into the target directory, "
        "or add the correct repository prefix (e.g. hermes-agent/...) to the diff paths."
    )
    return "\n".join(lines)


def _build_dry_run_result(
    file_patches,
    *,
    task_id: str,
    auto_fix_start: bool,
) -> Dict[str, Any]:
    """Preview a patch without writing, taking locks, or updating timestamps.

    Reads go through the SAME ``file_ops`` backend the real apply uses
    (``_get_file_ops``), so the preview reflects the file the agent's
    terminal actually sees. Reading through a host-local ``open()`` here
    would diverge from apply on any non-local backend (docker/ssh/modal/
    daytona) — the preview would show the host copy while apply touches the
    container/remote copy. The engine's ``dry_run=True`` path only ever
    calls ``read_file_raw`` (no writes/deletes/lint), so sharing the real
    file_ops is read-only.
    """
    from tools.file_tools import _get_file_ops

    file_ops = _get_file_ops(task_id)
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

    prevalidate_err = _prevalidate_patch_paths(file_patches, task_id=task_id)
    if prevalidate_err:
        return tool_error(prevalidate_err)

    _materialize_patch_paths(file_patches, task_id=task_id)

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
