# C05b · node010 部署切片与风险（2026-10-29 survey）

> 状态：**只读 survey + 可逆准备已完成**；**未**切生产流量、**未**改运行中 checkout、**未**重启 gateway。  
> 依据：node010 实机、设计稿 README、`node010-operations` skill、C05a tip `6825e533bb`（gitlab `origin/v2`）。

## 1. 现网快照（脱敏）

| 项 | 现状 |
|----|------|
| Hub | systemd `hermes-gateway.service`，`HERMES_HOME=/root/.hermes`，api `:8642`，飞书 WS |
| 代码 | `/data/hermes/hermes-agent` 在 **`owner`** @ `d72008c5e6`（落后 `origin/owner`；**不是** v2） |
| gitlab | `origin/v2` = `6825e533bb`（C05a 已在；Mac tip 可达） |
| 子网关 | 14× Docker `hermes-<profile>`，镜像 `hermes-profile:latest`（约 2026-08-04），`network_mode: host` |
| 挂载 | **现网单挂**：`/home/<name>:/root` + 代码/venv-docker RO + 共享运维卷；**尚未**三层（profiles→`.hermes` 叠 home） |
| `HERMES_PROFILE` | 与容器名一致（`yangtianbao` 等）；**无** `FEISHU_CONNECTION_MODE`（未显式 `send_only`） |
| 路由主源 | **`/root/.hermes/patch_feishu_profile.yaml`**（与仓内 `owner/config/…` **不是同一份**） |
| overlay | **不存在**（`/root/.hermes/overlay.yaml` 无） |
| 路由表 | 13 条 `ou→profile`；`default_profile=hermesxiyun`；14 个 `profile_endpoints`（26026–26041，跳号） |
| Hub 白名单 | `yangtianbao` / `wangtingwei` 对应 ou 在 `user_routing.whitelist` → **DM 留 Hub**（尽管也有 endpoint） |
| LDAP | patch 内 `enabled: true`，`enforce: seen`（**C06**；本切片不改认证） |
| passwd | 有 `yangtianbao` 等；**无** `yangtb` 用户；`/data/hermes/profiles/<name>` 多为 compose 目录，真数据在 `/home/<name>/.hermes` |

### 端口（api_server 均 UP）

`hermesxiyun:26026` `yangtianbao:26027` `liruiyang:26028` `sunqifei:26029` `xiaofan:26030` `wuyongjin:26031` `lizigao:26032` `yanwanhui:26034` `ruifengyun:26035` `gaorong:26037` `wangtingwei:26038` `zhangwenguo:26039` `caocan:26040` `lixin:26041`；Hub `:8642`。

## 2. 与目标态差距

| 目标（README） | 差距 |
|----------------|------|
| 跑 v2 C05a 代码 | 现网仍是 owner 旧 `profile_routing`（无人卡 / 无 M1 doorway 等修补） |
| `overlay.yaml` + `fleet_profiles` | 无 overlay；endpoints 仍在 patch |
| 主键 LDAP uid | 现网键是 **全名 profile**（`yangtianbao`）；与容器 `HERMES_PROFILE` 对齐 |
| 三层挂载 | 仍整挂 `/home/<name>:/root` |
| 子网关 `send_only` | env **未设**（代码支持；生产未钉死） |
| Hub `HERMES_HOME=/data/hermes` | 现网是 `/root/.hermes`（有 `/data/hermes/patch_*.yaml` 旁路文件，但 loader 读 `~/.hermes`） |

**硬约束**：`user_routing` / `fleet_profiles` 的目标名必须等于容器 `HERMES_PROFILE` / `container_profile_identity()`，否则 inbound **409 profile_mismatch**。故 **B 切片先保留现网全名键**；LDAP uid 改名（`yangtb`）属后续 Ops，需同步改 compose env + 路由表。

## 3. 已做的可逆准备（本轮）

| 产物 | 路径 | 说明 |
|------|------|------|
| v2 旁路 worktree | `/data/hermes/hermes-agent-v2-preview` @ `6825e533bb` | **不**影响运行中 `owner` checkout |
| overlay 草稿（含真 key） | `/data/hermes/c05b-draft/overlay.yaml.draft` mode 600 | **未**安装到 Hub；勿进 git |
| 脱敏结构 | 同目录 `overlay.yaml.draft.redacted` | 可对照 |
| 导入冒烟 | host venv + `venv-docker` 均可 `import owner.feishu.profile_routing`（sys.path→preview） | 非完整 gateway 冒烟 |

草稿语义：从**现网 live patch** 生成；`hub_only.feishu/api=true` 用于 `yangtianbao`/`wangtingwei`，以保持「白名单留 Hub」行为；`docker.*` 先记**当前** home 路径（三层迁挂另刀）。

## 4. 建议切片（未执行；需确认后再动红线）

### B1 — 配置准备（低风险，可继续）

- 审草稿 vs live patch；补齐 display_name / 缺 passwd 用户备注。  
- 子 profile `.env` **草稿清单**：统一加 `FEISHU_CONNECTION_MODE=send_only`（先文件、不重启）。  
- 文档：本文件 + README / 清单勾选进度。

### B2 — 代码切到 v2（**高风险 · 需确认**）

1. 备份：运行中 HEAD、live patch、各 profile `.env`、compose。  
2. `/data/hermes/hermes-agent`：`git fetch` + checkout **`v2`** @ `6825e533bb`（或快进 tip）；处理 untracked bak。  
3. **重启** Hub systemd + **全部** `hermes-*` 容器（飞书会断线；见 node010-operations 红线）。  
4. 冒烟：Hub 收消息；默认用户仍进 `hermesxiyun`；白名单用户仍留 Hub；抽测一非白名单用户 HTTP 转发；子侧日志 `send_only` / `inject_inbound`。  
5. 回滚：checkout 回原 `owner` SHA + 再重启。

风险：owner↔v2 历史分叉大（非快进）；venv 依赖可能缺件（今日 import 路由模块 OK，**整 gateway 未在 preview 起过**）；镜像虽旧但代码/venv 为 bind mount，一般**不必**先 rebuild image，若入口/系统库不兼容再议。

### B3 — 激活 overlay（中风险 · 建议紧接 B2 或同窗口）

1. 复制草稿 → `/root/.hermes/overlay.yaml`（保留 patch 作回落）。  
2. 热读 / 必要时 reload Hub；确认路由走 fleet_profiles。  
3. **不要**删 patch，直到稳定。

### B4 — 行为变更（另确认，勿与 B2/B3 绑死）

- 若要把 **yangtb** 从 Hub 本地改到 `yangtianbao` 容器：去掉 whitelist / `hub_only.feishu`（并确认 Hub+子 allowlist、home channel）。  
- LDAP uid 改名、三层挂载 rsync、rebuild `hermes-profile`：属 **Ops**，默认不进本 C05b 最小刀。

## 5. 明确本轮不做

- 不停生产、不切 `owner`→`v2`、不写 `/root/.hermes/overlay.yaml`、不改 compose 挂载、不迁 `/home`→`profiles/` 数据、不改 LDAP、不做 fleet_add / onboarding。

## 6. 建议下一刀

**默认下一刀 = B1 收尾 + 用户确认后的 B2（代码切 v2 + 全量重启）**；B3 overlay 激活可与 B2 同维保窗口。  
三层挂载与 uid 改名另开 Ops 窗口。
