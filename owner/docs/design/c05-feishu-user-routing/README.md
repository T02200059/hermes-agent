# C05 · 飞书多 profile 舰队路由（初步设计稿）

> 状态：**设计口径已拍板**（2026-10-28）；**未实现**路由代码。  
> 依据：node010 现网拓扑 + 挂载规范 + overlay 节名拍板 + `api_identity`/`ldap` 分节（方案 A）+ 逻辑名默认 LDAP uid + `二次开发规范.md` v2 基线。

## 意图

同一飞书 bot 的 WebSocket 只由 **Hub gateway** 持有；按飞书 `open_id` / `chat_id` 把入站消息 **HTTP 转发**到各人独立的 Hermes 进程（Docker profile 容器）。  
配置进 **`overlay.yaml`**。本轮 **不做 LDAP / `api_identity` 加载**（C06）。

**不**用官方同进程 `gateway.multiplex_profiles` / `gateway.profile_routes` 替代舰队；二者正交（见下）。

## 已拍板（本讨论收敛）

| 项 | 决定 |
|----|------|
| 路由实现策略 | **方案②**：照迁旧 owner HTTP 舰队路由（`resolve` → `POST …/v1/feishu/inbound`）；**不接**官方同进程 multiplex 送达 |
| 配置主源 | **`overlay.yaml`**（C01 `load_owner_config` / `load_patch_config`）；与 C09 一样可短暂回落 `patch_feishu_profile.yaml` |
| 配置节名（飞书） | **`feishu.bots.<app_id>.user_routing`**（含 `profile_endpoints`；贴近现网活文件键树） |
| Identity / LDAP 配置形状 | **方案 A**（见下）：顶层 **`api_identity`**（`routes` / `whitelist`）+ 顶层 **`ldap`**（认证）；endpoints **仍**在 `user_routing` |
| C05 vs C06 | **C05 仍忽略 identity**：不实现 `api_identity` 加载/匹配；旧 `identity_*` 仅作 **C06 迁移期只读别名来源**（设计约定，本轮不写代码） |
| 进程模型 | Docker；容器内 **uid0 自认 root**；一 profile 一容器 |
| 数据 / 家目录 | 三层挂载（见下）；passwd 用户 **保留**（好认、好找），**不**当隔离机制 |
| patch 回落 | **与 C09 同模式**：主 overlay、缺段再读 patch；C05b 稳定后文档标 deprecated，不设硬删除日 |
| ssh / 共享卷 | **先维持现网共享卷**；home 层先占位好认，内容清单 Ops 再收紧 |
| cron | 迁 `profiles/` 前 **先保持现网行为**（迁目录不改 cron 语义）；另开 Ops 条再收敛 |
| Mac overlay | **不写真舰队路由**；实现时用假数据单测夹具；生产键只上 Hub |
| 命名 / 逻辑 profile | **默认 LDAP uid**（passwd、profile、路由表值/endpoints key 对齐）；目录可用显式 map 兼容旧 basename |

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

## 命名与目录映射（LDAP uid 对齐 · 已拍板方向）

目标：**逻辑身份统一用 LDAP uid**（例：杨天宝 → `yangtb`），不再以旧 Hermes profile 全名（如 `yangtianbao`）为默认主键。

| 层 | 默认名 | 说明 |
|----|--------|------|
| 配置逻辑 profile 名 | **LDAP uid**（`yangtb`） | `user_profile_routes` 的**值**、`api_identity.routes` 的**值**、`profile_endpoints` 的 **key** 同一套 |
| Linux passwd / `/home/<name>` | **同 LDAP uid** | 好认；与逻辑名默认一致 |
| Hermes profile / `HERMES_HOME` 逻辑名 | **对齐 LDAP uid** | 官方 `-p` / 路由表用的名字 |
| 飞书侧 | `ou_*` → 逻辑 profile | 仍是飞书 open_id 表；值用 LDAP uid |
| 身份侧（C06） | LDAP uid → 逻辑 profile | 对齐后**多为恒等**；**保留** `api_identity.routes` 表以兼容别名/过渡 |

**灵活例外（历史目录）**：Docker 挂载时允许逻辑名 ≠ 宿主机路径 basename。例如逻辑 `yangtb`，数据目录仍可能是 `/data/hermes/profiles/yangtianbao`，home 仍可能是 `/home/yangtianbao`。用**显式 map**（实现时再定键名；候选见下「仍开放」）声明，例如：

```yaml
# 示意（键名未拍板；见开放项）
profile_dirs:                    # 候选形状之一
  yangtb:
    data_dir: /data/hermes/profiles/yangtianbao   # → 容器 /root/.hermes
    home_dir: /home/yangtianbao                   # → 容器 /root
# 未列出的 profile：约定 data_dir=/data/hermes/profiles/<逻辑名>
#                   home_dir=/home/<逻辑名>
```

原则：

- **路由表只认逻辑名**（LDAP uid）；目录例外不进 `ou_*` / identity 路由值。  
- 迁移期可暂时 `api_identity.routes: { yangtb: yangtianbao }`；目录迁完、逻辑名统一后改为恒等或删别名。  
- C05 实现路由时先按逻辑名查 `profile_endpoints`；**目录 map 属 Ops/compose**，可与 C05a 代码解耦，但配置形状要在设计里预留。

