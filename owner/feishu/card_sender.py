"""Feishu card sending via REST API (bypassing lark_oapi SDK).

Core implementation lives here per 二次开发规范:
- P1 import 编排：官方代码只做薄薄的代理 + import + 调用
- 所有真实逻辑放在 owner/ 下，便于独立演进和回滚
- 便于未来从上游 pull 时冲突最小化

This module is private customization for the fork.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from gateway.platforms.feishu import FeishuAdapter

from gateway.platforms.base import SendResult

logger = logging.getLogger(__name__)


async def send_card_via_rest(
    adapter: "FeishuAdapter",
    chat_id: str,
    card: Dict[str, Any],
    metadata: Optional[Dict[str, Any]] = None,
) -> SendResult:
    """Send an interactive card using direct Feishu REST API.

    Acquires its own tenant_access_token (never re-uses the WebSocket
    client's token) so that card sends cannot invalidate or interfere
    with the long-lived connection.

    The card dict must follow Feishu's interactive card schema.
    """
    try:
        import requests as _requests
    except ImportError:
        return SendResult(success=False, error="requests library not available")

    base_url = "https://open.feishu.cn/open-apis"

    # Own token acquisition — independent of adapter's _client/WebSocket.
    try:
        token_resp = _requests.post(
            f"{base_url}/auth/v3/tenant_access_token/internal",
            json={"app_id": adapter._app_id, "app_secret": adapter._app_secret},
            timeout=10,
        )
        token_data = token_resp.json()
        access_token = token_data.get("tenant_access_token", "")
        if not access_token:
            return SendResult(
                success=False,
                error=f"Failed to get Feishu token: {token_data.get('msg', 'unknown')}",
            )
    except Exception as exc:
        return SendResult(success=False, error=f"Feishu token request failed: {exc}")

    # Determine receive_id_type from chat_id pattern.
    if chat_id.startswith("ou_"):
        receive_id_type = "open_id"
    else:
        receive_id_type = "chat_id"

    # Send card via REST API (bypasses lark_oapi SDK entirely).
    try:
        payload = json.dumps(card, ensure_ascii=False)
        send_resp = _requests.post(
            f"{base_url}/im/v1/messages?receive_id_type={receive_id_type}",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={"receive_id": chat_id, "msg_type": "interactive", "content": payload},
            timeout=15,
        )
        send_data = send_resp.json()
        code = send_data.get("code", -1)
        if code != 0:
            logger.warning(
                "[Feishu] send_card failed (code %d): %s",
                code, send_data.get("msg", "unknown"),
            )
            return SendResult(
                success=False,
                error=f"Feishu API error (code {code}): {send_data.get('msg', 'unknown')}",
            )
        message_id = ""
        msg_data = send_data.get("data", {})
        if isinstance(msg_data, dict):
            message_id = str(msg_data.get("message_id", ""))
        return SendResult(success=True, message_id=message_id)
    except Exception as exc:
        logger.warning("[Feishu] send_card exception: %s", exc)
        return SendResult(success=False, error=f"Feishu card send failed: {exc}")
