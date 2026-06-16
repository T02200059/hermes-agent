# 飞书多 Profile 路由与子 Profile Gateway 架构设计

> 文档版本：v1.1 | 更新日期：2026-06-17
> 涉及 commits：
> - `541c4ba` feat(owner): add Feishu multi-profile routing with external containers
> - `2e692b4` fix(feishu): respect explicit platform disable in config.yaml
> - `8ced60a` feat(feishu): add send_only connection mode for multi-profile routing
> - `f7a3554` feat(feishu): multi-bot routing support

---

## 一、目的与痛点

### 1.1 核心问题

一个团队共用一个飞书 bot（同一个飞书应用 `cli_xxx`），但团队每个成员需要**独立的 Hermes 实例**——独立的 session store、独立的 memory、独立的 system prompt (SOUL.md)、独立的 skill 集合。

本质上是：**一个消息入口，服务 N 个隔离的 AI 助手**。

### 1.2 为什么不能"每人一个 bot + 一个 hermes"

市面上大多数基于 OpenClaw 开发的机器人没有 Hermes 的 profile 机制。为团队每个人都配置独立的 bot + Hermes 实例：

- **飞书侧**：每个 bot 需要管理员审批、权限配置、webhook 注册。为 100 人开 100 个 bot，运维成本 O(N) 线性增长。
- **Hermes 侧**：每个实例需要独立部署、独立配置、独立维护。没有统一的路由和管理能力。
- **用户侧**：每个用户要在飞书里找到自己的 bot，体验割裂。

**我们的方案**：结合 Hermes 的 profile 机制 + 二次开发，实现一个 bot 入口、多用户隔离。这是选型上的高瞻远瞩——市面上没有第二个框架能做到这一点。

### 1.3 具体痛点

| 痛点 | 说明 |
|------|------|
| 飞书 app_id 互斥 | 同一个飞书应用的 WebSocket 连接只能由一个进程持有。第二个 gateway 启动会抢占连接，导致前一个断连。 |
| Session 隔离 | 所有用户共享一个进程 = 共享 session store、memory、system prompt。Alice 的对话历史会出现在 Bob 的 context 里。 |
| 消息路由 | 用户只跟一个 bot 对话，但消息需要根据用户身份（open_id）分发到对应的独立 profile 容器。 |
| 子 profile 回复飞书 | 容器处理完消息后，需要直接回复飞书。但 WebSocket 连接在主 gateway 手里，容器没有通道。 |
| 代码污染 | 路由逻辑需要插入 gateway 关键路径，但不能永久修改官方代码（要兼容上游 pull）。 |
| 卡片跨进程路由 | 卡片按钮点击事件只能被 WebSocket 进程收到，需要路由回发送该卡片的容器处理。 |

---

## 二、整体架构

### 2.1 角色定义

| 角色 | 说明 |
|------|------|
| **主 Gateway** | 唯一持有飞书 WebSocket 连接的进程。职责：接收所有消息、路由分发、管理员自己的 Hermes 实例。 |
| **子 Profile 容器** | 独立的 Hermes api_server 进程，每个用户（或用户组）一个。有自己的 HERMES_HOME、session store、memory、soul、skills。 |
| **飞书** | 消息入口。所有消息通过 WebSocket 到达主 gateway。 |

### 2.2 组件关系