## 现状 vs 目标

| | 现网（node010 历史） | 目标 |
|--|--|--|
| 数据面 | `/home/<name>/.hermes` 整挂到容器 `/root` | `profiles/<name>` → `/root/.hermes`；home 另挂 `/root` |
| 路由配置主源 | `patch_feishu_profile.yaml`（活文件） | **`overlay.yaml`** → `feishu.bots.*.user_routing` |
| Identity 配置 | 埋在 `feishu.bots.*.user_routing.identity_*` | 顶层 **`api_identity`**（方案 A）；旧键 = C06 只读别名 |
| LDAP | 顶层 `ldap:`（认证） | **保持顶层 `ldap:`**；与 `api_identity` 分节 |
| 路由代码 | 旧树 `owner/feishu/profile_routing.py`（Hub HTTP 转发） | v2 **照迁同语义**（方案②）；加载主认 overlay |
| 官方 multiplex | 未用作舰队 | **继续不用** |
| Linux passwd | 有的有、有的无 | **保留**（好认）；非隔离机制 |
| 逻辑名 | 旧 profile 全名（如 `yangtianbao`）混用 | **默认 LDAP uid**；目录 basename 例外用显式 map |
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

        # 人 → 逻辑 profile（值 = LDAP uid）
        user_profile_routes:
          ou_alice: yangtb                 # 例：杨天宝 LDAP=yangtb
          ou_bob: liruiyang

        default_profile: fleet_default   # 可选；未命中时用

        # endpoints key = 逻辑 profile 名（LDAP uid）；共用给飞书转发与 C06 identity 反代
        profile_endpoints:
          fleet_default:
            url: http://127.0.0.1:26026
            api_key: "example-key-not-real"
          yangtb:
            url: http://127.0.0.1:26027
            api_key: "example-key-not-real"
          liruiyang:
            url: http://127.0.0.1:26028
            api_key: "example-key-not-real"

# ── C06 配置形状（方案 A；C05 不读、不实现）────────────────
# API Server 身份路由：按 LDAP uid / X-Hermes-Identity 选逻辑 profile 或留 Hub
# 对齐后 routes 多为恒等；保留表以兼容别名 / 过渡（旧 profile 全名）
api_identity:
  whitelist:                     # 原 identity_whitelist：留 Hub，不反代
    - hubops
  routes:                        # ldap_uid → 逻辑 profile（通常恒等）
    yangtb: yangtb
    liruiyang: liruiyang
    # 过渡别名例：yangtb: yangtianbao   # 仅当逻辑名尚未切到 uid 时

# LDAP 认证（现网已是顶层；保持分节，勿塞进 feishu）
ldap:
  enabled: false
  # host / bind / …   # 真值留部署机；C05 不实现
