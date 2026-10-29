# C05 · 飞书多 profile 舰队路由（初步设计稿）

> 状态：**配置结构已定稿**（2026-10-28），**C05a 已 push**；**C05b survey+可逆准备**见 [c05b-node010-plan.md](./c05b-node010-plan.md)（2026-10-29；**未**切生产）。  
> 依据：node010 现网拓扑 + 挂载规范 + **按人 `fleet_profiles` 主结构** + overlay 节名 + 方案② HTTP 舰队路由 + `二次开发规范.md` v2 基线。

## 意图

同一飞书 bot 的 WebSocket 只由 **Hub gateway** 持有；按飞书 `open_id` / `chat_id` 把入站消息 **HTTP 转发**到各人独立的 Hermes 进程（Docker profile 容器）。  
配置进 **`overlay.yaml`**。本轮 **不做 LDAP / `api_identity` 加载**（C06）；身份与目录、endpoints 在配置形状上已收成 **按人一张卡片**。

**不**用官方同进程 `gateway.multiplex_profiles` / `gateway.profile_routes` 替代舰队；二者正交（见下）。

**相关**：[舰队开户链路（fleet add）](./fleet-add.md) — 对话触发、Hermes 编排的加人设计；**O1–O3 已落地**（dry-run / overlay apply / 宿主机种子+三层 compose）；O4+ / 对话 UX **未实现**；**延后**：完全更新 `xy-user-onboarding`（先内核/模板，见该稿 §5 / D1）。

## 已拍板（本讨论收敛）

| 项 | 决定 |
|----|------|
| 路由实现策略 | **方案②**：照迁旧 owner HTTP 舰队路由（`resolve` → `POST …/v1/feishu/inbound`）；**不接**官方同进程 multiplex 送达 |
| 配置主源 | **`overlay.yaml`**（C01 `load_owner_config` / `load_patch_config`）；与 C09 一样可短暂回落 `patch_feishu_profile.yaml` |
| **人卡主结构** | 顶层 **`fleet_profiles.<ldap_uid>`**：每人下挂 `ldap` / `docker` / `api_server` / `hub_only`；**主键 = LDAP uid** |
| 全局 LDAP | 顶层 **`ldap:`** 只做连接 / enforce（认证怎么连）；**不**塞每人路由 |
| 飞书节 | **`feishu.bots.<app_id>.user_routing`** 只留 `ou_*`→uid、chat、`default_profile`、以及可选的飞书侧 `whitelist`（或改读人卡 `hub_only.feishu`）；**`profile_endpoints` 从 `fleet_profiles` 推导**，不再平行抄一份 |
| Identity 形状 | 原方案 A 的顶层 **`api_identity`** → **过渡/别名**；终态字段收进人卡（`hub_only.api`、恒等/别名由主键表达）；C05 **仍不读** identity |
| hub_only 白名单 | 按人、**飞书 / API 可分开**（`hub_only.feishu` / `hub_only.api`），便于指定某人「不路由、留 Hub」做测试；优于旧 patch 两张平行表 |
| 目录映射 | 收人卡 **`docker.hermes_dir` / `docker.home_dir`**；省略则按 uid 推导 |
| 进程模型 | Docker；容器内 **uid0 自认 root**；一 profile 一容器 |
| 数据 / 家目录 | 三层挂载（见下）；passwd 用户 **保留**（好认、好找），**不**当隔离机制 |
| patch 回落 | **与 C09 同模式**：主 overlay、缺段再读 patch；C05b 稳定后文档标 deprecated |
| ssh / 共享卷 | **先维持现网共享卷** |
| cron | 迁 `profiles/` 前 **先保持现网行为** |
| Mac overlay | **不写真舰队路由**；实现时用假数据单测夹具 |
| 命名 / 逻辑 profile | **默认 LDAP uid**（passwd、profile、路由表值、endpoints 推导 key 对齐） |

## 目标态拓扑

```
飞书 App（同一 bot）
    │ WS
    ▼
Hub gateway（宿主机 systemd，root，HERMES_HOME=/data/hermes）
    │ HTTP localhost:2602x  + Bearer per-profile key
    ▼
Docker hermes-<ldap_uid> ×N（容器内 uid0，自认 root）
    ├─ 代码/venv：RO 共用
    ├─ /root        ← passwd /home/<ldap_uid>（或 docker.home_dir）
    └─ /root/.hermes ← /data/hermes/profiles/<ldap_uid>
                       （或 docker.hermes_dir；叠挂在 home 之上）
```

