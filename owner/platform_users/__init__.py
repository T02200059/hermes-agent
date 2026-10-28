"""Platform display-name directory in ``state.db`` (sidecar ``platform_users``).

Persists ``platform + user_id → display_name`` (e.g. Feishu Chinese names) without
touching the official SessionDB SCHEMA literals. Feishu JSON cache (C04) remains
the hot path; this table is the durable directory for queries / C05 routing.
"""

from owner.platform_users.store import (
    PLATFORM_FEISHU,
    backfill_from_feishu_user_entries,
    dual_write_feishu_name,
    ensure_table,
    get_display_name,
    upsert_display_name,
)

__all__ = [
    "PLATFORM_FEISHU",
    "backfill_from_feishu_user_entries",
    "dual_write_feishu_name",
    "ensure_table",
    "get_display_name",
    "upsert_display_name",
]
