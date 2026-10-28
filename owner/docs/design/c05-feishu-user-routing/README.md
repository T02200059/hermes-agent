# C05 · 飞书多 profile 舰队路由（初步设计稿）

> 状态：**设计口径已拍板**（2026-10-28）；**未实现**路由代码。  
> 依据：node010 现网拓扑 + 挂载三层 + overlay + 方案② HTTP 舰队 + **按人 `fleet_profiles`** + 二次开发规范 v2 基线。

## 意图

同一飞书 bot 的 WebSocket 只由 **Hub gateway** 持有；按飞书 `open_id` / `chat_id` 把入站消息 **HTTP 转发**到各人独立的 Hermes 进程（Docker profile 容器）。  
配置进 **`overlay.yaml`**。本轮 **不做 LDAP 认证门 / API 身份反代**（C06）。

**不**用官方同进程 `gateway.multiplex_profiles` / `gateway.profile_routes` 替代舰队；二者正交（见下）。

## 已拍板（本讨论收敛）

| 项 | 决定 |
|----|------|
| 路由实现策略 | **方案②**：照迁旧 owner HTTP 舰队路由（`resolve` → `POST …/v1/feishu/inbound`）；**不接**官方同进程 multiplex 送达 |
| 配置主源 | **`overlay.yaml`**（C01 `load_owner_config` / `load_patch_config`）；与 C09 一样可短暂回落 `patch_feishu_profile.yaml` |
| **配置主结构** | **按人顶层 `fleet_profiles.<逻辑名>`**（逻辑名 = LDAP uid）；每人下挂 `ldap` / `docker` / `api_server` / 可选 `feishu` |
| 飞书 ou→人 | 仍在 **`feishu.bots.<app_id>.user_routing`**（`user_profile_routes` / `chat_profile_routes` / `default_profile`）；**值 = `fleet_profiles` 的 key** |
| `profile_endpoints` | **优先从 `fleet_profiles.*.api_server` 推导**；避免与按人表双维护。旧 `user_routing.profile_endpoints` 仅迁移回落 |
| 全局 LDAP 认证 | 顶层 **`ldap:`**（host / bind / enabled…）；**人维度 uid 在 `fleet_profiles.<id>.ldap`** |
| `api_identity` 平行表 | **收敛进按人表**（见下）；不再以顶层 `api_identity.routes` 为主路径 |
| Hub 白名单（测试/留 Hub） | **按人字段**：`feishu.hub_only` / `api_server.hub_only`（两套可分开）；短名单仅作可选全局 override，**不推荐主路径** |
| C05 vs C06 | **C05 仍不实现 LDAP 门 / API 身份反代**；可读 `fleet_profiles` 推导飞书 endpoints；Docker 映射字段写进设计供 Ops |
| 进程模型 | Docker；容器内 **uid0 自认 root**；一 profile 一容器 |
| 数据 / 家目录 | 三层挂载（见下）；passwd 用户名 **默认 = 逻辑名**（好认），**不**当隔离机制 |
| patch 回落 | **与 C09 同模式**：主 overlay、缺段再读 patch；C05b 稳定后文档标 deprecated |
| ssh / 共享卷 | **先维持现网共享卷** |
| cron | 迁 `profiles/` 前 **先保持现网行为** |
| Mac overlay | **不写真舰队路由**；实现时用假数据单测夹具 |

## 目标态拓扑

```
飞书 App（同一 bot）
    │ WS
    ▼
Hub gateway（宿主机 systemd，root，HERMES_HOME=/data/hermes）
    │ HTTP localhost:2602x  + Bearer per-profile key
    ▼
Docker hermes-<逻辑名> ×N（容器内 uid0，自认 root）
    ├─ 代码/venv：RO 共用
    ├─ /root        ← passwd /home/<逻辑名>（或 docker.home_dir 覆盖）
    └─ /root/.hermes ← /data/hermes/profiles/<逻辑名>（或 docker.hermes_dir）
```

