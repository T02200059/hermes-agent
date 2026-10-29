# C06：API Server LDAP 身份准入（v2）

> 记录：2026-10-29　|　分支 **v2**　|　**不照搬 owner 分支实现**；按 C05 `fleet_profiles` 形状 + 二次开发规范（Hook/owner 委托、官方文件极薄胶水）重做。
> 生产切流（C05b / node010）**不在本轮**。

## 一、问题

`xy-portal` 等消费方按「当前登录是谁」决定能否进对话。`X-Hermes-Identity` 是**声明式头**，任何人可伪造，必须回答：

1. **认证**：账号密码怎么验，验过之后凭什么免验？
2. **准入 / 路由**：验过了，此人走 Hub 还是子容器？
3. **降级**：LDAP 不可达是放行还是拒绝？
4. **可观测**：「未接线」与「拒绝」必须可区分，否则未接线会被放大成全员禁入。

## 二、配置形状（对齐 C05）

| 键 | 作用 | 谁读 |
|---|---|---|
| 顶层 **`ldap:`**（overlay 优先，patch 回落） | 连接 / `enabled` / `enforce` / TTL / `fail_open_on_error` | **C06** |
| **`fleet_profiles.<uid>.hub_only.api`** | `true` → 该 identity **留 Hub**（旧 `identity_whitelist`） | C05 合成表；**C06** 路由用 |
| **`fleet_profiles.<uid>.api_server`** | 推导 endpoints；有 endpoint 且非 hub_only.api → 可反代 | C05；C06 路由 |
| ~~顶层 `api_identity` / 飞书节 `identity_*`~~ | **只读别名**（迁移期）；终态废弃 | C06 经 C05 `_derive_identity_tables` |

```yaml
ldap:
  enabled: false          # 本机默认关；现网开启时再改
  host: "ldap.example.com"
  port: 389
  use_ssl: false
  timeout_seconds: 5
  user_dn_template: "cn={login},cn=people,dc=example,dc=com"
  enforce: "always"       # off | always | seen(=always 别名)；未知值 → always
  cache_ttl_hours: 72
  negative_cache_seconds: 10
  fail_open_on_error: false   # 带密码但不可验证时默认 503；true 为显式降级

fleet_profiles:
  yangtb:
    api_server: { url: "http://127.0.0.1:26001", api_key: "…" }
    hub_only: { feishu: false, api: false }
  hubops:
    hub_only: { api: true }   # API 身份留 Hub
```

**禁止**把真实 `admin_password` / `api_key` 写入仓内示例。

## 三、模块边界

```
owner/gateway/ldap_auth.py          # bind + 正/负缓存 + ldap_gate()
owner/gateway/identity_routing.py   # 中间件 + 准入查询处理
owner/feishu/profile_routing.py     # 已有：合成 identity_* / resolve / whitelist / diagnostics（C05）
gateway/platforms/api_server.py     # 极薄：注册中间件 + 路由 + 委托（# [owner] C06）
```

官方文件**不**放 LDAP / 反代实现。不能用 `pre_gateway_dispatch` hook：需要原始 HTTP 头、401/503、反向代理与 SSE 透传。

## 四、四阶段中间件（顺序即安全语义）

1. 无 `X-Hermes-Identity` → 透传  
2. **`ldap_gate` 先行** → 401/503（先于一切路由；T2-6）  
3. `hub_only.api` / whitelist 命中 → 透传 Hub（**不**免认证）  
4. `resolve_api_identity_route` 命中 → 反代子容器（剥 `X-Hermes-Identity` + 密码头；SSE 逐 chunk）

## 五、`ldap_gate` 判定（摘要）

