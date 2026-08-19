"""Feishu multi-profile routing (owner-v16 external-container architecture).

Extracts profile-route resolution and HTTP forwarding out of
``gateway/platforms/feishu.py`` so the core adapter stays a thin dispatcher.

Configuration is read from ``~/.hermes/patch_feishu_profile.yaml``
(``load_patch_feishu_profile_config``) rather than the main ``patch.yaml``.
"""

# [owner] Task 1 → Task 2 依赖声明（飞书多 profile 路由迁移）
# 本模块已逐字节保真从 owner-v17 迁移。以下对本进程内 FeishuAdapter
# （目标分支位于 plugins/platforms/feishu/adapter.py）的引用，需等 Task 2
# 在该 adapter.py 补齐相应方法后自动生效；在此之前通过 lazy import / getattr
# 调用，缺失时上层 fail-open，不会影响模块导入：
#   • FeishuAdapter.inject_inbound —— 子 profile 容器恢复 inbound 事件的入口
#     （见 _forward_to_profile_container docstring，由 Task 2 接线进 adapter）
#   • FeishuAdapter._dispatch_card_action —— handle_card_action_request() 在
#     L573 处直接调用 adapter._dispatch_card_action(...)，需 Task 2 在 adapter.py
#     补齐该方法并支持 allow_profile_routing=False 参数
# 注：_maybe_tag_card_profile（L583 引用）来自本 Task 迁移的 card_sender.py，
#     无外部依赖。

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

FEISHU_INBOUND_SCHEMA_VERSION = 1


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
    message_type: str = "text",
    user_id: str = "",
    union_id: str = "",
    is_bot: bool = False,
    thread_id: Optional[str] = None,
    reply_to_message_id: Optional[str] = None,
    reply_to_text: Optional[str] = None,
    raw_message_type: str = "",
    raw_content: str = "",
    media_expected: bool = False,
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
    if (not text or not text.strip()) and not media_expected:
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
        "schema_version": FEISHU_INBOUND_SCHEMA_VERSION,
        "text": text,
        "message_type": message_type,
        "open_id": open_id,
        "user_id": user_id,
        "union_id": union_id,
        "is_bot": bool(is_bot),
        "chat_id": chat_id,
        "chat_type": chat_type,
        "thread_id": thread_id,
        "reply_to_message_id": reply_to_message_id,
        "reply_to_text": reply_to_text,
        # Feishu message content contains resource keys, not file bytes.  The
        # target process uses these fields and its own send_only client to
        # download media into that profile's cache; local cache paths from the
        # ingress process are deliberately never sent across the RPC boundary.
        "raw_message_type": raw_message_type,
        "raw_content": raw_content,
        "media_expected": bool(media_expected),
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
                # Admission on the receiver is metadata-only (media
                # rehydration runs after the 202). A routed user is never
                # served locally on timeout — try_route_inbound_message
                # returns True either way and only notifies "子网关暂时不可用".
                # Keep this short so a hung container fails fast; 20s covers
                # chat_info + sender-profile lookups with slack.
                timeout=aiohttp.ClientTimeout(total=20),
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


async def _notify_forward_failure(
    adapter: Any, receive_id: str, profile_name: str = ""
) -> None:
    """Best-effort notify user when the routed sub-gateway is unreachable.

    ``profile_name`` is the route's profile (the key resolved from
    ``patch_feishu_profile.yaml``); it is spliced into the notice so the user
    knows which sub-gateway is down rather than seeing a generic message.
    """
    if not receive_id:
        return
    label = f"「{profile_name}」" if profile_name else ""
    try:
        await adapter.send(
            chat_id=receive_id,
            content=f"⚠️ 子网关{label}暂时不可用，请稍后再试",
        )
    except Exception:
        pass


def _lark_response_classes() -> Tuple[Any, Any]:
    """Return ``(P2CardActionTriggerResponse, CallBackCard)`` or ``(None, None)``.

    Imported from the submodule (not the top-level ``lark_oapi`` module, which
    does not export them on lark-oapi 1.5.x).
    """
    try:
        from lark_oapi.event.callback.model.p2_card_action_trigger import (
            CallBackCard,
            P2CardActionTriggerResponse,
        )

        return P2CardActionTriggerResponse, CallBackCard
    except Exception:
        return None, None