## 已定挂载规范

| # | 宿主机 | 容器 | 说明 |
|---|--------|------|------|
| 1 | `/data/hermes/hermes-agent`（+ venv） | 代码/venv 路径 | **一份**，只读共用 |
| 2 | `/data/hermes/profiles/<逻辑名>`（或 `docker.hermes_dir`） | `/root/.hermes` | 官方一等 `HERMES_HOME` |
| 3 | `/home/<逻辑名>`（或 `docker.home_dir`；passwd 默认 = 逻辑名） | `/root` | 容器自认 root 的家 |
| 4 | — | — | **`.hermes` 必须叠挂在 home 之上** |
| 5 | — | uid 0 | Docker 内自认 root；**不做**裸机 `User=`；**不用** `user:` 非 root |
| 6 | Hub：`/data/hermes` | — | systemd；**唯一**飞书 WS |

## 配置主结构：按人 `fleet_profiles`

### 为何按人分

- 一人一节：LDAP uid、Docker 路径、api_server 地址、Hub 白名单同屏，**少维护两张平行表**（旧 `profile_endpoints` ↔ `identity_routes`）。
- 给某人「不路由、留 Hub」做测试时，只改此人下的 `hub_only`，不必去翻全局 whitelist 短名单（优于旧 `patch_feishu_profile.yaml` 平行表）。
- 飞书侧与 API 侧白名单 **可分开**：例如只测飞书留 Hub、API 仍反代（或反过来）。

### 逻辑名约定

| 层 | 默认 | 说明 |
|----|------|------|
| `fleet_profiles` 的 **key** | **LDAP uid**（例 `yangtb`） | 全系统逻辑名 |
| `user_profile_routes` 的 **值** | 同 key | 飞书 ou → 人 |
| passwd / 默认 `home_dir` | 同 key | `/home/yangtb` |
| 默认 `hermes_dir` | 同 key | `/data/hermes/profiles/yangtb` |
| `api_server` 反代目标 | 同 key | C06；恒等，无需另表 |

历史 basename（如旧 `yangtianbao`）只写在此人 `docker.hermes_dir` / `home_dir`，**不**改逻辑 key。

### 完整示意 yaml（假数据；真值留部署机）

```yaml
# ~/.hermes/overlay.yaml  （Hub HERMES_HOME）

# ── 按人舰队表（主键 = LDAP uid）────────────────────────────
fleet_profiles:
  yangtb:                              # 杨天宝；逻辑名 = LDAP uid
    display_name: 杨天宝               # 可选，仅文档/运维
    ldap:
      uid: yangtb                      # 可省略（默认同 key）
    docker:
      # 省略则：hermes_dir=/data/hermes/profiles/yangtb
      #         home_dir=/home/yangtb；passwd 用户名默认 = yangtb
      hermes_dir: /data/hermes/profiles/yangtianbao   # 历史目录例外
      home_dir: /home/yangtianbao
    api_server:
      url: http://127.0.0.1:26027
      api_key: "example-key-not-real"
      # hub_only: true                 # C06：此 LDAP 身份留 Hub，不反代
    feishu:
      # hub_only: true                 # C05：此人对应的飞书 ou 若命中路由仍可…
      # 注意：飞书「谁对应此人」在 user_profile_routes；hub_only 见下节语义
      hub_only: false

  liruiyang:
    display_name: 李瑞阳
    # ldap / docker 全默认即可
    api_server:
      url: http://127.0.0.1:26028
      api_key: "example-key-not-real"
    feishu:
      hub_only: false

  hubops:                              # 例：运维号，飞书与 API 都留 Hub 做测试
    display_name: Hub Operator
    api_server:
      url: http://127.0.0.1:26026      # 可仍登记；hub_only 时不反代
      api_key: "example-key-not-real"
      hub_only: true                   # ↔ 旧 identity_whitelist
    feishu:
      hub_only: true                   # ↔ 旧 user_routing.whitelist（按人）

  fleet_default:                       # 可选默认落地容器（非真人 LDAP 亦可）
    api_server:
      url: http://127.0.0.1:26026
      api_key: "example-key-not-real"

# ── 飞书入站：ou / chat → 逻辑名（C05）─────────────────────
feishu:
  # … bot_menu / skill_approval / queue_card 等已有段 …
  bots:
    cli_example_app_id:
      user_routing:
        # 群 → 逻辑名（可选；现网常空）
        chat_profile_routes: {}

        # 人 → 逻辑名（值必须是 fleet_profiles 的 key）
        user_profile_routes:
          ou_alice_open_id: yangtb
          ou_bob_open_id: liruiyang
          ou_ops_open_id: hubops

        default_profile: fleet_default   # 可选

        # 可选全局短名单（不推荐主路径；见「Hub 白名单」）
        # whitelist:
        #   - ou_ops_open_id

        # 旧式 profile_endpoints：迁移期可留；运行时优先 fleet_profiles.*.api_server
        # profile_endpoints: { … }

# ── 全局 LDAP 认证（C06；与「人」分节）─────────────────────
ldap:
  enabled: false
  # host / bind_dn / bind_password / base_dn / …  真值留部署机
```

