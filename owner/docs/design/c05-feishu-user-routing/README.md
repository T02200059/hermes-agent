# C05 · 飞书多 profile 舰队路由（初步设计稿）

> 状态：**设计口径已拍板一截**（2026-10-28）；**未实现**路由代码。  
> 依据：node010 现网拓扑 + 挂载规范 + overlay 节名拍板 + `二次开发规范.md` v2 基线。

## 意图

同一飞书 bot 的 WebSocket 只由 **Hub gateway** 持有；按飞书 `open_id` / `chat_id` 把入站消息 **HTTP 转发**到各人独立的 Hermes 进程（Docker profile 容器）。  
配置进 **`overlay.yaml`**。本轮 **不做 LDAP**（C06）。

**不**用官方同进程 `gateway.multiplex_profiles` / `gateway.profile_routes` 替代舰队；二者正交（见下）。

## 已拍板（本讨论收敛）

| 项 | 决定 |
|----|------|
| 路由实现策略 | **方案②**：照迁旧 owner HTTP 舰队路由（`resolve` → `POST …/v1/feishu/inbound`）；**不接**官方同进程 multiplex 送达 |
| 配置主源 | **`overlay.yaml`**（C01 `load_owner_config` / `load_patch_config`）；与 C09 一样可短暂回落 `patch_feishu_profile.yaml` |
| 配置节名 | **`feishu.bots.<app_id>.user_routing`**（贴近现网活文件键树；见下） |
| 进程模型 | Docker；容器内 **uid0 自认 root**；一 profile 一容器 |
| 数据 / 家目录 | 三层挂载（见下）；passwd 用户 **保留**（好认、好找），**不**当隔离机制 |
| LDAP | **不做**（C06）；`ldap` 顶层段与 `identity_*` 键本轮不实现匹配逻辑 |

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
| 路由配置主源 | `patch_feishu_profile.yaml`（活文件） | **`overlay.yaml`** → `feishu.bots.*.user_routing` |
| 路由代码 | 旧树 `owner/feishu/profile_routing.py`（Hub HTTP 转发） | v2 **照迁同语义**（方案②）；加载主认 overlay |
| 官方 multiplex | 未用作舰队 | **继续不用** |
| Linux passwd | 有的有、有的无 | **保留**（好认）；非隔离机制 |
| `/data/hermes/profiles/` | 多是 compose 壳/旧副本，活数据不在 | **活 HERMES_HOME** |

## 路由配置（overlay 节名 · 主推荐）

### 为何用这个级别

- **主推荐**：`feishu.bots.<app_id>.user_routing`（含 `profile_endpoints`）  
  - 与 node010 活 `patch_feishu_profile.yaml` **同构**，迁配置几乎只是剪切。  
  - 落在已有 overlay 第一层段 `feishu:` 下（与 `bot_menu` / `skill_approval` / `queue_card` 同族）；C01 约定「文件第一层 = 能力段」，**不要**再套 `owner:` / `fleet:` 外壳。  
  - 按 **飞书 app_id** 分 bot：一 Hub 可挂多 bot 时路由表不搅在一起。
- **不放顶层 `fleet:`**：另起第一层段会与现网键树分叉、和 `feishu.*` 体验配置割裂；「舰队」本质仍是飞书入站路由，不是横切能力。
- **不放官方 `gateway.profile_routes`**：那是同进程 multiplex 切 `HERMES_HOME` 的表；打开它不会帮你 HTTP 打到 Docker，还会和「每容器单 profile」假设打架。

### 推荐 yaml 树（假数据；真值留部署机）

```yaml
# ~/.hermes/overlay.yaml  （Hub HERMES_HOME；与其它 feishu.* 段并列）
feishu:
  # … bot_menu / skill_approval / queue_card 等已有段 …

  bots:
    cli_example_app_id:          # 飞书 app_id
      user_routing:
        # DM 内这些 open_id 留 Hub（不转发）
        whitelist:
          - ou_hub_operator_aaa
          - ou_hub_operator_bbb

        # 群 → profile（可选；现网常为空）
        chat_profile_routes: {}

        # 人 → profile
        user_profile_routes:
          ou_alice: alice
          ou_bob: bob

        default_profile: fleet_default   # 可选；未命中时用

        profile_endpoints:
          fleet_default:
            url: http://127.0.0.1:26026
            api_key: "example-key-not-real"
          alice:
            url: http://127.0.0.1:26027
            api_key: "example-key-not-real"
          bob:
            url: http://127.0.0.1:26028
            api_key: "example-key-not-real"

        # ── 以下键现网已存在；C05 实现时忽略匹配，留给 C06 ──
        # identity_whitelist: []
        # identity_routes: {}

# LDAP 保持与飞书分节（现网为顶层 ldap:；C06 再定是否迁 overlay）
# ldap: { ... }   # C05 不读、不实现
```

运行时读取路径（与 C09 对齐）：`config.owner.feishu.bots.<app_id>.user_routing`（经 `apply_owner_overlay`），或直接 `load_patch_config()["feishu"]["bots"][…]`。

### 解析优先级（沿用现网 `resolve_profile_route`）

1. DM 且 `open_id ∈ whitelist` → Hub 本地（返回无路由）  
2. `chat_profile_routes[chat_id]`  
3. `user_profile_routes[open_id]`  
4. `default_profile`  
5. 仍无 → Hub 本地  

