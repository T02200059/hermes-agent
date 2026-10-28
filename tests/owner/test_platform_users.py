"""platform_users sidecar table: ensure / upsert / get / Feishu dual-write."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from owner.feishu.user_store import FeishuUserStore
from owner.platform_users import (
    PLATFORM_FEISHU,
    backfill_from_feishu_user_entries,
    get_display_name,
    upsert_display_name,
)
from owner.platform_users.store import ensure_table


@pytest.fixture
def state_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "hermes_home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    db = home / "state.db"
    return db


def test_ensure_table_creates_platform_users(state_db: Path):
    conn = sqlite3.connect(state_db)
    try:
        ensure_table(conn)
        conn.commit()
        cols = {row[1] for row in conn.execute("PRAGMA table_info(platform_users)")}
    finally:
        conn.close()
    assert cols == {"platform", "user_id", "display_name", "updated_at"}


def test_upsert_and_get_roundtrip(state_db: Path):
    assert upsert_display_name("feishu", "ou_abc", "杨天宝", db_path=state_db) is True
    assert get_display_name("feishu", "ou_abc", db_path=state_db) == "杨天宝"
    # refresh
    assert upsert_display_name("feishu", "ou_abc", "杨天宝二号", db_path=state_db) is True
    assert get_display_name("feishu", "ou_abc", db_path=state_db) == "杨天宝二号"


def test_upsert_skips_empty(state_db: Path):
    assert upsert_display_name("feishu", "ou_x", "", db_path=state_db) is False
    assert upsert_display_name("", "ou_x", "名", db_path=state_db) is False
    assert get_display_name("feishu", "ou_x", db_path=state_db) is None


def test_backfill_from_feishu_entries(state_db: Path):
    users = {
        "ou_1": SimpleNamespace(display_name="甲", display_name_expire_at=time.time()),
        "ou_2": SimpleNamespace(display_name="", display_name_expire_at=None),
        "oc_chat": SimpleNamespace(display_name="群", display_name_expire_at=None),
    }
    n = backfill_from_feishu_user_entries(users, db_path=state_db)
    assert n == 1
    assert get_display_name(PLATFORM_FEISHU, "ou_1", db_path=state_db) == "甲"
    assert get_display_name(PLATFORM_FEISHU, "ou_2", db_path=state_db) is None


def test_user_store_dual_writes_sqlite(state_db: Path, tmp_path: Path):
    cache = tmp_path / "feishu_chat_id_cache.json"
    store = FeishuUserStore(cache_path=cache)
    expire = time.time() + 3600
    store._store_resolved_name("ou_dual", "双写用户", expire)

    # C04 JSON path still works
    assert store.get_cached_name("ou_dual") == "双写用户"
    assert "ou_dual" in store.users
    assert store.users["ou_dual"].display_name == "双写用户"

    # sqlite directory got the name (HERMES_HOME → state_db)
    assert get_display_name("feishu", "ou_dual") == "双写用户"


def test_user_store_init_backfills_from_cache(state_db: Path, tmp_path: Path):
    cache = tmp_path / "feishu_chat_id_cache.json"
    cache.write_text(
        '{"_version": 2, "users": {"ou_seed": {"display_name": "种子名", "display_name_expire_at": 9999999999}}}',
        encoding="utf-8",
    )
    store = FeishuUserStore(cache_path=cache)
    assert store.get_cached_name("ou_seed") == "种子名"
    assert get_display_name("feishu", "ou_seed") == "种子名"


def test_c04_cache_unaffected_when_sqlite_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = tmp_path / "hermes_home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    cache = tmp_path / "cache.json"

    with patch(
        "owner.platform_users.store.dual_write_feishu_name",
        side_effect=RuntimeError("boom"),
    ):
        store = FeishuUserStore(cache_path=cache)
        store._store_resolved_name("ou_ok", "仍缓存", time.time() + 100)
    assert store.get_cached_name("ou_ok") == "仍缓存"
