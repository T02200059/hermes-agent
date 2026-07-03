#!/usr/bin/env python3
"""Compare deployed skills with their source-of-truth copies in the repo.

Exit codes:
    0  diff completed (regardless of how many skills are behind)
    2  bad arguments / missing directories
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from owner.scripts.skill_sync_lib import (
    DEFAULT_SKIP_TOP,
    compare_all,
    default_deployed_root,
    default_repo_root,
    default_source_roots,
    file_directions,
    index_deployed,
    index_source,
    line_count,
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Show which deployed skills are behind their repo copies.",
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
        help="Deployed skills directory to check (default: HERMES_HOME/skills).",
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
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of human-readable text.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Only print the summary and error messages.",
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


def _verdict_to_dict(verdict) -> dict[str, Any]:
    directions = file_directions(verdict.source_paths, verdict.deployed_paths, verdict.differs)
    return {
        "name": verdict.name,
        "behind": verdict.behind,
        "source": [str(p) for p in verdict.source_paths],
        "deployed": [str(p) for p in verdict.deployed_paths],
        "missing": verdict.missing,
        "differs": [
            {"path": rel, "direction": directions.get(rel, "?")}
            for rel in verdict.differs
        ],
        "extra": verdict.extra,
    }


def _run_json(source_roots: list[Path], deployed_root: Path, skip_top: set[str]) -> None:
    src_idx = index_source(source_roots)
    dep_idx = index_deployed(deployed_root, skip_top=skip_top)
    results = compare_all(source_roots, deployed_root, skip_top=skip_top)
    payload = {
        "source_roots": [str(p) for p in source_roots],
        "deployed_root": str(deployed_root),
        "source_only": sorted(set(src_idx) - set(dep_idx)),
        "deployed_only": sorted(set(dep_idx) - set(src_idx)),
        "skills": [_verdict_to_dict(v) for v in results],
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def _run_text(source_roots: list[Path], deployed_root: Path, skip_top: set[str], quiet: bool) -> None:
    src_idx = index_source(source_roots)
    dep_idx = index_deployed(deployed_root, skip_top=skip_top)
    results = compare_all(source_roots, deployed_root, skip_top=skip_top)

    common = sorted(set(src_idx) & set(dep_idx))
    behind = [v for v in results if v.behind]
    extra_only = [v for v in results if not v.behind and v.extra]
    in_sync = len(results) - len(behind) - len(extra_only)
    multi = [
        (name, src_idx[name], dep_idx[name])
        for name in common
        if len(src_idx[name]) > 1 or len(dep_idx[name]) > 1
    ]

    def log(*args, **kwargs):
        if not quiet:
            print(*args, **kwargs)

    log(f"source roots: {[str(p) for p in source_roots]}")
    log(f"deployed root: {deployed_root}")
    log(f"source skills:   {len(src_idx)}")
    log(f"deployed skills: {len(dep_idx)}")
    log(f"common skills:   {len(common)}")
    log("=" * 70)

    log(f"\n[behind source: {len(behind)} / {len(common)} skills]")
    for v in behind:
        log(f"\n■ {v.name}")
        if v.missing:
            log(f"  missing ({len(v.missing)}):")
            for rel in v.missing:
                log(f"    - {rel}")
        if v.differs:
            log(f"  differs ({len(v.differs)}):")
            directions = file_directions(v.source_paths, v.deployed_paths, v.differs)
            for rel in v.differs:
                sp0 = v.source_paths[0]
                dp0 = v.deployed_paths[0]
                s = line_count(sp0 / rel) if (sp0 / rel).exists() else -1
                d = line_count(dp0 / rel) if (dp0 / rel).exists() else -1
                log(f"    ~ {rel}  [{directions.get(rel, '?')}]  (source {s}L | deployed {d}L)")
        if v.extra:
            log(f"  extra ({len(v.extra)}):")
            for rel in v.extra:
                log(f"    + {rel}")

    log(f"\n[only extra (local additions): {len(extra_only)} skills]")
    for v in extra_only:
        log(f"  {v.name}: {len(v.extra)} extra files")

    log(f"\n[in sync: {in_sync} skills]")

    if multi:
        log(f"\n[ambiguous paths: {len(multi)} skills]")
        for name, sps, dps in multi:
            log(f"  {name}: src={[str(p) for p in sps]} dep={[str(p) for p in dps]}")

    print("\n" + "=" * 70)
    print("SUMMARY")
    print(f"  common skills:       {len(common)}")
    print(f"  behind:              {len(behind)}")
    print(f"    with missing:      {sum(1 for v in behind if v.missing)}")
    print(f"    with differs:      {sum(1 for v in behind if v.differs)}")
    print(f"    missing files:     {sum(len(v.missing) for v in behind)}")
    print(f"    differing files:   {sum(len(v.differs) for v in behind)}")
    print(f"  only extra:          {len(extra_only)}")
    print(f"  in sync:             {in_sync}")
    if behind:
        print(f"  behind list:         {', '.join(v.name for v in behind)}")


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

    if args.json:
        _run_json(source_roots, deployed_root, skip_top)
    else:
        _run_text(source_roots, deployed_root, skip_top, quiet=args.quiet)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
