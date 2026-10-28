# C05 · 飞书多 profile 舰队路由（初步设计稿）

> 状态：**设计定稿讨论中**（2026-10-28）。本回合只立稿，**未实现**路由代码。  
> 依据：node010 现网拓扑讨论 + 挂载规范拍板 + `二次开发规范.md` v2 基线。

## 意图

同一飞书 bot 的 WebSocket 只由 **Hub gateway** 持有；按飞书 `open_id` / `chat_id` 把入站消息 **HTTP 转发**到各人独立的 Hermes 进程（Docker profile 容器）。  
配置进 **`overlay.yaml`**。本轮 **不做 LDAP**（C06）。

**不**用官方同进程 `gateway.multiplex_profiles` / `gateway.profile_routes` 替代舰队；二者正交（见下）。

## 目标态拓扑

```
飞书 App（同一 bot）
    │ WS
    ▼
Hub gateway（宿主机 systemd，root，HERMES_HOME=/data/hermes）
    │ HTTP localhost:2602x  + Bearer per-profile key
    ▼
Docker hermes-<name> ×N（容器内 uid0，自认 root）
    ├─ 代码/venv：RO 共用
    ├─ /root        ← passwd 用户 /home/<name>
    └─ /root/.hermes ← /data/hermes/profiles/<name>   （叠挂在 home 之上）
```

## 已定挂载规范

| # | 宿主机 | 容器 | 说明 |
|---|--------|------|------|
| 1 | `/data/hermes/hermes-agent`（+ venv） | 代码/venv 路径 | **一份**，只读共用 |
| 2 | `/data/hermes/profiles/<name>` | `/root/.hermes` | 官方一等 `HERMES_HOME`（config / sqlite / skills…） |
| 3 | `/home/<name>`（passwd 用户家） | `/root` | 容器自认 root 的家；**passwd 非隔离必需**，为好认、好找 |
| 4 | — | — | **`.hermes` 必须叠挂在 home 之上**（先 `/root`，再 `/root/.hermes`） |
| 5 | — | uid 0 | Docker 内自认 root；**不做**裸机 `systemd User=`；**不用** `user:` 非 root |
| 6 | Hub：`/data/hermes` | — | systemd；**唯一**飞书 WS；HTTP 转发 `127.0.0.1:2602x` |

补充：

- **进程/目录隔离**靠「一 profile 一容器 + `profiles/<name>`」；passwd 只是命名与路径约定。
- 缺 passwd 用户的 profile（现网如部分账号）在 Ops 切片补齐，不挡路由代码迁 overlay。
- 共享运维卷（scripts、inventory、常挂 ssh 等）仍可挂；不算第四类「一人一份」。
- 官方 `get_profile_dir(name)` → `<hermes_root>/profiles/<name>`，与目标态目录布局对齐（相对现网 `/home/<name>/.hermes` 更干净）。

## 现状 vs 目标

| | 现网（node010 历史） | 目标 |
|--|--|--|
| 数据面 | `/home/<name>/.hermes` 整挂到容器 `/root` | `profiles/<name>` → `/root/.hermes`；home 另挂 `/root` |
| 路由配置主源 | `patch_feishu_profile.yaml`（活文件） | **`overlay.yaml`**（`feishu.bots.*.user_routing`） |
| 路由代码 | 旧树 `owner/feishu/profile_routing.py`（Hub HTTP 转发） | v2 迁同语义；加载只认 overlay（可短暂回落 patch） |
| 官方 multiplex | 未用作舰队 | **继续不用** |
| Linux passwd | 有的有、有的无 | **保留**（好认）；非隔离机制 |
| `/data/hermes/profiles/` | 多是 compose 壳/旧副本，活数据不在 | **活 HERMES_HOME** |

## 路由配置（进 overlay）

建议形状（与现网 keys 对齐，便于迁）：

```yaml
feishu:
  bots:
    <FEISHU_APP_ID>:
      user_routing:
        whitelist: []                 # DM 内 open_id → 留 Hub（不转发）
        chat_profile_routes: {}       # chat_id → profile
        user_profile_routes: {}       # open_id → profile
        default_profile: <name>       # 可选
        profile_endpoints:
          <name>:
            url: http://127.0.0.1:2602x
            api_key: "<per-profile>"  # 须与容器 API_SERVER_KEY 一致；文档示例脱敏
```

解析优先级（沿用现网 `resolve_profile_route`）：

1. DM 且 `open_id ∈ whitelist` → Hub 本地（返回无路由）
2. `chat_profile_routes[chat_id]`
3. `user_profile_routes[open_id]`
4. `default_profile`
5. 仍无 → Hub 本地

群聊跳过 whitelist，直接走 2→4。

与 C06 / LDAP：`ldap` / `identity_*` **分节**；本轮不迁、不实现。旧 patch 里 ldap 段先原样留着，避免误伤。

## 与官方 `profile_routes` / multiplex 的关系