```

运行时读取路径（与 C09 对齐）：`config.owner.feishu.bots.<app_id>.user_routing`（经 `apply_owner_overlay`），或直接 `load_patch_config()["feishu"]["bots"][…]`。  
C06 目标路径：`config.owner.api_identity` + `config.owner.ldap`（经同一 overlay 加载器）。

### 解析优先级（沿用现网 `resolve_profile_route`）— **仅飞书入站 / C05**

1. DM 且 `open_id ∈ whitelist` → Hub 本地（返回无路由）  
2. `chat_profile_routes[chat_id]`  
3. `user_profile_routes[open_id]`  
4. `default_profile`  
5. 仍无 → Hub 本地  

群聊跳过 whitelist，直接走 2→4。  
**C05 不走** `api_identity` / 旧 `identity_*` / LDAP。

### 可选备选（不推荐作主路径）

| 备选 | 形状 | 为何不选作主 |
|------|------|----------------|
| A | 顶层 `fleet.bots.<app_id>…` | 与现网/overlay `feishu` 族分裂；多一个第一层段 |
| B | `feishu.user_routing`（无 bots/app_id） | 单 bot 时更短，但丢多 bot 扩展，且与活文件不一致 |
| C | 继续只活在 `patch_feishu_profile.yaml` | 违背「配置收进 overlay」；仅作迁移回落 |

## Identity / LDAP 配置（方案 A · 已拍板）

现网把 `identity_routes` / `identity_whitelist` 塞在 `feishu.bots.<app_id>.user_routing` 里，与飞书 bot 绑死；但它们走的是 **api_server + LDAP uid**（`X-Hermes-Identity`），不是飞书 `ou_*`。顶层已有独立 `ldap:`（认证），身份路由却埋在飞书节——无 `FEISHU_APP_ID` 时整段可能读不到，C06 别扭。

| 节 | 职责 | 谁实现 |
|----|------|--------|
| `feishu.bots.<app_id>.user_routing` | 飞书 `ou_*` / chat 路由 + **`profile_endpoints`**（共用） | **C05** |
| **`api_identity`**（顶层） | `whitelist` + `routes`（LDAP uid → profile） | **C06** |
| **`ldap`**（顶层） | 认证（enabled / host / bind…） | **C06** |

**迁移期（C06，写在设计约定即可；C05 不写加载逻辑）**：

1. **主读** overlay 顶层 `api_identity.{routes,whitelist}`。  
2. **缺段时只读别名**：回落旧 `feishu.bots.<app_id>.user_routing.identity_routes` / `identity_whitelist`（及 patch 同树）。  
3. **不**再把「C05 静默忽略旧键就完事」当作终态表述——旧键的角色变为 **C06 别名来源**；C05 代码路径仍完全不读 identity。

曾考虑未采用：顶层 `fleet`（要挪 endpoints，改已拍板）；塞进 `ldap.identity`（认证与路由耦太紧）。

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
**C05 不**实现 `api_identity` / LDAP 加载；api_server identity 反代留给 C06。

## 复用官方的策略（已锁定）

1. ~~薄封装官方匹配、只换送达为 HTTP~~ — 不采用（匹配模型不同构）。  
2. **照迁旧 `profile_routing`，配置改读 overlay** — **已拍板**。  
3. ~~仅 Hook 送达层~~ — 不采用（无干净扩展点）。

## 明确不做

- LDAP / `api_identity` 匹配与加载（**C06**；C05 忽略）
- 官方 multiplex 替换舰队
- 容器内非 root / 裸机 `User=`
- 本轮改 Mac 开发 bot 拓扑；Mac overlay **不写真**舰队路由
- 把 Hub 拆进「多人自认 root 容器」 unless 另议
- 第三人路径半吊子迁移（有 `profiles/` 名无叠挂 home）

## 落地切片（以后实现）

| 切片 | 内容 |
|------|------|
| **C05a** | v2 迁 `profile_routing` + overlay `user_routing` + 单测；**不**接 `api_identity`；Mac/文档可先；node010 仍旧树直到切 |
| **C05b** | node010 配置切 overlay；退役 patch 作主路径（保持 Docker 拓扑） |
| **C06** | 顶层 `api_identity` + `ldap`；旧 `identity_*` 只读别名；api_server 身份反代 / 头剥离 / SSE |
| **Ops** | 数据 rsync → `profiles/<name>`；compose 双挂；补 passwd 用户；清双轨遗迹；cron/ssh 收紧（与路由解耦） |

## 已收开放项（原「仍开放」→ 默认已拍板）

| # | 原问题 | 拍板 |
|---|--------|------|
| 1 | patch 回落保留多久？ | **与 C09 同模式**；C05b 后文档 deprecated，无硬删除日 |
| 2 | ssh/ansible 共享卷 vs 每人 home？ | **先维持现网共享卷** |
| 3 | 迁 `profiles/` 前 cron？ | **先不动语义**；另开 Ops |
| 4 | Mac overlay 写空路由壳？ | **不写真路由**；夹具 / 生产只上 Hub |
| 5 | 旧 `identity_*`：C05 忽略 vs 告警？ | **C05 完全不读**；**方案 A 已取代**「静默忽略旧键就完事」——旧键改为 **C06 只读别名来源**，终态配置在顶层 `api_identity` |
| 6 | 逻辑 profile 默认名？ | **LDAP uid**（passwd / profile / 路由值 / endpoints key 对齐）；历史目录用显式 map |

已从开放问题划掉：节名、方案②、挂载三层、passwd、Docker root、不做 LDAP（C05）、不接官方 multiplex、**方案 A `api_identity`/`ldap` 分节**、逻辑名默认 LDAP uid。

## 仍开放（命名映射配置键 · 供后续拍板）

逻辑名与宿主机路径 basename 不一致时，显式 map 放哪、键叫什么——**未拍板**；候选：

| 候选 | 形状（示意） | 利 | 弊 |
|------|----------------|----|----|
| **M1** | 顶层 `fleet_dirs.<逻辑名>.{data_dir,home_dir}` | 与 feishu/api_identity 解耦；Ops 一眼找 | 又一个第一层段 |
| **M2** | `profile_endpoints.<逻辑名>` 旁挂 `data_dir` / `home_dir` | 和 endpoints 同表 | 把 compose/Ops 塞进飞书 bot 节；多 bot 重复 |
| **M3** | 顶层 `profiles.<逻辑名>.{endpoint,data_dir,home_dir,…}` | 一人一节聚合 | 要挪 endpoints，改已拍板「endpoints 在 user_routing」 |
| **M4** | 仅 compose/`hermes-fleet.env` 注释 + 约定，**不进 overlay** | 零 schema | 路由/文档看不到例外；易漂 |

**默认倾向（未拍板，仅讨论锚点）**：偏 **M1** 或 **M4**——目录例外是 Ops/compose 事，尽量别污染 `user_routing`；C05a 代码可不读 map，只认逻辑名 → URL。  
另可保留过渡别名：`api_identity.routes` / 临时 `user_profile_routes` 值仍指向旧逻辑名，直到目录与逻辑名双对齐。

## 非目标（本设计稿）

- 不写路由实现、不改 compose、不重启 gateway、不 push。  
- 不在本稿提交真实 `api_key` / `open_id` / LDAP 清单（示例脱敏；真值留在部署机配置）。
