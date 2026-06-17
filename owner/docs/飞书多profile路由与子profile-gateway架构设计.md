# 飞书多 Profile 路由与子 Profile Gateway 架构设计

> 文档版本：v2.0 | 更新日期：2026-06-17
> 涉及 commits：
> - `541c4ba` feat(owner): add Feishu multi-profile routing with external containers
> - `2e692b4` fix(feishu): respect explicit platform disable in config.yaml
> - `8ced60a` feat(feishu): add send_only connection mode for multi-profile routing
> - `f7a3554` feat(feishu): multi-bot routing support
> - *(owner-v16，待提交)* 子容器改走原生飞书 pipeline：`POST /v1/feishu/inbound` + `FeishuAdapter.inject_inbound`

---

## 架构演进说明（v2.0，必读）

**核心原则**：子 gateway 应当**像主 gateway 一样跑完整的飞书对话流程**，api_server 仅作为「主 → 子」的 HTTP 通信通道，**不**作为对话执行器。

早期草案（v1.x）让主 gateway 把消息 `POST /v1/runs` 转发给子容器，子容器用 api_server 自己的裸 agent 循环（`agent.run_conversation`）跑完，再用 `feishu_reply()` 通过 REST 直接发纯文本回去。**这条路是错的**——它绕过了飞书原生 pipeline，导致：

- 没有 auto-card（回复永远是纯文本）
- footer 是手工拼接的 `📋 profile · 🤖 model`，而非标准 `runtime_footer`（`model · context% · cwd`），且模型名取自 api_server 的 advertise 名（常退化为 profile 名）
- channel_prompt / hooks / agent:end 等飞书语义全部缺失

**最终设计（v2.0）**：主 gateway 把消息 `POST /v1/feishu/inbound`（纯通道，带 `open_id` + `p2p chat_id` + `chat_type`），子容器的 `_handle_feishu_inbound` 调用本进程 send_only `FeishuAdapter.inject_inbound()`，**重建一条原生 `MessageEvent` 注入 `_dispatch_inbound_event`**，后续完全复用飞书原生 pipeline（channel_prompt → hooks → `_handle_message` → agent → `agent:end` 自动卡片 → `runtime_footer`），回复由 send_only adapter 的正常发送路径发出。**一条被路由的对话，行为与原生对话完全一致，只是传输方式不同。**

下文中标注 ⚠️ *(v1.x 遗留)* 的章节描述的是已被取代的旧路径（代码暂时保留作回滚，但路由不再走它）。

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
│  └─ /v1/runs（管理员/通用 OpenAI 兼容请求）               │
│                                                          │
│  profile_routing.py                                      │
│  ├─ 路由解析：open_id → profile_name → endpoint          │
│  ├─ HTTP 转发：POST /v1/feishu/inbound 到子 profile 容器  │
│  │   (body: text + open_id + p2p chat_id + chat_type)    │
│  └─ 卡片 action 转发                                     │
└──────────────────────┬───────────────────────────────────┘
                       │  POST /v1/feishu/inbound（纯通道）
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
│ memory/soul  │ │ memory/soul  │ │ memory/soul  │
│ skills/      │ │ skills/      │ │ skills/      │
│              │ │              │ │              │
│ api_server   │ │ api_server   │ │ api_server   │
│ /v1/feishu/  │ │ /v1/feishu/  │ │ /v1/feishu/  │
│   inbound    │ │   inbound    │ │   inbound    │
│   ↓ inject   │ │   ↓ inject   │ │   ↓ inject   │
│ feishu       │ │ feishu       │ │ feishu       │
│ send_only:   │ │ send_only:   │ │ send_only:   │
│ 原生 pipeline │ │ 原生 pipeline │ │ 原生 pipeline │
│ +auto-card   │ │ +auto-card   │ │ +auto-card   │
│ +footer 回复 │ │ +footer 回复 │ │ +footer 回复 │
└──────────────┘ └──────────────┘ └──────────────┘
```

子容器内部：`_handle_feishu_inbound`（api_server）→ `FeishuAdapter.inject_inbound()`（重建 `MessageEvent`）→ `_dispatch_inbound_event` → `_handle_message` → agent → `agent:end` 自动卡片 → `runtime_footer` → send_only adapter 发出回复。

### 2.3 数据流

#### 普通消息

```text
Alice 发消息给 bot
       │
       ▼