```text
┌──────────────────────────────────────────────────────────┐
│                     飞书 (Feishu/Lark)                    │
│         WebSocket 连接只能由一个进程持有                    │
└──────────────────────┬───────────────────────────────────┘
                       │ 所有用户的消息
                       ▼
┌──────────────────────────────────────────────────────────┐
│                    主 Gateway                             │
│                                                          │
│  feishu.py                                               │
│  ├─ WebSocket 长连接（唯一）                               │
│  ├─ # [owner] 路由检查：根据 open_id 分发                  │
│  └─ send_only adapter（用于管理员的卡片发送）              │
│                                                          │
│  api_server.py                                           │
│  ├─ /v1/runs（管理员自己的请求）                           │
│  └─ _gateway_ref → feishu adapter                        │
│                                                          │
│  profile_routing.py                                      │
│  ├─ 路由解析：open_id → profile_name → endpoint          │
│  ├─ HTTP 转发：POST /v1/runs 到子 profile 容器            │
│  └─ 卡片 action 转发                                     │
└──────────────────────┬───────────────────────────────────┘
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ Alice 的容器  │ │ Bob 的容器   │ │ Charlie 的容器│
│              │ │              │ │              │
│ HERMES_HOME  │ │ HERMES_HOME  │ │ HERMES_HOME  │
│ = ~/.hermes  │ │ = ~/.hermes  │ │ = ~/.hermes  │
│   /alice     │ │   /bob       │ │   /charlie   │
│              │ │              │ │              │
│ session store│ │ session store│ │ session store│
│ memory       │ │ memory       │ │ memory       │
│ soul.md      │ │ soul.md      │ │ soul.md      │
│ skills/      │ │ skills/      │ │ skills/      │
│              │ │              │ │              │
│ api_server   │ │ api_server   │ │ api_server   │
│ port: 9101   │ │ port: 9102   │ │ port: 9103   │
│              │ │              │ │              │
│ send_only    │ │ send_only    │ │ send_only    │
│ feishu 回复  │ │ feishu 回复  │ │ feishu 回复  │
└──────────────┘ └──────────────┘ └──────────────┘
```

### 2.3 数据流

#### 普通消息

```text
Alice 发消息给 bot
       │
       ▼
飞书 ──WebSocket──▶ 主 gateway feishu.py
                   │
                   ▼
         try_route_inbound_message()
         resolve_profile_route(chat_id, open_id=Alice)
                   │
          ┌────────┴────────┐
          │命中路由: Alice   │未命中(管理员/白名单)
          ▼                ▼
  POST /v1/runs       本地处理
  ──▶ Alice 的容器     (管理员自己的 Hermes)
      (port 9101)
          │
          ▼
      Alice 的 AIAgent 处理
      (用 Alice 的 session/memory/soul)
          │
          ▼
  飞书 ◀──HTTP── feishu_reply()
  (Alice 的容器直接 REST API 回复，不经主 gateway)
```

#### 卡片按钮

```text
Alice 的容器发了一张卡片，按钮带 hermes_profile="alice"
       │
       ▼
用户点击按钮 → 飞书推送到 WebSocket → 主 gateway
       │
       ▼
try_route_card_action()
  ├─ 有 hermes_profile="alice" → 同步 POST 到 Alice 的容器
  └─ 无 hermes_profile → resolve_profile_route → 有路由: ack 丢弃
```

#### Bot 菜单

```text
用户点击 Bot 菜单 → 飞书推送到 WebSocket → 主 gateway
       │
       ▼
try_route_bot_menu_command()
  ├─ 命中路由 → HTTP 转发到对应容器
  └─ 未命中 → 本地 slash command
```

---

## 三、源代码改动详解

### 3.1 `gateway/platforms/feishu.py` — send_only 连接模式

**问题**：子 profile 容器需要能发消息到飞书（REST API 回复用户），但绝不能连 WebSocket（会抢占主 gateway 的连接）。

**改动**（commit `8ced60a`）：

```python
# connect() 方法中新增 send_only 分支
if self._connection_mode == "send_only":
    self._loop = asyncio.get_running_loop()
    domain = FEISHU_DOMAIN if self._domain_name != "lark" else LARK_DOMAIN
    self._client = self._build_lark_client(domain)
    self._user_store.bind_client(self._client)
    await self._hydrate_bot_identity()
    self._mark_connected()
    logger.info("[Feishu] Connected in send_only mode (no websocket, send-only)")
    return True
```

**为什么**：
- `_build_lark_client()` 创建 REST API 客户端（用于 send 操作）
- `_hydrate_bot_identity()` 获取 bot 身份信息
- **不调用** `_start_websocket()`，因此不建立长连接
- `_mark_connected()` 标记为已连接，使 adapter 可用

**效果**：子 profile 的 FeishuAdapter 只是一个"发送器"，能通过 REST API 回复用户，但不会接收任何 WebSocket 事件。

### 3.2 `gateway/config.py` — 尊重显式 enabled: false