## 已定挂载规范

| # | 宿主机 | 容器 | 说明 |
|---|--------|------|------|
| 1 | `/data/hermes/hermes-agent`（+ venv） | 代码/venv 路径 | **一份**，只读共用 |
| 2 | `/data/hermes/profiles/<ldap_uid>`（或 `docker.hermes_dir`） | `/root/.hermes` | 官方一等 `HERMES_HOME` |
| 3 | `/home/<ldap_uid>`（或 `docker.home_dir`） | `/root` | 容器自认 root 的家；passwd 好认 |
| 4 | — | — | **`.hermes` 必须叠挂在 home 之上** |
| 5 | — | uid 0 | Docker 内自认 root；**不做**裸机 `User=` |
| 6 | Hub：`/data/hermes` | — | systemd；**唯一**飞书 WS；HTTP 转发 |

补充：

- **子网关 connection_mode**：`FEISHU_CONNECTION_MODE=send_only`（只出站、不连 WS、不抢 Hub app_id lock；入站靠 Hub HTTP `inject_inbound`）。
- **`/v1/feishu/inbound` doorway**：仅 `send_only` 适配器可接；Hub（websocket）对该路径返回 **403** `inbound_not_send_only`（防共用 api_key 向 Hub 伪造注入）。
- **子 allowlist（M4）**：inject 路径**绕过** adapter `_admit`；授权仍靠子网关 **gateway authz** 读该 profile 的 `FEISHU_ALLOWED_USERS`（故开户仍必须写子白名单）。Hub 侧 `_admit` 在路由**之前**执行，开户还须把 ou / tenant user_id **同批写入 Hub** allowlist（或 Hub 用 `FEISHU_ALLOW_ALL_USERS`）。
- **卡按钮 `hermes_profile` 打标**：子侧用 `container_profile_identity()`（`HERMES_PROFILE`），**不要**依赖 `get_active_profile_name()`（目标态 `HERMES_HOME=/root/.hermes` 会误成 `default`）。
- **进程/目录隔离**靠「一 profile 一容器 + `profiles/<name>`」；passwd 只是命名与路径约定。
- 缺 passwd 用户的 profile 在 Ops 切片补齐，不挡路由代码迁 overlay。
- 共享运维卷（scripts、inventory、常挂 ssh 等）仍可挂。
- 官方 `get_profile_dir(name)` → `<hermes_root>/profiles/<name>`，与默认路径对齐。

## 配置主结构：按人 `fleet_profiles`（已拍板）

**键 = LDAP uid = 逻辑 profile = 默认 passwd 名。**  
每人一张卡片；飞书只做 `ou_*`→uid 的映射；endpoints / 目录 / hub 白名单都从人卡推导或读取。

### 完整示意 yaml（假数据；真值留部署机）

```yaml
# ~/.hermes/overlay.yaml  （Hub HERMES_HOME）

# ── 全局：LDAP 怎么连（C06 认证；C05 不读）────────────────
ldap:
  enabled: false
  # host / bind_dn / base_dn / enforce / …  真值留部署机

# ── 按人：舰队主表（主键 = LDAP uid）─────────────────────
fleet_profiles:
  yangtb:                              # 杨天宝；逻辑名 = LDAP uid
    display_name: 杨天宝
    ldap:
      uid: yangtb                      # 默认同键，可省略
    docker:
      # 省略则推导：
      #   hermes_dir = /data/hermes/profiles/yangtb
      #   home_dir   = /home/yangtb
      # 历史目录例外才写：
      hermes_dir: /data/hermes/profiles/yangtianbao   # → /root/.hermes
      home_dir: /home/yangtianbao                     # → /root
    api_server:
      url: http://127.0.0.1:26027
      api_key: "example-key-not-real"
    hub_only:
      feishu: false                    # true = 飞书入站留 Hub，不转发（测试白名单）
      api: false                       # true = API/X-Hermes-Identity 留 Hub（C06）

  liruiyang:
    display_name: 李瑞阳
    # ldap.uid / docker.* 全省略 → 路径与 uid 对齐
    api_server:
      url: http://127.0.0.1:26028
      api_key: "example-key-not-real"
    hub_only:
      feishu: false
      api: false

  hubops:                              # 例：只做 Hub 测试、不进容器
    display_name: Hub 运维
    hub_only:
      feishu: true
      api: true
    # 无 api_server / 无 docker → 不推导 endpoint

  fleet_default:
    display_name: 舰队默认兜底
    api_server:
      url: http://127.0.0.1:26026
      api_key: "example-key-not-real"

# ── 飞书：只留 ou→uid / default；endpoints 从人卡推导 ────
feishu:
  # … bot_menu / skill_approval / queue_card 等已有段 …
  bots:
    cli_example_app_id:
      user_routing:
        # 可选：仍可用 open_id 列表；实现时也可改读
        # fleet_profiles.*.hub_only.feishu == true 的人对应的 ou
        whitelist: []

        chat_profile_routes: {}

        # 值必须是 fleet_profiles 的键（LDAP uid）
        user_profile_routes:
          ou_alice: yangtb
          ou_bob: liruiyang

        default_profile: fleet_default

        # ❌ 不再平行抄 profile_endpoints
        # 运行时：profile → fleet_profiles[profile].api_server.{url,api_key}

# ── 过渡/别名（废弃方向；C05 不读，C06 迁移期可只读）────
# 旧顶层 api_identity / 旧 feishu…identity_* 仅作回落来源，
# 终态字段已收进 fleet_profiles（hub_only.api + 主键即路由目标）。
# api_identity:
#   whitelist: [hubops]
#   routes: { yangtb: yangtb }
```

