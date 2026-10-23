"""C01: attribution skeleton — bind + inject + messages column."""

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
    assert _INSERT_MESSAGE_SQL.count("?") == 28


def test_message_row_params_stamps_assistant_only():
    import inspect
    from hermes_state_messages import SessionMessagesMixin

    mixin = SessionMessagesMixin.__dict__.get("_message_row_params")
    assert mixin is not None
    src = inspect.getsource(mixin)
    assert 'msg.get("owner_provider_name") if role == "assistant" else None' in src
