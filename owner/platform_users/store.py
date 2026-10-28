"""Sidecar ``platform_users`` table on ``state.db`` (runtime CREATE, no SCHEMA edit).

Mirrors the delivery_ledger pattern: short-lived ``open_db`` + ``transaction``,
``CREATE TABLE IF NOT EXISTS`` on first use. Never rewrite ``sessions.display_name``.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Mapping, Optional

logger = logging.getLogger(__name__)

PLATFORM_FEISHU = "feishu"

_DDL = """
CREATE TABLE IF NOT EXISTS platform_users (
    platform TEXT NOT NULL,
    user_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY (platform, user_id)
)
"""

_DB_LOCK = threading.Lock()
_ensured_paths: set[str] = set()


def _db_path(db_path: Optional[Path] = None) -> Path:
    if db_path is not None:
        return Path(db_path)
    from hermes_constants import get_hermes_home

    return get_hermes_home() / "state.db"


def _connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    from hermes_cli.sqlite_util import open_db

    path = _db_path(db_path)
    return open_db(
        path,
        db_label="state.db (platform_users)",
        busy_timeout_ms=10_000,
        row_factory=None,
        initialize=ensure_table,
    )


def ensure_table(conn: sqlite3.Connection) -> None:
    """Idempotent DDL; safe to call on every connect."""
    conn.execute(_DDL)


def upsert_display_name(
    platform: str,
    user_id: str,
    display_name: str,
    *,
    db_path: Optional[Path] = None,
    updated_at: Optional[float] = None,
) -> bool:
    """Insert or refresh a platform display name. Empty name/id → no-op (False)."""
    platform = (platform or "").strip()
    user_id = (user_id or "").strip()
    name = (display_name or "").strip()
    if not platform or not user_id or not name:
        return False
    stamp = float(updated_at if updated_at is not None else time.time())
    path = _db_path(db_path)
    try:
        from hermes_cli.sqlite_util import transaction

        with _DB_LOCK:
            with transaction(_connect(path)) as conn:
                conn.execute(
                    """
                    INSERT INTO platform_users (platform, user_id, display_name, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(platform, user_id) DO UPDATE SET
                        display_name = excluded.display_name,
                        updated_at = excluded.updated_at
                    """,
                    (platform, user_id, name, stamp),
                )
        _ensured_paths.add(str(path))
        return True
    except Exception:
        logger.debug(
            "platform_users upsert failed for %s/%s",
            platform,
            user_id,
            exc_info=True,
        )
        return False


def get_display_name(
    platform: str,
    user_id: str,
    *,
    db_path: Optional[Path] = None,
) -> Optional[str]:
    """Return stored display_name or None. Fail-open on DB errors."""
    platform = (platform or "").strip()
    user_id = (user_id or "").strip()
    if not platform or not user_id:
        return None
    path = _db_path(db_path)
    try:
        from hermes_cli.sqlite_util import transaction

        with _DB_LOCK:
            with transaction(_connect(path)) as conn:
                row = conn.execute(
                    """
                    SELECT display_name FROM platform_users
                    WHERE platform = ? AND user_id = ?
                    """,
                    (platform, user_id),
                ).fetchone()
        if not row:
            return None
        name = row[0]
        return name if isinstance(name, str) and name.strip() else None
    except Exception:
        logger.debug(
            "platform_users get failed for %s/%s",
            platform,
            user_id,
            exc_info=True,
        )
        return None


def backfill_from_feishu_user_entries(
    users: Mapping[str, Any],
    *,
    db_path: Optional[Path] = None,
) -> int:
    """Upsert Feishu names already present on in-memory ``FeishuUserEntry`` records.

    Skips empty / missing names. Returns how many rows were written successfully.
    Safe to call repeatedly (idempotent upserts). Uses one short DB transaction.
    """
    rows: list[tuple[str, str, str, float]] = []
    now = time.time()
    for open_id, entry in users.items():
        if not isinstance(open_id, str) or not open_id.startswith("ou_"):
            continue
        name = getattr(entry, "display_name", None)
        if not isinstance(name, str) or not name.strip():
            continue
        expire = getattr(entry, "display_name_expire_at", None)
        stamp = float(expire) if isinstance(expire, (int, float)) else now
        rows.append((PLATFORM_FEISHU, open_id, name.strip(), stamp))
    if not rows:
        return 0
    path = _db_path(db_path)
    try:
        from hermes_cli.sqlite_util import transaction

        with _DB_LOCK:
            with transaction(_connect(path)) as conn:
                conn.executemany(
                    """
                    INSERT INTO platform_users (platform, user_id, display_name, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(platform, user_id) DO UPDATE SET
                        display_name = excluded.display_name,
                        updated_at = excluded.updated_at
                    """,
                    rows,
                )
        return len(rows)
    except Exception:
        logger.debug("platform_users backfill failed", exc_info=True)
        return 0


def dual_write_feishu_name(
    user_id: str,
    display_name: str,
    *,
    db_path: Optional[Path] = None,
) -> bool:
    """Convenience for the Feishu resolve path (platform fixed to ``feishu``)."""
    return upsert_display_name(
        PLATFORM_FEISHU,
        user_id,
        display_name,
        db_path=db_path,
    )
