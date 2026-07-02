from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from gateway.config import Platform
from owner.commands import providers


class _Adapters(dict):
    pass


def _source(platform=Platform.TELEGRAM):
    return SimpleNamespace(platform=platform, chat_id="chat-1")


def _event(platform=Platform.TELEGRAM):
    return SimpleNamespace(source=_source(platform))


@pytest.mark.asyncio
async def test_feishu_sends_model_picker_card(monkeypatch):
    rows = [{"slug": "openrouter", "name": "OpenRouter", "models": ["m"], "total_models": 1}]
    monkeypatch.setattr(providers, "_load_provider_rows", lambda: rows)
    adapter = SimpleNamespace(send_model_picker_card=AsyncMock())

    result = await providers.handle_providers_command(
        adapters=_Adapters({Platform.FEISHU: adapter}),
        event=_event(Platform.FEISHU),
    )

    assert result is None
    adapter.send_model_picker_card.assert_awaited_once()
    kwargs = adapter.send_model_picker_card.await_args.kwargs
    assert kwargs["chat_id"] == "chat-1"
    assert kwargs["providers"] == rows
    assert kwargs["source"].platform == Platform.FEISHU


@pytest.mark.asyncio
async def test_feishu_card_failure_falls_back_to_text(monkeypatch):
    rows = [{"slug": "openrouter", "name": "OpenRouter", "models": ["m"], "total_models": 1}]
    monkeypatch.setattr(providers, "_load_provider_rows", lambda: rows)
    adapter = SimpleNamespace(send_model_picker_card=AsyncMock(side_effect=RuntimeError("boom")))

    result = await providers.handle_providers_command(
        adapters=_Adapters({Platform.FEISHU: adapter}),
        event=_event(Platform.FEISHU),
    )

    assert result is not None
    assert "已配置 provider" in result
    assert "openrouter" in result


@pytest.mark.asyncio
async def test_non_feishu_returns_text(monkeypatch):
    monkeypatch.setattr(
        providers,
        "_load_provider_rows",
        lambda: [{"slug": "deepseek", "name": "DeepSeek", "models": [], "total_models": 0}],
    )

    result = await providers.handle_providers_command(
        adapters=_Adapters(),
        event=_event(Platform.TELEGRAM),
    )

    assert result is not None
    assert "deepseek" in result


@pytest.mark.asyncio
async def test_no_providers_text(monkeypatch):
    monkeypatch.setattr(providers, "_load_provider_rows", lambda: [])

    result = await providers.handle_providers_command(
        adapters=_Adapters(),
        event=_event(Platform.TELEGRAM),
    )

    assert result == "当前没有已配置的 provider（未设置任何 API Key）"


@pytest.mark.asyncio
async def test_load_failure_text(monkeypatch):
    def _raise():
        raise RuntimeError("boom")

    monkeypatch.setattr(providers, "_load_provider_rows", _raise)

    result = await providers.handle_providers_command(
        adapters=_Adapters(),
        event=_event(Platform.TELEGRAM),
    )

    assert result == "⚠️ 无法读取 provider 列表"
