"""Feishu interactive card send helpers (C11 base).

Core lives here per 二次开发规范: adapter only does thin import + call.
Profile tagging (C05) is fail-open and only active in send_only mode.
Includes REST bypass (``send_card_via_rest``) for freeze/notify paths that
must not touch the WebSocket client's token (queue status card lifecycle).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from plugins.platforms.feishu.adapter import FeishuAdapter

from gateway.platforms.base import SendResult

logger = logging.getLogger(__name__)


def _resolve_receive_target(chat_id: str, metadata: Optional[dict[str, Any]] = None) -> tuple[str, str]:
    """Resolve (receive_id, receive_id_type) for Feishu im/v1/messages.

    DM (p2p) paths require open_id + receive_id_type=open_id; group/thread
    always use chat_id. Driven off explicit chat_type (not prefix heuristics).
    """
    raw_chat_type = (metadata or {}).get("chat_type", "") or ""
    is_dm = raw_chat_type.strip().lower() in ("p2p", "dm")

    if is_dm:
        open_id = (metadata or {}).get("open_id") or (metadata or {}).get("sender_open_id")
        if open_id:
            return open_id, "open_id"
        logger.warning(
            "DM metadata missing open_id; falling back to chat_id (will likely 230001). "
            "chat_id=%r metadata_keys=%s",
            chat_id, sorted((metadata or {}).keys()),
        )
        return chat_id, "chat_id"

    return chat_id, "chat_id"



def _inject_profile_tag(node: Any, profile_tag: str) -> None:
    """Recursively set ``hermes_profile`` on interactive button values (C05 prep)."""
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


def _maybe_tag_card_profile(adapter: FeishuAdapter, card: dict[str, Any]) -> None:
    """Tag buttons with this container's profile when connection_mode is send_only.

    Source of truth is ``container_profile_identity()`` (same as T2-9 inbound
    ownership) — ``HERMES_PROFILE`` / ``user_routing.container_profile``.
    Do **not** use ``get_active_profile_name()``: under the Docker target layout
    ``HERMES_HOME=/root/.hermes`` that helper returns ``"default"`` and cards
    would ship untagged, breaking Hub card-action routing.

    Fail-open on unexpected errors (card left untagged). Non-send_only is a
    no-op. send_only with no resolvable identity logs a WARNING once-ish.
    """
    try:
        if getattr(adapter, "_connection_mode", "") != "send_only":
            return
        from owner.feishu.profile_routing import container_profile_identity

        profile_tag = container_profile_identity()
        if profile_tag and profile_tag not in ("default", "custom"):
            _inject_profile_tag(card, profile_tag)
            return
        logger.warning(
            "[Feishu] send_only card not tagged with hermes_profile "
            "(set HERMES_PROFILE or user_routing.container_profile); "
            "Hub card-action routing will treat clicks as local"
        )
    except Exception:
        logger.debug("[Feishu] hermes_profile tag injection skipped", exc_info=True)



async def send_card_via_rest(
    adapter: FeishuAdapter,
    chat_id: str,
    card: dict[str, Any],
    metadata: Optional[dict[str, Any]] = None,
) -> SendResult:
    """Send an interactive card using direct Feishu REST API.

    Acquires its own tenant_access_token (never re-uses the WebSocket
    client's token) so that card sends cannot invalidate or interfere
    with the long-lived connection. Used by queue freeze/notify paths
    that run on a daemon thread via ``asyncio.run``.
    """
    try:
        logger.debug("[Feishu] send_card_via_rest called: chat_id=%s", chat_id)
        import requests as _requests
    except ImportError:
        return SendResult(success=False, error="requests library not available")

    _maybe_tag_card_profile(adapter, card)

    base_url = "https://open.feishu.cn/open-apis"

    try:
        token_resp = _requests.post(  # noqa: ASYNC210 — sync REST avoids WS token refresh
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

    receive_id, receive_id_type = _resolve_receive_target(chat_id, metadata)

    try:
        payload = json.dumps(card, ensure_ascii=False)
        send_resp = _requests.post(  # noqa: ASYNC210 — sync REST avoids WS token refresh
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


def get_card_send_lock(adapter: FeishuAdapter, chat_id: str) -> asyncio.Lock:
    """Per-chat lock serializing multi-chunk auto-card dispatch.

    Separate from ``_get_chat_lock`` (inbound). Bounded LRU like chat locks.
    Callers use ``FeishuAdapter._get_card_send_lock``; missing method degrades
    to nullcontext in auto_card.
    """
    lock = adapter._card_send_locks.get(chat_id)
    if lock is not None:
        adapter._card_send_locks.move_to_end(chat_id)
        return lock
    if len(adapter._card_send_locks) >= adapter.CHAT_LOCK_MAX_SIZE:
        evicted = False
        for key in list(adapter._card_send_locks):
            if not adapter._card_send_locks[key].locked():
                adapter._card_send_locks.pop(key)
                evicted = True
                break
        if not evicted:
            adapter._card_send_locks.pop(next(iter(adapter._card_send_locks)))
    lock = asyncio.Lock()
    adapter._card_send_locks[chat_id] = lock
    return lock


async def send_card(
    adapter: FeishuAdapter,
    *,
    chat_id: str,
    card: dict[str, Any],
    metadata: Optional[dict[str, Any]] = None,
) -> SendResult:
    """Send a Feishu interactive card via official ``_feishu_send_with_retry``.

    Uses ``_finalize_send_result`` so API-level errors (9499 / 1120004 / …)
    surface as failure and auto-card can retry / fall through to plain text.
    """
    try:
        _maybe_tag_card_profile(adapter, card)
        payload = json.dumps(card, ensure_ascii=False)
        response = await adapter._feishu_send_with_retry(
            chat_id=chat_id,
            msg_type="interactive",
            payload=payload,
            reply_to=None,
            metadata=metadata,
        )
        result = adapter._finalize_send_result(response, "card send failed")
        if result.success:
            logger.info(
                "[Feishu card] send_card OK chat_id=%s message_id=%s",
                chat_id,
                result.message_id or "(none)",
            )
        else:
            logger.warning(
                "[Feishu card] send_card failed chat_id=%s error=%s",
                chat_id,
                result.error,
            )
        return result
    except Exception as exc:
        logger.warning("[Feishu] send_card failed: %s", exc)
        return SendResult(success=False, error=str(exc))