def _build_card_response(card_data: Optional[Dict[str, Any]]) -> Any:
    """Build a ``P2CardActionTriggerResponse``, inline-updating the card if given.

    ``card_data`` is the raw Feishu card JSON the sub-profile computed for the
    resolved state. Returning it as ``CallBackCard(type="raw")`` lets the main
    gateway relay the sub-profile's card update over the WebSocket it owns.
    """
    response_cls, callback_cls = _lark_response_classes()
    if response_cls is None:
        return None
    resp = response_cls()
    if card_data and callback_cls is not None:
        cb = callback_cls()
        cb.type = "raw"
        cb.data = card_data
        resp.card = cb
    return resp


def _build_error_card_response(profile_name: str) -> Any:
    """Inline-replace the card with a 'sub-gateway unavailable' notice."""
    label = f"「{profile_name}」" if profile_name else ""
    card = {
        "config": {"wide_screen_mode": True},
        "elements": [
            {"tag": "markdown", "content": f"⚠️ 子网关{label}暂时不可用，请稍后再试"}
        ],
    }
    return _build_card_response(card)


def _forward_card_action_sync(
    route: Tuple[str, str, str],
    event: Any,
    action_value: Dict[str, Any],
) -> Any:
    """Synchronously forward a card action to a profile container and relay back.

    Runs in the Feishu SDK callback thread (synchronous context), so uses
    ``urllib`` rather than ``aiohttp``. The sub-profile resolves the click and
    returns ``{"card": <json|null>}``; we wrap that card into the
    ``P2CardActionTriggerResponse`` so the card updates inline for all clients
    (the main gateway owns the only WebSocket). On any failure the user sees an
    explicit "sub-gateway unavailable" card — never a silent drop.
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
        # Feishu requires a card.action.trigger response within 3s (else the user
        # sees Feishu's own failure toast). Cap the forward below that so our
        # error card still lands in time on a slow/hung container; the happy path
        # is a localhost round-trip of a few ms.
        with _urlreq.urlopen(req, timeout=2.5) as resp:
            status = int(getattr(resp, "status", 0) or getattr(resp, "code", 0) or 200)
            raw = resp.read()
    except Exception as exc:
        logger.warning(
            "[Feishu] Sub-gateway '%s' unreachable for card action: %s",
            profile_name,
            exc,
        )
        return _build_error_card_response(profile_name)

    if status not in (200, 202):
        logger.warning(
            "[Feishu] Card action forward to '%s' returned HTTP %s",
            profile_name,
            status,
        )
        return _build_error_card_response(profile_name)

    card_data: Optional[Dict[str, Any]] = None
    if raw:
        try:
            body = json.loads(raw.decode("utf-8"))
            if isinstance(body, dict) and isinstance(body.get("card"), dict):
                card_data = body["card"]
        except Exception:
            card_data = None
    logger.info(
        "[Feishu] Routed card action to profile '%s'%s",
        profile_name,
        " (card updated)" if card_data else "",
    )
    return _build_card_response(card_data)


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
    message_type: str = "text",
    user_id: str = "",
    union_id: str = "",
    is_bot: bool = False,
    thread_id: Optional[str] = None,
    reply_to_message_id: Optional[str] = None,
    reply_to_text: Optional[str] = None,
    raw_message_type: str = "",
    raw_content: str = "",
    media_expected: bool = False,
) -> bool:
    """Route an inbound message to a profile container if configured.

    Returns True when the caller must stop local processing. This is the case
    whenever the user resolves to a sub-profile route — regardless of whether
    the forward actually succeeded. Once a user is bound to a sub-profile, the
    main gateway must NEVER serve them locally; a down container yields an error
    notice + drop, never a silent fallback to the main gateway.

    Returns False only when the message legitimately belongs to the main
    gateway: a local-only command, or no route resolved for this user.
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
        message_type=message_type,
        user_id=user_id,
        union_id=union_id,
        is_bot=is_bot,
        thread_id=thread_id,
        reply_to_message_id=reply_to_message_id,
        reply_to_text=reply_to_text,
        raw_message_type=raw_message_type,
        raw_content=raw_content,
        media_expected=media_expected,
    )
    if forwarded:
        logger.info(
            "[Feishu] Routed message id=%s to profile '%s' (%s)",
            message_id,
            profile,
            endpoint,
        )
        return True

    # Container down / forward failed: notify the user, but DO NOT fall back to
    # the main gateway. This user is bound to a sub-profile; serving them on the
    # main gateway would leak a routed conversation into the wrong agent.
    await _notify_forward_failure(adapter, notify_target, profile)
    return True


