#!/usr/bin/env python3
"""Sync the 6 outdated deployed skills from the source of truth.

For each (source_dir, deployed_dir) pair, copy the source tree over the
deployed tree with ``dirs_exist_ok=True``. This implements the user's rule:

  * source-first  -> files present in both are overwritten with the SOURCE copy
  * add missing   -> files only in source (e.g. new reference files) are added
  * keep local    -> files only in the deployed copy are PRESERVED (not deleted)

A timestamped backup of every deployed dir is taken before any write, so the
operation is fully reversible.

Usage:
    sync_skills_from_source.py [--dry-run]
"""

from __future__ import annotations

import argparse
import datetime
import shutil
import sys
from pathlib import Path

HERMES = Path("/Users/yangtb/.hermes")
SRC = HERMES / "hermes-agent/skills"

# (source relative to hermes-agent/skills, deployed relative to HERMES)
TARGETS: list[tuple[str, str]] = [
    ("autonomous-ai-agents/codex", "skills/autonomous-ai-agents/codex"),
    ("github/github-pr-workflow", "skills/github/github-pr-workflow"),
    ("github/github-repo-management", "skills/github/github-repo-management"),
    ("autonomous-ai-agents/hermes-agent", "skills/autonomous-ai-agents/hermes-agent"),
    ("autonomous-ai-agents/opencode", "skills/autonomous-ai-agents/opencode"),
    ("software-development/systematic-debugging", "skills/systematic-debugging"),
    ("software-development/systematic-debugging", "skills/software-development/systematic-debugging"),
]


def count_files(d: Path) -> int:
    return sum(1 for p in d.rglob("*") if p.is_file())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="Show plan, make no changes.")
    args = ap.parse_args()

    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_root = HERMES / f".skill_backup_{ts}"

    print("=" * 72)
    print(f"mode: {'DRY-RUN' if args.dry_run else 'APPLY'}")
    print(f"source root: {SRC}")
    print(f"backup root: {backup_root}")
    print("=" * 72)

    for src_rel, dep_rel in TARGETS:
        src = SRC / src_rel
        dep = HERMES / dep_rel
        if not src.is_dir():
            print(f"  SKIP  (no source)       {src_rel}")
            continue
        if not dep.is_dir():
            print(f"  SKIP  (no deployed)     {dep_rel}")
            continue

        before = count_files(dep)
        if args.dry_run:
            print(f"  PLAN  sync {dep_rel}  ({before} files) <- {src_rel}")
            continue

        # 1) timestamped backup
        bk = backup_root / dep_rel
        bk.parent.mkdir(parents=True, exist_ok=True)
        if dep.exists():
            shutil.copytree(dep, bk, dirs_exist_ok=True)

        # 2) source-first copy: overwrite common, add missing, keep extras
        shutil.copytree(src, dep, dirs_exist_ok=True)
        after = count_files(dep)
        print(f"  SYNC  {dep_rel}  files {before} -> {after}   (backup: {bk})")

    print("=" * 72)
    if not args.dry_run:
        print(f"done. backups under: {backup_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
