"""C06b: identity middleware + access probe (no live HTTP upstream)."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from owner.gateway import identity_routing as ir
from owner.gateway import ldap_auth as la


def _openai_error(message, err_type="invalid_request_error", param=None, code=None):
    err = {"message": message, "type": err_type}
    if code:
        err["code"] = code
    return {"error": err}


@pytest.fixture(autouse=True)
def _reset_ldap():
    la.reset_for_tests()
    yield
    la.reset_for_tests()


@pytest.mark.asyncio
async def test_gate_rejection_maps_verdicts():
    async def fake_gate(login, password):
        return la.DENY_BAD_CREDENTIALS

    req = MagicMock()
    req.headers = {"X-Hermes-Identity-Password": "x"}
    resp = await ir.identity_gate_rejection(
        "alice", req, web=web, openai_error=_openai_error, ldap_gate=fake_gate
    )
    assert resp.status == 401
    body = resp.body
    # json body
    import json

    data = json.loads(body.decode() if isinstance(body, (bytes, bytearray)) else body)
    assert data["error"]["code"] == "ldap_auth_failed"


@pytest.mark.asyncio
async def test_middleware_passthrough_without_identity_header():
    async def ok_handler(request):
        return web.json_response({"ok": True})

    async def gate(*a, **k):
        raise AssertionError("gate must not run")

    async def gate_rejection(identity, request):
        raise AssertionError("must not run")

    def owner_import(mod, name):
        raise AssertionError("must not import")

    mw = ir.make_identity_routing_middleware(
        web=web,
        owner_import=owner_import,
        gate_rejection=gate_rejection,
    )

    @web.middleware
    async def chain(request, handler):
        return await mw(request, handler)

    app = web.Application(middlewares=[mw])
    app.router.add_get("/ping", ok_handler)
    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/ping")
        assert resp.status == 200
        assert await resp.json() == {"ok": True}


@pytest.mark.asyncio
async def test_middleware_whitelist_skips_proxy_after_gate():
    async def ok_handler(request):
        return web.json_response({"hub": True})

    async def gate_rejection(identity, request):
        return None  # authenticated

    def owner_import(mod, name):
        if name == "is_api_identity_whitelisted":
            return lambda ident: ident == "hubops"
        if name == "resolve_api_identity_route":
            return lambda ident: (_ for _ in ()).throw(
                AssertionError("should not resolve")
            )
        return None

    mw = ir.make_identity_routing_middleware(
        web=web, owner_import=owner_import, gate_rejection=gate_rejection
    )
    app = web.Application(middlewares=[mw])
    app.router.add_get("/v1/models", ok_handler)
    async with TestClient(TestServer(app)) as client:
        resp = await client.get(
            "/v1/models", headers={"X-Hermes-Identity": "hubops"}
        )
        assert resp.status == 200
        assert await resp.json() == {"hub": True}


@pytest.mark.asyncio
async def test_middleware_strips_identity_headers_on_proxy():
    """Upstream must not see identity / password headers (anti self-loop)."""
    seen = {}

    async def upstream(request):
        seen["headers"] = {k.lower(): v for k, v in request.headers.items()}
        return web.json_response({"proxied": True})

    up_app = web.Application()
    up_app.router.add_post("/v1/chat/completions", upstream)
    up_server = TestServer(up_app)
    await up_server.start_server()
    try:
        endpoint = str(up_server.make_url("/")).rstrip("/")

        async def gate_rejection(identity, request):
            return None

        def owner_import(mod, name):
            if name == "is_api_identity_whitelisted":
                return lambda ident: False
            if name == "resolve_api_identity_route":
                return lambda ident: ("yangtb", endpoint, "secret-key")
            if name == "identity_routing_diagnostics":
                return lambda: {
                    "dormant": False,
                    "keys_present": True,
                    "config_source": "loaded",
                }
            return None

        mw = ir.make_identity_routing_middleware(
            web=web, owner_import=owner_import, gate_rejection=gate_rejection
        )
        app = web.Application(middlewares=[mw])
        async def _local(r):
            return web.json_response({"local": True})

        app.router.add_post("/v1/chat/completions", _local)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/v1/chat/completions",
                json={"model": "x", "messages": []},
                headers={
                    "X-Hermes-Identity": "yangtb",
                    "X-Hermes-Identity-Password": "super-secret",
                    "Authorization": "Bearer client-key",
                },
            )
            assert resp.status == 200
            assert await resp.json() == {"proxied": True}
            assert "x-hermes-identity" not in seen["headers"]
            assert "x-hermes-identity-password" not in seen["headers"]
            assert seen["headers"].get("authorization") == "Bearer secret-key"
    finally:
        await up_server.close()


@pytest.mark.asyncio
async def test_access_endpoint_tri_state():
    def owner_import(mod, name):
        if name == "resolve_api_identity_route":
            return lambda ident: (
                ("yangtb", "http://127.0.0.1:9", "k") if ident == "yangtb" else None
            )
        if name == "is_api_identity_whitelisted":
            return lambda ident: ident == "hubops"
        if name == "identity_routing_diagnostics":
            return lambda: {
                "dormant": False,
                "keys_present": True,
                "identity_route_count": 1,
                "identity_whitelist_count": 1,
                "config_source": "loaded",
            }
        return None

    def check_auth(request):
        return None

    req = MagicMock()
    req.match_info = {"identity": "yangtb"}
    resp = await ir.handle_ldap_identity_access(
        req, web=web, check_auth=check_auth, owner_import=owner_import
    )
    import json

    data = json.loads(resp.body.decode())
    assert data["allowed"] is True
    assert data["routed"] is True
    assert data["profile"] == "yangtb"
    assert data["whitelisted"] is False
    assert data["routing_dormant"] is False

    req2 = MagicMock()
    req2.match_info = {"identity": "hubops"}
    resp2 = await ir.handle_ldap_identity_access(
        req2, web=web, check_auth=check_auth, owner_import=owner_import
    )
    data2 = json.loads(resp2.body.decode())
    assert data2["whitelisted"] is True
    assert data2["routed"] is False
    assert data2["allowed"] is True

    req3 = MagicMock()
    req3.match_info = {"identity": "nobody"}
    resp3 = await ir.handle_ldap_identity_access(
        req3, web=web, check_auth=check_auth, owner_import=owner_import
    )
    data3 = json.loads(resp3.body.decode())
    assert data3["allowed"] is False
    assert data3["routing_dormant"] is False
