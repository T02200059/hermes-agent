"""C05: Feishu multi-profile HTTP fleet routing (Hub → sub-container).

设计见 ``owner/docs/design/c05-feishu-user-routing/README.md``。

本模块是 **方案②**：跨容器 HTTP 舰队（``POST …/v1/feishu/inbound``），
**不**接官方同进程 ``gateway.profile_routes`` multiplex。

配置主源：``~/.hermes/overlay.yaml``
  - 顶层 ``fleet_profiles.<ldap_uid>``：人卡（``api_server`` / ``hub_only`` / ``docker``）
  - ``feishu.bots.<app_id>.user_routing``：``ou_*``→uid、chat、default、可选飞书 whitelist
  - endpoints **从** ``fleet_profiles.*.api_server`` **推导**
  - 回落：``patch_feishu_profile.yaml``（与 C09 同模式）；旧 ``profile_endpoints`` /
    ``identity_*`` 只读别名

C05 **不**接 LDAP / ``ldap_gate``；``hub_only.api`` 可解析供 C06，飞书路径只用
``hub_only.feishu`` ∪ open_id whitelist。
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



def _load_overlay_and_patch() -> tuple[dict[str, Any], dict[str, Any]]:
    """Return ``(overlay, patch)``; both fail-open to ``{}``."""
    overlay: dict[str, Any] = {}
    patch: dict[str, Any] = {}
    try:
        from owner.patch_config import (
            load_owner_config,
            load_patch_feishu_profile_config,
        )

        raw_o = load_owner_config()
        raw_p = load_patch_feishu_profile_config()
        if isinstance(raw_o, dict):
            overlay = raw_o
        if isinstance(raw_p, dict):
            patch = raw_p
    except Exception:
        pass
    return overlay, patch


def _pick_fleet_profiles(
    overlay: dict[str, Any], patch: dict[str, Any]
) -> dict[str, Any]:
    """Prefer overlay ``fleet_profiles``; fall back to patch."""
    for src in (overlay, patch):
        fp = src.get("fleet_profiles")
        if isinstance(fp, dict) and fp:
            return fp
    return {}


def _pick_user_routing_section(
    overlay: dict[str, Any], patch: dict[str, Any]
) -> dict[str, Any]:
    """Load ``feishu.bots.<FEISHU_APP_ID>.user_routing`` (overlay then patch).

    Falls back to legacy flat ``feishu.user_routing`` when ``bots`` is absent.
    """
    app_id = os.getenv("FEISHU_APP_ID", "").strip()

    def _from(src: dict[str, Any]) -> dict[str, Any]:
        feishu_cfg = src.get("feishu", {})
        if not isinstance(feishu_cfg, dict):
            return {}
        bots_cfg = feishu_cfg.get("bots", {})
        if isinstance(bots_cfg, dict) and bots_cfg:
            if not app_id:
                logger.debug(
                    "[Feishu] FEISHU_APP_ID not set; cannot load bot-specific routing"
                )
                return {}
            bot_cfg = bots_cfg.get(app_id, {})
            if not isinstance(bot_cfg, dict):
                return {}
            routing = bot_cfg.get("user_routing", {})
            return routing if isinstance(routing, dict) else {}
        routing = feishu_cfg.get("user_routing", {})
        return routing if isinstance(routing, dict) else {}

    for src in (overlay, patch):
        routing = _from(src)
        if routing:
            return routing
    return {}


def _hub_only_flags(card: Any) -> tuple[bool, bool]:
    """Return ``(hub_only.feishu, hub_only.api)`` from a person card."""
    if not isinstance(card, dict):
        return False, False
    hub = card.get("hub_only")
    if isinstance(hub, bool):
        return hub, hub
    if isinstance(hub, dict):
        return bool(hub.get("feishu")), bool(hub.get("api"))
    return False, False


def _endpoint_from_api_server(api: Any) -> Optional[dict[str, str]]:
    if not isinstance(api, dict):
        return None
    url = str(api.get("url") or "").strip()
    if not url:
        return None
    return {"url": url, "api_key": str(api.get("api_key") or "")}


def _derive_profile_endpoints(
    fleet: dict[str, Any], legacy_endpoints: Any
) -> dict[str, Any]:
    """Build ``profile → {url, api_key}`` from fleet_profiles; fill gaps from legacy."""
    endpoints: dict[str, Any] = {}
    for uid, card in fleet.items():
        if not isinstance(card, dict):
            continue
        # hub_only.api does not remove the endpoint — C06 decides whether to use it
        ep = _endpoint_from_api_server(card.get("api_server"))
        if ep:
            endpoints[str(uid)] = ep
    if isinstance(legacy_endpoints, dict):
        for name, cfg in legacy_endpoints.items():
            key = str(name)
            if key in endpoints:
                continue
            if isinstance(cfg, dict):
                url = str(cfg.get("url") or "").strip()
                if url:
                    endpoints[key] = {
                        "url": url,
                        "api_key": str(cfg.get("api_key") or ""),
                    }
            elif cfg:
                endpoints[key] = {"url": str(cfg), "api_key": ""}
    return endpoints


def _derive_identity_tables(
    fleet: dict[str, Any], routing: dict[str, Any]
) -> tuple[dict[str, str], list]:
    """Synthesize identity_routes / identity_whitelist for C06-ready helpers.

    Primary: fleet_profiles keys (uid → uid) when ``api_server`` present and
    not ``hub_only.api``. Whitelist: ``hub_only.api``.
    Legacy ``identity_routes`` / ``identity_whitelist`` fill gaps only.
    """
    routes: dict[str, str] = {}
    whitelist: list = []
    for uid, card in fleet.items():
        if not isinstance(card, dict):
            continue
        uid_s = str(uid)
        feishu_hub, api_hub = _hub_only_flags(card)
        _ = feishu_hub  # feishu hub_only is for message path, not API identity
        if api_hub:
            whitelist.append(uid_s)
            continue
        if _endpoint_from_api_server(card.get("api_server")):
            # optional ldap.uid alias
            ldap = card.get("ldap") if isinstance(card.get("ldap"), dict) else {}
            alias = str((ldap or {}).get("uid") or uid_s).strip() or uid_s
            routes[alias] = uid_s
            if alias != uid_s:
                routes[uid_s] = uid_s
    legacy_routes = routing.get("identity_routes")
    if isinstance(legacy_routes, dict):
        for k, v in legacy_routes.items():
            ks = str(k)
            if ks not in routes:
                routes[ks] = str(v)
    legacy_wl = routing.get("identity_whitelist")
    if isinstance(legacy_wl, (list, tuple, set, frozenset)):
        for item in legacy_wl:
            s = str(item)
            if s not in whitelist:
                whitelist.append(s)
    elif isinstance(legacy_wl, str) and legacy_wl and legacy_wl not in whitelist:
        whitelist.append(legacy_wl)
    return routes, whitelist


def _hub_only_feishu_set(fleet: dict[str, Any]) -> set:
    out: set = set()
    for uid, card in fleet.items():
        feishu_hub, _api = _hub_only_flags(card)
        if feishu_hub:
            out.add(str(uid))
    return out


def _load_routing_config() -> dict[str, Any]:
    """Synthesize the runtime routing dict (fail-open).

    Returned shape (compat + C05 fields)::

        whitelist, chat_profile_routes, user_profile_routes, default_profile,
        profile_endpoints,          # derived from fleet_profiles (+ legacy fill)
        hub_only_feishu,            # set[str] of ldap uid
        identity_routes,            # synthesized (C06-ready; C05 Feishu path unused)
        identity_whitelist,         # synthesized from hub_only.api (+ legacy)
        container_profile,          # optional
        fleet_profiles,             # raw person cards (docker fields etc.)
    """
    try:
        overlay, patch = _load_overlay_and_patch()
        fleet = _pick_fleet_profiles(overlay, patch)
        routing = dict(_pick_user_routing_section(overlay, patch))
        endpoints = _derive_profile_endpoints(
            fleet, routing.get("profile_endpoints")
        )
        identity_routes, identity_whitelist = _derive_identity_tables(fleet, routing)
        synthesized = {
            "whitelist": routing.get("whitelist", []),
            "chat_profile_routes": routing.get("chat_profile_routes", {}) or {},
            "user_profile_routes": routing.get("user_profile_routes", {}) or {},
            "default_profile": routing.get("default_profile"),
            "profile_endpoints": endpoints,
            "hub_only_feishu": _hub_only_feishu_set(fleet),
            "identity_routes": identity_routes,
            "identity_whitelist": identity_whitelist,
            "fleet_profiles": fleet,
        }
        if isinstance(routing.get("container_profile"), str):
            synthesized["container_profile"] = routing["container_profile"]
        # If nothing configured at all, return {} so resolve short-circuits.
        has_routes = bool(
            synthesized["user_profile_routes"]
            or synthesized["chat_profile_routes"]
            or synthesized.get("default_profile")
            or endpoints
            or fleet
        )
        if not has_routes and not synthesized["whitelist"]:
            return {}
        return synthesized
    except Exception:
        return {}


def resolve_profile_route(
    chat_id: str,
    open_id: str,
    chat_type: str = "p2p",
) -> Optional[tuple[str, str, str]]:
    """Return ``(profile_name, endpoint_url, api_key)`` for an inbound message.

    Resolution priority (DM):
        1. open_id ``whitelist`` → Hub (None)
        2. ``chat_profile_routes`` / ``user_profile_routes`` / ``default_profile``
        3. candidate ∈ ``hub_only.feishu`` → Hub (None)
        4. ``fleet_profiles[candidate].api_server`` (via derived endpoints)
        5. missing endpoint → warn + None (Hub; same as现网缺失)

    Group chats skip open_id whitelist and hub_only.feishu (DM semantics only).
    """
    routing_cfg = _load_routing_config()
    if not routing_cfg:
        return None

    is_dm = (chat_type or "p2p").strip().lower() in ("p2p", "dm")

    if is_dm:
        whitelist = routing_cfg.get("whitelist", [])
        if isinstance(whitelist, (list, tuple, set, frozenset)):
            if open_id in whitelist:
                return None
        elif isinstance(whitelist, str):
            if open_id == whitelist:
                return None
        elif whitelist not in (None,):
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

    if is_dm:
        hub_only = routing_cfg.get("hub_only_feishu") or set()
        if isinstance(hub_only, (set, frozenset, list, tuple)) and profile in hub_only:
            return None

    endpoints = routing_cfg.get("profile_endpoints")
    if not isinstance(endpoints, dict):
        logger.warning(
            "[Feishu] derived profile_endpoints has invalid type %s; expected dict",
            type(endpoints).__name__,
        )
        return None

    endpoint_cfg = endpoints.get(profile)
    if not endpoint_cfg:
        logger.warning(
            "[Feishu] profile '%s' has no api_server/endpoint in fleet_profiles",
            profile,
        )
        return None

    if isinstance(endpoint_cfg, dict):
        url = endpoint_cfg.get("url", "")
        api_key = endpoint_cfg.get("api_key", "")
    else:
        url = str(endpoint_cfg)
        api_key = ""

    if not url:
        logger.warning(
            "[Feishu] profile '%s' endpoint has no 'url' field", profile
        )
        return None

    return (profile, str(url), str(api_key))


def resolve_profile_route_by_name(profile_name: str) -> Optional[tuple[str, str, str]]:
    """Resolve a profile by explicit name (card-action routing / identity)."""
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
            "[Feishu] hermes_profile '%s' not found in fleet_profiles/endpoints",
            profile_name,
        )
        return None

    if isinstance(endpoint_cfg, dict):
        url = endpoint_cfg.get("url", "")
        api_key = endpoint_cfg.get("api_key", "")
    else:
        url = str(endpoint_cfg)
        api_key = ""

    if not url:
        logger.warning(
            "[Feishu] hermes_profile '%s' endpoint has no 'url' field",
            profile_name,
        )
        return None

    return (profile_name, str(url), str(api_key))




# ── [owner T2-9] container-side ownership of the inbound RPC ─────────────────
#
# The main gateway holds the only Feishu WebSocket and forwards routed traffic
# to sub-profile containers over HTTP. That transport authenticated the caller
# (shared API key) but never checked *what* it was asked to serve: a container
# accepted an event addressed to any profile. Both sides are configured from
# the SAME ``profile_endpoints`` map, so the only way to land an event on the
# wrong container is drift between that map and the process that actually
# listens on the endpoint — exactly the configuration-error class this
# codebase keeps getting bitten by (cf. T2-6, where a missing
# ``profile_endpoints`` entry turned a gated uid into an ungated path).
#
# The check is deliberately asymmetric about failure:
#   * mismatch, both sides identified  → REJECT (the interesting case)
#   * target absent (older sender)     → accept + warn once
#   * own identity undeterminable      → accept + warn once
# Rejecting the latter two would turn a version skew or an unlabelled container
# into a total outage of multi-profile routing — a worse failure than the
# misroute this guards against. The API key remains the authentication
# boundary either way.
TARGET_PROFILE_KEY = "target_profile"
CONTAINER_PROFILE_ENV = "HERMES_PROFILE"
CONTAINER_PROFILE_CONFIG_KEY = "container_profile"

_ownership_notices: set = set()


def _warn_once(key: str, message: str, *args: Any) -> None:
    """Log ``message`` once per process per ``key``."""
    if key in _ownership_notices:
        return
    _ownership_notices.add(key)
    logger.warning(message, *args)


def container_profile_identity() -> Optional[str]:
    """Return the profile this process believes it serves, else ``None``.

    ``HERMES_PROFILE`` is the Docker-container identity (the same variable
    ``owner/approval/skill_manage_gate.py`` reads). The optional
    ``user_routing.container_profile`` config key lets a deployment that does
    not set the env var declare it.

    There is deliberately **no** fallback to the active profile name or
    ``"default"``: this value decides whether to *reject* traffic, and a guess
    here would either reject everything (guess differs from the target) or
    make the check vacuous (guess matches everything). ``None`` means "cannot
    decide", which the caller treats as "do not reject".
    """
    env_profile = (os.getenv(CONTAINER_PROFILE_ENV, "") or "").strip()
    if env_profile:
        return env_profile
    cfg_value = _load_routing_config().get(CONTAINER_PROFILE_CONFIG_KEY)
    if isinstance(cfg_value, str) and cfg_value.strip():
        return cfg_value.strip()
    return None


def verify_inbound_target_profile(body: Any) -> Optional[str]:
    """Check that an inbound RPC payload was addressed to *this* profile.

    Returns ``None`` when the payload may be served, or a short reason string
    when it must be rejected. Callers turn the reason into an explicit
    ``409 profile_mismatch`` rather than a silent drop, so a misconfigured
    ``profile_endpoints`` entry surfaces as a logged, attributable failure
    instead of a conversation quietly appearing in the wrong container.
    """
    if not isinstance(body, dict):
        return None
    target = str(body.get(TARGET_PROFILE_KEY) or "").strip()
    if not target:
        _warn_once(
            "target_absent",
            "[Feishu] inbound RPC carried no %s; accepting without an "
            "ownership check (sender predates the check)",
            TARGET_PROFILE_KEY,
        )
        return None
    mine = container_profile_identity()
    if not mine:
        _warn_once(
            "identity_unknown",
            "[Feishu] cannot determine this container's profile (set %s or "
            "user_routing.%s); accepting inbound RPC for '%s' unchecked",
            CONTAINER_PROFILE_ENV,
            CONTAINER_PROFILE_CONFIG_KEY,
            target,
        )
        return None
    if mine == target:
        return None
    logger.error(
        "[Feishu] REJECTING inbound RPC addressed to profile '%s' but this "
        "container serves '%s' — profile_endpoints and the container "
        "identity disagree",
        target,
        mine,
    )
    return (
        f"inbound RPC addressed to profile '{target}' but this container "
        f"serves '{mine}'"
    )


def reset_ownership_notices() -> None:
    """Clear the once-per-process notice set (tests)."""
    _ownership_notices.clear()


def resolve_api_identity_route(
    identity: str,
) -> Optional[tuple[str, str, str]]:
    """Resolve a profile by API identity string (LDAP uid, etc.).

    Reads ``identity_routes`` from the routing config, maps the identity to a
    profile name, then delegates to ``resolve_profile_route_by_name`` for the
    endpoint URL and API key.

    Returns (profile_name, endpoint_url, api_key) or None if the identity
    is unknown or the profile has no endpoint.
    """
    if not identity:
        return None

    routing_cfg = _load_routing_config()
    if not routing_cfg:
        return None

    identity_routes = routing_cfg.get("identity_routes", {})
    if not isinstance(identity_routes, dict):
        return None

    profile_name = identity_routes.get(identity)
    if not profile_name:
        return None

    return resolve_profile_route_by_name(str(profile_name))


def is_api_identity_whitelisted(identity: str) -> bool:
    """Return True if an API identity (LDAP uid) is whitelisted to the root gateway.

    Mirrors the feishu ``user_routing.whitelist`` semantics for api_server
    identity traffic: whitelisted identities skip sub-profile container
    routing and are handled by the root gateway itself (same trust level as
    the feishu main-gateway whitelist — the whitelisted uid chats with the
    root instance's memory/sessions, not a per-user docker container).

    Scope (T2-6): the whitelist decides **routing only**. It is not an
    authentication bypass — the middleware runs the LDAP gate before consulting
    it, so a whitelisted identity still has to prove the claim it presents.

    Reads ``identity_whitelist`` from the same routing config section as
    ``identity_routes``. Takes priority over ``identity_routes``: an entry
    in both lists resolves to the root gateway (dormant identity_routes
    entry, exactly like a feishu open_id present in both whitelist and
    user_profile_routes).
    """
    if not identity:
        return False

    routing_cfg = _load_routing_config()
    if not routing_cfg:
        return False

    whitelist = routing_cfg.get("identity_whitelist", [])
    if isinstance(whitelist, (list, tuple, set, frozenset)):
        return identity in whitelist
    if isinstance(whitelist, str):
        return identity == whitelist
    logger.warning(
        "[Feishu] user_routing.identity_whitelist has invalid type %s; "
        "expected list; treating as empty",
        type(whitelist).__name__,
    )
    return False


def identity_routing_diagnostics() -> dict[str, Any]:
    """Report whether API-server identity routing is actually wired (T2-3).

    ``resolve_api_identity_route`` and ``is_api_identity_whitelisted`` both read
    ``identity_routes`` / ``identity_whitelist`` from the ``user_routing``
    section. When neither key yields an entry, the whole identity chain is
    **dormant**: ``X-Hermes-Identity`` can never resolve a route, so no request
    is ever reverse-proxied to a sub-profile and every one of them is served by
    the root gateway as if the header were absent.

    The authentication gate is **not** among the casualties (T2-6): the
    middleware runs ``ldap_gate`` ahead of any routing decision, so a dormant
    config no longer disables second-factor auth. Before that change the gate
    lived inside the resolved-route branch and was unreachable by construction,
    which is what made dormancy a security trap rather than a plain
    misconfiguration.

    At a call site "this uid is not in ``identity_routes``" and "identity
    routing was never configured" are indistinguishable (both return ``None``),
    which is why the dormant state must be reported explicitly rather than
    inferred from a resolution failure. This helper is read-only and
    side-effect free; it never raises (``config_source="unavailable"`` covers
    loader failure).

    Returns:
        ``dormant``: no usable entries at all — the chain cannot fire.
        ``keys_present``: whether either key exists in the YAML section —
            distinguishes "keys absent" from "keys present but empty".
        ``identity_route_count`` / ``identity_whitelist_count``: entry counts.
        ``config_source``: ``"loaded"`` or ``"unavailable"``. The latter also
            covers a non-Feishu api_server node where ``FEISHU_APP_ID`` is
            unset, since ``_load_routing_config`` is keyed on it.
    """
    routing_cfg = _load_routing_config()
    if not routing_cfg:
        return {
            "dormant": True,
            "keys_present": False,
            "identity_route_count": 0,
            "identity_whitelist_count": 0,
            "config_source": "unavailable",
        }

    routes = routing_cfg.get("identity_routes")
    whitelist = routing_cfg.get("identity_whitelist")
    keys_present = "identity_routes" in routing_cfg or "identity_whitelist" in routing_cfg

    if isinstance(routes, (dict, list, tuple, set, frozenset)):
        route_count = len(routes)
    else:
        route_count = 0

    if isinstance(whitelist, (list, tuple, set, frozenset)):
        whitelist_count = len(whitelist)
    elif isinstance(whitelist, str):
        whitelist_count = 1 if whitelist.strip() else 0
    else:
        whitelist_count = 0

    return {
        "dormant": route_count == 0 and whitelist_count == 0,
        "keys_present": keys_present,
        "identity_route_count": route_count,
        "identity_whitelist_count": whitelist_count,
        "config_source": "loaded",
    }

async def _forward_to_profile_container(
    *,
    endpoint: str,
    api_key: str,
    text: str,
    open_id: str,
    chat_id: str,
    chat_type: str,
    message_id: Optional[str],
    profile: str = "",
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
    body: dict[str, Any] = {
        "schema_version": FEISHU_INBOUND_SCHEMA_VERSION,
        "text": text,
        "message_type": message_type,
        # [owner T2-9] Lets the receiving container check that it is the profile
        # this event was addressed to (see verify_inbound_target_profile).
        TARGET_PROFILE_KEY: profile,
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
    ``overlay fleet_profiles``); it is spliced into the notice so the user
    knows which sub-gateway is down rather than seeing a generic message.
    """
    if not receive_id:
        return
    label = f"「{profile_name}」" if profile_name else ""
    try:
        await adapter.send(
            chat_id=receive_id,
            content=f"💡 子网关{label}暂时不可用，请稍后再试",
        )
    except Exception:
        pass


def _lark_response_classes() -> tuple[Any, Any]:
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


def _build_card_response(card_data: Optional[dict[str, Any]]) -> Any:
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
            {"tag": "markdown", "content": f"💡 子网关{label}暂时不可用，请稍后再试"}
        ],
    }
    return _build_card_response(card)


