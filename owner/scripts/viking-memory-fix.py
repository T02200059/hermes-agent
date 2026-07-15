#!/usr/bin/env python3
"""Deferred fix worker for OpenViking memory quality.

The previous version auto-translated / consolidated via LLM. That path is
intentionally disabled until the read-only scan pipeline is stable.

This script only validates and summarizes work items from a scan report so
downstream agents can act deliberately.

Usage:
  python3 viking-memory-fix.py --report /tmp/report.json
  python3 viking-memory-fix.py --task translate --items '[...]'
  python3 viking-memory-fix.py --task consolidate --pairs '[...]'
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _load_json_arg(raw: str | None):
    if not raw:
        return []
    raw = raw.strip()
    if raw.startswith("@"):
        return json.loads(Path(raw[1:]).read_text(encoding="utf-8"))
    return json.loads(raw)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="OpenViking memory fix worker (analysis-only stub)"
    )
    parser.add_argument("--report", help="Path to pipeline/scan report JSON")
    parser.add_argument("--task", choices=["translate", "consolidate", "summarize"])
    parser.add_argument("--items", default="")
    parser.add_argument("--pairs", default="")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Not supported yet; will exit with error if set",
    )
    args = parser.parse_args()

    if args.apply:
        print(
            json.dumps(
                {
                    "error": "apply/write path disabled; use scan report for manual or later pipeline",
                    "applied": 0,
                },
                ensure_ascii=False,
            )
        )
        return 2

    items = []
    pairs = []
    if args.report:
        report = json.loads(Path(args.report).read_text(encoding="utf-8"))
        # Accept both pipeline shape and raw scan shape.
        if "tier1" in report:
            items = report.get("tier1", {}).get("items") or []
            pairs = report.get("tier2", {}).get("items") or []
        else:
            items = report.get("non_chinese") or report.get("details") or []
            pairs = (
                report.get("similar_pairs")
                or report.get("similar_pairs_detail")
                or report.get("details")
                or []
            )
            # If details look like non-chinese only, keep pairs empty when wrong shape.
            if pairs and isinstance(pairs, list) and pairs and "uri_a" not in pairs[0] and "similarity" not in pairs[0]:
                if "language" in (pairs[0] or {}):
                    pairs = []

    if args.items:
        items = _load_json_arg(args.items)
    if args.pairs:
        pairs = _load_json_arg(args.pairs)

    task = args.task or "summarize"
    if task == "translate":
        out = {
            "task": "translate",
            "status": "deferred",
            "count": len(items),
            "items": items,
            "message": "No auto-translate. Feed items to a later LLM step.",
        }
    elif task == "consolidate":
        out = {
            "task": "consolidate",
            "status": "deferred",
            "count": len(pairs),
            "pairs": pairs,
            "message": "No auto-merge. Feed pairs to a later LLM step.",
        }
    else:
        out = {
            "task": "summarize",
            "status": "ok",
            "non_chinese": len(items),
            "similar_pairs": len(pairs),
            "items_preview": items[:10],
            "pairs_preview": pairs[:10],
        }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
