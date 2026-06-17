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
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


def _load_routing_config() -> Dict[str, Any]:
    """Fail-open loader for the ``feishu.user_routing`` section.
    
    Supports multi-bot structure: ``feishu.bots.{app_id}.user_routing``
    Falls back to legacy flat structure: ``feishu.user_routing``
    """
    try:
        from owner.patch_config import load_patch_feishu_profile_config

        cfg = load_patch_feishu_profile_config()
        feishu_cfg = cfg.get("feishu", {})
        
        # Try multi-bot structure first
        bots_cfg = feishu_cfg.get("bots", {})
        if bots_cfg:
            # Get current gateway's app_id
            app_id = os.getenv("FEISHU_APP_ID", "").strip()
            if not app_id:
                logger.debug(
                    "[Feishu] FEISHU_APP_ID not set; cannot load bot-specific routing"
                )
                return {}
            
            bot_cfg = bots_cfg.get(app_id, {})
            if not bot_cfg:
                logger.debug(
                    "[Feishu] No routing config for app_id=%s in feishu.bots",
                    app_id,
                )
                return {}
            
            routing = bot_cfg.get("user_routing", {})
            logger.debug(
                "[Feishu] Loaded routing for app_id=%s from feishu.bots",
                app_id,
            )
        else:
            # Fallback to legacy flat structure
            routing = feishu_cfg.get("user_routing", {})
        
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

    endpoint_cfg = endpoints.get(profile)
    if not endpoint_cfg:
        logger.warning(
            "[Feishu] profile '%s' has no endpoint in profile_endpoints", profile
        )
        return None

    # endpoint_cfg can be a dict with 'url' and 'api_key', or a plain string (legacy)
    if isinstance(endpoint_cfg, dict):
        url = endpoint_cfg.get("url", "")
        api_key = endpoint_cfg.get("api_key", "")
    else:
        # Legacy: plain string URL
        url = str(endpoint_cfg)
        api_key = ""

    if not url:
        logger.warning(
            "[Feishu] profile '%s' endpoint has no 'url' field", profile
        )
        return None

    return (profile, str(url), str(api_key))


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

    endpoint_cfg = endpoints.get(profile_name)
    if not endpoint_cfg:
        logger.warning(
            "[Feishu] hermes_profile '%s' not found in profile_endpoints",
            profile_name,
        )
        return None

    # endpoint_cfg can be a dict with 'url' and 'api_key', or a plain string (legacy)
    if isinstance(endpoint_cfg, dict):
        url = endpoint_cfg.get("url", "")
        api_key = endpoint_cfg.get("api_key", "")
    else:
        # Legacy: plain string URL
        url = str(endpoint_cfg)
        api_key = ""

    if not url:
        logger.warning(
            "[Feishu] hermes_profile '%s' endpoint has no 'url' field",
            profile_name,
        )
        return None

    return (profile_name, str(url), str(api_key))


async def _forward_to_profile_container(
    *,
    endpoint: str,
    api_key: str,
    text: str,
    open_id: str,
    chat_id: str,
    chat_type: str,
    message_id: Optional[str],
) -> bool:
    """POST a Feishu message to a profile container's ``/v1/feishu/inbound``.

    Fire-and-forget transport: the main gateway holds the only WebSocket and
    forwards routed messages here. The container reconstructs the inbound
    event and runs it through its full native Feishu pipeline (see
    ``FeishuAdapter.inject_inbound``), then replies via its own ``send_only``
    adapter — so a routed conversation behaves exactly like a native one.

    ``chat_id`` is the p2p chat id (``oc_…``) for a DM or the group id for a
    group; ``open_id`` is always the sender. Both are forwarded so the
    container can pick whichever id Feishu needs at send time.

    Returns True if the HTTP request was accepted (200/202), False otherwise.
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

    url = endpoint.rstrip("/") + "/v1/feishu/inbound"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body: Dict[str, Any] = {
        "text": text,
        "open_id": open_id,
        "chat_id": chat_id,
        "chat_type": chat_type,
    }
    if message_id:
        body["message_id"] = message_id
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
    # Reply/notify fallback target: DM → sender open_id, group → group chat_id.
    notify_target = open_id if is_dm else chat_id

    forwarded = await _forward_to_profile_container(
        endpoint=endpoint,
        api_key=api_key,
        text=text,
        open_id=open_id,
        chat_id=chat_id,
        chat_type=chat_type,
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

    await _notify_forward_failure(adapter, notify_target)
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
    # Bot-menu commands are always DM-context synthetic messages; the chat_id
    # (p2p oc_) may be unknown here, so the container falls back to open_id.
    forwarded = await _forward_to_profile_container(
        endpoint=endpoint,
        api_key=api_key,
        text=synthetic_text,
        open_id=open_id,
        chat_id=chat_id or "",
        chat_type="p2p",
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


def _get_inprocess_feishu_adapter() -> Any:
    """Return the live FeishuAdapter running in this api_server process, or None.

    The sub-profile container runs both ``api_server`` and ``feishu`` (in
    ``send_only`` mode) in one GatewayRunner. We reach the runner via the
    module-level weakref in ``gateway.run`` and pull the registered Feishu
    adapter so replies can flow through ``send()`` → ``try_auto_card()``
    (auto-card + card formatting) instead of a bare REST text send.

    Fail-open: any import/attribute error returns None and the caller falls
    back to the direct REST path.
    """
    try:
        import gateway.run as _gr

        ref = getattr(_gr, "_gateway_runner_ref", None)
        runner = ref() if callable(ref) else None
        if runner is None:
            return None
        from gateway.config import Platform

        adapter = runner.adapters.get(Platform.FEISHU)
        # send_only / websocket / webhook all set ``_client`` on connect; without
        # it ``send()`` short-circuits to "Not connected".
        if adapter is not None and getattr(adapter, "_client", None) is not None:
            return adapter
    except Exception:
        return None
    return None
