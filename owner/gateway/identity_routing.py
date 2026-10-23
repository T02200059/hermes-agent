"""X-Hermes-Identity 的认证门 + 反代中间件（owner 定制）。

原位于 `gateway/platforms/api_server.py` 的 `_make_identity_routing_middleware`
（233 行）。上游没有对应实现，整段是 owner 定制 —— 按 §2.1「最小侵入源码」与
附录 C 第 11 项的要求收敛到此处，官方文件只留三行委托。

## 为什么必须是 aiohttp 中间件，不能是 plugin hook

曾评估迁入 `owner-extensions`（附录 C 第 11 项的原始问题）。结论：**不可行**。

`pre_gateway_dispatch` 在 `gateway/run_inbound.py` 触发，参数是已经解析好的
`MessageEvent` + `gateway`，能力是 `skip / rewrite / allow`。而这里需要的是：

| 需要 | hook 能否提供 |
|---|---|
| 读原始 HTTP 头（`X-Hermes-Identity`、口令头） | ✗ 事件已被规范化 |
| 自行返回 401/503 JSON 响应（在 handler 之前） | ✗ 只能丢弃或改写事件 |
| 把请求改道到另一个容器（反向代理） | ✗ 没有出站路径 |
| 逐字节透传 SSE 流 | ✗ 拿到的是解析后的事件 |

四阶段全部发生在**路由分发之前**，属于 HTTP 层语义。所以它只能是中间件；
能收敛的只是"实现搬去 owner/"，不是"换一种注入方式"。

## 四阶段（顺序即安全语义）

1. 无 identity 头 → 透传
2. **LDAP 二次认证门 → 401/503，先于一切路由判定**
3. 白名单命中 → 透传（由 root gateway 本体处理）
4. 路由命中 → 反向代理到该子 profile

第 2 步的顺序是 T2-6 的核心：identity 头只是一个**声明**，任何人只要能连到网关
就能设。历史缺陷是白名单命中就 early return，于是"由 root 处理"被读成"无需二次
认证"；另一个漏洞是路由解析失败也落到未设防的默认路径。认证门因此与路由解耦 ——
它回答"这个声明是否已认证"，该答案在任何后续分支下都必须成立。

## 依赖注入

`web` / `owner_import` / `gate_rejection` 由官方文件传入：本模块不导入
`gateway.platforms.api_server`（会形成循环导入），也不复制它的逻辑。
"""

from __future__ import annotations

import json
from typing import Any, Callable, Optional