### 字段职责

| 位置 | 职责 | 谁实现 |
|------|------|--------|
| **`fleet_profiles.<uid>`** | 人卡：docker 路径、api_server、hub_only、可选 ldap.uid | **C05** 读 `api_server` 推导 endpoints；**C06** 读 `hub_only.api` / ldap 关联 |
| **`ldap:`**（顶层） | 认证连接 / enforce | **C06** |
| **`feishu.bots.*.user_routing`** | `ou_*` / chat → uid、`default_profile`、可选飞书 whitelist | **C05** |
| ~~`api_identity`~~ | **过渡别名**；终态废弃，收敛到人卡 | C06 迁移期只读 |

### `hub_only`（测试白名单 · 优于旧平行表）

| 字段 | 语义 |
|------|------|
| `hub_only.feishu: true` | 该用户飞书入站 **留 Hub**，不 HTTP 转发（等价旧 `user_routing.whitelist` 按人表达） |
| `hub_only.api: true` | 该用户 API 身份 **留 Hub**（等价旧 `identity_whitelist`） |
| 两者可独立 | 例如只测飞书留 Hub、API 仍反代，或反过来 |

解析飞书入站时（C05）：若命中 profile 且 `hub_only.feishu`，视为「无路由 / Hub 本地」。  
（open_id→uid 仍靠 `user_profile_routes`；`hub_only` 挂在 uid 上，比「两张平行 ou/uid 表」好找。）

### 推导规则

- **endpoints**：`fleet_profiles[name].api_server` → `{url, api_key}`；缺 `api_server` 且已命中候选 profile → **ERROR + 拒绝并通知用户，绝不回落 Hub 本地**（与「绑定用户绝不回落」一致；实现返回 `(profile, "", "")`，由 `try_route_*` 停本地并通知）。  
- **默认路径**：未写 `docker.hermes_dir` → `/data/hermes/profiles/<uid>`；未写 `docker.home_dir` → `/home/<uid>`。  
- **逻辑名**：路由表值、compose 服务名、passwd 默认均用 uid；目录例外只写在 `docker.*`。

### 解析优先级（飞书入站 / C05）

1. 解析候选 profile：`chat_profile_routes` → `user_profile_routes` → `default_profile`  
2. 若候选 ∈ 飞书 open_id whitelist **或** 对应人卡 `hub_only.feishu`（DM）→ Hub 本地  
3. 用候选名查 `fleet_profiles[…].api_server` → HTTP 转发  
4. **无候选** → Hub 本地；**有候选但无 endpoint** → ERROR + 通知用户、**不**回落 Hub（已钉死，2026-10-29）

群聊跳过「按人 feishu hub_only / open_id whitelist」的 DM 语义，直接走 chat→user→default（与现网一致）。  
**C05 不走** `hub_only.api` / LDAP / 旧 `identity_*`。

### 相对旧 patch / 方案 A 的改进