群聊跳过 whitelist，直接走 2→4。  
**C05 不走** `identity_*` / LDAP（即使 yaml 里仍留着键）。

### 可选备选（不推荐作主路径）

| 备选 | 形状 | 为何不选作主 |
|------|------|----------------|
| A | 顶层 `fleet.bots.<app_id>…` | 与现网/overlay `feishu` 族分裂；多一个第一层段 |
| B | `feishu.user_routing`（无 bots/app_id） | 单 bot 时更短，但丢多 bot 扩展，且与活文件不一致 |
| C | 继续只活在 `patch_feishu_profile.yaml` | 违背「配置收进 overlay」；仅作迁移回落 |

## 与官方 `profile_routes` / multiplex 的关系

| | 官方 | 本舰队（C05） |
|--|--|--|
| 开关 | `gateway.multiplex_profiles` | **不依赖** |
| 路由表 | `gateway.profile_routes[]` | **`feishu.bots.*.user_routing` + `profile_endpoints`** |
| 匹配 | `gateway/profile_routing.py` | owner：`resolve_profile_route` → HTTP |
| 送达 | **同进程**切 `HERMES_HOME` | **跨容器** `POST {endpoint}/v1/feishu/inbound` |

**正交**：官方 = 同机多 profile 家目录切换；我们 = 一 bot 多容器。  
**可借鉴**：profile 名校验、`user_id` 匹配直觉、目标未配置则拒绝（我们侧 = endpoints 缺失告警）。  
**不可直接吃**：官方送达路径。

## 代码落点（实现时，本回合不写）

参考旧树（只读）：`hermes-agent-owner/owner/feishu/profile_routing.py`

| 入口 | 作用 |
|------|------|
| `try_route_inbound_message` | Hub 入站：有路由则转发；失败只通知、**不**回落 Hub 本地 |
| `try_route_card_action` / `handle_card_action_request` | 卡按钮按 `hermes_profile` 标签跨容器 |
| `try_route_bot_menu_command` | 菜单命令随用户路由 |
| `_forward_to_profile_container` | `POST …/v1/feishu/inbound` |
| 子容器 | `inject_inbound` + api_server doorway |

v2：逻辑放 `owner/feishu/profile_routing.py`；官方 adapter / api_server **薄胶水**（`# [owner] C05`）。配置加载：**主读 overlay**；回落 `load_patch_feishu_profile_config`（与 C09 同模式）。

## 复用官方的策略（已锁定）

1. ~~薄封装官方匹配、只换送达为 HTTP~~ — 不采用（匹配模型不同构）。  
2. **照迁旧 `profile_routing`，配置改读 overlay** — **已拍板**。  
3. ~~仅 Hook 送达层~~ — 不采用（无干净扩展点）。

## 明确不做

- LDAP / `identity_*` 匹配（C06）
- 官方 multiplex 替换舰队
- 容器内非 root / 裸机 `User=`
- 本轮改 Mac 开发 bot 拓扑
- 把 Hub 拆进「多人自认 root 容器」 unless 另议
- 第三人路径半吊子迁移（有 `profiles/` 名无叠挂 home）

## 落地切片（以后实现）

| 切片 | 内容 |
|------|------|
| **C05a** | v2 迁 `profile_routing` + overlay 节 + 单测；Mac/文档可先；node010 仍旧树直到切 |
| **C05b** | node010 配置切 overlay；退役 patch 作主路径（保持 Docker 拓扑） |
| **Ops** | 数据 rsync → `profiles/<name>`；compose 双挂；补 passwd 用户；清双轨遗迹（与路由解耦） |

## 仍开放（需拍板；附默认建议）

| # | 问题 | 默认建议 |
|---|------|----------|
| 1 | overlay 切主后，`patch_feishu_profile.yaml` 回落保留多久？ | **与 C09 同模式**：主 overlay、缺段再读 patch；C05b 稳定后文档标 deprecated，不设硬删除日 |
| 2 | `/root` 上除叠挂 `.hermes` 外，ssh/ansible 等继续**共享卷**还是主要靠每人 home？ | **先维持现网共享卷**；home 层先占位好认，内容清单 Ops 再收紧 |
| 3 | 数据迁 `profiles/` 前：共享 cron vs per-profile cron 留哪套？ | **先保持现网行为**（迁目录不改 cron 语义）；另开 Ops 条再收敛 |
| 4 | C05a 是否现在就往 Mac `owner/config/overlay.yaml` 写空 `bots.*.user_routing` 壳？ | **不写真路由**；实现 PR 再用假数据单测夹具；生产键只上 Hub |
| 5 | yaml 里已有 `identity_*`：C05 加载时忽略还是缺 LDAP 就告警？ | **静默忽略**（键保留给 C06）；文档注明勿指望生效 |

已从开放问题划掉：节名（→ 主推荐）、方案②、挂载三层、passwd、Docker root、不做 LDAP、不接官方 multiplex。

## 非目标（本设计稿）

- 不写路由实现、不改 compose、不重启 gateway、不 push。  
- 不在本稿提交真实 `api_key` / `open_id` 清单（示例脱敏；真值留在部署机配置）。
