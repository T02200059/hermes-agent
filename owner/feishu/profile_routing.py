"""Feishu multi-profile routing (owner-v16 external-container architecture).

Extracts profile-route resolution and HTTP forwarding out of
``gateway/platforms/feishu.py`` so the core adapter stays a thin dispatcher.

Configuration is read from ``~/.hermes/patch_feishu_profile.yaml``
(``load_patch_feishu_profile_config``) rather than the main ``patch.yaml``.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


def _load_routing_config() -> Dict[str, Any]:
    """Fail-open loader for the ``feishu.user_routing`` section."""
    try:
        from owner.patch_config import load_patch_feishu_profile_config

        cfg = load_patch_feishu_profile_config()
        routing = cfg.get("feishu", {}).get("user_routing", {})
        return routing if isinstance(routing, dict) else {}
    except Exception:
        return {}


def resolve_profile_route(
    chat_id: str,
    open_id: str,
) -> Optional[Tuple[str, str, str]]:
    """Return ``(profile_name, endpoint_url, api_key)`` for an inbound message.

    Resolution priority:
        1. ``whitelist`` open_ids → main gateway (return None)
        2. ``chat_profile_routes`` by chat_id
        3. ``user_profile_routes`` by open_id
        4. ``default_profile``
        5. no route → main gateway (return None)

    If a profile is resolved but has no entry in ``profile_endpoints``,
    a warning is logged and None is returned.
    """
    routing_cfg = _load_routing_config()
    if not routing_cfg:
        return None

    # Defensive: whitelist must be a list-like collection.
    whitelist = routing_cfg.get("whitelist", [])
    if isinstance(whitelist, (list, tuple, set, frozenset)):
        if open_id in whitelist:
            return None
    elif isinstance(whitelist, str):
        if open_id == whitelist:
            return None
    else:
        logger.warning(
            "[Feishu] user_routing.whitelist has invalid type %s; expected list",
            type(whitelist).__name__,
        )

    profile: Optional[str] = None
    chat_routes = routing_cfg.get("chat_profile_routes")
    user_routes = routing_cfg.get("user_profile_routes")
    if chat_id and isinstance(chat_routes, dict) and chat_id in chat_routes:
        profile = chat_routes[chat_id]
    elif open_id and isinstance(user_routes, dict) and open_id in user_routes:
        profile = user_routes[open_id]
    elif routing_cfg.get("default_profile"):
        profile = routing_cfg["default_profile"]

    if not profile:
        return None

    profile = str(profile)

    endpoints = routing_cfg.get("profile_endpoints")
    if not isinstance(endpoints, dict):
        logger.warning(
            "[Feishu] user_routing.profile_endpoints has invalid type %s; expected dict",
            type(endpoints).__name__,
        )
        return None

    endpoint = endpoints.get(profile)
    if not endpoint:
        logger.warning(
            "[Feishu] profile '%s' has no endpoint in profile_endpoints", profile
        )
        return None

    api_key = routing_cfg.get("internal_api_key", "")
    return (profile, str(endpoint), str(api_key))


def resolve_profile_route_by_name(profile_name: str) -> Optional[Tuple[str, str, str]]:
    """Resolve a profile by explicit name (used for card-action routing).

    Returns ``(profile_name, endpoint_url, api_key)`` or None if the profile
    is unknown or endpoints are misconfigured.
    """
    if not profile_name:
        return None
    routing_cfg = _load_routing_config()
    if not routing_cfg:
        return None

    endpoints = routing_cfg.get("profile_endpoints", {})
    if not isinstance(endpoints, dict):
        return None

    endpoint = endpoints.get(profile_name)
    if not endpoint:
        logger.warning(
            "[Feishu] hermes_profile '%s' not found in profile_endpoints",
            profile_name,
        )
        return None

    api_key = routing_cfg.get("internal_api_key", "")
    return (profile_name, str(endpoint), str(api_key))


async def _forward_to_profile_container(
    adapter: Any,
    *,
    endpoint: str,
    api_key: str,
    session_key: str,
    text: str,
    receive_id: str,
    receive_id_type: str,
    message_id: str,
) -> bool:
    """POST a normalized Feishu message to a profile container's ``/v1/runs``.

    Fire-and-forget: failures are logged and the user is notified via the
    main gateway. Returns True if the HTTP request was accepted (2xx/202),
    False otherwise.

    The container replies directly to Feishu using ``X-Hermes-Reply-Via`` headers.
    """
    if not text or not text.strip():
        logger.debug(
            "[Feishu] Skipping forward for message id=%s: empty text",
            message_id,
        )
        return True

    if not endpoint.startswith(("http://", "https://")):
        logger.error(
            "[Feishu] Invalid endpoint for message id=%s: %s "
            "(must start with http:// or https://)",
            message_id,
            endpoint,
        )
        return False

    url = endpoint.rstrip("/") + "/v1/runs"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Hermes-Session-Key": session_key,
        "X-Hermes-Reply-Via": "feishu",
        "X-Hermes-Reply-Receive-Id": receive_id,
        "X-Hermes-Reply-Receive-Id-Type": receive_id_type,
        "X-Hermes-Reply-Message-Id": message_id,
    }
    body = {"input": text}
    try:
        import aiohttp

        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                headers=headers,
                json=body,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status not in (200, 202):
                    logger.warning(
                        "[Feishu] Profile container RPC failed (HTTP %d) url=%s",
                        resp.status,
                        url,
                    )
                    return False
                return True
    except Exception as exc:
        logger.warning(
            "[Feishu] Profile container RPC exception url=%s: %s", url, exc
        )
        return False


async def _notify_forward_failure(adapter: Any, receive_id: str) -> None:
    """Best-effort notify user when profile container forward fails."""
    if not receive_id:
        return
    try:
        await adapter.send(
            chat_id=receive_id,
            content="⚠️ 服务暂时不可用，请稍后再试",
        )
    except Exception:
        pass


def _forward_card_action_sync(
    route: Tuple[str, str, str],
    event: Any,
    action_value: Dict[str, Any],
) -> Any:
    """Synchronously forward a card action to a profile container.

    Runs in the Feishu SDK callback thread (synchronous context), so uses
    ``urllib`` rather than ``aiohttp``. Returns a
    ``P2CardActionTriggerResponse`` to acknowledge the event to Feishu
    regardless of container outcome.
    """
    profile_name, endpoint, api_key = route
    operator = getattr(event, "operator", None)
    context = getattr(event, "context", None)
    # Strip hermes_profile so the container does not try to re-forward.
    clean_value = {k: v for k, v in action_value.items() if k != "hermes_profile"}
    payload = {
        "action_value": clean_value,
        "open_id": str(getattr(operator, "open_id", "") or ""),
        "user_id": str(getattr(operator, "user_id", "") or ""),
        "chat_id": str(getattr(context, "open_chat_id", "") or ""),
    }
    url = endpoint.rstrip("/") + "/v1/feishu/card-actions"
    try:
        import urllib.request as _urlreq

        req = _urlreq.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        _urlreq.urlopen(req, timeout=8)
        logger.info("[Feishu] Forwarded card action to profile '%s'", profile_name)
    except Exception as exc:
        logger.warning(
            "[Feishu] Failed to forward card action to profile '%s': %s",
            profile_name,
            exc,
        )

    try:
        from lark_oapi.event.callback.model.p2_card_action_trigger import (
            P2CardActionTriggerResponse,
        )

        return P2CardActionTriggerResponse()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Local-only command guard
# ---------------------------------------------------------------------------

# Commands that must be handled by the main gateway process, never forwarded
# to a profile container. They affect gateway-level state (process lifecycle,
# platform connections) rather than a single conversation session.
_LOCAL_ONLY_COMMANDS: frozenset[str] = frozenset({"restart"})


def _should_route_text(text: Optional[str]) -> bool:
    """Return False when ``text`` is a local-only slash command.

    Strips the leading ``/`` and any ``@botname`` suffix before comparing.
    Non-command text always returns True.
    """
    if not text or not isinstance(text, str):
        return True
    stripped = text.strip()
    if not stripped.startswith("/"):
        return True
    parts = stripped.split(maxsplit=1)
    cmd = parts[0][1:].lower().split("@", 1)[0]
    return cmd not in _LOCAL_ONLY_COMMANDS


# ---------------------------------------------------------------------------
# High-level entry points used by gateway/platforms/feishu.py
# ---------------------------------------------------------------------------


async def try_route_inbound_message(
    adapter: Any,
    *,
    chat_id: str,
    open_id: str,
    chat_type: str,
    text: str,
    message_id: str,
) -> bool:
    """Route an inbound message to a profile container if configured.

    Returns True if the message was forwarded (caller should stop local
    processing), False otherwise.
    """
    if not _should_route_text(text):
        return False

    route = resolve_profile_route(chat_id, open_id)
    if route is None:
        return False

    profile, endpoint, api_key = route
    is_dm = chat_type == "p2p"
    session_key = f"feishu:dm:{open_id}" if is_dm else f"feishu:group:{chat_id}"
    receive_id = open_id if is_dm else chat_id
    receive_id_type = "open_id" if is_dm else "chat_id"

    forwarded = await _forward_to_profile_container(
        adapter,
        endpoint=endpoint,
        api_key=api_key,
        session_key=session_key,
        text=text,
        receive_id=receive_id,
        receive_id_type=receive_id_type,
        message_id=message_id,
    )
    if forwarded:
        logger.info(
            "[Feishu] Routed message id=%s to profile '%s' (%s)",
            message_id,
            profile,
            endpoint,
        )
        return True

    await _notify_forward_failure(adapter, receive_id)
    return False


def try_route_card_action(event: Any, action_value: Dict[str, Any]) -> Any:
    """Route a card action to a profile container if configured.

    Returns a ``P2CardActionTriggerResponse`` when the action is handled
    (either forwarded or explicitly dropped), None when the caller should
    continue with local processing.
    """
    from lark_oapi.event.callback.model.p2_card_action_trigger import (
        P2CardActionTriggerResponse,
    )

    context = getattr(event, "context", None)
    chat_id = str(getattr(context, "open_chat_id", "") or "")
    operator = getattr(event, "operator", None)
    open_id = str(getattr(operator, "open_id", "") or "")
    card_profile = (
        action_value.get("hermes_profile")
        if isinstance(action_value, dict)
        else None
    )

    if card_profile:
        # B3: card was sent by a named profile container — forward to it.
        route = resolve_profile_route_by_name(str(card_profile))
        if route is not None:
            return _forward_card_action_sync(route, event, action_value)
        # Profile not in endpoints — fall through to local handling.
        return None

    route = resolve_profile_route(chat_id, open_id)
    if route is not None:
        logger.debug(
            "[Feishu] Dropping card action for routed profile '%s' (chat=%s, user=%s)",
            route[0],
            chat_id,
            open_id,
        )
        return P2CardActionTriggerResponse()

    return None


async def try_route_bot_menu_command(
    adapter: Any,
    *,
    chat_id: str,
    open_id: str,
    synthetic_text: str,
) -> bool:
    """Route a bot menu synthetic command to a profile container if configured.

    Returns True if forwarded, False otherwise.
    """
    if not _should_route_text(synthetic_text):
        return False

    route = resolve_profile_route(chat_id, open_id)
    if route is None:
        return False

    profile, endpoint, api_key = route
    forwarded = await _forward_to_profile_container(
        adapter,
        endpoint=endpoint,
        api_key=api_key,
        session_key=f"feishu:dm:{open_id}",
        text=synthetic_text,
        receive_id=open_id,
        receive_id_type="open_id",
        message_id=None,
    )
    if forwarded:
        logger.info(
            "[Feishu] Routed bot menu command=%r to profile '%s' (%s)",
            synthetic_text,
            profile,
            endpoint,
        )
        return True

    await _notify_forward_failure(adapter, open_id)
    return False


# ---------------------------------------------------------------------------
# api_server reply helper (used by gateway/platforms/api_server.py)
# ---------------------------------------------------------------------------

# Class-level token cache: app_id -> (token, expires_at)
_feishu_token_cache: Dict[str, tuple] = {}


async def _get_feishu_tenant_token(
    app_id: str, app_secret: str
) -> Optional[str]:
    """Fetch (or return cached) Feishu tenant_access_token."""
    import aiohttp as _aiohttp

    cached = _feishu_token_cache.get(app_id)
    if cached and cached[1] > time.time() + 60:
        return cached[0]

    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    try:
        async with _aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json={"app_id": app_id, "app_secret": app_secret},
                timeout=_aiohttp.ClientTimeout(total=10),
            ) as resp:
                data = await resp.json()
    except Exception as exc:
        logger.warning(
            "[api_server] Failed to fetch Feishu tenant token: %s", exc
        )
        return None

    if data.get("code") != 0:
        logger.warning("[api_server] Feishu tenant token error: %s", data)
        return None

    token = data["tenant_access_token"]
    _feishu_token_cache[app_id] = (
        token,
        time.time() + data.get("expire", 7200),
    )
    return token


async def feishu_reply(
    *,
    receive_id: str,
    receive_id_type: str,
    text: str,
    reply_message_id: Optional[str] = None,
) -> None:
    """Send a text message to Feishu.

    Called after run completes when ``X-Hermes-Reply-Via: feishu`` is set on
    the ``/v1/runs`` request.
    """
    import aiohttp as _aiohttp

    app_id = os.environ.get("FEISHU_APP_ID", "")
    app_secret = os.environ.get("FEISHU_APP_SECRET", "")
    if not app_id or not app_secret:
        logger.warning(
            "[api_server] X-Hermes-Reply-Via: feishu but "
            "FEISHU_APP_ID/SECRET not configured"
        )
        return

    token = await _get_feishu_tenant_token(app_id, app_secret)
    if not token:
        return

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    content_json = json.dumps({"text": text})

    try:
        async with _aiohttp.ClientSession() as session:
            if reply_message_id:
                url = f"https://open.feishu.cn/open-apis/im/v1/messages/{reply_message_id}/reply"
                body: Dict[str, Any] = {
                    "content": content_json,
                    "msg_type": "text",
                    "uuid": str(uuid.uuid4()),
                }
            else:
                url = f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type={receive_id_type}"
                body = {
                    "receive_id": receive_id,
                    "content": content_json,
                    "msg_type": "text",
                    "uuid": str(uuid.uuid4()),
                }
            async with session.post(
                url,
                headers=headers,
                json=body,
                timeout=_aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    logger.warning(
                        "[api_server] Feishu reply failed (HTTP %d): %s",
                        resp.status,
                        await resp.text(),
                    )
    except Exception as exc:
        logger.warning("[api_server] Feishu reply exception: %s", exc)