def try_route_card_action(event: Any, action_value: Dict[str, Any]) -> Any:
    """Route a card action to the sub-profile that sent the card.

    Routing is driven solely by the ``hermes_profile`` tag the sub-profile
    stamped onto each button (see ``card_sender._maybe_tag_card_profile``):

      * tagged + endpoint known → forward to that container and relay its card
        update back (Option B);
      * tagged + endpoint unknown (config drift / container removed) → explicit
        "sub-gateway unavailable" card, never a silent drop;
      * untagged → ``None`` → handle locally. An untagged card is one the main
        gateway itself sent (to a non-routed user); its correlation state lives
        in this process.

    Returns a ``P2CardActionTriggerResponse`` when handled, ``None`` when the
    caller should continue with local processing.
    """
    card_profile = (
        action_value.get("hermes_profile")
        if isinstance(action_value, dict)
        else None
    )
    if not card_profile:
        return None

    route = resolve_profile_route_by_name(str(card_profile))
    if route is not None:
        return _forward_card_action_sync(route, event, action_value)

    logger.warning(
        "[Feishu] Card action tagged profile '%s' has no endpoint; "
        "showing sub-gateway-unavailable card",
        card_profile,
    )
    return _build_error_card_response(str(card_profile))


def handle_card_action_request(
    adapter: Any, body: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """Replay a main-gateway-forwarded card action inside this sub-profile.

    Called by the thin ``/v1/feishu/card-actions`` glue in
    ``gateway/platforms/api_server.py``. Reconstructs the minimal lark-event
    shape the per-type handlers read, dispatches through the shared
    ``_dispatch_card_action`` (profile routing disabled — the click was already
    routed here and the ``hermes_profile`` tag stripped), then returns the
    resolved card JSON for the main gateway to relay inline.

    The returned card is re-tagged with this profile via
    ``_maybe_tag_card_profile`` so that *updated* cards which still carry buttons
    (recall expand/collapse, diff expand/collapse/full) keep routing their next
    click back here — those cards are returned over HTTP and never pass through
    the ``send_card`` choke point where the initial tagging happens.

    Returns the resolved card dict, or ``None`` for a no-update acknowledgement.
    """
    from types import SimpleNamespace

    action_value = body.get("action_value") or {}
    if not isinstance(action_value, dict):
        return None
    event = SimpleNamespace(
        action=SimpleNamespace(value=action_value, tag="button"),
        operator=SimpleNamespace(
            open_id=str(body.get("open_id") or "").strip(),
            user_id=str(body.get("user_id") or "").strip(),
        ),
        context=SimpleNamespace(open_chat_id=str(body.get("chat_id") or "").strip()),
        token="",
    )
    response = adapter._dispatch_card_action(
        event,
        action_value,
        getattr(adapter, "_loop", None),
        data=SimpleNamespace(event=event),
        allow_profile_routing=False,
    )
    card_obj = getattr(response, "card", None)
    card_data = getattr(card_obj, "data", None) if card_obj is not None else None
    if isinstance(card_data, dict):
        from owner.feishu.card_sender import _maybe_tag_card_profile

        _maybe_tag_card_profile(adapter, card_data)
        return card_data
    return None


async def try_route_bot_menu_command(
    adapter: Any,
    *,
    chat_id: str,
    open_id: str,
    synthetic_text: str,
) -> bool:
    """Route a bot menu synthetic command to a profile container if configured.

    Returns True when the caller must stop local processing — true for any
    routed user, even if the forward failed (no silent fallback to the main
    gateway). Returns False only for local-only commands or unrouted users.
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

    # Container down / forward failed: notify, but do NOT fall back to the main
    # gateway (see try_route_inbound_message for rationale).
    await _notify_forward_failure(adapter, open_id, profile)
    return True


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
