"""Tests for Feishu compression summary card dispatch."""

from __future__ import annotations

import asyncio
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch


class TestFeishuCompressionSummaryCard(unittest.TestCase):
    @patch.dict(os.environ, {}, clear=True)
    def test_send_uses_interactive_card_for_compression_summary(self):
        from gateway.config import PlatformConfig
        from gateway.platforms.feishu import FeishuAdapter, SendResult

        adapter = FeishuAdapter(PlatformConfig())
        adapter._client = SimpleNamespace()  # satisfy send() connection check
        captured_card = {}

        async def _fake_send_card(self, chat_id, card, metadata=None):
            captured_card["chat_id"] = chat_id
            captured_card["card"] = card
            return SendResult(success=True, message_id="om_compact")

        async def _direct(func, *args, **kwargs):
            return func(*args, **kwargs)

        content = (
            "🗜️ 上下文已压缩：32 → 8 条消息（缩短 75%）\n\n"
            "任务：重构 auth 模块\n\n"
            "进度：\n• 读取 config.py\n• 修改 jwt 逻辑"
        )

        with patch("gateway.platforms.feishu.asyncio.to_thread", side_effect=_direct), \
             patch.object(FeishuAdapter, "send_card", _fake_send_card):
            result = asyncio.run(
                adapter.send(
                    chat_id="oc_chat",
                    content=content,
                )
            )

        self.assertTrue(result.success)
        self.assertEqual(result.message_id, "om_compact")

        payload = captured_card["card"]
        self.assertEqual(payload["schema"], "2.0")
        self.assertEqual(payload["header"]["template"], "blue")
        self.assertIn("32 → 8", payload["header"]["title"]["content"])
        self.assertEqual(len(payload["body"]["elements"]), 1)
        self.assertEqual(payload["body"]["elements"][0]["tag"], "markdown")
        self.assertIn("任务：重构 auth 模块", payload["body"]["elements"][0]["content"])

    @patch.dict(os.environ, {}, clear=True)
    def test_send_falls_through_for_non_compression_text(self):
        from gateway.config import PlatformConfig
        from gateway.platforms.feishu import FeishuAdapter

        adapter = FeishuAdapter(PlatformConfig())
        captured = {}

        class _MessageAPI:
            def create(self, request):
                captured["request"] = request
                return SimpleNamespace(
                    success=lambda: True,
                    data=SimpleNamespace(message_id="om_post"),
                )

        adapter._client = SimpleNamespace(
            im=SimpleNamespace(
                v1=SimpleNamespace(
                    message=_MessageAPI(),
                )
            )
        )

        async def _direct(func, *args, **kwargs):
            return func(*args, **kwargs)

        # Auto-card is not relevant for this test; make it fall through.
        from gateway.platforms import feishu as _feishu_module

        _feishu_module._owner_lazy.pop("owner.feishu.auto_card.try_auto_card", None)

        async def _fake_try_auto_card(*args, **kwargs):
            return None

        def _fake_owner_import(module: str, name: str):
            if module == "owner.feishu.auto_card" and name == "try_auto_card":
                return _fake_try_auto_card
            return None

        with patch("gateway.platforms.feishu.asyncio.to_thread", side_effect=_direct), \
             patch.object(_feishu_module, "_owner_import", _fake_owner_import):
            result = asyncio.run(
                adapter.send(
                    chat_id="oc_chat",
                    content="你好，这是普通回复。",
                )
            )

        self.assertTrue(result.success)
        self.assertEqual(result.message_id, "om_post")
        self.assertIn(captured["request"].request_body.msg_type, ("text", "post"))

    def test_build_compression_summary_card_structure(self):
        from owner.feishu.compression_summary_card import build_compression_summary_card

        content = (
            "🗜️ 上下文已压缩：10 → 5 条消息（缩短 50%）\n\n"
            "任务：修复 bug\n\n"
            "进度：\n• 定位问题\n• 应用补丁"
        )
        card = build_compression_summary_card(content)

        self.assertEqual(card["schema"], "2.0")
        self.assertTrue(card["config"]["wide_screen_mode"])
        self.assertEqual(card["header"]["template"], "blue")
        self.assertIn("10 → 5", card["header"]["title"]["content"])
        self.assertEqual(card["body"]["elements"][0]["tag"], "markdown")
        self.assertIn("任务：修复 bug", card["body"]["elements"][0]["content"])

    def test_build_compression_summary_card_preserves_inline_separator(self):
        """The builder must not split a body line on ' · ' — content that
        legitimately contains the separator has to survive verbatim."""
        from owner.feishu.compression_summary_card import build_compression_summary_card

        content = (
            "🗜️ 上下文已压缩：10 → 5 条消息（缩短 50%）\n\n"
            "**任务**：迁移 a · b 模块"
        )
        card = build_compression_summary_card(content)
        body = card["body"]["elements"][0]["content"]
        self.assertIn("迁移 a · b 模块", body)
        # The separator inside the task must NOT have become a line break.
        self.assertNotIn("迁移 a\nb 模块", body)

    def test_build_compression_summary_card_body_only_header_when_no_body(self):
        from owner.feishu.compression_summary_card import build_compression_summary_card

        card = build_compression_summary_card("🗜️ 上下文已压缩：10 → 5 条消息")
        self.assertNotIn("body", card)
        self.assertIn("10 → 5", card["header"]["title"]["content"])


if __name__ == "__main__":
    unittest.main()
