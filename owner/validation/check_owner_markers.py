#!/usr/bin/env python3
"""Official files modified since the ``main`` baseline must carry an [owner] marker.

Lean v2 port of the source repo's Check 8 (changed-file marker coverage) plus
the only-shrinking debt-register discipline borrowed from its coverage_gaps
mechanism (spec: ``owner/docs/二次开发规范.md`` §2.2 「标记细则」 / §2.2.0).
The source repo's per-file inventory asserts (Check 7) are deliberately NOT
ported — in v2 that job belongs to the capability-package guard tests under
``tests/owner/``.

Why this check exists: a modified official file with no ``[owner]`` marker
anywhere reads as untouched upstream code, so at sync time a merge resolver
takes upstream's side and the customization disappears without a trace.
The marker scan is a plain substring match on purpose (spec §2.2): ``[owner]``
is the only spelling, and the retired ``[owner-patch]`` still counts so that
merge-resurrected old lines stay visible.

Scope:
  * official file = tracked file outside ``owner/``, ``tests/owner/`` and
    ``*.md``;
  * baseline = local ``main`` (spec §4: main always equals upstream/main),
    compared via merge-base; only files *modified* vs the baseline (status M)
    are checked — files newly added under official directories are identified
    by the ``[owner]`` commit-message prefix instead (spec §2.2), and pure
    deletions/renames have no line left to mark;
  * generated artifacts (``uv.lock``, ``package-lock.json``, ``*.min.js``, …)
    are exempt: a tool rewrites them wholesale, so any marker inside is wiped
    on the next regeneration (spec §2.2 「生成物不挂标记」);
  * a file registered in ``owner/validation/marker_debt.txt`` with a reason is
    an acknowledged debt, not a failure — but the register only shrinks: an
    entry whose file now carries a marker, or no longer diverges from the
    baseline, or whose path is gone, is STALE and must be retired.

Modes:
  * ``--staged``  compare the git index against the baseline (pre-commit, fast);
  * ``--all``     compare the working tree against the baseline (manual / CI).

Environments without a local ``main`` ref or a merge-base fail OPEN with a
warning — this check must never block an unrelated clone.
"""

from __future__ import annotations

import argparse
import fnmatch
import re
import subprocess
import sys
from pathlib import Path

BASE_REF = "main"

# Substring scan (bytes, so any content works). The retired [owner-patch]
# spelling still counts, per spec §2.2.
MARKER_RE = re.compile(rb"\[owner(?:-patch)?\]")

DEBT_REGISTER_REL = "owner/validation/marker_debt.txt"