| 情形 | 判定 |
|---|---|
| `enabled: false` 且配置可读 | `allow`（门未开） |
| 配置文件存在但 ldap 段损坏/不可解析 | `deny_backend_unavailable`（fail-closed） |
| 密码 bind 成功 | `allow` + 正缓存 |
| 密码错误 | `deny_bad_credentials` + 负缓存；清正缓存 |
| 空密码 | `deny_empty_password`（防匿名 bind 假成功） |
| 无密码 + 有效正缓存 | `allow` |
| 无密码 + `enforce`∈{always,seen} | `deny_reauth_required` |
| 无密码 + `enforce=off` | `allow`（唯一灰度档；负缓存期内仍拒） |
| 带密码但不可验证（超时等） | 默认 503；`fail_open_on_error` 显式放行 |
| `no_config` / `ldap3_missing` | 一律 503（不受 fail_open） |

缓存键：`casefold()+strip()`。状态文件 HMAC（进程内密钥、不落盘）；坏签忽略整文件。

## 六、切片

| 切片 | 内容 | 本轮 |
|---|---|---|
| **C06a** | 设计稿 + `ldap_auth` + 单测（mock bind） | ✅ |
| **C06b** | `identity_routing` 中间件 + api_server 薄胶水 + 准入查询 + 头剥离/SSE | ✅ |
| **C06c** | 现网 `ldap:` 接线 / E2E 真 LDAP | ✅ 本轮（连接字段进 overlay；启用默认关；探针+E2E） |
| **C05b** | node010 切流 | **最后**（用户拍板） |
| **C07** | API media | 延后 |

## 七、可移除性

删除 `owner/gateway/ldap_auth.py` / `identity_routing.py` → 身份门与反代失效；飞书 C05 路由不受影响。官方文件仅委托，owner 缺失时 `_owner_import` 返回 None → 无 identity 头行为与上游一致。

## 八、落地状态（2026-10-29）

- **C06a/b 已落地（v2 重做，不照搬 owner）**：`ldap_auth` / `identity_routing` + api_server `_owner_import` 薄胶水 + overlay `ldap.enabled:false` 桩 + `pyproject` optional `ldap`；单测 `test_c06_ldap_auth.py` / `test_c06_identity_routing.py`（20 passed）。
- **C06c 已落地（同日）**：
  - overlay 写入**非机密**连接字段（`host` / `port` / `user_dn_template=cn={login},cn=people,dc=westhpc,dc=com`）；**`enabled: false`**（本机默认不开门）。
  - `HERMES_LDAP_*` env 覆盖（`ENABLED`/`HOST`/`PORT`/`USER_DN_TEMPLATE`/…）；**不**经 env 传用户密码；遗留 `admin_*` 键忽略。
  - 探针 `owner/scripts/c06_ldap_probe.py`；E2E `tests/owner/test_c06_ldap_e2e.py`（`HERMES_LDAP_E2E=1`）；负向 bind 无需真密码。
  - node010 生产 `patch_feishu_profile.yaml` 的 ldap 段仍可由 loader 回落读取；**本轮不改 node010、不做 C05b 切流**。
- **未**：C05b node010 切流；本机/生产默认仍 `enabled:false`（或仅节点 patch 自管）。

## 九、C06c 如何启用

1. **只探活（TCP）**：`.venv/bin/python owner/scripts/c06_ldap_probe.py`
2. **负向 E2E（推荐）**：`HERMES_LDAP_ENABLED=1 HERMES_LDAP_E2E=1 .venv/bin/python -m pytest tests/owner/test_c06_ldap_e2e.py -q`  
   或探针：`HERMES_LDAP_ENABLED=1 .venv/bin/python owner/scripts/c06_ldap_probe.py --negative-bind`
3. **正向 bind（可选）**：另设 `HERMES_LDAP_E2E_PASSWORD` + `HERMES_LDAP_E2E_LOGIN`（密码只走 env，勿进 git / 勿进 argv）。
4. **长期开启**：overlay `ldap.enabled: true`（或节点 patch 同键）；装 optional `ldap` extra（`ldap3`）。依赖缺失且 enabled 时门返回 503（`ldap3_missing`）。
