#!/usr/bin/env python3
"""Post-merge health check: detect dead owner code caused by upstream refactoring.

Runs 8 checks:
  1. _owner_import chain validation (P0)
  2. Direct from owner.* import validation (P0)
  3. owner/patches/*.py target validation (P0)
  4. [owner] marker inventory & context validation (P1)
  5. Merge diff dead-marker detection (P2)
  6. Critical owner anchor validation (P0)
  7. Owner inventory static validation (P0)
  8. Changed-file [owner] marker coverage (P1)

Exit code 0 = all pass (warnings OK), 1 = any FAIL.
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# Type alias for check results: (name, issues, metric1, metric2)
CheckResult = Tuple[str, List[str], int, int]

# ---------------------------------------------------------------------------
# Repo root resolution
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent          # owner/validation/
REPO_ROOT = SCRIPT_DIR.parent.parent                  # 2 levels up
ANCHORS_PATH = SCRIPT_DIR / "anchors.yaml"
INVENTORY_PATH = SCRIPT_DIR / "inventory.yaml"

# Directories to exclude from scanning
EXCLUDE_DIRS = {"owner", "tests", ".git", "__pycache__", "node_modules", ".venv", "venv"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ast_cache: Dict[Path, Optional[ast.Module]] = {}


def _iter_py_files(root: Path, exclude: Optional[Set[str]] = None) -> List[Path]:
    """Yield all .py files under *root*, skipping excluded dirs."""
    if exclude is None:
        exclude = EXCLUDE_DIRS
    result: List[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel = Path(dirpath).relative_to(root)
        dirnames[:] = [d for d in dirnames if d not in exclude and not d.startswith(".")]
        if any(part in exclude for part in rel.parts):
            continue
        for fn in filenames:
            if fn.endswith(".py"):
                result.append(Path(dirpath) / fn)
    return result


def _parse_ast(path: Path) -> Optional[ast.Module]:
    """Parse a Python file into an AST, returning None on syntax errors."""
    if path in _ast_cache:
        return _ast_cache[path]
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
        result = ast.parse(source, filename=str(path))
        _ast_cache[path] = result
        return result
    except (SyntaxError, UnicodeDecodeError, ValueError):
        _ast_cache[path] = None
        return None


def _get_top_level_names(tree: ast.Module) -> Set[str]:
    """Return the set of top-level class/function/variable names in a module.

    This includes names defined directly AND names imported at the top level
    (re-exports). For example, if __init__.py has:
        from owner.foo import bar
    then 'bar' will be in the returned set.
    """
    names: Set[str] = set()
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            # ``AnnAssign`` matters as much as ``Assign`` here: an annotated
            # module-level constant (``FOO: FrozenSet[str] = frozenset()``) is
            # a normal way to declare an export, and missing it made this check
            # report a live import as broken — ``gateway/run.py``'s CR-004
            # delegate reads ``OWNER_RAW_TEXT_PLATFORMS`` that way, so every
            # run carried a false FAIL that could hide a real one.
            targets = (
                node.targets if isinstance(node, ast.Assign) else [node.target]
            )
            for target in targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
                elif isinstance(target, (ast.Tuple, ast.List)):
                    for elt in target.elts:
                        if isinstance(elt, ast.Name):
                            names.add(elt.id)
        elif isinstance(node, ast.ImportFrom):
            # Re-exports: from x import y makes y available in this module
            for alias in node.names:
                local_name = alias.asname if alias.asname else alias.name
                names.add(local_name)
        elif isinstance(node, ast.Import):
            # import x as y makes y available
            for alias in node.names:
                local_name = alias.asname if alias.asname else alias.name
                names.add(local_name)
    return names


def _resolve_module_file(module_dotted: str) -> Optional[Path]:
    """Try to find the .py file for a dotted module path."""
    parts = module_dotted.split(".")
    rel_path = Path(*parts[:-1], parts[-1] + ".py") if len(parts) > 1 else Path(parts[0] + ".py")
    candidate = REPO_ROOT / rel_path
    if candidate.is_file():
        return candidate
    pkg_path = Path(*parts, "__init__.py")
    candidate = REPO_ROOT / pkg_path
    if candidate.is_file():
        return candidate
    return None


def _extract_chain_from_expr(expr: ast.expr) -> Optional[str]:
    """Extract a dotted name chain from an AST expression.

    e.g. `MemoryManager.prefetch_all` -> "MemoryManager.prefetch_all"
    """
    if isinstance(expr, ast.Name):
        return expr.id
    if isinstance(expr, ast.Attribute):
        base = _extract_chain_from_expr(expr.value)
        if base:
            return f"{base}.{expr.attr}"
    return None


# ---------------------------------------------------------------------------
# Check 1: _owner_import chain validation
# ---------------------------------------------------------------------------

def check_owner_import_chain() -> CheckResult:
    """Scan for _owner_import("module.path", "symbol") calls and validate."""
    py_files = _iter_py_files(REPO_ROOT)
    issues: List[str] = []
    total_calls = 0
    scanned_files = 0

    for fpath in py_files:
        scanned_files += 1

        # Pre-filter: only parse files containing _owner_import
        try:
            source = fpath.read_text(encoding="utf-8", errors="replace")
            if "_owner_import" not in source:
                continue
        except OSError:
            continue

        tree = ast.parse(source, filename=str(fpath))
        rel_path = fpath.relative_to(REPO_ROOT)

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue

            func_name = None
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                func_name = node.func.attr

            if func_name != "_owner_import":
                continue

            if len(node.args) < 2:
                continue
            arg0, arg1 = node.args[0], node.args[1]
            if not isinstance(arg0, ast.Constant) or not isinstance(arg0.value, str):
                continue
            if not isinstance(arg1, ast.Constant) or not isinstance(arg1.value, str):
                continue

            module_dotted = arg0.value
            symbol_name = arg1.value
            total_calls += 1

            target_file = _resolve_module_file(module_dotted)
            if target_file is None:
                issues.append(
                    f"{rel_path}:{node.lineno} — _owner_import(\"{module_dotted}\", \"{symbol_name}\") "
                    f"— module '{module_dotted}' not found"
                )
                continue

            target_tree = _parse_ast(target_file)
            if target_tree is None:
                issues.append(
                    f"{rel_path}:{node.lineno} — _owner_import(\"{module_dotted}\", \"{symbol_name}\") "
                    f"— cannot parse {target_file.relative_to(REPO_ROOT)}"
                )
                continue

            names = _get_top_level_names(target_tree)
            if symbol_name not in names:
                issues.append(
                    f"{rel_path}:{node.lineno} — _owner_import(\"{module_dotted}\", \"{symbol_name}\") "
                    f"— symbol '{symbol_name}' not found in {target_file.relative_to(REPO_ROOT)}"
                )

    return "Check 1: _owner_import chain validation", issues, total_calls, scanned_files


# ---------------------------------------------------------------------------
# Check 2: Direct from owner.* import validation
# ---------------------------------------------------------------------------

def check_from_owner_imports() -> CheckResult:
    """Scan for from owner.xxx import yyy and validate."""
    py_files = _iter_py_files(REPO_ROOT)
    issues: List[str] = []
    total_imports = 0

    for fpath in py_files:
        try:
            source = fpath.read_text(encoding="utf-8", errors="replace")
            if "from owner" not in source:
                continue
        except OSError:
            continue

        try:
            tree = ast.parse(source, filename=str(fpath))
        except SyntaxError:
            continue

        rel_path = fpath.relative_to(REPO_ROOT)

        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if node.module is None or not node.module.startswith("owner."):
                continue

            module_dotted = node.module
            target_file = _resolve_module_file(module_dotted)

            for alias in node.names:
                imported_name = alias.name
                total_imports += 1

                if target_file is None:
                    issues.append(
                        f"{rel_path}:{node.lineno} — from {module_dotted} import {imported_name} "
                        f"— module '{module_dotted}' not found"
                    )
                    continue

                target_tree = _parse_ast(target_file)
                if target_tree is None:
                    issues.append(
                        f"{rel_path}:{node.lineno} — from {module_dotted} import {imported_name} "
                        f"— cannot parse {target_file.relative_to(REPO_ROOT)}"
                    )
                    continue

                names = _get_top_level_names(target_tree)
                if imported_name not in names:
                    issues.append(
                        f"{rel_path}:{node.lineno} — from {module_dotted} import {imported_name} "
                        f"— symbol '{imported_name}' not found"
                    )

    return "Check 2: Direct from owner.* import validation", issues, total_imports, len(py_files)


# ---------------------------------------------------------------------------
# Check 3: Patch target validation
# ---------------------------------------------------------------------------

def check_patch_targets() -> CheckResult:
    """Validate that _originals["name"] = <dotted.path> targets exist."""
    patches_dir = REPO_ROOT / "owner" / "patches"
    issues: List[str] = []
    total_targets = 0

    if not patches_dir.is_dir():
        return "Check 3: Patch target validation", ["owner/patches/ directory not found"], 0, 0

    patch_files = sorted(patches_dir.glob("*.py"))
    patch_files = [f for f in patch_files if f.name != "__init__.py" and not f.name.startswith("_")]

    for pf in patch_files:
        tree = _parse_ast(pf)
        if tree is None:
            issues.append(f"{pf.relative_to(REPO_ROOT)} — cannot parse")
            continue

        import_aliases: Dict[str, str] = {}
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    local = alias.asname or alias.name
                    import_aliases[local] = alias.name
            elif isinstance(node, ast.ImportFrom) and node.module:
                for alias in node.names:
                    local = alias.asname or alias.name
                    import_aliases[local] = f"{node.module}.{alias.name}"

        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if not isinstance(target, ast.Subscript):
                    continue
                if not isinstance(target.value, ast.Name) or target.value.id != "_originals":
                    continue

                key = None
                slice_node = target.slice
                if isinstance(slice_node, ast.Constant) and isinstance(slice_node.value, str):
                    key = slice_node.value

                if key is None:
                    continue

                rhs = node.value
                total_targets += 1

                chain = _extract_chain_from_expr(rhs)
                if chain is None:
                    continue

                parts = chain.split(".")
                if len(parts) < 2:
                    continue

                root_name = parts[0]
                resolved_module = import_aliases.get(root_name, root_name)

                found = False
                for split_point in range(len(parts), 0, -1):
                    candidate_module = ".".join(parts[:split_point])
                    if candidate_module in import_aliases:
                        candidate_module = import_aliases[candidate_module]

                    target_file = _resolve_module_file(candidate_module)
                    if target_file is not None:
                        remaining = parts[split_point:]
                        if not remaining:
                            found = True
                            break

                        target_tree = _parse_ast(target_file)
                        if target_tree is None:
                            issues.append(
                                f"{pf.relative_to(REPO_ROOT)} — "
                                f"_originals[\"{key}\"] = {chain} — "
                                f"cannot parse {target_file.relative_to(REPO_ROOT)}"
                            )
                            found = True
                            break

                        names = _get_top_level_names(target_tree)
                        if remaining[0] not in names:
                            issues.append(
                                f"{pf.relative_to(REPO_ROOT)} — "
                                f"_originals[\"{key}\"] = {chain} — "
                                f"'{remaining[0]}' not found on module"
                            )
                        found = True
                        break

    return "Check 3: Patch target validation", issues, total_targets, len(patch_files)


# ---------------------------------------------------------------------------
# Check 4: [owner] marker inventory & context validation
# ---------------------------------------------------------------------------

# ``[owner]`` is the only sanctioned marker (二次开发规范 §2.2). The retired
# ``[owner-patch]`` alternative stays in the pattern so a line reintroduced by a
# merge is still inventoried by Check 4 and adjudicated by Check 5 — dropping it
# from the pattern would turn a visible legacy marker into an invisible hunk.
_OWNER_MARKER_RE = re.compile(r"\[owner(?:-patch)?\]")
_DIFF_HUNK_RE = re.compile(r"@@ -(\d+)(?:,\d+)? \+\d+(?:,\d+)? @@")

_OWNER_MARKER_TOKEN_STOPWORDS = {
    "and",
    "are",
    "but",
    "for",
    "from",
    "into",
    "see",
    "the",
    "this",
    "via",
    "with",
}

_UPSTREAM_SYMBOLS = {
    "resolve_display_setting_for_source": "gateway/display_config.py",
    "_adapter_for_source": None,
}


def check_owner_markers() -> CheckResult:
    """Inventory [owner] markers and validate context.

    ``_OWNER_MARKER_RE`` also accepts the retired ``[owner-patch]`` spelling.
    That tolerance is deliberate: a stray one reintroduced by a merge must still
    be *counted* here and *resolved* by Check 5, not silently ignored.
    """
    py_files = _iter_py_files(REPO_ROOT)
    issues: List[str] = []
    total_markers = 0
    marker_files = 0

    for fpath in py_files:
        try:
            source = fpath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        lines = source.splitlines()
        rel_path = fpath.relative_to(REPO_ROOT)

        file_markers = 0
        for lineno_0, line in enumerate(lines):
            if _OWNER_MARKER_RE.search(line):
                file_markers += 1
                total_markers += 1

        if file_markers > 0:
            marker_files += 1

            tree = _parse_ast(fpath)
            if tree is None:
                continue

            func_ranges: List[Tuple[int, int, str]] = []

            def _walk_functions(node: ast.AST, prefix: str = "") -> None:
                for child in ast.iter_child_nodes(node):
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        name = f"{prefix}{child.name}" if prefix else child.name
                        end_lineno = getattr(child, "end_lineno", child.lineno + 50)
                        func_ranges.append((child.lineno, end_lineno, name))
                        _walk_functions(child, f"{name}.")
                    elif isinstance(child, ast.ClassDef):
                        _walk_functions(child, f"{child.name}.")

            _walk_functions(tree)

            for lineno_0, line in enumerate(lines):
                if not _OWNER_MARKER_RE.search(line):
                    continue

                lineno = lineno_0 + 1
                enclosing_func = None
                for start, end, name in func_ranges:
                    if start <= lineno <= end:
                        enclosing_func = name
                        break

                if enclosing_func:
                    context_start = max(0, lineno_0 - 2)
                    context_end = min(len(lines), lineno_0 + 10)
                    context_block = "\n".join(lines[context_start:context_end])

                    for symbol, expected_file in _UPSTREAM_SYMBOLS.items():
                        if symbol in context_block and expected_file:
                            target = REPO_ROOT / expected_file
                            if target.is_file():
                                target_tree = _parse_ast(target)
                                if target_tree:
                                    names = _get_top_level_names(target_tree)
                                    if symbol not in names:
                                        issues.append(
                                            f"{rel_path}:{lineno} — [owner] in '{enclosing_func}' "
                                            f"— references '{symbol}' which is not defined in {expected_file}"
                                        )

    return "Check 4: [owner] marker inventory & context validation", issues, total_markers, marker_files


# ---------------------------------------------------------------------------
# Check 5: Merge diff dead-marker detection
# ---------------------------------------------------------------------------

def _normalize_owner_marker_line(line: str) -> str:
    """Return a stable, comparable representation of an owner marker line."""
    if line.startswith(("+", "-")):
        line = line[1:]
    line = line.strip()
    if line.startswith("#"):
        line = line[1:].strip()
    return re.sub(r"\s+", " ", line).lower()


def _owner_marker_tokens(line: str) -> Set[str]:
    """Extract significant tokens from a marker line for fuzzy survival checks."""
    text = _normalize_owner_marker_line(line).replace("[owner-patch]", " ").replace("[owner]", " ")
    tokens = set(re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{2,}", text))
    return {tok for tok in tokens if tok not in _OWNER_MARKER_TOKEN_STOPWORDS}


def _iter_deleted_owner_marker_lines(diff_text: str) -> List[Tuple[Optional[int], str]]:
    """Return deleted diff lines that carried an owner marker, with old line numbers."""
    result: List[Tuple[Optional[int], str]] = []
    old_lineno: Optional[int] = None

    for diff_line in diff_text.splitlines():
        hunk_match = _DIFF_HUNK_RE.match(diff_line)
        if hunk_match:
            old_lineno = int(hunk_match.group(1))
            continue

        if diff_line.startswith("-") and not diff_line.startswith("---"):
            if _OWNER_MARKER_RE.search(diff_line):
                result.append((old_lineno, diff_line[1:]))
            if old_lineno is not None:
                old_lineno += 1
            continue

        if diff_line.startswith("+") and not diff_line.startswith("+++"):
            continue

        if old_lineno is not None:
            old_lineno += 1

    return result


def _deleted_owner_marker_has_surviving_glue(deleted_line: str, current_source: str) -> bool:
    """Return True when a deleted marker appears to have been moved/refactored.

    This suppresses false positives where an upstream merge reshuffled a block
    but the owner glue still exists in the same file.  It is intentionally
    conservative: exact marker-line survival wins; otherwise require either a
    surviving owner module reference from the deleted line, or a strong token
    overlap with another current owner marker line.
    """
    if not current_source:
        return False

    deleted_norm = _normalize_owner_marker_line(deleted_line)
    current_marker_norms = [
        _normalize_owner_marker_line(line)
        for line in current_source.splitlines()
        if _OWNER_MARKER_RE.search(line)
    ]

    if deleted_norm in current_marker_norms:
        return True

    owner_modules = set(re.findall(r"owner(?:\.[A-Za-z_][A-Za-z0-9_]*)+", deleted_line))
    if owner_modules and all(module in current_source for module in owner_modules):
        return True

    deleted_tokens = _owner_marker_tokens(deleted_line)
    if len(deleted_tokens) < 4:
        return False

    for current_norm in current_marker_norms:
        current_tokens = _owner_marker_tokens(current_norm)
        if len(deleted_tokens & current_tokens) >= min(4, len(deleted_tokens)):
            return True

    return False


def _preview_deleted_marker(line: str) -> str:
    text = _normalize_owner_marker_line(line)
    return text if len(text) <= 140 else text[:137] + "..."

def check_merge_diff() -> CheckResult:
    """Check if [owner] markers deleted by the last merge lost live glue."""
    issues: List[str] = []

    try:
        subprocess.run(
            ["git", "--version"],
            cwd=REPO_ROOT,
            capture_output=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "Check 5: Merge diff dead-marker detection", ["git not available — skipped"], 0, 0

    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "--merges", "-1"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return "Check 5: Merge diff dead-marker detection", ["no merge commits found — skipped"], 0, 0

        merge_line = result.stdout.strip()
        merge_hash = merge_line.split()[0]
    except subprocess.TimeoutExpired:
        return "Check 5: Merge diff dead-marker detection", ["git log timed out — skipped"], 0, 0

    try:
        result = subprocess.run(
            ["git", "diff", f"{merge_hash}^1...{merge_hash}", "--diff-filter=MD", "--name-only"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            return "Check 5: Merge diff dead-marker detection", [f"git diff failed: {result.stderr.strip()}"], 0, 0

        changed_files = [f.strip() for f in result.stdout.strip().splitlines() if f.strip()]
    except subprocess.TimeoutExpired:
        return "Check 5: Merge diff dead-marker detection", ["git diff timed out — skipped"], 0, 0

    removed_candidates = 0
    resolved_candidates = 0
    for cf in changed_files:
        try:
            result = subprocess.run(
                ["git", "diff", f"{merge_hash}^1...{merge_hash}", "--", cf],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                continue

            current_path = REPO_ROOT / cf
            try:
                current_source = (
                    current_path.read_text(encoding="utf-8", errors="replace")
                    if current_path.is_file()
                    else ""
                )
            except OSError:
                current_source = ""

            for old_lineno, deleted_line in _iter_deleted_owner_marker_lines(result.stdout):
                removed_candidates += 1
                if _deleted_owner_marker_has_surviving_glue(deleted_line, current_source):
                    resolved_candidates += 1
                    continue
                location = f"{cf}:{old_lineno}" if old_lineno is not None else cf
                issues.append(
                    f"{location} — [owner] marker deleted by merge {merge_hash[:9]} "
                    f"without equivalent current glue: {_preview_deleted_marker(deleted_line)!r}"
                )
        except subprocess.TimeoutExpired:
            continue

    return "Check 5: Merge diff dead-marker detection", issues, removed_candidates, resolved_candidates


# ---------------------------------------------------------------------------
# Check 6: Critical owner anchor validation
# ---------------------------------------------------------------------------

def _load_anchor_specs() -> Tuple[List[Dict[str, Any]], List[str]]:
    """Load critical owner glue anchors from owner/validation/anchors.yaml."""
    if not ANCHORS_PATH.is_file():
        return [], [f"{ANCHORS_PATH.relative_to(REPO_ROOT)} not found"]

    try:
        import yaml
    except Exception as exc:
        return [], [f"cannot import PyYAML to read {ANCHORS_PATH.relative_to(REPO_ROOT)}: {exc}"]

    try:
        data = yaml.safe_load(ANCHORS_PATH.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        return [], [f"cannot parse {ANCHORS_PATH.relative_to(REPO_ROOT)}: {exc}"]

    anchors = data.get("anchors") if isinstance(data, dict) else None
    if not isinstance(anchors, list):
        return [], [f"{ANCHORS_PATH.relative_to(REPO_ROOT)} must contain a top-level 'anchors' list"]

    issues: List[str] = []
    specs: List[Dict[str, Any]] = []
    for idx, item in enumerate(anchors, start=1):
        if not isinstance(item, dict):
            issues.append(f"anchors[{idx}] must be a mapping")
            continue
        anchor_id = str(item.get("id") or "").strip()
        rel_file = str(item.get("file") or "").strip()
        contains = item.get("contains")
        if not anchor_id:
            issues.append(f"anchors[{idx}] missing id")
        if not rel_file:
            issues.append(f"anchors[{idx}] missing file")
        if not isinstance(contains, list) or not all(isinstance(s, str) and s for s in contains):
            issues.append(f"anchors[{idx}] ({anchor_id or '?'}) must have non-empty string list 'contains'")
        if anchor_id and rel_file and isinstance(contains, list):
            specs.append(item)

    return specs, issues


def check_critical_owner_anchors() -> CheckResult:
    """Validate critical owner glue anchors that must survive upstream merges."""
    specs, issues = _load_anchor_specs()
    checked = 0

    for spec in specs:
        anchor_id = str(spec["id"])
        rel_file = str(spec["file"])
        contains = [str(s) for s in spec.get("contains", [])]
        file_path = REPO_ROOT / rel_file

        if not file_path.is_file():
            issues.append(f"{anchor_id}: {rel_file} not found")
            continue

        try:
            source = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            issues.append(f"{anchor_id}: cannot read {rel_file}: {exc}")
            continue

        checked += 1
        for needle in contains:
            if needle not in source:
                issues.append(f"{anchor_id}: {rel_file} missing anchor {needle!r}")

    return "Check 6: Critical owner anchor validation", issues, checked, len(specs)


# ---------------------------------------------------------------------------
# Check 7: Owner inventory static validation
# ---------------------------------------------------------------------------

def _load_inventory_items() -> Tuple[List[Dict[str, Any]], List[str]]:
    """Load lightweight validation items from owner/validation/inventory.yaml."""
    if not INVENTORY_PATH.is_file():
        return [], [f"{INVENTORY_PATH.relative_to(REPO_ROOT)} not found"]

    try:
        import yaml
    except Exception as exc:
        return [], [f"cannot import PyYAML to read {INVENTORY_PATH.relative_to(REPO_ROOT)}: {exc}"]

    try:
        data = yaml.safe_load(INVENTORY_PATH.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        return [], [f"cannot parse {INVENTORY_PATH.relative_to(REPO_ROOT)}: {exc}"]

    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return [], [f"{INVENTORY_PATH.relative_to(REPO_ROOT)} must contain a top-level 'items' list"]

    issues: List[str] = []
    normalized: List[Dict[str, Any]] = []
    for idx, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            issues.append(f"items[{idx}] must be a mapping")
            continue
        item_id = str(item.get("id") or "").strip()
        checks = item.get("static_checks")
        if not item_id:
            issues.append(f"items[{idx}] missing id")
        if not isinstance(checks, list) or not checks:
            issues.append(f"items[{idx}] ({item_id or '?'}) must have non-empty static_checks")
        elif not all(isinstance(check, dict) for check in checks):
            issues.append(f"items[{idx}] ({item_id or '?'}) static_checks must be mappings")
        if item_id and isinstance(checks, list):
            normalized.append(item)

    return normalized, issues


def _check_inventory_file_exists(item_id: str, check: Dict[str, Any]) -> List[str]:
    rel_path = str(check.get("path") or "").strip()
    if not rel_path:
        return [f"{item_id}: file_exists check missing path"]
    if not (REPO_ROOT / rel_path).is_file():
        return [f"{item_id}: expected file {rel_path} to exist"]
    return []


def _check_inventory_file_contains(item_id: str, check: Dict[str, Any]) -> List[str]:
    rel_path = str(check.get("file") or "").strip()
    contains = check.get("contains")
    if isinstance(contains, str):
        needles = [contains]
    elif isinstance(contains, list) and all(isinstance(s, str) and s for s in contains):
        needles = contains
    else:
        return [f"{item_id}: file_contains check must provide string or string list 'contains'"]
    if not rel_path:
        return [f"{item_id}: file_contains check missing file"]

    path = REPO_ROOT / rel_path
    if not path.is_file():
        return [f"{item_id}: expected file {rel_path} to exist"]
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return [f"{item_id}: cannot read {rel_path}: {exc}"]

    return [f"{item_id}: {rel_path} missing {needle!r}" for needle in needles if needle not in source]


def _check_inventory_module_symbol(item_id: str, check: Dict[str, Any]) -> List[str]:
    module = str(check.get("module") or "").strip()
    symbol = str(check.get("symbol") or "").strip()
    if not module or not symbol:
        return [f"{item_id}: module_symbol check missing module or symbol"]

    target_file = _resolve_module_file(module)
    if target_file is None:
        return [f"{item_id}: module {module} not found"]

    tree = _parse_ast(target_file)
    if tree is None:
        return [f"{item_id}: cannot parse {target_file.relative_to(REPO_ROOT)}"]

    names = _get_top_level_names(tree)
    if symbol not in names:
        return [f"{item_id}: symbol {symbol!r} not found in {target_file.relative_to(REPO_ROOT)}"]
    return []


def _run_inventory_static_check(item_id: str, check: Dict[str, Any]) -> List[str]:
    check_type = str(check.get("type") or "").strip()
    if check_type == "file_exists":
        return _check_inventory_file_exists(item_id, check)
    if check_type == "file_contains":
        return _check_inventory_file_contains(item_id, check)
    if check_type == "module_symbol":
        return _check_inventory_module_symbol(item_id, check)
    return [f"{item_id}: unknown static check type {check_type!r}"]


def check_validation_inventory() -> CheckResult:
    """Run simple static checks from the owner change inventory."""
    items, issues = _load_inventory_items()
    checks_run = 0

    for item in items:
        item_id = str(item.get("id") or "").strip()
        for check in item.get("static_checks", []):
            checks_run += 1
            issues.extend(_run_inventory_static_check(item_id, check))

    return "Check 7: Owner inventory static validation", issues, checks_run, len(items)


# ---------------------------------------------------------------------------
# Check 8: Changed-file [owner] marker coverage
# ---------------------------------------------------------------------------

# Refs tried in order to locate the last common ancestor with upstream.
_UPSTREAM_BASE_REFS = ("upstream/main", "origin/main", "main")

# Generated artifacts that must NOT carry hand-written markers. A tool rewrites
# them wholesale, so a marker inside is wiped on the next regeneration; worse,
# during a sync conflict it invites preserving our generated lines instead of
# regenerating the file. The hand-authored source of truth carries the marker
# instead -- e.g. pyproject.toml for a dependency pin that shows up in uv.lock.
_GENERATED_ARTIFACTS = {
    "uv.lock",
    "poetry.lock",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "Cargo.lock",
}


def _is_generated_artifact(rel_path: str) -> bool:
    return rel_path.rsplit("/", 1)[-1] in _GENERATED_ARTIFACTS


# Verbatim upstream ports: official files whose *only* local change is upstream code
# copied in ahead of the sync (T2-20's "port the missing symbols" route).
#
# These files must NOT carry an [owner] marker, and adding one would be actively
# harmful: the marker's meaning in this repo is "this is OUR customization -- keep
# ours at conflict time", whereas for a verbatim port the correct resolution is
# upstream's version. Marking them would tell a future resolver to preserve a stale
# copy of upstream's own code.
#
# So the exemption is per-file and reasoned, and it is kept honest by two asserts:
# an allowlisted file that gains an [owner] marker is reported as a stale entry
# (which means it now carries real customization and must be marked normally), and
# an allowlisted file that is no longer modified since the base is reported so the
# entry gets retired. Without this, Check 8 could be silently neutralised by
# parking a customized file here.
_UPSTREAM_PORT_ALLOWLIST = REPO_ROOT / "owner" / "validation" / "upstream_port_files.txt"


def _load_upstream_port_allowlist() -> dict:
    """``{rel_path: reason}`` from ``upstream_port_files.txt`` (missing file -> {})."""
    try:
        raw = _UPSTREAM_PORT_ALLOWLIST.read_text(encoding="utf-8")
    except OSError:
        return {}
    entries: dict = {}
    for line in raw.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        path, _, reason = line.partition("  ")
        entries[path.strip()] = reason.strip() or "(no reason given)"
    return entries


def _resolve_upstream_base() -> Optional[str]:
    """Last common ancestor of HEAD and the upstream mainline, or None."""
    for ref in _UPSTREAM_BASE_REFS:
        try:
            result = subprocess.run(
                ["git", "merge-base", "HEAD", ref],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    return None


def check_changed_file_markers() -> CheckResult:
    """Every modified official file must carry at least one [owner] marker.

    Resolving a fork sync means deciding, hunk by hunk, whether a change is ours
    or upstream's -- and the [owner] marker at the change site is the only
    signal that answers it. A modified file with no marker anywhere reads as
    untouched upstream code, so the entire customization is taken from upstream
    and disappears without a trace: merge 315551234 lost four markers exactly
    that way (see Check 5).

    Scope is official files *modified* since the upstream base, excluding
    ``owner/`` and ``tests/``. Files *added* under an official directory are out
    of scope: ``owner/docs/二次开发规范.md`` 2.2 identifies those through the
    ``[owner]`` commit-message prefix, not an in-file marker. Generated
    artifacts are out of scope for the reason documented at
    ``_GENERATED_ARTIFACTS``.
    """
    base = _resolve_upstream_base()
    if base is None:
        return (
            "Check 8: Changed-file [owner] marker coverage",
            ["cannot resolve an upstream base ref — skipped"],
            0,
            0,
        )

    try:
        result = subprocess.run(
            ["git", "diff", "--diff-filter=M", "--name-only", f"{base}..HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except subprocess.TimeoutExpired:
        return (
            "Check 8: Changed-file [owner] marker coverage",
            ["git diff timed out — skipped"],
            0,
            0,
        )

    if result.returncode != 0:
        return (
            "Check 8: Changed-file [owner] marker coverage",
            [f"git diff failed: {result.stderr.strip()}"],
            0,
            0,
        )

    candidates = [
        f.strip()
        for f in result.stdout.splitlines()
        if f.strip() and not f.strip().startswith(("owner/", "tests/"))
    ]

    issues: List[str] = []
    examined = 0
    covered = 0
    allowlist = _load_upstream_port_allowlist()
    seen_allowlisted: set = set()
    for rel_path in candidates:
        if _is_generated_artifact(rel_path):
            continue
        fpath = REPO_ROOT / rel_path
        if not fpath.is_file():
            continue  # deleted by the same window — nothing left to mark
        examined += 1
        try:
            source = fpath.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            issues.append(f"{rel_path} — unreadable: {exc}")
            continue
        has_marker = bool(_OWNER_MARKER_RE.search(source))
        if rel_path in allowlist:
            seen_allowlisted.add(rel_path)
            if has_marker:
                issues.append(
                    f"{rel_path} — stale entry in upstream_port_files.txt: the file now "
                    "carries an [owner] marker, so it is a real customization (and must be "
                    "marked as one) rather than a verbatim upstream port; remove the entry"
                )
                covered += 1
                continue
            covered += 1
            continue
        if has_marker:
            covered += 1
            continue
        issues.append(
            f"{rel_path} — modified official file with no [owner] marker anywhere; "
            "a sync would treat this customization as upstream code and drop it "
            "(if the file is purely a verbatim upstream port, list it in "
            "owner/validation/upstream_port_files.txt with a reason)"
        )

    for rel_path, reason in sorted(allowlist.items()):
        if rel_path not in seen_allowlisted:
            issues.append(
                f"{rel_path} — stale entry in upstream_port_files.txt: no longer a modified "
                f"official file ({reason}); retire the entry"
            )

    return "Check 8: Changed-file [owner] marker coverage", issues, examined, covered


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    repo_str = str(REPO_ROOT)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print("═" * 59)
    print("  Owner Merge Health Check")
    print(f"  Repo: {repo_str}")
    print(f"  Date: {now}")
    print("═" * 59)
    print()

    checks = [
        check_owner_import_chain,
        check_from_owner_imports,
        check_patch_targets,
        check_owner_markers,
        check_merge_diff,
        check_critical_owner_anchors,
        check_validation_inventory,
        check_changed_file_markers,
    ]

    total_pass = 0
    total_fail = 0
    total_warn = 0

    for check_fn in checks:
        name, issues, *counts = check_fn()

        is_warn = check_fn in (check_owner_markers, check_merge_diff)

        print(f"[{name}]")

        if check_fn == check_owner_import_chain:
            found, scanned = counts
            print(f"  Scanned {scanned} files, found {found} _owner_import calls")
        elif check_fn == check_from_owner_imports:
            found, scanned = counts
            print(f"  Scanned {scanned} files, found {found} from-owner imports")
        elif check_fn == check_patch_targets:
            targets, pfiles = counts
            print(f"  Checked {pfiles} patch files, {targets} targets")
        elif check_fn == check_owner_markers:
            markers, mfiles = counts
            print(f"  Found {markers} markers across {mfiles} files")
        elif check_fn == check_merge_diff:
            removed, resolved = counts
            if removed:
                print(f"  Found {removed} removed marker candidates, {resolved} resolved by current glue")
        elif check_fn == check_critical_owner_anchors:
            checked, total = counts
            print(f"  Checked {checked}/{total} critical owner anchors")
        elif check_fn == check_validation_inventory:
            checks_run, item_count = counts
            print(f"  Ran {checks_run} static checks across {item_count} inventory items")
        elif check_fn == check_changed_file_markers:
            examined, covered = counts
            print(f"  {covered}/{examined} modified official files carry an [owner] marker")

        if not issues:
            if is_warn:
                print("  ✅ PASS — no issues")
            else:
                print("  ✅ PASS — all resolve correctly")
            total_pass += 1
        else:
            if is_warn:
                print(f"  ⚠️ WARN ({len(issues)} issue{'s' if len(issues) != 1 else ''}):")
                total_warn += 1
            else:
                print(f"  ❌ FAIL ({len(issues)} issue{'s' if len(issues) != 1 else ''}):")
                total_fail += 1

            for issue in issues:
                print(f"    {issue}")

        print()

    print("═" * 59)
    summary_parts = [f"{total_pass} passed"]
    if total_fail:
        summary_parts.append(f"{total_fail} failed")
    if total_warn:
        summary_parts.append(f"{total_warn} warning{'s' if total_warn != 1 else ''}")
    print(f"  Summary: {', '.join(summary_parts)}")
    print("═" * 59)

    return 1 if total_fail > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
