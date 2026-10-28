# C05 · 舰队开户链路（fleet add）

> 状态：**仅设计，未实现**（2026-10-28）。  
> 隶属 [`README.md`](./README.md)（C05 飞书多 profile 舰队路由）。挂载三层、`fleet_profiles`、`hub_only` 以该主稿已定稿为准。  
> 本文件描述「加人」如何**对话触发、由 Hermes 编排执行**；**不**实现 skill/CLI/脚本、**不**改生产、**不**改 compose 现网。

## 1. 目标

把「加人」收成一条可 dry-run 的链路；**默认 UX 是对话，不是人手敲 shell**。

```
运维在飞书 / Gateway 会话里对 Hermes 说
「给某某开户 / 加 fleet profile」
        │
        ▼
  Hermes（agent）收集最小字段、确认、编排
        │
        ▼
  （内部）调用 fleet-add 工具 / 脚本 / 可选 hermes fleet add
        │
        ▼
  fleet_profiles.<uid> 人卡 + user_profile_routes
        │
        ▼
  passwd 用户 + /home/<uid>
  /data/hermes/profiles/<uid> 种子
        │
        ▼
  compose 双挂载（home → /root；profiles → /root/.hermes）
        │
        ▼
  docker compose up + health（localhost:2602x）
```

终态与主稿一致：**逻辑名 = LDAP uid**；passwd 仅为好认；隔离靠「一 profile 一容器 + `profiles/<uid>`」。

**口径（2026-10-28 对齐）**：

1. **触发**：对话式（飞书 / Gateway 里跟 Hermes 说开户类意图）。
2. **执行**：由 Hermes 去跑开户动作；人**不**把 `hermes fleet add` 当主入口在终端手敲。
3. **`hermes fleet add` / `owner/scripts/fleet_add.*`**：若存在，是 **Hermes 可调用的工具 / 命令面**（以及运维逃生舱），不是给人的默认 UX。

## 2. 最小人工输入 vs 可全自动

对话里由 Hermes 向运维收集；字段集合不变。

### 必须提供（对话收集）

| 输入 | 说明 |
|------|------|
| **`ldap_uid`** | 主键（如 `yangtb`）；默认 = 逻辑 profile = passwd 名 = `fleet_profiles` 键 |
| **`display_name`** | 中文名（人卡 / 运维展示） |
| **飞书 `ou_*`** | 写入 `feishu.bots.<app_id>.user_routing.user_profile_routes`；冷用户可先建号、后补 ou（或「已私聊 Bot，从日志解析」半自动） |

选填：`hub_only.feishu` / `hub_only.api`、历史 `docker.hermes_dir` / `home_dir`、skill 套餐、是否开 OV。

### 可全自动（Hermes 编排后执行）

| 步骤 | 默认行为 |
|------|----------|
| 分配 API 端口 | 扫描现网 `2602x`，取 `max+1`（避开已知空缺策略可配置） |
| 写 overlay | 增 `fleet_profiles.<uid>`；增 `user_profile_routes[ou]=uid`；`api_server.url/api_key` |
| `api_key` | **舰队共用一把**（与现网一致），自动写入人卡，不每人新钥 |
| `useradd` + home | 建 passwd + `/home/<uid>`（缺则补；已存在则校验对齐） |
| 种子 Hermes 家 | `/data/hermes/profiles/<uid>`（config/sqlite 骨架；可从模板或 hub 拷贝最小集） |
| 生成 compose | **目标态双挂载**（见主稿 §已定挂载规范）；**禁止**照抄现网「只挂 home」模板 |
| `compose up` | 起 `hermes-<uid>`；探活 `url` / health |
| dry-run | 默认先在对话里展示将改文件与将执行命令，确认后再写 |

### 半自动 / 仍要人

| 项 | 原因 |
|----|------|
| 冷用户的 `ou_*` | 无稳定 contact API；私聊 Bot / 日志解析可辅助 |
| skill 勾选、OV 特例 | 有默认套餐；例外要人（仍在对话里确认） |
| 飞书应用可见性、LDAP 目录建号 | 组织侧，出 Hermes 树 |
| 历史目录迁徙 rsync | 老 profile 从 `/home/.../.hermes` → `profiles/<uid>` 属 Ops 切片，不并进「新开户」默认路径 |

## 3. 推荐形态

**默认路径：对话触发 → Hermes 编排 →（内部）调 fleet-add 工具/脚本。**