### 节职责一览

| 节 | 职责 | 谁实现 |
|----|------|--------|
| **`fleet_profiles.<id>`** | 人：ldap uid、docker 路径、api_server url/key、两侧 hub_only | **C05** 读 api_server 推导飞书转发；**Ops** 读 docker；**C06** 读 hub_only / ldap.uid |
| **`feishu.bots.<app_id>.user_routing`** | 飞书 `ou_*` / chat → 逻辑名；可选 `default_profile`；可选短 `whitelist` | **C05** |
| **`ldap`**（顶层） | 全局认证（host/bind…） | **C06** |
| ~~顶层 `api_identity`~~ | **不再作主路径**；迁移见下 | — |
| ~~`user_routing.profile_endpoints`~~ | **不再作主路径**；由 `fleet_profiles.*.api_server` 取代 | 迁移回落 |

### Hub 白名单（按人 · 推荐主路径）

旧 patch 用两条**平行短名单**：

- `user_routing.whitelist`：飞书 DM 命中则留 Hub  
- `identity_whitelist`：API `X-Hermes-Identity` 命中则留 Hub  

按人后改为每人可选字段（**默认同 false / 省略 = 正常转发**）：

| 字段 | 语义 | 对应旧键 |
|------|------|----------|
| `fleet_profiles.<id>.feishu.hub_only: true` | 飞书侧：解析到该逻辑名后 **不 HTTP 转发**，留 Hub 本地处理 | `user_routing.whitelist`（按 open_id；见解析） |
| `fleet_profiles.<id>.api_server.hub_only: true` | API 侧（C06）：该 LDAP 身份 **不反代**，留 Hub | `identity_whitelist` |

**两套可分开**：例如 `feishu.hub_only: true` 且 `api_server.hub_only: false` → 只测飞书留 Hub，API 仍进容器。

**飞书解析与 `hub_only` 的关系（推荐语义）**：

1. 仍用 `user_profile_routes[open_id]`（或 chat / default）得到逻辑名 `id`。  
2. 若 `fleet_profiles[id].feishu.hub_only` → **留 Hub**（等同旧 whitelist 命中）。  
3. 否则查 `fleet_profiles[id].api_server.{url,api_key}` 转发；缺 endpoint → 告警且不回落乱发。

> 也可保留「DM + open_id ∈ 短 `whitelist`」作 **全局 override**（迁移期 / 临时），但 **不推荐主路径**：测试「某人留 Hub」应改此人 `feishu.hub_only`，避免 ou 与逻辑名两处维护。

**API（C06）**：`X-Hermes-Identity` → 匹配 `fleet_profiles.*.ldap.uid`（默认 = key）→ 若 `api_server.hub_only` 留 Hub，否则反代到 `api_server.url`。

