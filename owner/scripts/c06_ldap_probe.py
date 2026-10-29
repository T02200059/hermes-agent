#!/usr/bin/env python3
"""C06c: probe LDAP reachability + optional bind against the live directory.

Usage (from repo root, with HERMES_HOME pointing at a home that has overlay)::

  # TCP only (no bind)
  .venv/bin/python owner/scripts/c06_ldap_probe.py

  # Force enable + wrong-password negative bind (proves directory answers)
  HERMES_LDAP_ENABLED=1 .venv/bin/python owner/scripts/c06_ldap_probe.py --negative-bind

  # Positive bind (password via env only; never argv / never logged)
  HERMES_LDAP_ENABLED=1 HERMES_LDAP_E2E_PASSWORD='…' \\
    .venv/bin/python owner/scripts/c06_ldap_probe.py --login yangtb --positive-bind

Exit codes: 0 ok, 2 config/tcp fail, 3 bind unexpected, 4 ldap3 missing.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _tcp_check(host: str, port: int, timeout: float) -> tuple[bool, str]:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, "ok"
    except OSError as exc:
        return False, f"{type(exc).__name__}: {exc}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--login", default="c06c-probe-nonexistent")
    parser.add_argument(
        "--negative-bind",
        action="store_true",
        help="bind with a known-bad password; expect deny_bad_credentials",
    )
    parser.add_argument(
        "--positive-bind",
        action="store_true",
        help="bind with HERMES_LDAP_E2E_PASSWORD; expect allow",
    )
    parser.add_argument(
        "--gate-no-password",
        action="store_true",
        help="call ldap_gate(login, None); report verdict",
    )
    args = parser.parse_args()

    from owner.gateway import ldap_auth as la

    cfg = la._load_ldap_config()
    host = str(cfg.get("host") or "").strip()
    try:
        port = int(cfg.get("port", 389))
    except (TypeError, ValueError):
        port = 389
    try:
        timeout = float(cfg.get("timeout_seconds", 5) or 5)
    except (TypeError, ValueError):
        timeout = 5.0
    enabled = bool(cfg.get("enabled", False))
    template = str(cfg.get("user_dn_template") or "")

    print(f"enabled={enabled}")
    print(f"host={host or '(empty)'}")
    print(f"port={port}")
    print(f"user_dn_template={template or '(empty)'}")
    print(f"enforce={cfg.get('enforce')}")
    print(f"fail_open_on_error={cfg.get('fail_open_on_error')}")

    if not host:
        print("RESULT config_error: no host (set overlay ldap.host or HERMES_LDAP_HOST)")
        return 2

    ok, detail = _tcp_check(host, port, min(timeout, 5.0))
    print(f"tcp={('OK' if ok else 'FAIL')} {detail}")
    if not ok:
        return 2

    if not (args.negative_bind or args.positive_bind or args.gate_no_password):
        print("RESULT tcp_ok (pass --negative-bind / --positive-bind to exercise gate)")
        return 0

    import importlib.util

    if importlib.util.find_spec("ldap3") is None:
        print("RESULT ldap3_missing (pip/uv install optional extra 'ldap')")
        return 4

    la.reset_for_tests()

    async def _run() -> int:
        if args.gate_no_password:
            verdict = await la.ldap_gate(args.login, None)
            print(f"gate_no_password={verdict}")
            return 0

        if args.negative_bind:
            verdict = await la.ldap_gate(args.login, "c06c-definitely-wrong-password")
            print(f"negative_bind={verdict}")
            if not enabled:
                print("NOTE: enabled=false → gate short-circuits to allow; set HERMES_LDAP_ENABLED=1")
            expected = la.DENY_BAD_CREDENTIALS if enabled else la.ALLOW
            if verdict != expected:
                print(f"RESULT unexpected (want {expected})")
                return 3
            print("RESULT ok")
            return 0

        if args.positive_bind:
            password = os.environ.get("HERMES_LDAP_E2E_PASSWORD")
            if not password:
                print("RESULT need HERMES_LDAP_E2E_PASSWORD in env (not argv)")
                return 2
            if not enabled:
                print("RESULT need HERMES_LDAP_ENABLED=1 for positive bind")
                return 2
            verdict = await la.ldap_gate(args.login, password)
            # never print password; verdict only
            print(f"positive_bind={verdict}")
            if verdict != la.ALLOW:
                print("RESULT unexpected (want allow)")
                return 3
            print("RESULT ok")
            return 0
        return 0

    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
