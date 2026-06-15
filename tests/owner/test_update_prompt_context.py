"""Tests for FeishuUpdatePromptContext state lifecycle."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from owner.feishu.update_prompt import (
    FeishuUpdatePromptContext,
    build_update_prompt_card,
    resolve_update_prompt,
)


class TestFeishuUpdatePromptContext:
    def test_register_and_pop(self):
        ctx = FeishuUpdatePromptContext()
        ctx.register(1, session_key="sess", message_id="msg", chat_id="oc_1")
        assert ctx.get(1)["session_key"] == "sess"
        assert ctx.pop(1)["chat_id"] == "oc_1"
        assert ctx.get(1) is None

    def test_state_property_alias(self):
        ctx = FeishuUpdatePromptContext()
        ctx.register(2, session_key="s", message_id="m", chat_id="c")
        assert 2 in ctx.state


class TestBuildUpdatePromptCard:
    def test_includes_default_hint(self):
        card = build_update_prompt_card(prompt="Continue?", default="y", prompt_id=9)
        content = card["elements"][0]["content"]
        assert "Continue?" in content
        assert "`y`" in content
        actions = card["elements"][1]["actions"]
        assert [a["value"]["hermes_update_prompt_action"] for a in actions] == ["y", "n"]


class TestResolveUpdatePrompt:
    @pytest.mark.asyncio
    async def test_writes_response_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "owner.feishu.update_prompt.get_hermes_home",
            lambda: tmp_path,
        )
        ctx = FeishuUpdatePromptContext()
        ctx.register(3, session_key="sess", message_id="m", chat_id="oc_1")
        adapter = MagicMock()
        adapter._allow_group_message.return_value = True

        await resolve_update_prompt(ctx, adapter, 3, "y", "User", open_id="ou_x", chat_id="oc_1")

        assert (tmp_path / ".update_response").read_text() == "y"
        assert ctx.get(3) is None