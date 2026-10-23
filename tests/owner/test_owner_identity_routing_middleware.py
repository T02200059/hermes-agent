"""Guard: identity 中间件的四阶段契约（T2-3 / T2-6）。

New-baseline owner test (2026-10-23). 这一族原本**零测试覆盖** —— `X-Hermes-Identity`
与 `identity_routing` 在 `tests/` 里搜不到任何引用。按 §八.2 ④「每个安全控制项上线
前必须有一条端到端负例冒烟」，此处补齐后再做迁移。

为什么必须在 owner 侧自带：整段中间件（认证门 → 白名单 → 路由 → 反代）是 owner
在 `gateway/platforms/api_server.py` 里的定制，上游没有对应实现。

**T2-6 是这里最要紧的一条**：认证门必须跑在任何路由判定之前。历史缺陷是白名单命中
就 early return，于是"由 root 处理"被读成了"不需要二次认证"——而 identity 头是
任何人只要能连到网关就能设的**声明**。以下用例把这条钉死。

另钉：反代必须剥掉 identity 头（否则子容器会再解析、把自己代理到自己，直到
aiohttp 超时），以及反代失败要显式 503 而不是静默透传。
"""

from __future__ import annotations

import asyncio
import contextlib

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import gateway.platforms.api_server as api_server


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@contextlib.asynccontextmanager
async def _identity_app(*, gate=None, whitelisted=None, route=None, diag=None):
    """只有 identity 中间件的 app，三个 owner 依赖以 stub 注入。

    用 context manager 而不是普通协程：补丁必须在**整个请求期间**保持生效。
    写成 `await start_server(); return client` 时，`finally` 会在调用方发请求之前
    就恢复原函数，所有 stub 静默失效、用例读到的全是透传结果。
    """
    hits: list = []

    async def handler(request):
        hits.append(request.headers.get("X-Hermes-Identity"))
        return web.json_response({"served_by": "root"})

    adapter = api_server.APIServerAdapter.__new__(api_server.APIServerAdapter)

    orig_import = api_server._owner_import
    orig_gate = api_server._owner_identity_gate_rejection

    def _stub_import(module, name):
        if module == "owner.feishu.profile_routing":
            if name == "is_api_identity_whitelisted":
                return whitelisted
            if name == "resolve_api_identity_route":
                return route
            if name == "identity_routing_diagnostics":
                return diag
        return orig_import(module, name)

    async def _stub_gate(identity, request):
        if gate is None:
            return None
        return gate(identity, request)

    api_server._owner_import = _stub_import
    api_server._owner_identity_gate_rejection = _stub_gate
    client = None
    try:
        mw = adapter._make_identity_routing_middleware()
        app = web.Application(middlewares=[mw])
        app.router.add_route("*", "/{tail:.*}", handler)
        client = TestClient(TestServer(app))
        await client.start_server()
        yield client, hits
    finally:
        if client is not None:
            await client.close()
        api_server._owner_import = orig_import
        api_server._owner_identity_gate_rejection = orig_gate


# ── 阶段 1：无头透传 ────────────────────────────────────────────────────────

def test_request_without_identity_header_passes_through():
    async def _t():
        async with _identity_app() as (client, hits):
            resp = await client.get("/v1/models")
            assert resp.status == 200
            assert (await resp.json())["served_by"] == "root"
            assert hits == [None]

    _run(_t())


# ── 阶段 2：认证门先行（T2-6 核心）─────────────────────────────────────────

def test_gate_runs_before_the_whitelist():
    """白名单命中**不得**跳过认证门。

    历史缺陷：白名单 early return，"root 处理"被当成"无需二次认证"。
    identity 头是任何人都能声明的值，跳过认证等于把门拆了。
    """
    gate_called: list = []

    async def _t():
        def gate(identity, request):
            gate_called.append(identity)
            return web.json_response({"error": "unauthenticated"}, status=401)

        def whitelisted(identity):
            return True

        def route(identity):
            return None

        async with _identity_app(
            gate=gate, whitelisted=whitelisted, route=route
        ) as (client, hits):
            resp = await client.get("/v1/models", headers={"X-Hermes-Identity": "alice"})
            assert resp.status == 401, "认证门被白名单绕过了"
            assert gate_called == ["alice"], "认证门根本没跑"
            assert hits == [], "拒绝后不应到达 handler"

    _run(_t())


def test_gate_runs_before_route_resolution():
    """未知 identity / 路由解析失败也必须先过认证门（T2-6 的第二个漏洞）。"""
    gate_called: list = []

    async def _t():
        def gate(identity, request):
            gate_called.append(identity)
            return web.json_response({"error": "unauthenticated"}, status=401)

        def route(identity):
            return None

        async with _identity_app(gate=gate, route=route) as (client, hits):
            resp = await client.get("/x", headers={"X-Hermes-Identity": "ghost"})
            assert resp.status == 401
            assert gate_called == ["ghost"]
            assert hits == []

    _run(_t())