| 旧 | 新 |
|----|----|
| `identity_routes` + `identity_whitelist` 埋在飞书 bot 节 | 人卡 `hub_only.api` + 主键即目标 |
| `profile_endpoints` 与路由表平行、易漂移 | **从 `fleet_profiles` 推导** |
| 顶层 `api_identity` 平行表（方案 A） | **过渡别名**；主结构改为按人 |
| 目录 map 另开 `fleet_dirs` / 开放项 | **`docker.hermes_dir` / `home_dir`** 收人卡 |
| 测试白名单两张表难找 | **按人 `hub_only`，飞书/API 可分开** |

## 现状 vs 目标

| | 现网（node010 历史） | 目标 |
|--|--|--|
| 数据面 | `/home/<name>/.hermes` 整挂 `/root` | `profiles/<uid>` → `/root/.hermes`；home 另挂 `/root` |
| 路由配置主源 | `patch_feishu_profile.yaml` | **`overlay.yaml`**：`fleet_profiles` + `feishu…user_routing` |
| Identity / 人 | 飞书节 `identity_*` 平行表 | **`fleet_profiles` 人卡**；`api_identity` 仅过渡 |
| LDAP | 顶层 `ldap:` | **保持顶层**（只认证） |
| endpoints | `user_routing.profile_endpoints` | **`fleet_profiles.*.api_server`** |
| 路由代码 | 旧 `owner/feishu/profile_routing.py` | v2 照迁同语义；加载主认 overlay + 人卡推导 |
| 官方 multiplex | 未用作舰队 | **继续不用** |
| 逻辑名 | 旧 profile 全名混用 | **默认 LDAP uid**；目录例外 `docker.*` |

## 与官方 `profile_routes` / multiplex 的关系

| | 官方 | 本舰队（C05） |
|--|--|--|
| 开关 | `gateway.multiplex_profiles` | **不依赖** |
| 路由表 | `gateway.profile_routes[]` | **`user_routing`（ou→uid）+ `fleet_profiles`（送达）** |
| 匹配 | `gateway/profile_routing.py` | owner：`resolve` → 查人卡 → HTTP |
| 送达 | **同进程**切 `HERMES_HOME` | **跨容器** `POST {endpoint}/v1/feishu/inbound` |

**正交**：官方 = 同机多 profile 家目录切换；我们 = 一 bot 多容器。  
**可借鉴**：profile 名校验、目标未配置则拒绝。  
**不可直接吃**：官方送达路径。

## 代码落点（实现时，本回合不写）

参考旧树（只读）：`hermes-agent-owner/owner/feishu/profile_routing.py`

| 入口 | 作用 |
|------|------|
| `try_route_inbound_message` | Hub 入站：有路由则转发；失败只通知、**不**回落 Hub 本地 |
| `try_route_card_action` / `handle_card_action_request` | 卡按钮按 profile 标签跨容器 |
| `try_route_bot_menu_command` | 菜单命令随用户路由 |
| `_forward_to_profile_container` | `POST …/v1/feishu/inbound` |
| 子容器 | `inject_inbound` + api_server doorway |

v2：逻辑放 `owner/feishu/profile_routing.py`；官方 adapter / api_server **薄胶水**（`# [owner] C05`）。  
配置加载：**主读 overlay** 的 `fleet_profiles` + `user_routing`；回落 patch（与 C09 同模式）。  
**C05 不**实现 LDAP 认证、不读 `hub_only.api` / 旧 `api_identity` 作主路径。

## 复用官方的策略（已锁定）

1. ~~薄封装官方匹配、只换送达为 HTTP~~ — 不采用。  
2. **照迁旧 `profile_routing`，配置改读 overlay + 人卡推导 endpoints** — **已拍板**。  
3. ~~仅 Hook 送达层~~ — 不采用。

## 明确不做

- LDAP 认证 / `hub_only.api` 匹配加载（**C06**；C05 忽略）
- 官方 multiplex 替换舰队
- 容器内非 root / 裸机 `User=`
- 本轮改 Mac 开发 bot；Mac overlay **不写真**舰队路由
- 把 Hub 拆进「多人自认 root 容器」 unless 另议
- 第三人路径半吊子迁移

## 落地切片（以后实现）

| 切片 | 内容 |
|------|------|
| **C05a** | v2 迁 `profile_routing` + overlay `fleet_profiles`/`user_routing` + 单测；endpoints 从人卡推导；**不**接 LDAP/`hub_only.api` |
| **C05b** | node010 配置切 overlay；退役 patch 作主路径 |
| **C06** | 顶层 `ldap` 认证 + 人卡 `hub_only.api`；旧 `api_identity`/`identity_*` 只读别名；api_server 身份反代 |
| **Ops** | 数据 rsync → `profiles/<uid>`；compose 读 `docker.*` 双挂；补 passwd；清遗迹；**开户**（对话触发、Hermes 执行）见 [fleet-add.md](./fleet-add.md)（未实现；**延后**完全更新 `xy-user-onboarding`） |