def _forward_card_action_sync(
    route: tuple[str, str, str],
    event: Any,
    action_value: dict[str, Any],
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
        # [owner T2-9] Same ownership check as the inbound transport — a click
        # must be replayed by the container that owns the card's state.
        TARGET_PROFILE_KEY: profile_name,
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

    card_data: Optional[dict[str, Any]] = None
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

# [owner §17.2] /restart no longer local-only: route resolution now runs FIRST
# in try_route_inbound_message / try_route_bot_menu_command, so a user bound to
# a sub-profile gets /restart forwarded to that container (restarting THEIR
# gateway), while whitelist / unrouted users still restart the main gateway.
# _should_route_text and _LOCAL_ONLY_COMMANDS were removed with that reordering.


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
    gateway: no route resolved for this user. [owner §17.2] /restart is no
    longer local-only — a routed user's /restart restarts THEIR sub-profile
    gateway, not the main one.
    """
    route = resolve_profile_route(chat_id, open_id, chat_type)
    if route is None:
        return False

    profile, endpoint, api_key = route
    is_dm = chat_type == "p2p"
    # Reply/notify fallback target: DM → sender open_id, group → group chat_id.
    notify_target = open_id if is_dm else chat_id

    forwarded = await _forward_to_profile_container(
        endpoint=endpoint,
        api_key=api_key,
        profile=profile,
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


def try_route_card_action(event: Any, action_value: dict[str, Any]) -> Any:
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
    adapter: Any, body: dict[str, Any]
) -> Optional[dict[str, Any]]:
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
    gateway). Returns False only for unrouted users. [owner §17.2] local-only
    command filtering was removed with the /restart routing fix.
    """
    # Bot-menu commands are always DM-context synthetic messages (see the
    # chat_type="p2p" below), so the route resolves in DM mode.  The
    # chat_type parameter has a "p2p" default but is NOT in this function's
    # signature — passing it through was a NameError (2026-09-01 node010 log).
    route = resolve_profile_route(chat_id, open_id)
    if route is None:
        return False

    profile, endpoint, api_key = route
    # Bot-menu commands are always DM-context synthetic messages; the chat_id
    # (p2p oc_) may be unknown here, so the container falls back to open_id.
    forwarded = await _forward_to_profile_container(
        endpoint=endpoint,
        api_key=api_key,
        profile=profile,
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