飞书 ──WebSocket──▶ 主 gateway feishu.py:_handle_inbound_message
                   │
                   ▼
         try_route_inbound_message()
         resolve_profile_route(chat_id, open_id=Alice)
                   │
          ┌────────┴────────┐
          │命中路由: Alice   │未命中(管理员/白名单)
          ▼                ▼
  POST /v1/feishu/inbound  本地处理
  (纯通道: text+open_id    (管理员自己的 Hermes)
   +p2p chat_id+chat_type)
  ──▶ Alice 的容器 :9101
          │
          ▼
  _handle_feishu_inbound → adapter.inject_inbound()
          │  (重建原生 MessageEvent)
          ▼
  _dispatch_inbound_event → _handle_message
  (Alice 的 session/memory/soul，channel_prompt 在此解析)
          │
          ▼
  agent → agent:end 自动卡片 → runtime_footer
          │
          ▼
  飞书 ◀── send_only FeishuAdapter
  (Alice 的容器用自己的 feishu adapter 直接回复；
   DM 用 open_id、群用 chat_id，按需选择)
```

> 主 gateway 转发的是 `text + open_id + p2p chat_id + chat_type`，子容器据此重建 source：DM 的 `source.chat_id` 用 p2p chat_id（`oc_…`）、`user_id` 用 open_id；这样卡片路径（`metadata.open_id`）与纯文本路径（`source.chat_id`）都能正确投递。

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

### 3.4 `gateway/platforms/api_server.py` — `/v1/feishu/inbound` 传输端点（v2.0 核心）

**问题**：主 gateway 需要把路由命中的消息交给子容器，让子容器**用原生飞书 pipeline 跑完整对话**，而不是用 api_server 的裸 agent 循环。

**改动**：新增专用传输端点 `POST /v1/feishu/inbound`（与既有的 `POST /v1/feishu/card-actions` 同一模式）。该 handler 是**纯通道**——不跑 agent，只把消息交给本进程的 send_only FeishuAdapter：

```python
async def _handle_feishu_inbound(self, request):
    auth_err = self._check_auth(request)          # Bearer 必须匹配 API_SERVER_KEY
    if auth_err: return auth_err
    body, err = await self._read_json_body(request)
    if err: return err

    text       = body.get("text") or body.get("input") or ""
    open_id    = str(body.get("open_id") or "").strip()
    chat_id    = str(body.get("chat_id") or "").strip()   # DM=p2p chat_id, 群=群 id
    chat_type  = str(body.get("chat_type") or "p2p").strip()
    message_id = body.get("message_id") or None

    # 通过 gateway.run._gateway_runner_ref 拿到本进程的 send_only feishu adapter
    _get_adapter = _owner_import("owner.feishu.profile_routing",
                                 "_get_inprocess_feishu_adapter")
    adapter = _get_adapter() if _get_adapter else None
    if adapter is None or not hasattr(adapter, "inject_inbound"):
        return web.json_response(..., status=503)

    # fire-and-forget：完整 pipeline 在 gateway loop 上跑，HTTP 立即 202
    asyncio.ensure_future(adapter.inject_inbound(
        text=str(text), open_id=open_id, chat_id=chat_id,
        chat_type=chat_type, message_id=str(message_id) if message_id else None,
    ))
    return web.json_response({"accepted": True}, status=202)