def make_identity_routing_middleware(
    *,
    web: Any,
    owner_import: Callable[[str, str], Any],
    gate_rejection: Callable[[str, Any], Any],
    logger: Any,
) -> Any:
    """构造 identity 路由中间件。

    参数都是官方模块的运行时依赖，由调用方注入：

    - ``web``：``aiohttp.web``（``@middleware`` / ``StreamResponse`` / ``Response``）
    - ``owner_import(module, name)``：官方的懒导入助手，owner/ 缺失时返回 ``None``
    - ``gate_rejection(identity, request)``：异步，返回可发送的拒绝响应或 ``None``
    - ``logger``：官方模块的 logger（日志归属一致，便于排查）
    """
    # [owner] T2-3: 下面的 dormant 提示每进程只响一次。结构性问题（identity
    # 路由从未接线）逐请求重复只会淹没日志，不增加信息。
    dormant_notice_emitted = [False]

    @web.middleware
    async def identity_routing_middleware(request, handler):
        identity = request.headers.get("X-Hermes-Identity", "").strip()
        if not identity:
            return await handler(request)

        # [owner] T2-6: 认证门先行。identity 头是**身份声明**，决定该声明是否已
        # 认证的是门、不是路由表。把它放在任何路由判定之前，才能堵住两条绕行：
        #   - 白名单身份提前返回，"root 处理"被当成"无需二次因子"——而这个头
        #     任何人只要能连到网关就能设；
        #   - 路由解析失败的身份（未知 uid，或已注册但 profile_endpoints 配坏的
        #     uid）落到未设防的默认路径。
        # 此后路由只选择目的地，不再决定该声明是否被验证。
        _rejection = await gate_rejection(identity, request)
        if _rejection is not None:
            return _rejection

        # [owner] LDAP identity whitelist —— 与飞书 user_routing.whitelist 同语义：
        # 白名单内的 LDAP 身份不反代到子容器，直接由 root gateway 本体处理（对话
        # 落在 root 实例的 memory/会话）。优先级高于 identity_routes；owner/ 模块
        # 缺失时 fail-open 跳过。白名单只决定「不反代」，**不决定「免认证」** ——
        # 认证已在上一步完成（T2-6）。
        _whitelisted = owner_import(
            "owner.feishu.profile_routing", "is_api_identity_whitelisted"
        )
        if _whitelisted is not None and _whitelisted(identity):
            return await handler(request)

        _resolve = owner_import(
            "owner.feishu.profile_routing", "resolve_api_identity_route"
        )
        if _resolve is None:
            return await handler(request)

        route = _resolve(identity)
        if route is None:
            # [owner] T2-3: "不在 identity_routes 里"与"identity 路由从未接线"都会
            # 走到这里，后者是一个值得点名值得解释的安全陷阱 —— 沉睡的配置会把每个
            # 带头的请求变成普通默认路径请求，而且没有任何信号。认证门已不再是它的
            # 后果之一（T2-6 让它跑在路由判定之前），这正是这条提示不能那么说的原因。
            _diagnose = owner_import(
                "owner.feishu.profile_routing", "identity_routing_diagnostics"
            )
            _diag = None
            if _diagnose is not None:
                try:
                    _diag = _diagnose()
                except Exception:  # pragma: no cover - 诊断永不打断入站
                    _diag = None
            if isinstance(_diag, dict) and _diag.get("dormant"):
                if not dormant_notice_emitted[0]:
                    dormant_notice_emitted[0] = True
                    logger.warning(
                        "[API] X-Hermes-Identity=%r ignored: identity routing "
                        "is DORMANT — identity_routes/identity_whitelist are %s "
                        "(routing section: %s). Consequence: no sub-profile "
                        "reverse-proxy — the request is served by the root "
                        "gateway, as if the header were absent. See "
                        "owner改动清单 §15.",
                        identity,
                        "present but empty"
                        if _diag.get("keys_present")
                        else "ABSENT from user_routing",
                        _diag.get("config_source"),
                    )
                else:
                    logger.debug(
                        "[API] X-Hermes-Identity=%r ignored (identity routing dormant)",
                        identity,
                    )
            else:
                logger.warning(
                    "[API] X-Hermes-Identity=%r is unknown; falling through to default",
                    identity,
                )
            return await handler(request)

        profile_name, endpoint_url, api_key = route

        # 目标 URL：同一路径 + 查询串
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
            or (
                isinstance(parsed_body, dict)
                and bool(parsed_body.get("stream"))
            )
        )

        # 转发头：剥掉逐跳头并补认证。LDAP 口令头**绝不**越过代理边界。identity
        # 头也要剥：子 profile 容器跑同一套 routing 配置（identity_routes +
        # profile_endpoints），转过去会让子网关重新解析并把请求代理回自己，形成
        # 无限循环，直到 aiohttp 的 120s 超时/递归以 503 收场。
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

        # 长时 SSE 轮次（工具循环、大段生成）可能远超 120s 仍然活着：旧的
        # ``total=120`` 硬顶会把合法的长流中途掐断。流式请求保持 total 无上限
        # （客户端断连会通过连接重置传导）；缓冲型 JSON 回包仍适用连接/读取预算。
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
                    if "text/event-stream" in content_type:
                        # SSE 必须逐块透传：整包缓冲会把首字节推迟到整轮结束。
                        resp_headers = {
                            k: v
                            for k, v in resp.headers.items()
                            if k.lower()
                            not in (
                                "transfer-encoding",
                                "content-encoding",
                                "content-length",
                                "connection",
                            )
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
                        if k.lower()
                        not in (
                            "transfer-encoding",
                            "content-encoding",
                            "content-length",
                            "connection",
                        )
                    }
                    return web.Response(
                        status=resp.status,
                        headers=resp_headers,
                        body=response_body,
                    )
        except Exception as exc:
            logger.error(
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
