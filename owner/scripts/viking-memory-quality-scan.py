#!/usr/bin/env python3
"""Cron / human entry for OpenViking memory quality analysis (read-only).

Replaces the previous auto-fix scanner that depended on admin key resolution
and LLM writes. This entry only **analyzes**:

- non-Chinese content
- near-duplicates (embedding cosine; exact peer mirrors excluded)

Connection: ``$HERMES_HOME/.env`` (OPENVIKING_*).

Usage:
  python3 viking-memory-quality-scan.py [--json] [--threshold 0.85] [--verbose]
  python3 viking-memory-quality-scan.py --output /tmp/report.json

Cron-compatible: with default ``--json``, prints nothing when clean.
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
    parser = argparse.ArgumentParser(
        description="OpenViking memory quality scan (non-Chinese + near-dups)"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=True,
        help="Emit JSON report on stdout when there is work (default)",
    )
    parser.add_argument(
        "--always-print",
        action="store_true",
        help="Always print full report even when clean",
    )
    parser.add_argument(
        "--output",
        "--output-json",
        dest="output",
        help="Write full report to path",
    )
    parser.add_argument("--threshold", type=float, default=0.85)
    parser.add_argument(
        "--user-only",
        action="store_true",
        help="Skip peer tree for non-Chinese inventory",
    )
    parser.add_argument("--skip-similar", action="store_true")
    parser.add_argument("--skip-non-chinese", action="store_true")
    parser.add_argument(
        "--include-english",
        action="store_true",
        help="Also flag English-heavy memories (default: only pt/es/it/fr/de contamination)",
    )
    parser.add_argument(
        "--exclude-category",
        default="",
        help="Comma-separated categories to exclude",
    )
    parser.add_argument("--verbose", action="store_true")
    # Accept legacy flag from older cron prompts (no longer writes).
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Accepted for compatibility; scan is always read-only",
    )
    args = parser.parse_args()

    log = lib.get_logger("viking-mq")
    if args.verbose:
        import logging

        log.setLevel(logging.DEBUG)

    try:
        client = lib.OVClient(log=log)
    except Exception as exc:  # noqa: BLE001
        # Cron used to crash here on admin key resolution — keep structured error.
        err = {
            "scanned": 0,
            "flagged": 0,
            "translated": 0,
            "errors": 1,
            "details": [{"error": f"Init failed: {exc}"}],
            "has_work": True,
        }
        print(json.dumps(err, ensure_ascii=False))
        return 1

    exclude = [p.strip() for p in args.exclude_category.split(",") if p.strip()]
    report = lib.build_scan_report(
        client,
        include_peer=not args.user_only,
        threshold=args.threshold,
        skip_similar=args.skip_similar,
        skip_non_chinese=args.skip_non_chinese,
        include_english=args.include_english,
        exclude_categories=exclude or None,
    )

    # Compact cron-facing summary fields (keep old key names where useful).
    compact = {
        "scan_time": report["scan_time"],
        "scanned": report["inventory"]["total_files"],
        "flagged": report["summary"]["non_chinese_count"],
        "similar_pairs": report["summary"]["similar_pairs_count"],
        "translated": 0,  # analysis-only; no auto translate
        "errors": report["inventory"]["read_failures"],
        "has_work": report["summary"]["has_work"],
        "inventory": report["inventory"],
        "non_chinese": report["non_chinese"],
        "similar_pairs_detail": report["similar_pairs"],
        "similar_meta": report["similar_meta"],
        "config": report["config"],
        "details": [
            {
                "path": item["rel"],
                "uri": item["uri"],
                "language": item["detection"].get("language"),
                "density": item["detection"].get("density"),
                "zh_ratio": item["detection"].get("zh_ratio"),
                "reason": item["detection"].get("reason"),
            }
            for item in report["non_chinese"]
        ],
    }

    if args.output:
        Path(args.output).write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        log.info("full report written to %s", args.output)

    if not compact["has_work"] and not args.always_print:
        return 0

    print(json.dumps(compact, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