```

**为什么用 `_owner_import` 懒加载**：api_server.py 是官方代码，不能直接 import owner 模块。懒加载确保 owner/ 不存在时优雅降级。

**`_get_inprocess_feishu_adapter()`**（`owner/feishu/profile_routing.py`）通过 `gateway.run._gateway_runner_ref`（模块级 weakref）拿到 GatewayRunner，再取 `runner.adapters[Platform.FEISHU]`。子容器同时启用了 `api_server` 与 `feishu(send_only)`，两者在同一个 GatewayRunner / 同一 event loop 中，所以 api_server handler 能直接调度 adapter 的协程。

### 3.4.1 `gateway/platforms/feishu.py` — `FeishuAdapter.inject_inbound()`（v2.0 核心）

把转发来的字段重建成一条与 WebSocket 入站**等价**的 `MessageEvent`，注入原生分发路径：

```python
async def inject_inbound(self, *, text, open_id, chat_id="", chat_type="p2p", message_id=None):
    is_dm = (chat_type or "").lower() in ("p2p", "dm")
    # DM 优先用 p2p chat_id（与原生流程一致）；缺失时回退 open_id（bot menu）
    src_chat_id = chat_id or (open_id if is_dm else "")
    source = self.build_source(
        chat_id=src_chat_id,
        chat_type="dm" if is_dm else "group",
        user_id=open_id,                      # run.py 据此把 open_id 注入卡片 metadata
    )
    # channel_prompt 在容器内解析：DM 优先按 open_id（每用户），回退 p2p chat_id
    from gateway.platforms.base import resolve_channel_prompt
    prompt = (resolve_channel_prompt(self.config.extra, open_id, parent_id=src_chat_id)
              if is_dm else resolve_channel_prompt(self.config.extra, src_chat_id))
    event = MessageEvent(text=text, source=source, message_id=message_id,
                         channel_prompt=prompt, message_type=MessageType.TEXT)
    await self._dispatch_inbound_event(event)   # 进入原生 pipeline，绕过路由块防回环
