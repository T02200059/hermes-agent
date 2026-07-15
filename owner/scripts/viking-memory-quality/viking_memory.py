#!/usr/bin/env python3
"""OpenViking memory quality analysis CLI (read-only).

Usage:
  python3 viking_memory.py scan [options]
  python3 viking_memory.py doctor

Connection: $HERMES_HOME/.env (OPENVIKING_ENDPOINT / API_KEY / USER / ...).
No LLM calls. No writes. Report is for subsequent governance pipelines.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Allow ``python3 viking-memory-quality/viking_memory.py`` and sibling imports.
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import viking_memory_lib as lib  # noqa: E402


def _parse_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def cmd_doctor(_: argparse.Namespace) -> int:
    log = lib.get_logger("viking-doctor")
    try:
        cfg = lib.load_ov_config()
    except Exception as exc:  # noqa: BLE001
        print(f"config error: {exc}", file=sys.stderr)
        return 1
    print(f"HERMES_HOME={lib.hermes_home()}")
    print(f".env={lib.hermes_env_path()} exists={lib.hermes_env_path().exists()}")
    print(f"endpoint={cfg.endpoint}")
    print(f"user={cfg.user} account={cfg.account} agent={cfg.agent}")
    print(f"api_key_set={bool(cfg.api_key)} source={cfg.source}")
    client = lib.OVClient(cfg, log=log)
    ok = client.health()
    print(f"reachable={ok}")
    if not ok:
        return 2
    user_ls = client.fs_ls(cfg.user_memories_uri)
    peer_ls = client.fs_ls(cfg.peer_memories_uri)
    print(f"user_memories_entries={len(user_ls or [])}")
    print(f"peer_memories_entries={len(peer_ls or [])}")
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    import logging

    log = lib.get_logger("viking-scan")
    if args.verbose:
        log.setLevel(logging.DEBUG)

    try:
        client = lib.OVClient(log=log)
    except Exception as exc:  # noqa: BLE001
        print(f"init failed: {exc}", file=sys.stderr)
        return 1

    exclude = _parse_csv(args.exclude_category)
    include = _parse_csv(args.only_category) or None

    log.info(
        "scan start endpoint=%s user=%s threshold=%.3f include_peer=%s",
        client.endpoint,
        client.user,
        args.threshold,
        not args.user_only,
    )

    report = lib.build_scan_report(
        client,
        include_peer=not args.user_only,
        threshold=args.threshold,
        skip_similar=args.skip_similar,
        skip_non_chinese=args.skip_non_chinese,
        include_english=args.include_english,
        exclude_categories=exclude or None,
        categories=include,
    )

    # Human summary on stderr so stdout can be pure JSON when desired.
    summary = report["summary"]
    inv = report["inventory"]
    log.info(
        "done files=%s mirrors=%s non_chinese=%s similar_pairs=%s",
        inv["total_files"],
        inv["exact_mirrors_marked"],
        summary["non_chinese_count"],
        summary["similar_pairs_count"],
    )

    if args.quiet_if_clean and not summary.get("has_work"):
        return 0

    text = json.dumps(report, ensure_ascii=False, indent=2 if args.pretty else None)
    if args.output_json:
        Path(args.output_json).write_text(text + "\n", encoding="utf-8")
        log.info("report written to %s", args.output_json)
        if args.print_summary:
            print(
                json.dumps(
                    {
                        "summary": summary,
                        "inventory": inv,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
    else:
        print(text)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="OpenViking memory quality analysis (read-only)"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="Validate HERMES_HOME/.env connectivity")
    doctor.set_defaults(func=cmd_doctor)

    scan = sub.add_parser(
        "scan",
        help="Scan non-Chinese content and near-duplicates (excludes exact peer mirrors)",
    )
    scan.add_argument(
        "--output-json",
        help="Write full report to this path (still prints summary if --print-summary)",
    )
    scan.add_argument(
        "--threshold",
        type=float,
        default=0.85,
        help="Near-duplicate cosine threshold (default 0.85)",
    )
    scan.add_argument(
        "--user-only",
        action="store_true",
        help="Only scan user memories (skip peer tree walk for non-Chinese)",
    )
    scan.add_argument(
        "--skip-similar",
        action="store_true",
        help="Skip embedding near-duplicate analysis",
    )
    scan.add_argument(
        "--skip-non-chinese",
        action="store_true",
        help="Skip non-Chinese language detection",
    )
    scan.add_argument(
        "--include-english",
        action="store_true",
        help="Also flag English-heavy memories (default: pt/es/it/fr/de only)",
    )
    scan.add_argument(
        "--exclude-category",
        default="",
        help="Comma-separated categories to skip (e.g. events,trajectories)",
    )
    scan.add_argument(
        "--only-category",
        default="",
        help="Comma-separated categories to include exclusively",
    )
    scan.add_argument(
        "--quiet-if-clean",
        action="store_true",
        help="Print nothing when there is no work (cron-friendly)",
    )
    scan.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON",
    )
    scan.add_argument(
        "--print-summary",
        action="store_true",
        help="When using --output-json, also print summary JSON to stdout",
    )
    scan.add_argument("--verbose", action="store_true")
    scan.set_defaults(func=cmd_scan)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
