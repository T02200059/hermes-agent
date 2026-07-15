#!/usr/bin/env python3
"""Near-duplicate scanner only (read-only).

Uses OpenViking stored dense vectors. Exact peer mirrors are excluded.

Usage:
  python3 viking-memory-dedup-scan.py [--threshold 0.85] [--verbose]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import viking_memory_lib as lib  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="OpenViking near-duplicate scan")
    parser.add_argument("--threshold", type=float, default=0.85)
    parser.add_argument("--exclude-category", default="")
    parser.add_argument("--max-pairs", type=int, default=200)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Accepted for compatibility; always read-only",
    )
    args = parser.parse_args()

    log = lib.get_logger("viking-dedup")
    if args.verbose:
        import logging

        log.setLevel(logging.DEBUG)

    try:
        client = lib.OVClient(log=log)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": str(exc), "pairs_found": 0}, ensure_ascii=False))
        return 1

    exclude = [p.strip() for p in args.exclude_category.split(",") if p.strip()]
    pairs, meta = lib.scan_similar_from_vectors(
        client,
        threshold=args.threshold,
        exclude_categories=exclude or None,
        skip_exact_mirrors=True,
        max_pairs=args.max_pairs,
    )
    out = {
        "scanned": meta.get("vectors_used", 0),
        "pairs_found": len(pairs),
        "threshold": args.threshold,
        "meta": meta,
        "details": pairs,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
