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
    # [owner] 目标分支飞书适配器已重构为插件 plugins/platforms/feishu/adapter.py
    # （源码为单体 gateway/platforms/feishu.py）。类名仍为 FeishuAdapter。
    from plugins.platforms.feishu.adapter import FeishuAdapter

from gateway.platforms.base import SendResult

logger = logging.getLogger(__name__)


def _resolve_receive_target(chat_id: str, metadata: Optional[Dict[str, Any]] = None) -> tuple[str, str]:
    """Resolve (receive_id, receive_id_type) for Feishu im/v1/messages.

    DM (p2p) paths require open_id + receive_id_type=open_id; group/thread
    always use chat_id. We drive off explicit chat_type (not prefix heuristics)
    because:
      - Feishu raw events use chat_type="p2p"
      - Hermes SessionSource._map_chat_type normalizes p2p -> "dm"
      - chat_id for DMs is oc_xxx (not ou_), so startswith("ou_") is wrong.
      - thread_id/om_xxx cases must not be misclassified by prefix.

    When DM but metadata lacks open_id (e.g. some synthetic paths), we fail-open
    to chat_id (with warning) to avoid regressing group-like sends.
    """
    raw_chat_type = (metadata or {}).get("chat_type", "") or ""
    is_dm = raw_chat_type.strip().lower() in ("p2p", "dm")

    if is_dm:
        open_id = (metadata or {}).get("open_id") or (metadata or {}).get("sender_open_id")
        if open_id:
            return open_id, "open_id"
        # fail-open：DM 缺 open_id 时降级回 chat_id + 打 warning
        # 必须带上下文（chat_id + metadata keys），否则线上 230001 复发时无法定位是哪条 synthetic 路径漏注入了 open_id
        logger.warning(
            "DM metadata missing open_id; falling back to chat_id (will likely 230001). "
            "chat_id=%r metadata_keys=%s",
            chat_id, sorted((metadata or {}).keys()),
        )
        return chat_id, "chat_id"

    # group / thread / 其它：保持 chat_id 路径完全不变
    return chat_id, "chat_id"


def _inject_profile_tag(node: Any, profile_tag: str) -> None:
    """Recursively set ``hermes_profile`` on every interactive button's value.

    Feishu nests buttons inside ``action`` / ``column_set`` / ``column`` /
    ``form`` / ``div`` containers, so the whole card structure is walked. Only
    dict button values are tagged (button values in this codebase are always
    dicts); an existing tag is left untouched so the call is idempotent.
    """
    if isinstance(node, dict):
        if node.get("tag") == "button":
            value = node.get("value")
            if isinstance(value, dict):
                value.setdefault("hermes_profile", profile_tag)
        for child in node.values():
            _inject_profile_tag(child, profile_tag)
    elif isinstance(node, list):
        for item in node:
            _inject_profile_tag(item, profile_tag)


def _maybe_tag_card_profile(adapter: "FeishuAdapter", card: Dict[str, Any]) -> None:
    """Tag card buttons with this container's profile name when sub-profile.

    Gated on ``send_only`` connection mode — only sub-profile containers run in
    that mode. The tag is the active profile name, which equals the key under
    ``profile_endpoints`` in ``patch_feishu_profile.yaml`` (e.g. ``hermesxiyun``).
    ``default`` / ``custom`` are skipped: they are not routable profile keys, and
    tagging them would make the main gateway emit a spurious "unknown profile"
    error card. Fail-open: any error leaves the card untagged (legacy behaviour).
    """
    try:
        if getattr(adapter, "_connection_mode", "") != "send_only":
            return
        from hermes_cli.profiles import get_active_profile_name

        profile_tag = get_active_profile_name()
        if profile_tag and profile_tag not in ("default", "custom"):
            _inject_profile_tag(card, profile_tag)
    except Exception:
        logger.debug("[Feishu] hermes_profile tag injection skipped", exc_info=True)


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
        logger.debug("[Feishu] send_card_via_rest called: chat_id=%s", chat_id)
        import requests as _requests
    except ImportError:
        return SendResult(success=False, error="requests library not available")

    # [owner] multi-profile routing: tag every button with this sub-profile's
    # name so the main gateway (which holds the only WebSocket) can route the
    # click back here. Only sub-profile containers run in send_only mode; the
    # main gateway leaves cards untagged and resolves clicks locally.
    _maybe_tag_card_profile(adapter, card)

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
            logger.warning("[Feishu] send_card failed to get token: %s", token_data)
            return SendResult(
                success=False,
                error=f"Failed to get Feishu token: {token_data.get('msg', 'unknown')}",
            )
    except Exception as exc:
        return SendResult(success=False, error=f"Feishu token request failed: {exc}")

    # Determine receive target (id + type) from metadata chat_type.
    # Replaces the previous startswith("ou_") heuristic which was incorrect
    # for DMs (chat_id is oc_xxx; upstream normalizes p2p->dm).
    receive_id, receive_id_type = _resolve_receive_target(chat_id, metadata)

    # Send card via REST API (bypasses lark_oapi SDK entirely).
    try:
        payload = json.dumps(card, ensure_ascii=False)
        send_resp = _requests.post(
            f"{base_url}/im/v1/messages?receive_id_type={receive_id_type}",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={"receive_id": receive_id, "msg_type": "interactive", "content": payload},
            timeout=15,
        )
        send_data = send_resp.json()
        code = send_data.get("code", -1)
        if code != 0:
            logger.warning(
                "[Feishu] send_card API error (code %d): %s",
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
        logger.info(
            "[Feishu card] send_via_rest OK chat_id=%s message_id=%s receive_id_type=%s",
            chat_id,
            message_id or "(none)",
            receive_id_type,
        )
        return SendResult(success=True, message_id=message_id)
    except Exception as exc:
        logger.warning("[Feishu] send_card exception: %s", exc)
        return SendResult(success=False, error=f"Feishu card send failed: {exc}")