### 解析优先级（飞书入站 / C05）

1. （可选全局 override）DM 且 `open_id ∈ user_routing.whitelist` → Hub  
2. `chat_profile_routes[chat_id]` → 逻辑名  
3. `user_profile_routes[open_id]` → 逻辑名  
4. `default_profile` → 逻辑名  
5. 仍无 → Hub 本地  
6. 得到逻辑名后：若 `fleet_profiles[id].feishu.hub_only` → Hub；否则转发 `api_server`

群聊跳过步骤 1 的短名单直觉可与现网一致（现网群聊跳过 whitelist）；`hub_only` 在步骤 6 对群/人统一生效——**实现时与现网行为对齐**：若现网 whitelist 仅 DM，则 `hub_only` 亦可约定仅 DM，或文档写清「hub_only 对所有解析到该人的会话生效」。**推荐**：`hub_only` **对解析到该逻辑名的一切入站生效**（比旧「仅 DM whitelist」更好测）；若需兼容旧「仅 DM」，另加 `feishu.hub_only_dm_only: true`（默认 false）。实现前可再钉一句。

### endpoints 推导（避免双表）

```text
forward(profile_id):
  person = fleet_profiles[profile_id]
  url/key = person.api_server.url / api_key
  # 若无 fleet_profiles 或缺 api_server：回落旧 user_routing.profile_endpoints[profile_id]
```

C06 反代共用同一 `api_server` 块。

## 从旧配置迁移

| 旧（patch / 现网） | 新（按人） |
|--------------------|------------|
| `user_routing.user_profile_routes: { ou_x: yangtianbao }` | 值改为逻辑名 **`yangtb`**；目录例外写 `yangtb.docker.*` |
| `user_routing.profile_endpoints.yangtianbao` | → `fleet_profiles.yangtb.api_server.{url,api_key}` |
| `user_routing.whitelist: [ou_ops]` | → 先保证 `user_profile_routes` 有 `ou_ops → hubops`，再设 `fleet_profiles.hubops.feishu.hub_only: true`；短 `whitelist` 可暂留 |
| `user_routing.identity_routes: { yangtb: yangtianbao }` | **删除主路径**：逻辑 key 已是 uid；过渡期若 API 仍报旧名，用 `ldap.uid` 别名或临时 routes 回落（C06） |
| `user_routing.identity_whitelist: [hubops]` | → `fleet_profiles.hubops.api_server.hub_only: true` |
| 顶层 `ldap:`（host/bind） | **保留不动**（全局认证） |
| 顶层 `api_identity`（若曾写入设计） | **不采用为主**；routes 恒等可删；whitelist → 各人 `api_server.hub_only` |

迁移脚本（以后 Ops，本回合不写）：按旧 endpoints 的 key 建 `fleet_profiles` 骨架 → 改名为 LDAP uid → 填 `docker.*` 指旧路径 → 改 `user_profile_routes` 值 → 删平行 `identity_*` / `profile_endpoints`。

## 现状 vs 目标

| | 现网（node010 历史） | 目标 |
|--|--|--|
| 数据面 | `/home/<name>/.hermes` 整挂 `/root` | `hermes_dir` → `/root/.hermes`；`home_dir` → `/root` 叠挂 |
| 人/端点表 | `profile_endpoints` + `identity_*` 平行 | **`fleet_profiles` 按人一节** |
| 飞书 ou 表 | `user_profile_routes`（值=旧 profile 全名） | 同节；**值 = LDAP uid = fleet key** |
| Hub 白名单 | 全局 `whitelist` / `identity_whitelist` | **按人 `feishu.hub_only` / `api_server.hub_only`** |
| LDAP 认证 | 顶层 `ldap:` | **保持** |
| 路由代码 | 旧 `owner/feishu/profile_routing.py` | v2 照迁语义；endpoints 改读 `fleet_profiles` |
| 官方 multiplex | 未用作舰队 | **继续不用** |

