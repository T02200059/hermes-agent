#!/usr/bin/env python3
"""Unified OpenViking memory quality pipeline (read-only orchestrator).

Always emits a full JSON report to stdout (unlike the cron scanner which is
silent when clean). Never writes to OpenViking.

Layers:
  tier1 — non-Chinese
  tier2 — near-duplicates (URIs pending translate this round are deferred)
  tier3 — preference / hard-claim candidates (skips human_reviewed=1)

Usage:
  python3 viking-memory-pipeline.py [--threshold 0.85] [--verbose]
  python3 viking-memory-pipeline.py --output /tmp/viking-report.json
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
    parser = argparse.ArgumentParser(description="OpenViking memory quality pipeline")
    parser.add_argument("--threshold", type=float, default=0.85)
    parser.add_argument("--user-only", action="store_true")
    parser.add_argument("--skip-similar", action="store_true")
    parser.add_argument("--skip-non-chinese", action="store_true")
    parser.add_argument(
        "--include-english",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Flag English / low-Chinese Latin text for translate tier (default: on)",
    )
    parser.add_argument("--exclude-category", default="")
    parser.add_argument(
        "--preference-limit",
        type=int,
        default=10,
        help="Max preference (tier3) candidates to return (default 10; 0=unlimited)",
    )
    parser.add_argument("--output", help="Also write report to this path")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Accepted for compatibility; always read-only",
    )
    args = parser.parse_args()

    log = lib.get_logger("viking-pipeline")
    if args.verbose:
        import logging

        log.setLevel(logging.DEBUG)

    try:
        client = lib.OVClient(log=log)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": str(exc), "has_work": False}, ensure_ascii=False))
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
        preference_limit=args.preference_limit,
    )

    pref = report.get("preferences") or {}
    out = {
        "tier1": {
            "scanned": report["inventory"]["total_files"],
            "flagged": report["summary"]["non_chinese_count"],
            "items": [
                {
                    "path": item["rel"],
                    "uri": item["uri"],
                    "space": item["space"],
                    "category": item["category"],
                    "language": item["detection"].get("language"),
                    "density": item["detection"].get("density"),
                    "zh_ratio": item["detection"].get("zh_ratio"),
                    "reason": item["detection"].get("reason"),
                    "snippet": item.get("snippet"),
                }
                for item in report["non_chinese"]
            ],
        },
        "tier2": {
            "scanned": report["similar_meta"].get("vectors_used", 0),
            "pairs": report["summary"]["similar_pairs_count"],
            "deferred_for_translate": report["summary"].get(
                "similar_pairs_deferred_translate_count", 0
            ),
            "items": [
                {
                    "similarity": pair["similarity"],
                    "file_a": pair["rel_a"],
                    "file_b": pair["rel_b"],
                    "uri_a": pair["uri_a"],
                    "uri_b": pair["uri_b"],
                    "category_a": pair["category_a"],
                    "category_b": pair["category_b"],
                    "same_category": pair["same_category"],
                    "suggestion": pair["suggestion"],
                    "snippets": pair.get("snippets"),
                }
                for pair in report["similar_pairs"]
            ],
            "deferred_items": report.get("similar_pairs_deferred_translate") or [],
            "meta": report["similar_meta"],
        },
        "tier3": {
            "scanned": pref.get("scanned_files", 0),
            "skipped_human_reviewed": pref.get("skipped_human_reviewed", 0),
            "candidates": pref.get("candidate_count", 0),
            "limit": report["config"].get("preference_limit"),
            "items": pref.get("candidates") or [],
            "tag_schema": pref.get("tag_schema") or {},
        },
        "inventory": report["inventory"],
        "config": report["config"],
        "has_work": report["summary"]["has_work"],
        "summary": report["summary"],
        "scan_time": report["scan_time"],
    }

    text = json.dumps(out, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
