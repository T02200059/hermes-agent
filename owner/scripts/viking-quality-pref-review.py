#!/usr/bin/env python3
"""Layer-3: OpenViking preference / hard-claim review helpers.

Tags (OpenViking k=v, lowercased by server):
  human_reviewed=1          permanently skip re-queue (no TTL)
  human_reviewed_at=<dt>    2026-07-16_10-43-18+0800  (avoid ISO 'T'; OV lowercases)

Usage:
  python3 viking-quality-pref-review.py scan [--limit 20] [--output ...]
  python3 viking-quality-pref-review.py tag --uri 'viking://...' [--dry-run]
  python3 viking-quality-pref-review.py tag-sample --n 2   # tag top-N unreviewed candidates
  python3 viking-quality-pref-review.py show --uri 'viking://...'
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import viking_memory_lib as lib  # noqa: E402


def cmd_scan(args: argparse.Namespace) -> int:
    log = lib.get_logger("viking-pref")
    client = lib.OVClient(log=log)
    report = lib.scan_preference_candidates(
        client,
        include_peer=not args.user_only,
        skip_reviewed=not args.include_reviewed,
        limit=args.limit,
    )
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
        log.info("wrote %s (%d candidates)", args.output, report["candidate_count"])
    print(text)
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    client = lib.OVClient()
    attrs = client.fs_attrs(args.uri)
    tags = lib.tags_from_attrs(attrs)
    print(
        json.dumps(
            {
                "uri": args.uri,
                "tags": tags,
                "tag_map": lib.parse_tag_map(tags),
                "human_reviewed": lib.is_human_reviewed(tags),
                "raw_attrs": attrs,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_tag(args: argparse.Namespace) -> int:
    client = lib.OVClient()
    tags = lib.human_review_tag_list(reviewed=True)
    if args.dry_run:
        print(json.dumps({"uri": args.uri, "would_set": tags, "dry_run": True}, ensure_ascii=False, indent=2))
        return 0
    result = lib.mark_human_reviewed(client, args.uri)
    # read back
    attrs = client.fs_attrs(args.uri)
    result["attrs_after"] = lib.tags_from_attrs(attrs)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    ok = result.get("response", {}).get("status") == "ok"
    return 0 if ok else 1


def cmd_tag_sample(args: argparse.Namespace) -> int:
    """Scan candidates, tag top-N unreviewed (for trial)."""
    log = lib.get_logger("viking-pref")
    client = lib.OVClient(log=log)
    report = lib.scan_preference_candidates(
        client,
        include_peer=not args.user_only,
        skip_reviewed=True,
        limit=max(args.n * 3, 20),
    )
    picked = report["candidates"][: args.n]
    results = []
    for item in picked:
        uri = item["uri"]
        if args.dry_run:
            results.append({"uri": uri, "would_set": lib.human_review_tag_list(), "dry_run": True, "flags": item["flags"]})
            continue
        r = lib.mark_human_reviewed(client, uri)
        attrs = client.fs_attrs(uri)
        results.append(
            {
                "uri": uri,
                "flags": item["flags"],
                "score": item["score"],
                "tags_set": r["tags"],
                "attrs_after": lib.tags_from_attrs(attrs),
                "ok": r.get("response", {}).get("status") == "ok",
            }
        )
    # re-scan to show skip count
    after = lib.scan_preference_candidates(
        client,
        include_peer=not args.user_only,
        skip_reviewed=True,
        limit=5,
    )
    out = {
        "tagged": results,
        "after_skip_human_reviewed": after["skipped_human_reviewed"],
        "after_candidate_count": after["candidate_count"],
        "after_top": [
            {"uri": c["uri"], "flags": c["flags"], "human_reviewed": c["human_reviewed"]}
            for c in after["candidates"][:5]
        ],
    }
    text = json.dumps(out, ensure_ascii=False, indent=2, default=str)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Preference review + human_* tags")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", help="Scan preference candidates")
    s.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Max candidates to return (default 10; 0=unlimited)",
    )
    s.add_argument("--user-only", action="store_true")
    s.add_argument("--include-reviewed", action="store_true", help="Do not skip human_reviewed=1")
    s.add_argument("--output", help="Write JSON report path")
    s.set_defaults(func=cmd_scan)

    sh = sub.add_parser("show", help="Show tags on one URI")
    sh.add_argument("--uri", required=True)
    sh.set_defaults(func=cmd_show)

    t = sub.add_parser("tag", help="Mark one URI human_reviewed=1")
    t.add_argument("--uri", required=True)
    t.add_argument("--dry-run", action="store_true")
    t.set_defaults(func=cmd_tag)

    ts = sub.add_parser("tag-sample", help="Tag top-N unreviewed preference candidates (trial)")
    ts.add_argument("--n", type=int, default=2)
    ts.add_argument("--user-only", action="store_true")
    ts.add_argument("--dry-run", action="store_true")
    ts.add_argument("--output")
    ts.set_defaults(func=cmd_tag_sample)

    args = p.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