| 选项 | 角色 | 评价 |
|------|------|------|
| **对话 + onboarding skill（如 `xy-user-onboarding`）** | **默认 UX** | 运维只说话：「给某某开户」；skill 收集三字段 → dry-run 确认 → 调开户工具。**不再**逐步手改 yaml/compose，也**不**要求人手敲 CLI |
| **`owner/scripts/fleet_add.py`（或同目录包）** | **执行内核** | 开户逻辑全在 `owner/`（二次开发规范）；由 Hermes **作为 tool** 调用；亦可用 `python -m` 作逃生舱 |
| **`hermes fleet add` 子命令** | **工具面 / 逃生舱** | 若官方 CLI 扩展点干净，做 **薄入口** 委托上述脚本，供 Hermes tool 或运维紧急手敲；**不是**推荐给人的主入口；**不要**把开户业务写进官方 `cli/` 深改 |
| **ansible** | 不主用 | 现有 inventory 面向 GPU 集群，不是舰队开户；避免两套真相源 |

实现时优先：**对话包装 + 可 dry-run 的执行内核**；CLI 子命令仅作内部 tool / 逃生，可后挂，且不得写成「运维默认去敲 `hermes fleet add`」。

## 4. 与已定稿设计的关系

| 已定项 | 开户链路如何服从 |
|--------|------------------|
| **挂载三层** | 新 compose：**代码 RO** + **`profiles/<uid>`→`/root/.hermes`** + **`/home/<uid>`→`/root`**（`.hermes` 叠在 home 上） |
| **`fleet_profiles.<ldap_uid>`** | 开户写入的**唯一人卡真相源**；`api_server` 供 C05 推导 endpoints |
| **`hub_only`** | 人卡可选；测试号可 `hub_only.feishu: true` 留 Hub、不转发 |
| **端口** | 写入 `api_server.url: http://127.0.0.1:<port>`；与现网 2602x 段一致 |
| **共用 `api_key`** | 从现网/overlay 已有密钥读取后写入新人卡，不轮转每人一把 |
| **passwd** | 保留、与 uid 对齐；不为隔离，为好找 |
| **C05 路由** | 开户只写配置；路由代码已读人卡（C05a）。新 ou 生效需 Hub 热读或重启策略另定 |
| **C06 LDAP** | 开户**不**建 LDAP 目录账号；人卡 `ldap.uid` 默认同键即可。认证门仍属 C06 |

## 5. 明确未实现 · 建议切片

**当前：设计 only。无对话 skill、无 CLI、无脚本、无生产改动。**

建议实现切片（以后开做时）：

| 切片 | 内容 | 验收 |
|------|------|------|
| **O1** | dry-run 内核：读 overlay + 端口扫描 → 打印将写入的人卡 / ou 路由 / compose 草稿 / 系统命令 | 不落盘；可供对话回显 |
| **O2** | 写 overlay（`fleet_profiles` + `user_profile_routes`）；可选备份 | diff 可审；Mac 用假数据夹具 |
| **O3** | 宿主机：`useradd`、种子 `profiles/<uid>`、生成 compose 双挂载 | 路径符合主稿；不碰已有容器 |
| **O4** | `compose up` + health；失败可回滚说明 | 探活通过；文档记录回滚步骤 |
| **O5** | **对话 UX**：onboarding skill / 工具声明，让 Hermes 收集字段 → 调 O1–O4；可选薄 `hermes fleet add` 仅作 tool 面 | 飞书会话可走完开户；人手敲 CLI **非**验收项 |

顺序：**O1 → O2 → O3 → O4**；**O5 是默认产品面**，可与 O1 并行设计 skill 契约，但不挡内核落地。  
与 **C05b**（生产切 overlay）、**Ops**（存量 rsync 迁 `profiles/`）分开：开户工具服务**增量新人**；存量迁移另单。

## 6. 仍开放

| # | 问题 | 默认倾向 |
|---|------|----------|
| F1 | **工具面落点**：仅 Hermes tool → `owner/scripts/fleet_add.py`，是否再加 `hermes fleet add` 薄入口给 tool/逃生？ | 先脚本/tool；有干净扩展点再加子命令。**默认 UX 仍是对话** |
| F2 | **是否双写旧 `patch_feishu_profile.yaml`**？ | C05b 前若 Hub 仍回落 patch：**可双写**路由相关键；C05b 后只写 overlay。人卡主结构只进 overlay |
| F3 | Hub 加载新人卡：热更新 vs 重启 gateway？ | 先文档「改完需 reload/重启」；热更新另议 |
| F4 | 种子 `profiles/<uid>` 从哪来（空骨架 / 模板 profile / 拷 hub 最小集）？ | 最小空骨架 + 必要 config 键；模板可后加 |
| F5 | 对话鉴权：谁可以在飞书里触发开户？ | 仅运维白名单 / Hub 管理员会话；开户 tool 默认高权限 |

## 7. 非目标

- 不实现本文件所述对话 skill / CLI / 脚本（直到另开实现任务）。
- 不把「人手敲 `hermes fleet add`」写成推荐主路径。
- 不改 node010 现网 compose / passwd / overlay 真值。
- 不替代 C05b 配置迁移、不替代存量 home→profiles rsync。
- 不在文档提交真实 `api_key` / `ou_*` / LDAP 密码。