**问题**：子 profile 的 config.yaml 设置 `platforms.feishu.enabled: false`，但 .env 中有 FEISHU_APP_ID/SECRET（用于 `feishu_reply`），原逻辑会无条件启用飞书 adapter → 抢占 WebSocket。

**改动**（commit `2e692b4`）：

```python
feishu_cfg = config.platforms[Platform.FEISHU]
enabled_was_explicit = bool(feishu_cfg.extra.pop("_enabled_explicit", False))
if not feishu_cfg.enabled and not enabled_was_explicit:
    feishu_cfg.enabled = True
```

**为什么**：子 profile 需要 FEISHU 凭据来回复用户，但不希望 WebSocket adapter 被自动启用。`_enabled_explicit` 标志确保 config.yaml 中的 `enabled: false` 不被 env 覆盖。

### 3.3 `gateway/config.py` — connection_mode 优先级

```python
feishu_cfg.extra.setdefault("connection_mode", os.getenv("FEISHU_CONNECTION_MODE", "websocket"))
```

**优先级**：`config.yaml > env > default(websocket)`

子 profile 在 config.yaml 中显式写 `connection_mode: send_only`，确保不被 env 覆盖。

### 3.4 `gateway/platforms/api_server.py` — X-Hermes-Reply-Via

**问题**：子 profile 处理完消息后，需要直接回复飞书，而不是返回给主 gateway 中转。

**改动**（commit `8ced60a`）：

```python
# 读取 X-Hermes-Reply-Via header
reply_via = request.headers.get("X-Hermes-Reply-Via", "").lower().strip()
reply_receive_id = request.headers.get("X-Hermes-Reply-Receive-Id", "")
reply_receive_id_type = request.headers.get("X-Hermes-Reply-Receive-Id-Type", "open_id")
reply_message_id = request.headers.get("X-Hermes-Reply-Message-Id", "")

# run.completed 后直接回复飞书
if reply_via == "feishu" and reply_receive_id and final_response:
    _feishu_reply = _owner_import("owner.feishu.profile_routing", "feishu_reply")
    asyncio.ensure_future(_feishu_reply(
        receive_id=reply_receive_id,
        receive_id_type=reply_receive_id_type,
        text=final_response,
        reply_message_id=reply_message_id,
    ))
```

**为什么用 `_owner_import` 懒加载**：api_server.py 是官方代码，不能直接 import owner 模块。懒加载确保 owner/ 不存在时优雅降级。

### 3.5 `owner/hooks/message_receive.py` — send_only 卡片发送

**问题**：子 profile 的 api_server 收到消息后，hooks 生成的卡片需要通过飞书 adapter 发送。但子 profile 的 platform 值是 `api_server`（不是 `feishu`）。

**改动**（commit `8ced60a`）：

```python
if platform_value == "api_server" and feishu_card:
    feishu_adapter = adapters.get(Platform.FEISHU)
    if feishu_adapter and hasattr(feishu_adapter, "send_card"):
        adapter = feishu_adapter
        platform_value = "feishu"
```

**为什么**：子 profile 同进程中有 `send_only` 模式的 feishu adapter，hooks 需要用它来发送卡片。

### 3.6 `owner/feishu/profile_routing.py` — 核心路由模块

**职责**：所有 profile 路由逻辑集中在此模块，gateway 官方代码只保留 1-3 行薄委托。

**主要函数**：

| 函数 | 作用 | 调用方 |
|------|------|--------|
| `resolve_profile_route(chat_id, open_id)` | 根据用户 open_id 解析路由，返回 (profile_name, endpoint, api_key) 或 None | feishu.py |
| `try_route_inbound_message(...)` | 路由消息到用户对应的容器 | feishu.py |
| `try_route_card_action(event, action_value)` | 路由卡片按钮到发送该卡片的容器 | feishu.py |
| `try_route_bot_menu_command(...)` | 路由 bot 菜单到用户对应的容器 | bot_menu.py |
| `feishu_reply(...)` | 子 profile 容器直接回复飞书（REST API） | api_server.py |