| | 官方 | 本舰队（C05） |
|--|--|--|
| 开关 | `gateway.multiplex_profiles`（上游已趋向默认开、false 退役） | **不依赖**；Hub/容器各自单 profile 进程即可 |
| 路由表 | `gateway.profile_routes[]`：`platform` + `user_id`/`chat_id`/`thread_id`/`guild_id`，特异度计分 | `feishu.bots.*.user_routing`：飞书 open_id/chat 图 + `profile_endpoints` |
| 匹配实现 | `gateway/profile_routing.py`：`parse_profile_routes` / `match_profile_route` / `ProfileRoute` | owner：`resolve_profile_route` → HTTP |
| 送达 | **同进程**切 `HERMES_HOME` / secret_scope（`_resolve_profile_home_for_source`） | **跨容器** `POST {endpoint}/v1/feishu/inbound`（+ card-actions） |
| 会话/状态 | 共享或分 home，但同 OS 进程树 | 每容器独立 `state.db` / 独立 send_only 飞书适配器 |

**正交**：官方表解决「同进程多 profile 家目录切换」；我们解决「一 bot 多容器进程隔离」。  
**可借鉴**：特异度 / `user_id` 匹配直觉、profile 名校验（`normalize_profile_name`）、拒绝未 serve 的 profile（我们侧对应「endpoints 无此名则告警」）。  
**不可直接吃**：把 `profile_routes` 打开当舰队——会假设同进程 session、同锁、同 adapter 生命周期，与 Docker uid0 + 分家目录模型冲突（亦见 `二次开发规范.md` v2 基线）。

## 代码落点（实现时，本回合不写）

参考旧树（只读）：`hermes-agent-owner/owner/feishu/profile_routing.py`

| 入口 | 作用 |
|------|------|
| `try_route_inbound_message` | Hub 入站：有路由则转发；失败只通知、**不**回落 Hub 本地 |
| `try_route_card_action` / `handle_card_action_request` | 卡按钮按 `hermes_profile` 标签跨容器 |
| `try_route_bot_menu_command` | 菜单命令随用户路由 |
| `_forward_to_profile_container` | `POST …/v1/feishu/inbound`，schema_version + target profile |
| 子容器 | `inject_inbound` + api_server doorway；`verify_inbound_target_profile` |

v2：逻辑放 `owner/feishu/profile_routing.py`；官方 adapter / api_server **薄胶水**（`# [owner] C05`）。配置加载对齐 C01/C09：主读 overlay。

## 复用官方的策略选项（调研结论，实现前再拍）

详见本回合调研回报；摘要：

1. **薄封装官方匹配、只换送达为 HTTP** — 匹配模型不完全同构（缺 whitelist / default_profile / bots 嵌套 / endpoints）；强行映射收益有限。  
2. **基本照迁旧 `profile_routing`，配置改读 overlay** — **倾向推荐**：现网已验证；与规范「跨进程自研」一致。  
3. **仅 Hook 送达层** — 官方匹配与 `_resolve_profile_home_for_source` 耦合紧，无干净「只换送达」扩展点。

官方**不能**当舰队用的假设（摘要）：同进程；路由命中后切 ContextVar/`HERMES_HOME`；`profiles_to_serve` 同 host；共享 listener / secret_scope；`ProfileRouteRejected` 表示「本进程未 serve」而非「转发到别的容器」。

## 明确不做

- LDAP / `identity_*`（C06）
- 官方 multiplex 替换舰队
- 容器内非 root / 裸机 `User=`
- 本轮改 Mac 开发 bot 拓扑
- 把 Hub 拆进「多人自认 root 容器」 unless 另议
- 第三人路径 `/data/hermes/profiles/` 当运行时却无叠挂 home（迁移期禁止半吊子）

## 落地切片（以后实现）

| 切片 | 内容 |
|------|------|
| **C05a** | v2 迁 `profile_routing` + overlay 节 + 单测；Mac/文档可先；node010 仍旧树直到切 |
| **C05b** | node010 配置切 overlay；退役 patch 作主路径（保持 Docker 拓扑） |
| **Ops** | 数据 rsync → `profiles/<name>`；compose 双挂；补 passwd 用户；清双轨遗迹（与路由解耦，可并行规划） |

## 开放问题

1. overlay 节名是否完全沿用 `feishu.bots.<app_id>.user_routing`（推荐，少迁成本），或另立顶层 `fleet:`？  
2. 迁 overlay 时 patch 回落保留多久？  
3. `/root` 除 `.hermes` 外，ssh/ansible 等继续共享挂还是每人 home 自带？（挂载规范已定「有 home 层」，内容清单仍可收紧）  
4. 共享 cron vs per-profile cron：数据迁 `profiles/` 前定留哪套。  
5. 实现时复用策略是否锁定「照迁 + overlay」（见上选项 2）？

## 非目标（本设计稿）

- 不写路由实现、不改 compose、不重启 gateway、不 push。  
- 不在本稿提交真实 `api_key` / `open_id` 清单（示例脱敏；真值留在部署机配置）。
