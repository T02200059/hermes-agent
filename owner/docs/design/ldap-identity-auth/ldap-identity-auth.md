# ldap_identity_auth：LDAP 登录认证 + 身份路由准入

> 记录时间：2026-10-23　|　代码位置：`owner/gateway/ldap_auth.py`（核心）、`owner/feishu/profile_routing.py`（路由诊断）、`gateway/platforms/api_server.py`（薄委托）
> 编排模式：**门面 + 独立状态机**（owner 独占模块，官方文件只留委托入口）

## 一、要解决的问题

`xy-portal` 的智能巡检要按"当前登录是谁"决定能不能进。原始需求只有一句"接 LDAP 验证身份"，但实现时必须回答四个互相牵连的问题：

1. **认证**：账号密码怎么验，验过之后凭什么免验？
2. **准入**：验过了，这个人有没有权限进这个功能？
3. **降级**：LDAP 服务器挂了，是放行还是拒绝？
4. **可观测**：链路没接线时，消费方怎么知道自己拿到的是"没权限"还是"没人配"？

第 4 条是这模块真正的难点——**"未接线"与"拒绝"如果无法区分，下游会把未接线放大成全员禁入**。

## 二、结构

```
owner/gateway/ldap_auth.py
├── _normalize_login()        # casefold+strip，缓存键唯一化（T3-1）
├── _build_user_dn()          # 模板替换 + RFC4514 转义（DN 注入防护）
├── _state_file_*()           # 跨进程正向缓存（HMAC 完整性，T3-2）
├── _cache_get/_put/_evict()  # 内存 LRU + TTL
├── _negative_put/_active()   # 负缓存（防爆破）
└── authenticate()            # 唯一对外入口
```

官方文件侧（`gateway/platforms/api_server.py`）只有薄委托：中间件取 `X-Hermes-Identity` → 调 `try_route_inbound_message` → 未命中再走 LDAP gate。**核心逻辑一行都不在官方文件里**，删除 `owner/gateway/ldap_auth.py` 后官方代码仍可正常运行。

## 三、四个关键决策

### 3.1 缓存键必须规范化

**问题**：`Alice` 与 `alice` 是同一个 LDAP 账号，但作为缓存键是两个。后果是两个方向都坏：

- 正向缓存：同一个人登录两次，第二次仍要走网络认证
- **负缓存失效（更严重）**：爆破者可以用 `alice` / `Alice` / `ALICE` 轮换，绕过负缓存的次数限制

**决策**：`_normalize_login()` 用 `casefold() + strip()` 作为**缓存键**；构造 DN 时仍用用户原始输入的 login（LDAP 侧大小写语义由服务端决定，本地不越权改写）。

### 3.2 状态文件必须防篡改

**问题**：正向缓存落盘在 `~/.hermes/ldap_identity_cache.json`，文件权限 `0600` 是对的，但 **agent 自己能写**（它就跑在同一个 uid 下）。写入目标态即可免密：

```json
{"version": 2, "entries": {"alice": 9999999999}}
```

**决策**：进程内随机 HMAC 密钥（**不落盘**）+ 文件内 `mac` 字段。

- 无签名 / 错签 / 版本不符 → **一律忽略整个文件**（fail-closed）
- 密钥不持久化 ⇒ 进程重启后缓存自然失效、需重新认证

这是刻意的权衡：**缓存的目的只是"同进程内免重复网络认证"，不是"跨重启免登录"**。跨重启免登录的收益远小于"文件可被伪造"的风险。

### 3.3 失败方向：fail-closed，但要说清是哪一种

| 情形 | 判定 | 理由 |
|---|---|---|
| LDAP 服务器不可达 | 拒绝 | 认证是准入前提，不可达 ≠ 通过 |
| 用户名/密码错误 | 拒绝 + 负缓存 | 防爆破 |
| 配置缺失（无 LDAP 配置段） | **dormant**，不是"拒绝" | 见 3.4 |
| 状态文件损坏/无签名 | 忽略文件，重新认证 | 不信任来源不明的状态 |

注意与 `owner/approval/approval_history_policy.py` 的区别：那里 `status` 字段优先于一切，同理这里 **`config_source` 先于认证结果被报告**。

### 3.4 「未接线」是第三态，不是「拒绝」

**问题**（实测踩过）：`identity_routes` / `identity_whitelist` 两个键从未写入配置时，端点对任何 uid 都返回 `allowed: false`。而消费方（`xy-portal`）按契约把 `false` 读作"必须拒绝" ⇒ **未接线被放大成全员禁入**，且没有任何日志说明原因。

**决策**：把"配置在不在"变成显式可查的状态，三处同时暴露：

1. `identity_routing_diagnostics()` 返回 `{config_source, keys_present, dormant, ...}`
2. 中间件 `route is None` 分支区分"该 uid 未配置"与"整条链路未接线"，后者打印**一次**点名后果与成因的告警（每中间件实例一次，避免按请求刷屏）
3. `GET /v1/ldap/identity/{uid}/access` 响应新增 `routing_dormant` / `routing_keys_present`

**最关键的一条**：`config_source=loaded` + `keys_present=false` = "键从未写入"；`loaded` + `true` = "键在但被清空"；`unavailable` = "段取不到"。三者成因不同、修法不同，**不能合并成一个 `enabled: false`**。

**另一个坑**：`_load_routing_config()` 以 `FEISHU_APP_ID` 为入口。纯 `api_server` 节点即使配好了键也读不到 —— 这是与"键缺失"**不同的**另一种 dormant 成因，诊断函数必须能分辨。

## 四、可移除性

| 删除对象 | 后果 |
|---|---|
| `owner/gateway/ldap_auth.py` | LDAP 认证与准入失效，`/v1/ldap/*` 端点返回 500；飞书路由不受影响 |
| `owner/feishu/profile_routing.py` | 多 profile 路由回退到单 profile；identity 路由一并消失 |

两者互不依赖，官方文件侧只有委托调用，删除后官方代码可正常 import 与运行。

## 五、守卫与验证

- `tests/owner/test_identity_routing_dormant.py`（14 例）：诊断五分档 / 中间件透传 + 告警 + 只提示一次 / `ldap_gate` 探针 / 端点 dormant 与**已接线对照组**
- `tests/owner/test_owner_429_reset_window.py` 同族范式：断言"删掉 owner 产品代码后必须变红"
- **变异验证 3 条全红**：关掉 dormant 分支 → 2 例失败；端点不返回 `routing_dormant` → 3 例失败；`keys_present` 恒真 → 3 例失败

**探针陷阱**（踩过）：`ldap_gate` 探针必须同时清 `_owner_lazy` 缓存，否则会静默命中旧函数使断言变成空断言。