**路由优先级**：
1. `whitelist` open_ids → 留在主 gateway（管理员/特殊用户）
2. 本地命令黑名单（`/restart`）→ 留在主 gateway（影响进程生命周期）
3. `chat_profile_routes[chat_id]` → 按群聊路由
4. `user_profile_routes[open_id]` → 按用户路由（核心场景）
5. `default_profile` → 兜底 profile（未配置路由的用户）
6. 无匹配 → 主 gateway 处理

**会话隔离**：
- P2P: `session_key = feishu:dm:{open_id}`（每个用户独立 session）
- 群聊: `session_key = feishu:group:{chat_id}`（每个群独立 session）

### 3.7 `owner/feishu/profile_routing.py` — feishu_reply 回复机制

子 profile 容器通过 REST API 直接回复用户：

```python
async def feishu_reply(*, receive_id, receive_id_type, text,
                       reply_message_id=None, model=None, profile_name=None):
    token = await _get_feishu_tenant_token(app_id, app_secret)
    # 构建 footer: 📋 profile_name · 🤖 model_name
    # POST 到飞书 im/v1/messages 或 im/v1/messages/{id}/reply
```

**关键设计**：
- 每个子 profile 容器用同一个飞书应用的凭据（app_id/app_secret）
- `tenant_access_token` 独立获取和缓存，不与主 gateway 的 token 冲突
- 支持回复原消息（reply_message_id）或发送新消息

### 3.8 `owner/feishu/card_sender.py` — REST 卡片发送

独立于 lark_oapi SDK 的飞书卡片发送器：

```python
async def send_card_via_rest(adapter, chat_id, card, metadata=None):
    token_resp = _requests.post(f"{base_url}/auth/v3/tenant_access_token/internal", ...)
    send_resp = _requests.post(f"{base_url}/im/v1/messages?receive_id_type=...", ...)
```

**为什么绕过 SDK**：token 独立获取不影响主 gateway 的 WebSocket 连接；DM 场景需要正确解析 `receive_id`（open_id 而非 chat_id）。

---

## 四、`patch_feishu_profile.yaml` 配置结构

### 4.1 文件位置

- **模板**：`owner/config/patch_feishu_profile.yaml`（仓库内）
- **运行时**：`~/.hermes/patch_feishu_profile.yaml`（主 gateway 的 HERMES_HOME）
- **加载器**：`owner/patch_config.py::load_patch_feishu_profile_config()`

### 4.2 配置结构（multi-bot 模式）

```yaml
# ~/.hermes/patch_feishu_profile.yaml
feishu:
  bots:
    # 以 app_id 为 key，每个 bot 独立路由
    cli_a7bfbfdbbcf8d00c:          # 团队共用的 bot
      user_routing:
        internal_api_key: ""        # 主 gateway → 子容器的认证 key

        # 白名单：这些用户由主 gateway 直接处理（管理员）
        whitelist: []
        # whitelist:
        #   - ou_admin_open_id

        # 按群聊路由（群聊 → 指定 profile 容器）
        chat_profile_routes: {}
        # chat_profile_routes:
        #   oc_team_a_chat: team-a
        #   oc_team_b_chat: team-b

        # 按用户路由（核心：每个用户 → 自己的 profile 容器）
        user_profile_routes: {}
        # user_profile_routes:
        #   ou_alice: alice        # Alice → Alice 的独立容器
        #   ou_bob: bob            # Bob → Bob 的独立容器
        #   ou_charlie: charlie    # Charlie → Charlie 的独立容器

        # 兜底：未配置路由的用户走这个 profile
        default_profile: ""
        # default_profile: default    # 所有未配置的用户 → default 容器

        # profile_name → 容器 HTTP 地址
        profile_endpoints: {}
        # profile_endpoints:
        #   alice: http://localhost:9101
        #   bob: http://localhost:9102
        #   charlie: http://localhost:9103
        #   default: http://localhost:9100
```

### 4.3 配置加载逻辑

