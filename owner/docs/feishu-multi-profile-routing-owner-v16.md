# Feishu 多 Profile 路由（owner-v16 外部容器架构）

## 功能描述

当飞书机器人收到消息时，根据 `~/.hermes/patch_feishu_profile.yaml` 中的
`feishu.user_routing` 配置，把消息转发到不同的 Hermes profile 容器（即独立
的 hermes-agent API server 实例）。

典型场景：

- 工作对话路由到「工作 profile」容器。
- 个人对话路由到「个人 profile」容器。
- 群聊按 chat_id 路由到指定团队容器。
- 白名单 open_id 始终留在主 gateway 处理。

支持三种入口：

1. **普通文本消息** (`im.message.message_received_v1`)
2. **卡片按钮点击** (`card.action.trigger`)
3. **Bot 菜单点击** (`application.bot.menu_v6`)

容器处理完消息后，直接把最终回复发回飞书（通过 `X-Hermes-Reply-Via: feishu`
header），无需再经过主 gateway。

## 架构

```text
gateway/platforms/feishu.py
├── _process_inbound_message
│   └── # [owner] 调用 owner.feishu.profile_routing.try_route_inbound_message
├── _on_card_action_trigger
│   └── # [owner] 调用 owner.feishu.profile_routing.try_route_card_action
└── 不保留任何 profile 路由相关状态/方法

gateway/platforms/api_server.py
├── /v1/runs 读取 X-Hermes-Reply-Via 等 header
└── run.completed 后调用 owner.feishu.profile_routing.feishu_reply

owner/feishu/
├── profile_routing.py      # 核心：路由解析、HTTP 转发、卡片 action 转发、飞书回复
└── bot_menu.py             # Bot 菜单入口，委托 try_route_bot_menu_command

owner/config/
└── patch_feishu_profile.yaml   # 配置模板

owner/patch_config.py
└── load_patch_feishu_profile_config()  # 独立加载器
```

所有核心逻辑都在 `owner/feishu/profile_routing.py`；`gateway/platforms/feishu.py`
和 `api_server.py` 只保留 1-3 行 `# [owner]` 标记的薄委托。

## 配置

```yaml
# ~/.hermes/patch_feishu_profile.yaml
feishu:
  user_routing:
    # 容器之间通信用的共享 API key（/v1/runs 的 Authorization）
    internal_api_key: "change-me"

    # 白名单用户始终留在主 gateway 处理
    whitelist:
      - ou_admin

    # 按 chat_id 路由
    chat_profile_routes:
      oc_team_a: "work"

    # 按 open_id 路由
    user_profile_routes:
      ou_alice: "personal"

    # 兜底
    default_profile: "default"

    # profile 名称 → 容器地址
    profile_endpoints:
      default: "http://127.0.0.1:8642"
      work: "http://127.0.0.1:9100"
      personal: "http://127.0.0.1:9101"
```

profile 容器本身也是 hermes-agent API server，需要暴露 `/v1/runs`。
容器要把 `FEISHU_APP_ID` / `FEISHU_APP_SECRET` 配成同一个飞书应用，才能直接回消息。

## 数据流

### 1. 普通消息

```text
飞书 ──WebSocket──▶ 主 gateway feishu.py
                   try_route_inbound_message()
                   resolve_profile_route(chat_id, open_id)
                   POST /v1/runs ──▶ profile 容器
                                       │
                                       ▼
                                   AIAgent 处理
                                       │
                                       ▼
   飞书 ◀──HTTP── feishu_reply() ◀── run.completed
   (X-Hermes-Reply-Via: feishu)
```

### 2. 卡片按钮

卡片渲染时若来自 profile 容器，会带上 `action_value.hermes_profile=<profile_name>`。
主 gateway 收到 `card.action.trigger` 后：

- 有 `hermes_profile` → 转发到对应容器 `/v1/feishu/card-actions`（同步 POST）。
- 无 `hermes_profile` 但当前用户在路由表里 → 直接 ack 丢弃，避免重复处理。
- 其他 → 走本地卡片处理。

### 3. Bot 菜单

Bot 菜单事件只到达主 gateway。解析出 synthetic command 后，调用
`try_route_bot_menu_command()`。若命中路由则转发；否则走本地 slash command。

## 关键实现细节

### 路由优先级

1. `whitelist` open_ids
2. 本地命令黑名单（目前只有 `/restart`）→ 留在主 gateway
3. `chat_profile_routes[chat_id]`
4. `user_profile_routes[open_id]`
5. `default_profile`
6. 无匹配 → 本地处理

`/restart` 影响的是主 gateway 进程生命周期，因此强制由主 gateway 处理；
`/new`, `/stop`, `/reset`, `/model`, `/status` 等会话级命令正常路由到 profile 容器。

### 会话隔离

- P2P: `session_key = feishu:dm:{open_id}`
- 群聊: `session_key = feishu:group:{chat_id}`

### 回复方式

容器收到 `X-Hermes-Reply-Via: feishu` 时，在 `run.completed` 后读取
`X-Hermes-Reply-Receive-Id*` / `X-Hermes-Reply-Message-Id`，直接调用飞书
IM API 回复/引用原消息。

### 失败降级

- `patch_feishu_profile.yaml` 不存在或格式错误 → 全部走主 gateway。
- profile 容器 HTTP 失败 → 给用户发送提示 "⚠️ 服务暂时不可用，请稍后再试"，然后走主 gateway。
- 删除 `owner/feishu/profile_routing.py` 后，`gateway/platforms/feishu.py` 和
  `api_server.py` 仍可正常启动运行，只是路由功能消失（`_owner_import` 懒加载返回
  None）。

## 可移除性

- 删除 `owner/feishu/profile_routing.py` → 路由功能消失，官方文件不会崩溃。
- 删除 `owner/config/patch_feishu_profile.yaml` → 只是模板，无运行影响。
- 删除 `owner/docs/feishu-multi-profile-routing-owner-v16.md` → 文档丢失，不影响运行。
- 删除 `tests/owner/test_feishu_profile_routing.py` → 测试丢失，不影响运行。

## 源码改动清单

| 文件 | 改动类型 | 说明 |
|------|----------|------|
| `gateway/platforms/feishu.py` | fix | 2 处 `# [owner]` 薄委托，删除原 adapter 内 helper 方法 |
| `gateway/platforms/api_server.py` | fix | 1 处 `# [owner]` 薄委托 + lazy import helper，删除原 helper 方法 |
| `owner/feishu/profile_routing.py` | feat | 新增高层 `try_route_*` 封装，迁移 `feishu_reply` 实现 |
| `owner/feishu/bot_menu.py` | refactor | 使用 `try_route_bot_menu_command` 替代 adapter 方法探针 |
| `owner/patch_config.py` | feat | 新增 `load_patch_feishu_profile_config()` 通用 YAML 加载器 |
| `owner/config/patch_feishu_profile.yaml` | feat | 配置模板 |
| `tests/owner/test_feishu_profile_routing.py` | test | 路由解析与加载器测试 |
| `owner/docs/feishu-multi-profile-routing-owner-v16.md` | docs | 本文档 |

## Commit 建议

```
fix(gateway): minimal [owner] hooks for Feishu multi-profile routing
fix(api_server): minimal [owner] hook for X-Hermes-Reply-Via feishu
feat(owner): add Feishu multi-profile routing with external containers
refactor(owner/feishu): use profile_routing.try_route_bot_menu_command
```
