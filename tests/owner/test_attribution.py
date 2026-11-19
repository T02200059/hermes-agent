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
        "model",
        "provider",
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
        "provider": "damodel",
    }
    cleaned = without_persistence_fields(msg)
    assert "owner_provider_name" not in cleaned
    assert "input_tokens" not in cleaned
    assert "model" not in cleaned
    assert "provider" not in cleaned
    assert cleaned["content"] == "hi"
    # original untouched
    assert msg["owner_provider_name"] == "damodel"
    assert msg["model"] == "x"
    assert msg["provider"] == "damodel"


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


def test_bind_strips_custom_colon_slug():
    """Mid-switch passes wire id custom:<slug>; attribution wants the slug."""
    from owner.attribution import bind_agent_attribution

    agent = SimpleNamespace(provider="custom", owner_provider_name=None)
    bind_agent_attribution(agent, "custom:xfyun")
    assert agent.owner_provider_name == "xfyun"


def test_bind_keeps_bare_custom():
    from owner.attribution import bind_agent_attribution

    agent = SimpleNamespace(provider="custom", owner_provider_name=None)
    bind_agent_attribution(agent, "custom")
    assert agent.owner_provider_name == "custom"


def test_bind_strips_custom_colon_from_provider_fallback():
    from owner.attribution import bind_agent_attribution

    agent = SimpleNamespace(provider="custom:Damodel", owner_provider_name=None)
    bind_agent_attribution(agent, None)
    assert agent.owner_provider_name == "damodel"


# ── C02: switch_model mid-switch attribution (named-custom alias survives) ────────────────


def _switch_agent(provider: str, model: str):
    """Bare MagicMock agent with the attributes agent.switch_model touches
    (mirrors tests/agent/test_switch_model_pool_reload.py)."""
    from unittest.mock import MagicMock

    agent = MagicMock(name=f"Agent[{provider}]")
    agent.provider = provider
    agent.model = model
    agent.base_url = f"https://{provider}.example/v1"
    agent.api_key = f"{provider}-key"
    agent.api_mode = "chat_completions"
    agent._client_kwargs = {"api_key": "***", "base_url": agent.base_url}
    agent._config_context_length = None
    agent._transport_cache = {}
    agent._cached_system_prompt = "cached"
    agent.context_compressor = None
    agent._use_prompt_caching = False
    agent._use_native_cache_layout = False
    agent._primary_runtime = {}
    agent._fallback_activated = False
    agent._fallback_index = 0
    agent._fallback_chain = []
    agent._fallback_model = None
    agent._credential_pool = None
    agent._session_db = None
    agent._anthropic_prompt_cache_policy = MagicMock(return_value=(False, False))
    return agent


def _run_switch(agent, **overrides):
    from unittest.mock import patch
    from agent.agent_runtime_helpers import switch_model

    fields = dict(new_model="deepseek-v4-flash", new_provider="custom",
                  api_key="k", base_url="https://token.xfyun.cn/v1",
                  api_mode="chat_completions")
    fields.update(overrides)
    with patch("agent.credential_pool.load_pool", return_value=None), \
         patch("agent.agent_runtime_helpers._resolve_switch_context_length", return_value=(None, None)):
        switch_model(agent, **fields)


def test_switch_model_bare_custom_wire_name_recovers_named_alias(monkeypatch, tmp_path):
    """C02: /model mid-switch handed the agent the bare WIRE name "custom" — the same
    canonical_custom_identity lookup every persistence/restore path shares must recover
    custom:<name>, and bind strips the prefix, so attribution keeps the alias."""
    from unittest.mock import patch

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    agent = _switch_agent("openrouter", "anthropic/claude-sonnet-4")
    with patch("hermes_cli.runtime_provider_custom.canonical_custom_identity",
               return_value="custom:xfyun") as recover:
        _run_switch(agent, base_url="https://token.xfyun.cn/v1")
    assert agent.owner_provider_name == "xfyun"
    recover.assert_called_once()
    assert recover.call_args.kwargs.get("base_url") == "https://token.xfyun.cn/v1"


def test_switch_model_bare_custom_without_identity_keeps_wire_name(monkeypatch, tmp_path):
    """A genuinely bare custom endpoint (no named entry) keeps the wire attribution."""
    from unittest.mock import patch

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    agent = _switch_agent("openrouter", "anthropic/claude-sonnet-4")
    with patch("hermes_cli.runtime_provider_custom.canonical_custom_identity", return_value=None):
        _run_switch(agent)
    assert agent.owner_provider_name == "custom"


def test_switch_model_prefixed_custom_slug_binds_without_recovery(monkeypatch, tmp_path):
    """A caller that already passes custom:<slug> (the designed mid-switch wire id) binds
    directly; the recovery lookup must not even run."""
    from unittest.mock import patch

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    agent = _switch_agent("openrouter", "anthropic/claude-sonnet-4")
    with patch("hermes_cli.runtime_provider_custom.canonical_custom_identity",
               side_effect=AssertionError("recovery must not run for custom:<slug>")):
        _run_switch(agent, new_provider="custom:sensenova")
    assert agent.owner_provider_name == "sensenova"


def test_switch_model_non_custom_provider_skips_recovery(monkeypatch, tmp_path):
    from unittest.mock import patch

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    agent = _switch_agent("openrouter", "anthropic/claude-sonnet-4")
    with patch("hermes_cli.runtime_provider_custom.canonical_custom_identity",
               side_effect=AssertionError("recovery is custom-only")):
        _run_switch(agent, new_provider="groq", base_url="https://api.groq.com/openai/v1")
    assert agent.owner_provider_name == "groq"


def test_switch_model_recovers_alias_from_real_config_entry(monkeypatch, tmp_path):
    """End-to-end: switching to a named custom_providers entry's endpoint (wire provider
    "custom") attributes the configured alias, not "custom"."""
    home = tmp_path / "hermes-home"
    home.mkdir()
    (home / "config.yaml").write_text(
        "custom_providers:\n"
        "  - name: Xfyun\n"
        "    base_url: https://token.xfyun.cn/v1\n"
        "    model: deepseek-v4-flash\n",
        encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(home))
    agent = _switch_agent("openrouter", "anthropic/claude-sonnet-4")
    _run_switch(agent, base_url="https://token.xfyun.cn/v1")
    assert agent.owner_provider_name == "xfyun"