```python
def _load_routing_config():
    cfg = load_patch_feishu_profile_config()
    feishu_cfg = cfg.get("feishu", {})

    # 优先: multi-bot 结构 (feishu.bots.{app_id}.user_routing)
    bots_cfg = feishu_cfg.get("bots", {})
    if bots_cfg:
        app_id = os.getenv("FEISHU_APP_ID", "")
        bot_cfg = bots_cfg.get(app_id, {})
        return bot_cfg.get("user_routing", {})

    # 降级: legacy 扁平结构 (feishu.user_routing)
    return feishu_cfg.get("user_routing", {})
```

**向后兼容**：如果没有 `bots` 层，回退到旧的扁平结构。

### 4.4 子 Profile 容器配置

每个子 profile 容器的 `~/.hermes/config.yaml`：

```yaml
platforms:
  feishu:
    enabled: false          # 关键：不自动启用 WebSocket adapter
  api_server:
    enabled: true
    port: 9101              # 每个用户用不同端口

# .env 文件（同一个飞书应用凭据）
FEISHU_APP_ID=cli_a7bfbfdbbcf8d00c
FEISHU_APP_SECRET=...
FEISHU_CONNECTION_MODE=send_only    # 确保不连 WebSocket
```

**为什么子 profile 也配 FEISHU 凭据**：
- `feishu_reply()` 需要 app_id/app_secret 来获取 tenant_access_token
- `send_card_via_rest()` 同样需要
- 但 `enabled: false` + `send_only` 确保不会启动 WebSocket 连接

---

## 五、安全与降级设计

### 5.1 故障降级

| 故障场景 | 行为 |
|----------|------|
| `patch_feishu_profile.yaml` 不存在 | 全部消息走主 gateway，无路由 |
| 配置格式错误 | 同上，`_load_routing_config` 返回空 dict |
| 子 profile 容器 HTTP 超时/失败 | 给用户发 "⚠️ 服务暂时不可用"，消息走主 gateway |
| owner/ 模块被删除 | `_owner_import` 返回 None，官方代码不受影响 |
| `/restart` 命令 | 强制留在主 gateway（`_LOCAL_ONLY_COMMANDS`） |

### 5.2 可移除性

所有 owner 改动遵循"薄委托"模式——官方代码中只有 `# [owner]` 标记的 1-3 行。删除整个 `owner/` 目录后：

- `feishu.py` 正常启动，只是不执行路由
- `api_server.py` 正常启动，只是不处理 `X-Hermes-Reply-Via`
- 不会产生 import 错误或运行时崩溃

### 5.3 app_id 互斥保护

`feishu.py` 的 `connect()` 中有 scoped lock 机制：

```python
acquired, existing = acquire_scoped_lock(
    _FEISHU_APP_LOCK_SCOPE, self._app_lock_identity, ...)
if not acquired:
    # "Another local Hermes gateway is already using this Feishu app_id"
```

`send_only` 模式**绕过此锁**（不调用 acquire_scoped_lock），因为 send_only 不建立 WebSocket 连接，不存在互斥问题。

---

## 六、文件清单

| 文件 | 改动类型 | 说明 |
|------|----------|------|
| `gateway/platforms/feishu.py` | feat | 新增 `send_only` 连接模式分支 |
| `gateway/config.py` | fix | 尊重 `enabled: false`；`connection_mode` 优先级 |
| `gateway/platforms/api_server.py` | feat | 读取 `X-Hermes-Reply-Via` header，run.completed 后调用 feishu_reply |
| `gateway/run.py` | feat | adapter 连接后设置 `_gateway_ref` |
| `owner/feishu/profile_routing.py` | feat | 核心路由模块（路由解析、HTTP 转发、卡片转发、飞书回复） |
| `owner/feishu/card_sender.py` | feat | REST API 卡片发送（独立于 SDK） |
| `owner/feishu/bot_menu.py` | refactor | 委托 `try_route_bot_menu_command` |
| `owner/hooks/message_receive.py` | feat | send_only 模式卡片发送适配 |
| `owner/patch_config.py` | feat | `load_patch_feishu_profile_config()` 加载器 |
| `owner/config/patch_feishu_profile.yaml` | feat | 配置模板（multi-bot 结构） |
| `tests/owner/test_feishu_profile_routing.py` | test | 路由解析与加载器测试 |
| `owner/docs/feishu-multi-profile-routing-owner-v16.md` | docs | 初始设计文档 |