# Lockfiles and other tool-generated artifacts that must NOT carry hand-written
# markers: a tool rewrites them wholesale, so a marker inside is wiped on the
# next regeneration and, during a sync conflict, invites preserving our
# generated lines instead of regenerating the file (spec §2.2). The marker
# belongs on the hand-authored source (e.g. pyproject.toml for a pin that
# surfaces in uv.lock).
GENERATED_NAMES = frozenset(
    {
        "uv.lock",
        "poetry.lock",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "bun.lock",
        "Cargo.lock",
        "go.sum",
        "Gemfile.lock",
        "composer.lock",
        "Pipfile.lock",
        "pdm.lock",
        "flake.lock",
    }
)
GENERATED_PATTERNS = ("*.min.js", "*.min.css")


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[bytes] | None:
    try:
        return subprocess.run(
            ["git", *args], check=False, cwd=cwd, capture_output=True, timeout=60
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _repo_root(cwd: Path) -> Path | None:
    result = _git(["rev-parse", "--show-toplevel"], cwd)
    if result is None or result.returncode != 0:
        return None
    return Path(result.stdout.decode("utf-8", "surrogateescape").strip())


def _resolve_base(root: Path) -> str | None:
    """merge-base of HEAD and the local ``main`` ref, or None."""
    result = _git(["merge-base", "HEAD", BASE_REF], root)
    if result is None or result.returncode != 0:
        return None
    base = result.stdout.decode("utf-8", "surrogateescape").strip()
    return base or None


def is_official(rel_path: str) -> bool:
    if rel_path.startswith(("owner/", "tests/owner/")):
        return False
    return not rel_path.endswith(".md")


def is_generated(rel_path: str) -> bool:
    name = rel_path.rsplit("/", 1)[-1]
    if name in GENERATED_NAMES:
        return True
    return any(fnmatch.fnmatch(name, pattern) for pattern in GENERATED_PATTERNS)


def load_debt_register(root: Path) -> tuple[dict[str, str], list[str]]:
    """``({path: reason}, parse_errors)`` from ``marker_debt.txt``.

    A missing file is an empty (fully drained) register, not an error. Line
    format is ``<path> # <reason>``; ``#``-prefixed lines are prose.
    """
    register_path = root / DEBT_REGISTER_REL
    try:
        raw = register_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}, []
    except OSError as exc:
        return {}, [f"cannot read {DEBT_REGISTER_REL}: {exc}"]

    entries: dict[str, str] = {}
    errors: list[str] = []
    for lineno, raw_line in enumerate(raw.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        path, sep, reason = line.partition(" # ")
        path = path.strip()
        reason = reason.strip()
        if not sep or not path or not reason:
            errors.append(
                f"{DEBT_REGISTER_REL}:{lineno}: malformed entry {raw_line!r} "
                "(need `<path> # <reason>`)"
            )
            continue
        if path in entries:
            errors.append(f"{DEBT_REGISTER_REL}:{lineno}: duplicate entry for {path}")
            continue
        entries[path] = reason
    return entries, errors


def _staged_content(root: Path, rel_path: str) -> bytes | None:
    result = _git(["show", f":{rel_path}"], root)
    if result is None or result.returncode != 0:
        return None
    return result.stdout


def _worktree_content(root: Path, rel_path: str) -> bytes | None:
    try:
        return (root / rel_path).read_bytes()
    except OSError:
        return None


def _stale_reason(root: Path, rel_path: str) -> str:
    """Why a register entry is stale, phrased for the retire message."""
    if not (root / rel_path).exists():
        return "path no longer exists"
    content = _worktree_content(root, rel_path)
    if content is not None and MARKER_RE.search(content):
        return "file carries an [owner] marker now"
    return "no longer a modified official file vs the baseline"


def run_check(root: Path, staged: bool) -> int:
    base = _resolve_base(root)
    if base is None:
        print(
            f"warning: no merge-base with local '{BASE_REF}' — "
            "[owner] marker check skipped (fail-open)"
        )
        return 0

    diff_args = ["diff", "--name-only", "-z", "--diff-filter=M"]
    if staged:
        diff_args.append("--cached")
    diff_args.append(base)
    result = _git(diff_args, root)
    if result is None or result.returncode != 0:
        stderr = result.stderr.decode("utf-8", "replace").strip() if result else ""
        print(
            f"warning: git diff vs {BASE_REF} failed{f': {stderr}' if stderr else ''} — "
            "[owner] marker check skipped (fail-open)"
        )
        return 0

    changed = [
        p for p in result.stdout.decode("utf-8", "surrogateescape").split("\0") if p
    ]
    official = sorted(p for p in changed if is_official(p))
    generated = [p for p in official if is_generated(p)]
    candidates = [p for p in official if not is_generated(p)]
    read_content = _staged_content if staged else _worktree_content

    register, issues = load_debt_register(root)

    missing: list[str] = []
    stale_marked: list[str] = []
    debt_seen: dict[str, str] = {}
    examined = 0
    marked = 0
    for rel in candidates:
        content = read_content(root, rel)
        if content is None:
            continue  # vanished between the diff and the read — nothing to mark
        examined += 1
        has_marker = MARKER_RE.search(content) is not None
        if rel in register:
            if has_marker:
                stale_marked.append(rel)
            else:
                debt_seen[rel] = register[rel]
            continue
        if has_marker:
            marked += 1
        else:
            missing.append(rel)

    stale_retire: list[tuple[str, str]] = []
    if not staged:
        # The register only shrinks (--all mode): any entry that is not an
        # active debt on a current candidate must be retired.
        for rel, reason in sorted(register.items()):
            if rel in debt_seen or rel in stale_marked:
                continue
            stale_retire.append((rel, _stale_reason(root, rel)))

    mode = "staged" if staged else "all"
    print(
        f"[owner] markers ({mode}, vs {BASE_REF}@{base[:9]}): {len(official)} modified "
        f"official files, {len(generated)} generated-exempt, {examined} examined — "
        f"{marked} carry markers"
    )
    if debt_seen:
        print(f"acknowledged debt ({DEBT_REGISTER_REL}):")
        for rel, reason in sorted(debt_seen.items()):
            print(f"  - {rel}: {reason}")

    if missing:
        print(f"\nMISSING [owner] markers ({len(missing)}):")
        for rel in missing:
            print(f"  - {rel}")
        print(
            "  A modified official file with no marker is read as upstream code at\n"
            "  sync time and the customization is silently dropped (spec §2.2).\n"
            "  Fix: add a short marker above the changed lines, e.g.\n"
            "      # [owner] 审批卡片:委托 owner/feishu/approval 实现\n"
            "  If the file genuinely must stay marker-free (generated artifact outside\n"
            "  the builtin exemption, pure test data), register the debt instead:\n"
            f"      {DEBT_REGISTER_REL}: <path> # <原因>"
        )
    if stale_marked:
        print(
            f"\nSTALE {DEBT_REGISTER_REL} entries ({len(stale_marked)}) — "
            "the register only shrinks:"
        )
        for rel in stale_marked:
            print(f"  - {rel}: file carries an [owner] marker now — remove the entry")
    if stale_retire:
        print(
            f"\nSTALE {DEBT_REGISTER_REL} entries ({len(stale_retire)}) — "
            "the register only shrinks:"
        )
        for rel, why in stale_retire:
            print(f"  - {rel}: {why} — remove the entry")
    if issues:
        print(f"\n{DEBT_REGISTER_REL} parse errors:")
        for message in issues:
            print(f"  - {message}")

    issue_count = len(missing) + len(stale_marked) + len(stale_retire) + len(issues)
    if issue_count:
        print(f"\nFAIL: {issue_count} issue(s) — see above")
        return 1
    print("OK: every modified official file is marked, exempt, or debt-registered")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Check that official files modified since the local 'main' baseline "
            "carry an [owner] marker (spec §2.2)."
        )
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--staged",
        action="store_true",
        help="check the git index against the baseline (pre-commit; fast)",
    )
    mode.add_argument(
        "--all",
        action="store_true",
        help="check the working tree against the baseline (manual / CI; default)",
    )
    args = parser.parse_args(argv)

    root = _repo_root(Path.cwd())
    if root is None:
        print("warning: not inside a git repository — [owner] marker check skipped")
        return 0
    return run_check(root, staged=args.staged)


if __name__ == "__main__":
    sys.exit(main())