```

**关键点**：
- 直接调 `_dispatch_inbound_event`（不走 `_handle_inbound_message`），**避免再次触发 `try_route_inbound_message` 形成回环**。
- 回复完全由原生 `agent:end`（`owner/feishu/agent_end.py` → `try_auto_card_on_end`）+ `gateway/runtime_footer.py` 产出，**无需任何特殊回复代码**。footer 即标准 `model · context% · cwd`，模型名是 agent 实际所用模型。
- `channel_prompt` **由子容器解析**（主 gateway 只转发）；DM 按 open_id 命中可实现「每用户专属 prompt」。

### 3.5 ⚠️ *(v1.x 遗留)* `X-Hermes-Reply-Via` + `message_receive` 卡片发送

> 以下为已被 3.4 取代的旧路径。代码暂时保留（路由不再走 `/v1/runs`），可在确认稳定后清理。

旧设计中，主 gateway `POST /v1/runs` 并带 `X-Hermes-Reply-Via: feishu` 等 header，子容器在 `run.completed` 后调用 `feishu_reply()` 直接 REST 回复；卡片则由 `owner/hooks/message_receive.py` 在 `platform=api_server` 时改用 feishu adapter 的 `send_card` 发送。

新设计下消息走 `/v1/feishu/inbound` → `inject_inbound`，回复经原生 `agent:end`，因此 `X-Hermes-Reply-Via` 分支与 `message_receive` 的卡片改投逻辑对被路由的消息不再生效。

### 3.6 `owner/feishu/profile_routing.py` — 核心路由模块

**职责**：所有 profile 路由逻辑集中在此模块，gateway 官方代码只保留 1-3 行薄委托。

**主要函数**：

| 函数 | 作用 | 调用方 |
|------|------|--------|
| `resolve_profile_route(chat_id, open_id)` | 根据用户 open_id 解析路由，返回 (profile_name, endpoint, api_key) 或 None | feishu.py |
| `try_route_inbound_message(...)` | 路由消息 → `POST /v1/feishu/inbound`（带 open_id+chat_id+chat_type） | feishu.py |
| `try_route_card_action(event, action_value)` | 路由卡片按钮到发送该卡片的容器 | feishu.py |
| `try_route_bot_menu_command(...)` | 路由 bot 菜单 → `/v1/feishu/inbound`（chat_id 可空，回退 open_id） | bot_menu.py |
| `_forward_to_profile_container(...)` | 实际 HTTP 转发到 `/v1/feishu/inbound` | 上述三者 |
| `_get_inprocess_feishu_adapter()` | 子容器内取本进程 send_only feishu adapter（经 `_gateway_runner_ref`） | api_server.py |
| `feishu_reply(...)` | ⚠️ *(v1.x 遗留)* 旧 REST 直接回复，被 `inject_inbound` 取代 | api_server.py |

**路由优先级**：
1. `whitelist` open_ids → 留在主 gateway（管理员/特殊用户）
2. 本地命令黑名单（`/restart`）→ 留在主 gateway（影响进程生命周期）
3. `chat_profile_routes[chat_id]` → 按群聊路由
4. `user_profile_routes[open_id]` → 按用户路由（核心场景）
5. `default_profile` → 兜底 profile（未配置路由的用户）
6. 无匹配 → 主 gateway 处理

**会话隔离**：路由本身不再计算 session_key——消息注入子容器后，由原生 pipeline 通过 `build_session_key(source, …)` 计算（DM 按 chat_id/open_id、群按 chat_id），与原生飞书会话完全一致。每个 profile 容器有独立的 HERMES_HOME / session store / memory / SOUL，进程级隔离。

### 3.7 ⚠️ *(v1.x 遗留)* `owner/feishu/profile_routing.py` — feishu_reply 回复机制

> 已被 3.4.1 的原生 `agent:end` 回复取代。代码暂时保留作回滚。

旧机制让子容器通过 REST API 直接回复用户，并手工拼接 footer `📋 profile · 🤖 model`。**这个 footer 是错的**：

- 正确的 footer 是标准 `runtime_footer`：`model · context% · cwd`（如 `deepseek-v4-flash · 21% · ~/.hermes`），由 `gateway/runtime_footer.py::build_footer_line` 按 `display.runtime_footer.fields` 生成。
- 旧实现里的「模型名」取自 api_server 的 advertise 名（`_resolve_model_name`，读 `extra["model_name"]`/`API_SERVER_MODEL_NAME`），常退化为 profile 名，与 agent 实际所用模型不符。
- v2.0 下回复走原生 pipeline，footer 由 `build_footer_line` 用 agent 真实模型 + 上下文占用自动产出，无需手工拼接。

**为什么会退化为纯文本**：`feishu_reply` 直接 REST 发 `msg_type: text`，绕过了 `FeishuAdapter.send()` → `try_auto_card()`，所以没有 auto-card。v2.0 经 `inject_inbound` 走原生 `send()` 后，auto-card 自动生效。

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
    # ⚠️ 以 app_id 为 key——必须等于主 gateway 的 FEISHU_APP_ID（~/.hermes/.env）。
    # _load_routing_config 用 bots[os.getenv("FEISHU_APP_ID")] 查找；key 不匹配
    # 会静默返回空配置 → 所有消息都不被路由（排查时极易踩坑）。
    cli_xxxxxxxxxxxxxxxx:          # 团队共用的 bot，填真实 FEISHU_APP_ID
      user_routing:
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

        # profile_name → 容器配置（url + api_key）
        # 每个 profile 自带 api_server 认证 key
        profile_endpoints: {}
        # profile_endpoints:
        #   alice:
        #     url: http://localhost:9101
        #     api_key: "alice-api-key"
        #   bob:
        #     url: http://localhost:9102
        #     api_key: "bob-api-key"
        #   default:
        #     url: http://localhost:9100
        #     api_key: ""
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

每个子 profile 容器的 `~/.hermes/profiles/<name>/config.yaml`（实测采用的写法）：

```yaml
platforms:
  feishu:
    enabled: true                  # 必须启用：要有一个活着的 adapter 才能回复
    extra:
      connection_mode: send_only   # 只发不连 WebSocket（不抢主 gateway 的连接）
  api_server:
    enabled: true
    port: 26026                    # 每个用户用不同端口

