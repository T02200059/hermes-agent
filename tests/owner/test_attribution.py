"""C01/C02: attribution — bind + inject + strip + messages/sessions usage cols."""

from __future__ import annotations

from types import SimpleNamespace

import pytest


def test_bind_explicit_wins():
    from owner.attribution import bind_agent_attribution, get_current_attribution

    agent = SimpleNamespace(provider="openai", owner_provider_name=None)
    bind_agent_attribution(agent, "Xfyun-Custom")
    assert agent.owner_provider_name == "xfyun-custom"
    assert get_current_attribution(agent) == "xfyun-custom"


def test_bind_falls_back_to_provider():
    from owner.attribution import bind_agent_attribution

    agent = SimpleNamespace(provider="DeepSeek", owner_provider_name=None)
    bind_agent_attribution(agent, None)
    assert agent.owner_provider_name == "deepseek"


def test_bind_keeps_existing_when_arg_none():
    from owner.attribution import bind_agent_attribution

    agent = SimpleNamespace(provider="openai", owner_provider_name="Damodel")
    bind_agent_attribution(agent, None)
    assert agent.owner_provider_name == "damodel"


def test_inject_stamps_model_provider_and_owner():
    from owner.attribution import bind_agent_attribution, inject_attribution_into_message

    agent = SimpleNamespace(model="deepseek-v4-flash", provider="deepseek", owner_provider_name=None)
    bind_agent_attribution(agent, "xfyun")
    msg: dict = {"role": "assistant", "content": "hi"}
    inject_attribution_into_message(agent, msg)
    assert msg["model"] == "deepseek-v4-flash"
    assert msg["provider"] == "deepseek"
    assert msg["owner_provider_name"] == "xfyun"


def test_inject_never_raises_on_bad_agent():
    from owner.attribution import inject_attribution_into_message

    msg = {"role": "assistant"}
    inject_attribution_into_message(None, msg)  # type: ignore[arg-type]
    assert "owner_provider_name" not in msg


def test_schema_sql_declares_messages_owner_provider_name():
    from hermes_state_common import SCHEMA_SQL

    assert "owner_provider_name TEXT" in SCHEMA_SQL
    # messages table section (before sessions-related later uses)
    messages_idx = SCHEMA_SQL.find("CREATE TABLE IF NOT EXISTS messages (")
    assert messages_idx >= 0
    chunk = SCHEMA_SQL[messages_idx : messages_idx + 1200]
    assert "owner_provider_name TEXT" in chunk


def test_insert_sql_includes_owner_provider_name_placeholder():
    from hermes_state_messages import _INSERT_MESSAGE_SQL

    assert "owner_provider_name" in _INSERT_MESSAGE_SQL
    assert _INSERT_MESSAGE_SQL.count("?") == 32


def test_message_row_params_stamps_assistant_only():
    import inspect
    from hermes_state_messages import SessionMessagesMixin

    mixin = SessionMessagesMixin.__dict__.get("_message_row_params")
    assert mixin is not None
    src = inspect.getsource(mixin)
    assert 'msg.get("owner_provider_name") if role == "assistant" else None' in src



def test_persistence_only_strips_owner_and_token_cols():
    from agent.message_metadata import PERSISTENCE_ONLY_MESSAGE_FIELDS, without_persistence_fields

    for key in (
        "owner_provider_name",
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
    ):
        assert key in PERSISTENCE_ONLY_MESSAGE_FIELDS

    msg = {
        "role": "assistant",
        "content": "hi",
        "owner_provider_name": "damodel",
        "input_tokens": 10,
        "output_tokens": 2,
        "cache_read_tokens": 1,
        "cache_write_tokens": 0,
        "model": "x",
    }
    cleaned = without_persistence_fields(msg)
    assert "owner_provider_name" not in cleaned
    assert "input_tokens" not in cleaned
    assert cleaned["content"] == "hi"
    assert cleaned["model"] == "x"
    # original untouched
    assert msg["owner_provider_name"] == "damodel"


def test_schema_sql_declares_sessions_owner_and_message_token_cols():
    from hermes_state_common import SCHEMA_SQL

    sessions_idx = SCHEMA_SQL.find("CREATE TABLE IF NOT EXISTS sessions (")
    assert sessions_idx >= 0
    sessions_chunk = SCHEMA_SQL[sessions_idx : sessions_idx + 2500]
    assert "owner_provider_name TEXT" in sessions_chunk

    messages_idx = SCHEMA_SQL.find("CREATE TABLE IF NOT EXISTS messages (")
    assert messages_idx >= 0
    messages_chunk = SCHEMA_SQL[messages_idx : messages_idx + 2000]
    for col in (
        "input_tokens INTEGER DEFAULT 0",
        "output_tokens INTEGER DEFAULT 0",
        "cache_read_tokens INTEGER DEFAULT 0",
        "cache_write_tokens INTEGER DEFAULT 0",
    ):
        assert col in messages_chunk


def test_insert_sql_includes_message_token_columns():
    from hermes_state_messages import _INSERT_MESSAGE_SQL

    for col in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens"):
        assert col in _INSERT_MESSAGE_SQL


def test_token_update_sql_coalesces_owner_provider_name():
    from hermes_state_usage import _TOKEN_UPDATE_DELTA_SQL, _TOKEN_UPDATE_ABSOLUTE_SQL

    needle = "owner_provider_name = COALESCE(?, owner_provider_name)"
    assert needle in _TOKEN_UPDATE_DELTA_SQL
    assert needle in _TOKEN_UPDATE_ABSOLUTE_SQL