## 已收开放项

| # | 原问题 | 拍板 |
|---|--------|------|
| 1 | patch 回落 | 与 C09 同模式；C05b 后 deprecated |
| 2 | ssh/共享卷 | 先维持现网共享卷 |
| 3 | cron | 先不动语义 |
| 4 | Mac overlay | 不写真路由 |
| 5 | identity 配置形状 | **按人 `fleet_profiles`**；`api_identity` = 过渡别名；C05 不读 identity |
| 6 | 逻辑名 | **LDAP uid** |
| 7 | 目录 map 键 | **`docker.hermes_dir` / `docker.home_dir`** 收人卡（原 M1/M3 候选关闭） |
| 8 | 测试白名单 | **`hub_only.feishu` / `hub_only.api` 按人可分开** |

已从开放问题划掉：节名、方案②、挂载三层、passwd、Docker root、不接 multiplex、**人卡主结构**、目录字段、hub_only。

## 仍开放（实现前可再钉）

| # | 问题 | 默认倾向 |
|---|------|----------|
| R1 | 飞书 `whitelist`（ou 列表）是否完全废弃，只认 `hub_only.feishu`？ | 迁移期两者兼容：ou whitelist ∪ 人卡 hub_only；稳定后文档建议只维护人卡 |
| R2 | compose 是否直接读 overlay `fleet_profiles`，还是生成中间 env？ | Ops 另议；设计上人卡是真相源 |
| R3 | 开户自动化（fleet add）对话/tool 落点 / 是否双写旧 patch；**延后完全更新 user-onboarding** | 见 [fleet-add.md](./fleet-add.md) §5 D1 / §6；默认对话触发；**未实现** |

## 清单（实现 / 评审用）

- [x] C05a：overlay 加载 `fleet_profiles` + `user_routing`；endpoints 从 `api_server` 推导  
- [x] C05a：`hub_only.feishu`（及可选 ou whitelist）参与 resolve  
- [x] C05a：单测夹具用假 `fleet_profiles`（无真 key / ou）  
- [ ] C05b：node010 从 patch 迁到 overlay 人卡；旧 `profile_endpoints` / `identity_*` 标回落
  - 2026-10-29：survey + v2 preview worktree + overlay 草稿已就绪；**未**切流（见 c05b-node010-plan.md）  
- [ ] C06：`ldap:` + `hub_only.api`；`api_identity` 只读别名后废弃  
- [x] Ops：开户内核 O3 三层 compose 模板 + 种子（见 [fleet-add.md](./fleet-add.md)；**O1–O3 已落地** 2026-10-29；现网挂载迁徙 / passwd 对齐仍属另开 Ops；O4+ 未实现）  
- [x] **配置形状**：按人 `fleet_profiles`（ldap/docker/api_server/hub_only）已写入本稿  

## 非目标（本设计稿）

- 不写路由实现、不改 compose、不重启 gateway、不 push。  
- 不在本稿提交真实 `api_key` / `open_id` / LDAP 清单（示例脱敏）。


## 实现状态（C05a）

- **已落地已 push（Mac v2 → origin/gitlab `v2`，2026-10-29；未部署 node010 / C05b；fleet_add / onboarding 仍开）**
  - `owner/feishu/profile_routing.py`：fleet_profiles 加载、hub_only.feishu、HTTP 转发、归属校验
  - `owner/feishu/card_action.py`：卡片分派表（含 try_route_card_action）
  - adapter / api_server 薄胶水：`try_route_inbound`、`inject_inbound`、`/v1/feishu/inbound|card-actions`
  - 单测：`tests/owner/test_c05_*.py`
- **C05b 进行中（2026-10-29）**：只读 survey + `/data/hermes/hermes-agent-v2-preview` + `/data/hermes/c05b-draft/`；**未**切 `v2`、**未**装 overlay、**未**重启。详见 [c05b-node010-plan.md](./c05b-node010-plan.md)。
- **仍开**：C05b 生产切流；Ops 挂载迁 `profiles/`；C06；开户 O4+ / onboarding 见 [fleet-add.md](./fleet-add.md)（O1–O3 已落地）