# .env 文件（同一个飞书应用凭据 + api_server key）
FEISHU_APP_ID=cli_xxxxxxxxxxxxxxxx     # 与主 gateway 同一应用
FEISHU_APP_SECRET=...
API_SERVER_KEY=sk-xxxx                 # 与 patch_feishu_profile 的 api_key 一致
GATEWAY_ALLOW_ALL_USERS=true           # 信任主 gateway 鉴权
```

**为什么子 profile 也配 FEISHU 凭据**：
- send_only `FeishuAdapter` 用 app_id/app_secret 获取 tenant_access_token 来回复（`send()` / `send_card_via_rest()`）
- `connection_mode: send_only` 确保只创建 REST 客户端、不建立 WebSocket，不与主 gateway 抢 app_id

> 备选写法：`feishu.enabled: false` + `.env FEISHU_CONNECTION_MODE=send_only`，配合 `gateway/config.py` 的 `_enabled_explicit` 机制（见 3.2/3.3）也能达到「有 send_only adapter 但不连 WebSocket」。两种写法等价，推荐上面的显式 `extra.connection_mode` 写法。

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
| `gateway/platforms/feishu.py` | feat | `send_only` 连接模式 + **v2.0 `inject_inbound()`**（重建原生 MessageEvent 注入 pipeline） |
| `gateway/platforms/api_server.py` | feat | **v2.0 `POST /v1/feishu/inbound` 传输端点**（`_handle_feishu_inbound`，纯通道）；*(v1.x 遗留)* `X-Hermes-Reply-Via` 分支保留 |
| `gateway/config.py` | fix | 尊重 `enabled: false`；`connection_mode` 优先级 |
| `gateway/run.py` | feat | 模块级 `_gateway_runner_ref`（子容器经此取本进程 feishu adapter） |
| `owner/feishu/profile_routing.py` | feat | 核心路由模块；**v2.0 `_forward_to_profile_container` 改投 `/v1/feishu/inbound`**（body 带 open_id+chat_id+chat_type）+ `_get_inprocess_feishu_adapter()`；*(v1.x 遗留)* `feishu_reply` 保留 |
| `owner/feishu/card_sender.py` | feat | REST API 卡片发送（独立于 SDK），原生回复的 auto-card 也复用它 |
| `owner/feishu/auto_card.py` | feat | `try_auto_card`（原生 `agent:end` 回复经此产出卡片） |
| `gateway/runtime_footer.py` | — | 标准 footer `model · context% · cwd`（原生回复自动附加） |
| `owner/feishu/bot_menu.py` | refactor | 委托 `try_route_bot_menu_command` |
| `owner/hooks/message_receive.py` | feat | *(v1.x 遗留)* send_only 卡片改投；v2.0 路由消息不再经此 |
| `owner/patch_config.py` | feat | `load_patch_feishu_profile_config()` 加载器（mtime + 1min TTL 缓存） |
| `owner/config/patch_feishu_profile.yaml` | feat | 配置模板（multi-bot 结构） |
| `tests/owner/test_feishu_profile_routing.py` | test | 路由解析与加载器测试 |
| `owner/docs/feishu-multi-profile-routing-owner-v16.md` | docs | 初始设计文档 |

---

## 七、运维命令

### 7.1 手动启动子 Profile Gateway

每个子 profile 容器需要独立启动 gateway 进程。使用 `hermes -p <profile_name> gateway install` 命令：

```bash
# 启动 hermesxiyun profile 的 gateway（安装为 launchd 服务）
hermes -p hermesxiyun gateway install

# 或者手动启动（前台运行，调试用）
hermes -p hermesxiyun gateway run

# 查看状态
hermes -p hermesxiyun gateway status

# 重启
hermes -p hermesxiyun gateway restart

# 停止
hermes -p hermesxiyun gateway stop
```

**说明**：
- `-p hermesxiyun` 指定 profile 名称，Hermes 会加载 `~/.hermes/profiles/hermesxiyun/` 作为 HERMES_HOME
- `gateway install` 会创建 macOS launchd 服务（或 Linux systemd 服务），实现开机自启
- 每个子 profile 的 gateway 独立运行，互不干扰
- 主 gateway（default profile）负责接收飞书 WebSocket 消息并路由到子 profile



### 7.1.1 Profile Alias 与 Systemd 服务安装（推荐流程）

> `hermes -p <name>` 每次要敲很长，`hermes profile alias` 会创建一个同名 wrapper script，之后直接用 `<profile_name> gateway restart` 即可。

#### Step 1: 创建 Alias

```bash
hermes profile alias hermesxiyun
hermes profile alias hermeswangtingwei
# ... 为每个子 profile 创建
```

创建后生成 `~/.local/bin/<profile_name>` 可执行脚本。确保 `~/.local/bin` 在 PATH 中：

```bash
# bashrc / zshrc 中添加
export PATH="$HOME/.local/bin:$PATH"
```

#### Step 2: 端口规划

每个子 profile 的 `api_server.port` 必须唯一，避免端口冲突：

| Profile | Port | 备注 |
|---------|------|------|
| hermesxiyun | 26026 | 基准端口 |
| hermeswangtingwei | 26027 | |
| hermesyangtb | 26028 | |
| liruiyang | 26029 | |
| sunqifei | 26030 | |

在每个子 profile 的 `config.yaml` 中设置：

```yaml
platforms:
  api_server:
    enabled: true
    extra:
      port: 26027   # 每个 profile 不同
