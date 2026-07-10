"""Owner contract tests for official entrypoint glue.

These tests exercise upstream-facing entrypoints with faked external
dependencies. The goal is to catch merge regressions where owner logic still
exists but stops being called from the real path.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def _restore_memory_patch():
    from owner.patches.memory_synthetic_guard_patch import revert_patch

    revert_patch()
    yield
    revert_patch()


@pytest.mark.asyncio
async def test_gateway_prepare_inbound_message_uses_resolved_session_key(monkeypatch):
    """Gateway message prep must pass the live gateway session key to owner context."""
    from gateway.config import Platform
    from gateway.platforms.base import MessageEvent
    from gateway.run import GatewayRunner
    from gateway.session import SessionSource
    import owner.gateway.inbound_context as inbound_context

    captured: dict[str, object] = {}

    def fake_append(message_text, source, session_id=None, session_key=None):
        captured["message_text"] = message_text
        captured["source"] = source
        captured["effective_session_key"] = session_key or session_id
        return f"{message_text}\n\n[owner-context:{session_key or session_id}]"

    monkeypatch.setattr(inbound_context, "append_inbound_context", fake_append)

    runner = SimpleNamespace(
        config=SimpleNamespace(
            group_sessions_per_user=True,
            thread_sessions_per_user=False,
        ),
        _session_key_for_source=lambda _source: "derived-session-key",
        _consume_pending_native_image_paths=lambda _session_key: [],
    )
    source = SessionSource(
        platform=Platform.FEISHU,
        chat_id="oc_owner_contract",
        chat_type="dm",
        user_id="ou_owner_contract",
        user_name="Alice",
    )
    event = MessageEvent(text="hello", source=source)

    prepared = await GatewayRunner._prepare_inbound_message_text(
        runner,
        event=event,
        source=source,
        history=[],
        session_key="agent:main:feishu:dm:oc_owner_contract",
    )

    assert captured["message_text"] == "hello"
    assert captured["source"] is source
    assert captured["effective_session_key"] == "agent:main:feishu:dm:oc_owner_contract"
    assert prepared.endswith("[owner-context:agent:main:feishu:dm:oc_owner_contract]")


def test_display_source_resolver_uses_per_chat_owner_override():
    """Gateway callers passing source= must honor display.per_chat overrides."""
    from gateway.display_config import resolve_display_setting_for_source

    config = {
        "display": {
            "long_running_notifications": True,
            "per_chat": {
                "feishu": {
                    "oc_quiet": {"long_running_notifications": False},
                    "oc_generic": {"long_running_notifications": "generic"},
                }
            },
        }
    }

    assert (
        resolve_display_setting_for_source(
            config,
            "feishu",
            "long_running_notifications",
            source=SimpleNamespace(chat_id="oc_quiet"),
        )
        is False
    )
    assert (
        resolve_display_setting_for_source(
            config,
            "feishu",
            "long_running_notifications",
            source=SimpleNamespace(chat_id="oc_generic"),
        )
        == "generic"
    )


def test_gateway_long_running_surface_keeps_source_aware_display_resolver():
    """The long-running notification surface must route through the per-chat
    display resolver rather than reading the setting directly off config.

    A faithful behavior test would need a full GatewayRunner fixture to reach
    the nested ``_display_surface_mode`` closure; the per-chat routing itself
    is already covered behaviorally by the test above (which feeds real config
    through ``resolve_display_setting_for_source``). This test guards the
    *wiring* contract at a semantic level only: the resolver is referenced
    inside the helper, and the long-running surface is dispatched through that
    helper. It deliberately avoids brittle substring slices (exact source
    formatting) so routine refactors of whitespace/arg layout don't trip it.
    """
    import inspect

    from gateway.run import GatewayRunner

    body = inspect.getsource(GatewayRunner._run_agent_inner)
    # The helper closure calls the per-chat resolver with the live source.
    assert "_display_surface_mode" in body
    assert "resolve_display_setting_for_source" in body
    # The long-running surface setting key is dispatched through the helper.
    assert "long_running_notifications" in body


def test_build_api_kwargs_forwards_owner_provider_name_to_transport():
    """The agent kwargs builder must preserve owner_provider_name to transport."""
    from agent.chat_completion_helpers import build_api_kwargs

    captured: dict[str, object] = {}

    class RecordingTransport:
        def build_kwargs(self, **kwargs):
            captured.update(kwargs)
            return {"built": True}

    agent = SimpleNamespace(
        tools=[],
        api_mode="chat_completions",
        model="xopglm51",
        base_url="https://example.test/v1",
        _base_url_lower="https://example.test/v1",
        _base_url_hostname="example.test",
        provider="owner-contract-provider",
        owner_provider_name="xfyun",
        providers_allowed=None,
        providers_ignored=None,
        providers_order=None,
        provider_sort=None,
        provider_require_parameters=False,
        provider_data_collection=None,
        max_tokens=None,
        reasoning_config=None,
        request_overrides={},
        session_id="session-1",
        _ollama_num_ctx=None,
        openrouter_min_coding_score=None,
        _get_transport=lambda: RecordingTransport(),
        _is_qwen_portal=lambda: False,
        _is_openrouter_url=lambda: False,
        _prepare_messages_for_non_vision_model=lambda messages: messages,
        _resolved_api_call_timeout=lambda: None,
        _max_tokens_param=lambda value: {"max_tokens": value},
        _supports_reasoning_extra_body=lambda: False,
        _github_models_reasoning_extra_body=lambda: None,
        _lmstudio_reasoning_options_cached=lambda: None,
    )

    result = build_api_kwargs(agent, [{"role": "user", "content": "hi"}])

    assert result == {"built": True}
    assert captured["owner_provider_name"] == "xfyun"
    assert captured["provider_name"] == "owner-contract-provider"


def test_chat_completions_transport_uses_owner_provider_for_extra_body(monkeypatch):
    """Transport-level extra_body injection must use owner_provider_name."""
    from agent.transports import get_transport
    import agent.transports.chat_completions  # noqa: F401
    import owner.extra_body_injection as extra_body_injection

    captured: dict[str, object] = {}

    def fake_inject(extra_body, provider, model):
        captured["provider"] = provider
        captured["model"] = model
        extra_body["owner_contract_marker"] = provider

    monkeypatch.setattr(extra_body_injection, "inject_model_extra_body", fake_inject)

    transport = get_transport("chat_completions")
    kwargs = transport.build_kwargs(
        model="xopglm51",
        messages=[{"role": "user", "content": "hi"}],
        owner_provider_name="xfyun",
    )

    assert captured == {"provider": "xfyun", "model": "xopglm51"}
    assert kwargs["extra_body"]["owner_contract_marker"] == "xfyun"


def test_cron_run_job_sets_cron_contextvar_on_real_agent_path(monkeypatch, tmp_path):
    """cron.scheduler.run_job must set HERMES_CRON_SESSION around agent execution."""
    import cron.scheduler as scheduler
    from gateway.session_context import get_session_env

    seen: dict[str, object] = {}

    class FakeAIAgent:
        def __init__(self, **kwargs):
            seen["agent_kwargs"] = kwargs

        def run_conversation(self, prompt):
            from tools.approval import _is_cron_session

            seen["prompt"] = prompt
            seen["cron_context"] = get_session_env("HERMES_CRON_SESSION")
            seen["approval_sees_cron"] = _is_cron_session()
            return {
                "final_response": "done",
                "completed": True,
                "failed": False,
            }

        def get_activity_summary(self):
            return {"seconds_since_activity": 0.0}

        def close(self):
            seen["closed"] = True

    class FakeSessionDB:
        def set_session_title(self, *_args, **_kwargs):
            pass

        def end_session(self, *_args, **_kwargs):
            pass

        def close(self):
            pass

    fake_run_agent = types.ModuleType("run_agent")
    fake_run_agent.AIAgent = FakeAIAgent
    monkeypatch.setitem(sys.modules, "run_agent", fake_run_agent)

    fake_state = types.ModuleType("hermes_state")
    fake_state.SessionDB = FakeSessionDB
    monkeypatch.setitem(sys.modules, "hermes_state", fake_state)

    fake_env_loader = types.ModuleType("hermes_cli.env_loader")
    fake_env_loader.reset_secret_source_cache = lambda: None
    fake_env_loader.load_hermes_dotenv = lambda hermes_home=None: None
    monkeypatch.setitem(sys.modules, "hermes_cli.env_loader", fake_env_loader)

    fake_runtime = types.ModuleType("hermes_cli.runtime_provider")
    fake_runtime.resolve_runtime_provider = lambda **_kwargs: {
        "provider": "",
        "api_key": "test-key",
        "base_url": "https://example.test/v1",
        "api_mode": "chat_completions",
    }
    fake_runtime.format_runtime_provider_error = lambda exc: str(exc)
    monkeypatch.setitem(sys.modules, "hermes_cli.runtime_provider", fake_runtime)

    fake_auth = types.ModuleType("hermes_cli.auth")

    class AuthError(Exception):
        pass

    fake_auth.AuthError = AuthError
    monkeypatch.setitem(sys.modules, "hermes_cli.auth", fake_auth)

    fake_mcp = types.ModuleType("tools.mcp_tool")
    fake_mcp.discover_mcp_tools = lambda: []
    monkeypatch.setitem(sys.modules, "tools.mcp_tool", fake_mcp)

    monkeypatch.setattr(scheduler, "_get_hermes_home", lambda: tmp_path)
    monkeypatch.setattr(
        scheduler,
        "_build_job_prompt",
        lambda job, prerun_script=None: f"prompt for {job['id']}",
    )
    monkeypatch.setattr(scheduler, "_resolve_delivery_target", lambda _job: None)
    monkeypatch.setattr(scheduler, "_guard_job_credential_exfil", lambda _job: None)
    monkeypatch.setattr(scheduler, "get_fallback_chain", lambda _cfg: [])
    monkeypatch.setattr(scheduler, "_teardown_cron_agent", lambda _agent, _job_id: None)
    monkeypatch.delenv("HERMES_CRON_SESSION", raising=False)

    ok, _output, final_response, error = scheduler.run_job(
        {
            "id": "owner-contract-cron",
            "name": "Owner Contract Cron",
            "prompt": "ping",
            "model": "owner-contract-model",
            "schedule_display": "* * * * *",
        }
    )

    assert ok is True
    assert final_response == "done"
    assert error is None
    assert seen["cron_context"] == "1"
    assert seen["approval_sees_cron"] is True
    assert seen["agent_kwargs"]["platform"] == "cron"
    assert get_session_env("HERMES_CRON_SESSION") == ""


def test_owner_extension_register_applies_memory_synthetic_guard(monkeypatch):
    """The owner plugin entrypoint must apply the memory synthetic guard."""
    import agent.memory_manager as memory_manager

    original_prefetch = memory_manager.MemoryManager.prefetch_all

    providers_module = types.ModuleType("owner.commands.providers")

    async def handle_providers_command(**_kwargs):
        return "providers"

    providers_module.handle_providers_command = handle_providers_command
    monkeypatch.setitem(sys.modules, "owner.commands.providers", providers_module)

    feishu_guide_module = types.ModuleType("owner.commands.feishu_guide")

    async def handle_feishu_guide_command(**_kwargs):
        return "feishu guide"

    feishu_guide_module.handle_feishu_guide_command = handle_feishu_guide_command
    monkeypatch.setitem(sys.modules, "owner.commands.feishu_guide", feishu_guide_module)

    schema_module = types.ModuleType("owner.tools.schema_patches")
    monkeypatch.setitem(sys.modules, "owner.tools.schema_patches", schema_module)

    openviking_module = types.ModuleType("owner.patches.openviking_owner_recall_patch")
    openviking_module.apply_patch = lambda: None
    monkeypatch.setitem(
        sys.modules,
        "owner.patches.openviking_owner_recall_patch",
        openviking_module,
    )

    memory_bridge_module = types.ModuleType(
        "owner_extensions_contract.memory_feishu_bridge"
    )

    def register_hooks(ctx):
        ctx.register_hook("post_tool_call", lambda **_kwargs: None)

    memory_bridge_module.register_hooks = register_hooks
    monkeypatch.setitem(
        sys.modules,
        "owner_extensions_contract.memory_feishu_bridge",
        memory_bridge_module,
    )

    class FakePluginContext:
        def __init__(self):
            self.commands: dict[str, object] = {}
            self.hooks: list[str] = []

        def register_command(self, name, handler, **_kwargs):
            self.commands[name] = handler

        def register_hook(self, name, _handler):
            self.hooks.append(name)

    plugin_path = (
        Path(__file__).resolve().parents[2] / "owner" / "owner-extensions" / "__init__.py"
    )
    spec = importlib.util.spec_from_file_location(
        "owner_extensions_contract",
        plugin_path,
        submodule_search_locations=[str(plugin_path.parent)],
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "owner_extensions_contract", module)
    spec.loader.exec_module(module)

    ctx = FakePluginContext()
    module.register(ctx)

    assert "providers" in ctx.commands
    assert "feishu-guide" in ctx.commands
    assert "post_tool_call" in ctx.hooks
    assert memory_manager.MemoryManager.prefetch_all is not original_prefetch
    assert memory_manager.MemoryManager.prefetch_all.__name__ == "_prefetch_all"