## 与官方 `profile_routes` / multiplex 的关系

| | 官方 | 本舰队（C05） |
|--|--|--|
| 开关 | `gateway.multiplex_profiles` | **不依赖** |
| 人/端点 | 同进程切 `HERMES_HOME` | **`fleet_profiles` + HTTP** |
| 飞书匹配表 | `gateway.profile_routes[]` | **`feishu.bots.*.user_routing`（ou→逻辑名）** |
| 送达 | 同进程 ContextVar | **跨容器** `POST {api_server.url}/v1/feishu/inbound` |

**正交**：官方 = 同机多 profile 家目录切换；我们 = 一 bot 多容器。  
**可借鉴**：profile 名校验、目标未配置则拒绝。  
**不可直接吃**：官方送达路径。→ **方案②**。

## 代码落点（实现时，本回合不写）

参考旧树（只读）：`hermes-agent-owner/owner/feishu/profile_routing.py`

| 入口 | 作用 |
|------|------|
| `try_route_inbound_message` | Hub 入站：有路由则转发；失败只通知、**不**回落 Hub 本地 |
| `try_route_card_action` / 菜单 | 按 profile 标签 / 用户路由跨容器 |
| `_forward_to_profile_container` | `POST …/v1/feishu/inbound` |
| 配置 | 读 `fleet_profiles` + `user_routing`；推导 url/key；尊重 `feishu.hub_only` |

v2：`owner/feishu/profile_routing.py` + 官方 adapter **薄胶水**（`# [owner] C05`）。  
**C05 不**实现 LDAP bind / `api_server.hub_only` 反代（C06）。

## 明确不做

- LDAP 认证门 / API 身份反代（**C06**）
- 官方 multiplex 替换舰队
- 容器内非 root / 裸机 `User=`
- 本轮改 Mac 开发 bot；Mac overlay **不写真**舰队
- 继续以 `api_identity` + `profile_endpoints` 双平行表为主路径

## 落地切片（以后实现）

| 切片 | 内容 |
|------|------|
| **C05a** | v2 迁 `profile_routing`；读 `fleet_profiles` + `user_routing`；`feishu.hub_only`；单测夹具 |
| **C05b** | node010 配置切 overlay 按人表；退役 patch 主路径 |
| **C06** | 顶层 `ldap` 认证 + `api_server.hub_only` 反代；旧 `identity_*` 只读别名 |
| **Ops** | rsync → `hermes_dir`；compose 读 `docker.*`；补 passwd；清双轨 |

## 已收开放项

| # | 原问题 | 拍板 |
|---|--------|------|
| 1 | patch 回落 | 与 C09 同模式 |
| 2 | ssh 共享卷 | 先维持 |
| 3 | cron | 先不动语义 |
| 4 | Mac overlay | 不写真路由 |
| 5 | identity 结构 | **并入 `fleet_profiles`**；全局仅留 `ldap:` 认证 |
| 6 | 逻辑名 | **LDAP uid**；目录用 `docker.*` |
| 7 | 配置主结构 | **按人 `fleet_profiles`** |
| 8 | Hub 白名单 | **按人 `feishu.hub_only` / `api_server.hub_only`**；短名单不推荐主路径 |
| 9 | endpoints | **从 `api_server` 推导** |

## 仍可钉一句（实现前）

- `feishu.hub_only`：对「解析到该人的所有会话」生效，还是「仅 DM」（兼容旧 whitelist）？**稿内推荐：全部会话；可选 `hub_only_dm_only`。**
- `fleet_default` 这类非 LDAP 键：是否要求必须有 `ldap.uid`，或允许无 ldap 块的「纯落地容器」。

## 非目标（本设计稿）

- 不写路由实现、不改 compose、不重启 gateway、不 push。  
- 不在本稿提交真实 `api_key` / `open_id` / LDAP 清单。