```

#### Step 3: 环境变量同步

子 profile 的 `.env` 需要与主 `.env` 保持一致的模型 provider 凭据。当前需要同步的变量组：

```bash
# 在每个子 profile 的 .env 中追加（从主 ~/.hermes/.env 复制）
# DeepSeek 直连
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_API_KEY=sk-xxx

# DashScope (阿里云)
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DASHSCOPE_API_KEY=sk-xxx

# DAMODEL (NewAPI 代理)
DAMODEL_BASE_URL=https://genai.damodel.com/v1
DAMODEL_API_KEY=sk-xxx
```

**批量同步脚本**（在主 gateway 机器上执行）：

```bash
PROFILES="hermeswangtingwei hermesxiyun hermesyangtb liruiyang sunqifei"
for p in $PROFILES; do
  cat >> ~/.hermes/profiles/$p/.env << EOF

# DeepSeek 直连
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_API_KEY=\$(grep DEEPSEEK_API_KEY ~/.hermes/.env | cut -d= -f2)

# DashScope
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DASHSCOPE_API_KEY=\$(grep DASHSCOPE_API_KEY ~/.hermes/.env | cut -d= -f2)

# DAMODEL
DAMODEL_BASE_URL=https://genai.damodel.com/v1
DAMODEL_API_KEY=\$(grep DAMODEL_API_KEY ~/.hermes/.env | cut -d= -f2)
EOF
  echo "$p ✓"
done
```

同步 `.env` 后，还需同步 `config.yaml` 中 provider 的环境变量引用。例如 `providers.deepseek` 的 `api_key` 和 `base_url` 应指向 `DEEPSEEK_*` 而非 `DAMODEL_*`：

```yaml
providers:
  deepseek:
    api_key: ${DEEPSEEK_API_KEY}      # 而非 ${DAMODEL_API_KEY}
    base_url: ${DEEPSEEK_BASE_URL}    # 而非 ${DAMODEL_BASE_URL}
```

#### Step 4: 安装为 Systemd 服务

```bash
# 为每个子 profile 安装 gateway 服务（自动创建 systemd user service）
yes | hermesxiyun gateway install
yes | hermeswangtingwei gateway install
# ...
```

`gateway install` 会：
1. 创建 `~/.config/systemd/user/hermes-gateway-<profile>.service`
2. 启用 systemd linger（服务在用户登出后继续运行）
3. 立即启动服务

#### Step 5: 日常运维

```bash
# 重启（推荐方式，走 systemd 优雅重启）
hermesxiyun gateway restart

# 查看所有 profile gateway 状态
hermes gateway list

# 查看日志
journalctl --user -u hermes-gateway-hermesxiyun -f

# 停止
hermesxiyun gateway stop

# 卸载服务
hermesxiyun gateway uninstall
```

**注意**：`hermesxiyun gateway restart` 是 systemd 级别的优雅重启（SIGTERM → 等待 drain → 启动新进程），不会影响主 gateway 和其他子 profile。

### 7.2 配置验证（含两个高频踩坑点）

启动子 profile 前，确保**主 gateway** 的 `~/.hermes/patch_feishu_profile.yaml`：

```yaml
feishu:
  bots:
    cli_xxxxxxxxxxxxxxxx:      # ⚠️ 必须 == 主 gateway 的 FEISHU_APP_ID
      user_routing:
        whitelist: []          # 用自己的号测路由时，把自己的 open_id 从这里去掉
        default_profile: hermesxiyun
        profile_endpoints:
          hermesxiyun:
            url: http://localhost:26026
            api_key: "sk-xxxx"  # ⚠️ 必须 == 子容器的 API_SERVER_KEY
```

**子容器**的 `~/.hermes/profiles/hermesxiyun/config.yaml`：

```yaml
platforms:
  feishu:
    enabled: true                  # 必须启用，否则没有可用于回复的 send_only adapter
    extra:
      connection_mode: send_only   # 只发不连 WebSocket（不抢主 gateway 的连接）
  api_server:
    enabled: true
    port: 26026