# ── 阶段 3：白名单 → root 处理 ──────────────────────────────────────────────

def test_whitelisted_identity_is_served_by_root_after_gate():
    """过了认证门 + 白名单命中 → 由 root 处理，即使配了路由也不反代。"""

    async def _t():
        def whitelisted(identity):
            return True

        def route(identity):
            return ("sub", "http://127.0.0.1:1", "key")

        async with _identity_app(
            whitelisted=whitelisted, route=route
        ) as (client, hits):
            resp = await client.get("/v1/models", headers={"X-Hermes-Identity": "alice"})
            assert resp.status == 200
            assert (await resp.json())["served_by"] == "root"
            assert hits == ["alice"]

    _run(_t())


def test_unknown_identity_falls_through_to_root():
    async def _t():
        def route(identity):
            return None

        async with _identity_app(route=route) as (client, hits):
            resp = await client.get("/v1/models", headers={"X-Hermes-Identity": "nobody"})
            assert resp.status == 200
            assert hits == ["nobody"]

    _run(_t())


def test_missing_owner_module_falls_through():
    """owner/ 缺失时（_owner_import 返回 None）fail-open 透传，不炸。"""

    async def _t():
        async with _identity_app(whitelisted=None, route=None) as (client, hits):
            resp = await client.get("/v1/models", headers={"X-Hermes-Identity": "alice"})
            assert resp.status == 200
            assert hits == ["alice"]

    _run(_t())


# ── 阶段 4：反代 ────────────────────────────────────────────────────────────

def test_proxy_strips_identity_headers_and_injects_bearer():
    """反代必须剥掉 identity 两个头，并注入 ``Authorization: Bearer <route key>``。

    不剥 identity 头 → 子容器用同一套 routing 配置再解析一次 → 把自己代理到自己，
    直到 aiohttp 超时/递归以 503 收场。LDAP 口令头则绝不能越过代理边界。
    """
    received: dict = {}

    async def _upstream(request):
        received.update({k.lower(): v for k, v in request.headers.items()})
        return web.json_response({"served_by": "sub"})

    async def _t():
        up_app = web.Application()
        up_app.router.add_route("*", "/{tail:.*}", _upstream)
        up = TestClient(TestServer(up_app))
        await up.start_server()
        try:
            def route(identity):
                return ("sub", str(up.make_url("")).rstrip("/"), "sub-key")

            async with _identity_app(route=route) as (client, _hits):
                resp = await client.get(
                    "/v1/models",
                    headers={
                        "X-Hermes-Identity": "alice",
                        "X-Hermes-Identity-Password": "ldap-secret",
                    },
                )
                assert resp.status == 200
                assert (await resp.json())["served_by"] == "sub"
        finally:
            await up.close()

    _run(_t())

    assert "x-hermes-identity" not in received, "identity 头被转发 → 会无限自代理"
    assert "x-hermes-identity-password" not in received, "LDAP 口令越过了代理边界"
    assert received.get("authorization") == "Bearer sub-key"


def test_proxy_failure_returns_503_not_a_silent_passthrough():
    """反代失败必须显式 503。

    静默透传给 root 会把"子容器挂了"变成"请求被错误的实例处理"——用户看到 200，
    但对象是另一个 profile 的会话。
    """

    async def _t():
        def route(identity):
            return ("sub", "http://127.0.0.1:1", "k")

        async with _identity_app(route=route) as (client, hits):
            resp = await client.get("/v1/models", headers={"X-Hermes-Identity": "alice"})
            assert resp.status == 503
            assert hits == [], "反代失败后不应落到 root handler"

    _run(_t())


# ── dormant 提示：每进程一次 ────────────────────────────────────────────────

def test_dormant_routing_is_reported_once(monkeypatch):
    """结构性条件（identity routing 从未接线）逐请求刷屏会淹没日志，只响一次。"""
    warnings: list = []

    def _capture(msg, *a, **k):
        warnings.append(msg % a if a else msg)

    monkeypatch.setattr(api_server.logger, "warning", _capture)

    async def _t():
        def route(identity):
            return None

        def diag():
            return {"dormant": True, "keys_present": False, "config_source": "loaded"}

        async with _identity_app(route=route, diag=diag) as (client, _hits):
            for _ in range(3):
                await client.get("/x", headers={"X-Hermes-Identity": "alice"})

    _run(_t())

    dormant = [w for w in warnings if "DORMANT" in str(w)]
    assert len(dormant) == 1, f"dormant 提示响了 {len(dormant)} 次（应恰好 1 次）"
    assert "ABSENT" in str(dormant[0])
