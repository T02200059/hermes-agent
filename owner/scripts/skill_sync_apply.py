#!/usr/bin/env python3
"""Sync skills that are behind from their source-of-truth repo copies.

By default a dry-run preview is printed and no files are changed; use
``--apply`` to actually copy files.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from owner.scripts.skill_sync_lib import (
    DEFAULT_SKIP_TOP,
    apply_one,
    compare_all,
    default_deployed_root,
    default_repo_root,
    default_source_roots,
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Copy behind skills from the repo to the deployed skills directory.",
    )
    parser.add_argument(
        "--repo",
        type=Path,
        help="Path to the hermes-agent repo root (default: inferred from script location).",
    )
    parser.add_argument(
        "--source",
        action="append",
        type=Path,
        help="Source skill root to scan. Can be given multiple times. "
        "(default: REPO/skills and REPO/optional-skills)",
    )
    parser.add_argument(
        "--deployed",
        type=Path,
        help="Deployed skills directory to update (default: HERMES_HOME/skills).",
    )
    parser.add_argument(
        "--hermes-home",
        type=Path,
        help="Override HERMES_HOME when resolving the deployed directory.",
    )
    parser.add_argument(
        "--skip-top",
        action="append",
        help=f"Top-level deployed directories to ignore. "
        f"(default: {sorted(DEFAULT_SKIP_TOP)})",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually perform the copy. Without this flag, only a preview is shown.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the interactive confirmation when --apply is used.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Only print errors and the final summary.",
    )
    return parser.parse_args(argv)


def _resolve_paths(args: argparse.Namespace) -> tuple[list[Path], Path]:
    repo_root = args.repo or default_repo_root()

    source_roots: list[Path]
    if args.source:
        source_roots = [p.resolve() for p in args.source]
    else:
        source_roots = [p for p in default_source_roots(repo_root) if p.is_dir()]

    if args.deployed:
        deployed_root = args.deployed.resolve()
    elif args.hermes_home:
        deployed_root = (args.hermes_home / "skills").resolve()
    else:
        deployed_root = default_deployed_root().resolve()

    missing = [str(p) for p in source_roots if not p.is_dir()]
    if missing:
        raise ValueError(f"source root(s) do not exist: {', '.join(missing)}")
    if not deployed_root.is_dir():
        raise ValueError(f"deployed root does not exist: {deployed_root}")

    return source_roots, deployed_root


def _confirm(count: int) -> bool:
    try:
        answer = input(f"Apply sync for {count} skill(s)? [y/N] ")
    except (EOFError, KeyboardInterrupt):
        return False
    return answer.strip().lower() in {"y", "yes"}


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    skip_top: set[str] = DEFAULT_SKIP_TOP.copy()
    if args.skip_top:
        skip_top |= set(args.skip_top)

    try:
        source_roots, deployed_root = _resolve_paths(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    results = compare_all(source_roots, deployed_root, skip_top=skip_top)
    targets = [v for v in results if v.behind]

    def log(*a, **kw):
        if not args.quiet:
            print(*a, **kw)

    mode = "APPLY" if args.apply else "DRY-RUN"
    log(f"mode: {mode}")
    log(f"source roots: {[str(p) for p in source_roots]}")
    log(f"deployed root: {deployed_root}")
    log(f"BEHIND skills: {len(targets)}")
    log("=" * 70)

    if not targets:
        log("Nothing to sync.")
        return 0

    for v in targets:
        log(f"\n■ {v.name}")
        log(f"  source: {v.source_paths[0]}")
        log(f"  deployed: {v.deployed_paths[0]}")
        if v.missing:
            log(f"  will add ({len(v.missing)}): {v.missing}")
        if v.differs:
            log(f"  will overwrite ({len(v.differs)}): {v.differs}")

    if args.apply:
        if not args.yes and not _confirm(len(targets)):
            print("Cancelled.")
            return 1

        for v in targets:
            apply_one(v.source_paths[0], v.deployed_paths[0])

        log(f"\n{'=' * 70}")
        log(f"Synced {len(targets)} skill(s): {', '.join(v.name for v in targets)}")
    else:
        log(f"\n{'=' * 70}")
        log("Dry-run complete. Use --apply to perform the sync.")
        log(f"Would sync {len(targets)} skill(s): {', '.join(v.name for v in targets)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
