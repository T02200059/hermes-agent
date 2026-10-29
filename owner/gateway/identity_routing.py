"""C06: ``X-Hermes-Identity`` auth gate + reverse-proxy middleware.

Design: ``owner/docs/design/c06-ldap-identity-auth/README.md``.

Why an aiohttp middleware (not a gateway hook): needs raw HTTP headers,
early 401/503 JSON, reverse proxy, and byte-streaming SSE — all before
handler dispatch. Official ``api_server.py`` only constructs this via
:func:`make_identity_routing_middleware` and registers the route for
:func:`handle_ldap_identity_access`.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable, Optional
import inspect

logger = logging.getLogger(__name__)

# Verdict → (HTTP status, openai-ish code, message)
_GATE_HTTP = {
    "deny_bad_credentials": (
        401,
        "ldap_auth_failed",
        "LDAP authentication failed for the given identity",
    ),
    "deny_reauth_required": (
        401,
        "ldap_auth_required",
        "LDAP re-authentication required (send X-Hermes-Identity-Password)",
    ),
    "deny_empty_password": (
        401,
        "ldap_auth_required",
        "LDAP re-authentication required (send X-Hermes-Identity-Password)",
    ),
    "deny_invalid_login": (
        401,
        "ldap_identity_invalid",
        "X-Hermes-Identity failed LDAP login validation",
    ),
    "deny_backend_unavailable": (
        503,
        "ldap_backend_unavailable",
        "LDAP backend unavailable; identity could not be verified",
    ),
}


async def identity_gate_rejection(
    identity: str,
    request: Any,
    *,
    web: Any,
    openai_error: Callable[..., dict],
    ldap_gate: Optional[Callable[..., Awaitable[str]]] = None,
) -> Any:
    """Run LDAP gate; return an aiohttp Response to reject, or None to continue."""
    if ldap_gate is None:
        try:
            from owner.gateway.ldap_auth import ldap_gate as _lg

            ldap_gate = _lg
        except ImportError:
            return None

    password = request.headers.get("X-Hermes-Identity-Password", "").strip() or None
    try:
        verdict = await ldap_gate(identity, password)
    except Exception as exc:
        logger.error("[API] ldap_gate raised for %r: %s", identity, exc)
        return web.json_response(
            openai_error(
                "LDAP backend unavailable; identity could not be verified",
                code="ldap_backend_unavailable",
            ),
            status=503,
        )

    if verdict == "allow" or verdict is None:
        return None
    mapped = _GATE_HTTP.get(str(verdict))
    if mapped is None:
        logger.warning("[API] unexpected ldap_gate verdict %r; treating as 503", verdict)
        mapped = _GATE_HTTP["deny_backend_unavailable"]
    status, code, message = mapped
    return web.json_response(openai_error(message, code=code), status=status)


def make_identity_routing_middleware(
    *,
    web: Any,
    owner_import: Callable[[str, str], Any],
    gate_rejection: Callable[[str, Any], Any],
    logger_: Any = None,
) -> Any:
    """Build the identity middleware (deps injected from api_server)."""
    log = logger_ or logger
    dormant_notice_emitted = [False]

    @web.middleware
    async def identity_routing_middleware(request, handler):
        identity = request.headers.get("X-Hermes-Identity", "").strip()
        if not identity:
            return await handler(request)

        rejection = await gate_rejection(identity, request)
        if rejection is not None:
            return rejection

        whitelisted_fn = owner_import(
            "owner.feishu.profile_routing", "is_api_identity_whitelisted"
        )
        if whitelisted_fn is not None and whitelisted_fn(identity):
            return await handler(request)

        resolve_fn = owner_import(
            "owner.feishu.profile_routing", "resolve_api_identity_route"
        )
        if resolve_fn is None:
            return await handler(request)

        route = resolve_fn(identity)
        if route is None:
            diagnose = owner_import(
                "owner.feishu.profile_routing", "identity_routing_diagnostics"
            )
            diag = None
            if diagnose is not None:
                try:
                    diag = diagnose()
                except Exception:
                    diag = None
            if isinstance(diag, dict) and diag.get("dormant"):
                if not dormant_notice_emitted[0]:
                    dormant_notice_emitted[0] = True
                    log.warning(
                        "[API] X-Hermes-Identity=%r ignored: identity routing "
                        "is DORMANT — synthesized identity_routes/whitelist are "
                        "%s (config_source=%s). Request served by root gateway. "
                        "See owner/docs/design/c06-ldap-identity-auth/.",
                        identity,
                        "present but empty"
                        if diag.get("keys_present")
                        else "ABSENT / unavailable",
                        diag.get("config_source"),
                    )
                else:
                    log.debug(
                        "[API] X-Hermes-Identity=%r ignored (identity routing dormant)",
                        identity,
                    )
            else:
                log.warning(
                    "[API] X-Hermes-Identity=%r is unknown; falling through to default",
                    identity,
                )
            return await handler(request)

        profile_name, endpoint_url, api_key = route
        path = request.path
        query = request.query_string
        target = f"{endpoint_url.rstrip('/')}{path}"
        if query:
            target = f"{target}?{query}"

        body = await request.read()
        try:
            parsed_body = json.loads(body) if body else None
        except (ValueError, TypeError):
            parsed_body = None
        is_sse_request = request.method == "POST" and (
            request.path.endswith("/chat/stream")
            or (isinstance(parsed_body, dict) and bool(parsed_body.get("stream")))
        )

        import aiohttp

        headers = {
            k: v
            for k, v in request.headers.items()
            if k.lower()
            not in (
                "host",
                "transfer-encoding",
                "content-length",
                "x-hermes-identity-password",
                "x-hermes-identity",
            )
        }
        headers["Authorization"] = f"Bearer {api_key}"
        headers["X-Forwarded-For"] = getattr(request, "remote", "") or ""

        timeout = (
            aiohttp.ClientTimeout(total=None, sock_read=600, connect=10)
            if is_sse_request
            else aiohttp.ClientTimeout(total=120)
        )
        try:
            async with aiohttp.ClientSession() as session:
                async with session.request(
                    method=request.method,
                    url=target,
                    headers=headers,
                    data=body,
                    timeout=timeout,
                ) as resp:
                    content_type = (resp.headers.get("Content-Type") or "").lower()
                    hop_by_hop = {
                        "transfer-encoding",
                        "content-encoding",
                        "content-length",
                        "connection",
                    }
                    if "text/event-stream" in content_type:
                        resp_headers = {
                            k: v
                            for k, v in resp.headers.items()
                            if k.lower() not in hop_by_hop
                        }
                        stream_resp = web.StreamResponse(
                            status=resp.status, headers=resp_headers
                        )
                        await stream_resp.prepare(request)
                        async for chunk in resp.content.iter_any():
                            await stream_resp.write(chunk)
                        await stream_resp.write_eof()
                        return stream_resp
                    response_body = await resp.read()
                    resp_headers = {
                        k: v
                        for k, v in resp.headers.items()
                        if k.lower() not in hop_by_hop
                    }
                    return web.Response(
                        status=resp.status,
                        headers=resp_headers,
                        body=response_body,
                    )
        except Exception as exc:
            log.error(
                "[API] Identity proxy to %s (%s) failed: %s",
                profile_name,
                endpoint_url,
                exc,
            )
            return web.json_response(
                {"error": f"Sub-gateway '{profile_name}' unavailable"},
                status=503,
            )

    return identity_routing_middleware


async def handle_ldap_identity_access(
    request: Any,
    *,
    web: Any,
    check_auth: Callable[[Any], Any],
    owner_import: Callable[[str, str], Any],
    logger_: Any = None,
) -> Any:
    """GET /v1/ldap/identity/{identity}/access — read-only tri-state query."""
    log = logger_ or logger
    auth_err = check_auth(request)
    if inspect.isawaitable(auth_err):
        auth_err = await auth_err
    if auth_err:
        return auth_err

    identity = (request.match_info.get("identity") or "").strip()
    if not identity:
        return web.json_response(
            {
                "error": {
                    "message": "Missing LDAP identity in request path",
                    "type": "invalid_request_error",
                }
            },
            status=400,
        )

    resolve_fn = owner_import(
        "owner.feishu.profile_routing", "resolve_api_identity_route"
    )
    whitelist_fn = owner_import(
        "owner.feishu.profile_routing", "is_api_identity_whitelisted"
    )
    diagnose = owner_import(
        "owner.feishu.profile_routing", "identity_routing_diagnostics"
    )
    if resolve_fn is None:
        log.warning(
            "[API] ldap identity access: profile_routing unavailable for %r",
            identity,
        )
        return web.json_response(
            {
                "error": {
                    "message": "Identity routing module unavailable on this gateway",
                    "type": "gateway_unavailable",
                }
            },
            status=503,
        )

    try:
        whitelisted = bool(whitelist_fn(identity)) if whitelist_fn else False
        route = None if whitelisted else resolve_fn(identity)
    except Exception:
        log.exception("[API] ldap identity access lookup failed for %r", identity)
        return web.json_response(
            {
                "error": {
                    "message": "Identity lookup failed",
                    "type": "server_error",
                }
            },
            status=500,
        )

    routing_dormant = None
    routing_keys_present = None
    if diagnose is not None:
        try:
            diag = diagnose()
        except Exception:
            diag = None
        if isinstance(diag, dict):
            routing_dormant = bool(diag.get("dormant"))
            routing_keys_present = bool(diag.get("keys_present"))

    routed = route is not None
    return web.json_response(
        {
            "object": "hermes.api_server.ldap_identity_access",
            "ldap_identity": identity,
            "routed": routed,
            "profile": route[0] if route else None,
            "whitelisted": whitelisted,
            "allowed": bool(routed or whitelisted),
            "routing_dormant": routing_dormant,
            "routing_keys_present": routing_keys_present,
        }
    )
