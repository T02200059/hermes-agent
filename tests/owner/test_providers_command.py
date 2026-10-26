"""C26: /providers slash command (text path + plugin registration)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_providers_text_lists_rows():
    from owner.commands.providers import handle_providers_command

    rows = [
        {
            "slug": "damodel",
            "name": "Damodel",
            "models": ["glm-5.1", "glm-5.2"],
            "total_models": 2,
        },
        {
            "slug": "openrouter",
            "name": "OpenRouter",
            "models": ["m1"],
            "total_models": 10,
        },
    ]
    with patch(
        "owner.commands.providers._load_provider_rows", return_value=rows
    ):
        out = await handle_providers_command("", source=SimpleNamespace(platform=None))

    assert out is not None
    assert "共 2 个" in out
    assert "damodel" in out
    assert "glm-5.1" in out
    assert "共 10 个模型" in out


@pytest.mark.asyncio
async def test_providers_empty():
    from owner.commands.providers import handle_providers_command

    with patch("owner.commands.providers._load_provider_rows", return_value=[]):
        out = await handle_providers_command("")
    assert out == "当前没有已配置的 provider（未设置任何 API Key）"


@pytest.mark.asyncio
async def test_providers_load_failed():
    from owner.commands.providers import handle_providers_command

    with patch(
        "owner.commands.providers._load_provider_rows",
        side_effect=RuntimeError("boom"),
    ):
        out = await handle_providers_command("")
    assert "无法读取" in out


@pytest.mark.asyncio
async def test_providers_feishu_card_when_adapter_supports():
    from gateway.config import Platform
    from owner.commands.providers import handle_providers_command

    rows = [{"slug": "damodel", "name": "Damodel", "models": ["m"], "total_models": 1}]
    adapter = MagicMock()
    adapter.send_model_picker_card = AsyncMock()
    source = SimpleNamespace(platform=Platform.FEISHU, chat_id="oc_x")
    with patch("owner.commands.providers._load_provider_rows", return_value=rows):
        out = await handle_providers_command(
            "",
            source=source,
            adapters={Platform.FEISHU: adapter},
        )
    assert out is None
    adapter.send_model_picker_card.assert_awaited_once()


def test_owner_extensions_registers_providers_command():
    init = Path(__file__).resolve().parents[2] / "owner" / "owner-extensions" / "__init__.py"
    spec = importlib.util.spec_from_file_location("owner_extensions_plugin", init)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)

    registered = {}

    class Ctx:
        def register_command(self, name, handler, description=""):
            registered[name] = (handler, description)

    mod.register(Ctx())
    assert "providers" in registered
    assert registered["providers"][0].__name__ == "handle_providers_command"
