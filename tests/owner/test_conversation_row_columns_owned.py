"""C02 follow-up: conversation SELECT must cover transcript_row_snapshot OWNED cols.

Missing columns caused gateway.errors.history_unavailable (IndexError: No item with that key)
on the second Feishu turn after C02 added token qty columns to INSERT/_OWNED_COLUMNS.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _parse_conversation_columns() -> set[str]:
    text = (ROOT / "hermes_state.py").read_text(encoding="utf-8")
    m = re.search(r"_CONVERSATION_ROW_COLUMNS = \(\n(.*?)\n    \)", text, re.DOTALL)
    assert m, "_CONVERSATION_ROW_COLUMNS not found"
    return {c.strip() for c in "".join(re.findall(r'"([^"]+)"', m.group(1))).split(",") if c.strip()}


def _parse_owned_columns() -> list[str]:
    # Mirror agent.transcript_repair without importing the heavy agent stack.
    msg = (ROOT / "hermes_state_messages.py").read_text(encoding="utf-8")
    m = re.search(
        r'_INSERT_MESSAGE_SQL = """INSERT INTO messages \((.*?)\)\s*VALUES',
        msg,
        re.DOTALL,
    )
    assert m, "INSERT SQL not found"
    write_cols = tuple(re.findall(r"\w+", m.group(1)))
    non_payload = {
        "session_id",
        "role",
        "timestamp",
        "active",
        "display_identity",
        "message_uid",
        "tool_call_uid",
    }
    metadata = {
        "display_kind",
        "display_metadata",
        "api_content",
        "codex_reasoning_items",
        "platform_message_id",
    }
    repair = [c for c in write_cols if c not in non_payload]
    return [c for c in repair if c not in metadata]


def test_conversation_row_columns_cover_owned_snapshot_columns():
    conv = _parse_conversation_columns()
    owned = _parse_owned_columns()
    missing = [c for c in owned if c not in conv]
    assert missing == [], f"_CONVERSATION_ROW_COLUMNS missing OWNED cols: {missing}"
    # Explicit C02 columns that previously broke second-turn Feishu history loads.
    for col in (
        "owner_provider_name",
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
    ):
        assert col in conv
