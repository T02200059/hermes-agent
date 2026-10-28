"""C05: FeishuAdapter connection_mode=send_only — outbound client, no WS lock."""

from __future__ import annotations

import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from gateway.config import PlatformConfig
from plugins.platforms.feishu.adapter import FeishuAdapter


class TestFeishuSendOnlyConnect(unittest.TestCase):
    """Sub-profile gateways share Hub's app_id; send_only must not steal the WS lock."""

    @patch.dict(os.environ, {}, clear=True)
    def test_send_only_connects_without_acquiring_app_lock(self):
        adapter = FeishuAdapter(
            PlatformConfig(
                enabled=True,
                extra={
                    "app_id": "cli_shared",
                    "app_secret": "secret_shared",
                    "connection_mode": "send_only",
                },
            )
        )
        fake_client = SimpleNamespace()
        lock = MagicMock(return_value=(True, None))

        with (
            patch("plugins.platforms.feishu.adapter.FEISHU_AVAILABLE", True),
            patch(
                "plugins.platforms.feishu.adapter._load_lark_oapi",
                return_value=True,
            ),
            patch(
                "plugins.platforms.feishu.adapter.acquire_scoped_lock",
                lock,
            ),
            patch.object(adapter, "_hydrate_bot_identity", new=AsyncMock()),
            patch.object(adapter, "_build_lark_client", return_value=fake_client) as build,
            patch.object(adapter, "_mark_connected") as mark,
        ):
            connected = asyncio.run(adapter.connect())

        self.assertTrue(connected)
        lock.assert_not_called()
        build.assert_called_once()
        mark.assert_called_once()
        self.assertIs(adapter._client, fake_client)
        self.assertIsNone(getattr(adapter, "_ws_supervisor", None))

    @patch.dict(os.environ, {}, clear=True)
    def test_unsupported_mode_still_rejected(self):
        adapter = FeishuAdapter(
            PlatformConfig(
                enabled=True,
                extra={
                    "app_id": "cli_x",
                    "app_secret": "secret_x",
                    "connection_mode": "not_a_mode",
                },
            )
        )
        self.assertFalse(asyncio.run(adapter.connect()))


if __name__ == "__main__":
    unittest.main()