```

对应的 `~/.hermes/profiles/hermesxiyun/.env`：

```bash
FEISHU_APP_ID=cli_xxxxxxxxxxxxxxxx        # 与主 gateway 同一个飞书应用（回复身份一致）
FEISHU_APP_SECRET=...
API_SERVER_KEY=sk-xxxx                    # 主 gateway 转发的 Bearer 必须与此一致
GATEWAY_ALLOW_ALL_USERS=true              # 信任主 gateway 已做的鉴权；否则需配 FEISHU_ALLOWED_USERS
```

**两个最容易踩的坑（实测踩过）**：

1. **app_id 不匹配 → 完全不路由**：`patch_feishu_profile.yaml` 的 `bots.<key>` 必须等于主 gateway 进程的 `FEISHU_APP_ID`。不匹配时 `_load_routing_config` 静默返回空，所有消息都走主 gateway，且无任何报错。
2. **api_key 不匹配 → 401**：`profile_endpoints.<profile>.api_key` 必须等于子容器的 `API_SERVER_KEY`，否则子容器 `_check_auth` 拒绝转发请求（日志：`API server rejected invalid API key … path='/v1/feishu/inbound'`）。

> `patch_feishu_profile.yaml` 按 mtime + 1 分钟 TTL 缓存：改完后下一条消息即可生效，无需重启主 gateway（保险起见也可 `launchctl kickstart -k gui/$(id -u)/ai.hermes.gateway`）。

### 7.2.1 channel_prompt（由子容器解析）

主 gateway 只转发消息，**per-channel ephemeral prompt 在子容器内解析**。在**子 profile** 的 `config.yaml` 配置：

```yaml
platforms:
  feishu:
    extra:
      channel_prompts:
        ou_alice_open_id: "你在和 Alice 私聊……"   # DM 按 open_id 命中（每用户专属）
        oc_group_chat_id: "这是 X 群……"            # 群按 chat_id 命中
```

如果设置了 `api_server.key`/`API_SERVER_KEY`，主 gateway 对应的 `profile_endpoints.<profile>.api_key` 必须配相同值。

### 7.3 创建新 Profile（Fork/Copy）

使用 `hermes profile create` 命令创建新的 profile 容器：

```bash
# 创建空 profile（无配置，需要手动配置）
hermes profile create alice

# 从当前 active profile 复制配置（config.yaml, .env, SOUL.md, skills）
hermes profile create alice --clone

# 完整复制当前 active profile（包括所有状态，排除 per-profile history）
hermes profile create alice --clone-all

# 从指定 profile 复制（隐含 --clone）
hermes profile create alice --clone-from bob

# 从指定 profile 完整复制
hermes profile create alice --clone-from bob --clone-all

# 创建空 profile，不安装 bundled skills
hermes profile create alice --no-skills

# 添加描述（用于 kanban 任务路由）
hermes profile create alice --description "Alice 的独立助手实例"
```

**创建后的步骤**：

1. 编辑 `~/.hermes/profiles/alice/config.yaml`：设 `api_server.port`、`feishu.enabled: true` + `feishu.extra.connection_mode: send_only`、`model`（见 4.4）；在 `.env` 设 `API_SERVER_KEY`、`FEISHU_APP_ID/SECRET`、`GATEWAY_ALLOW_ALL_USERS=true`
2. 在主 gateway 的 `~/.hermes/patch_feishu_profile.yaml` 中添加路由（`bots.<key>` 必须 == 主 gateway 的 `FEISHU_APP_ID`）：
   ```yaml
   user_profile_routes:
     ou_alice_open_id: alice
   profile_endpoints:
     alice:
       url: http://localhost:9101
       api_key: "sk-alice-key"   # 必须 == alice 容器的 API_SERVER_KEY
   ```
3. 启动子 profile gateway：`hermes -p alice gateway install`（查看日志：`tail -f ~/.hermes/profiles/alice/logs/gateway.log`，出现 `[Feishu] inject_inbound: dispatching…` 即通）

**其他 profile 管理命令**：

```bash
# 列出所有 profile
hermes profile list

# 删除 profile
hermes profile delete alice

# 切换 active profile
hermes profile use alice

# 查看 profile 详情
hermes profile show alice

# 添加/修改 profile 描述
hermes profile describe alice "Alice 的独立助手实例"
```
