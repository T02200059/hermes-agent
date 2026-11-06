# C05b · node010 切流计划（2026-11-06 拍板）

> 状态：**计划已更新**；**未**切生产流量、**未**改运行中 checkout、**未**装正式 overlay、**未**重启 gateway。  
> 目标 tip（Mac `v2`）：`7be19213ff`（写稿时 `git rev-parse --short=10 HEAD` 核过）。  
> 冻结 tag：`owner-2026-11-06` → `d72008c5e6`（gitlab + GitHub 已推）。  
> 飞书 ou / user_id：**只用 node010 生产机器人隔离 id**，禁止混入 Mac 本机 overlay。

---

## 0. 已拍板（2026-11-06）

| 项 | 决定 |
|----|------|
| 目标 tip | 直接 Mac 现 tip `7be19213ff`（不先快进 preview 再切生产） |
| B2 / B3 | **同维保窗**；同窗必须激活 overlay `fleet_profiles`（**不**接受以 `patch_feishu_profile` 回落作主路径过渡） |
| 人卡主键 | **LDAP uid**；同窗改容器 `HERMES_PROFILE`（全名 → uid） |
| 183 owner-only | 默认信任 v2 已覆盖；只抽测飞书关键路径 |
| 三层挂载 | **后置**（本窗不做） |
| 旧 patch 文件 | **先不删除**；保留作回落材料 |

---

## 1. 目标与非目标

### 目标（本窗 B2+B3）

1. `/data/hermes/hermes-agent` checkout → `v2` @ `7be19213ff`。  
2. 安装 `/root/.hermes/overlay.yaml`（由 B1 草稿晋升；人卡键 = LDAP uid）。  
3. 15 个子容器 `HERMES_PROFILE` 与 compose 环境改为对应 ldap_uid（见 §7 映射表）。  
4. 子网关钉 `FEISHU_CONNECTION_MODE=send_only`（home `.env` 或 compose env）。  
5. 全量重启 Hub systemd + 全部 `hermes-*` 容器；按 §5 冒烟。

### 非目标（本窗明确不做）

- **不删除** `/root/.hermes/patch.yaml` 软链、`/root/.hermes/patch_feishu_profile.yaml`、`/data/hermes/patch*.yaml`、仓内 `owner/config/patch*.yaml`。稳定前一律保留。  
- **不做**三层挂载迁徙（`/home/<name>:/root` → profiles 叠 home）；compose 挂载仍用现网整挂 + `legacy_*` 路径。  
- **不** rebuild `hermes-profile` 镜像（代码/venv 为 bind mount；入口不兼容再议）。  
- **不**清 Hub 白名单两人（yangtb / wangtw 继续 `hub_only.feishu` 留 Hub）。  
- **不**把 Mac 本机飞书 ou 写入生产。  
- **不**开 C05b 以外的 C06 enforce 变更（现网 LDAP 段可随 overlay 带入，但不改认证策略为本切片主目标）。

---

## 2. 切片

| 切片 | 状态 | 内容 |
|------|------|------|
| **B0** 冻结 tag | **已做** | `owner-2026-11-06` @ `d72008c5e6`，双推 gitlab + GitHub |
| **B1** 配置准备 | **已做** | overlay 草稿刷新（含 xiejd:26042；主键 ldap_uid；ou 来自生产 live） |
| **B2+B3** 同窗切流 | **未做** | 代码切 v2 + 装 overlay + `HERMES_PROFILE` 改 uid + send_only + 全量重启 + 冒烟 |
| **B4** Ops 后置 | **未做** | 三层挂载、`/home` 全名→uid、是否清白名单、镜像 rebuild |

### B1 产物（node010，勿入库密钥稿）

| 文件 | 路径 |
|------|------|
| 含密草稿 | `/data/hermes/c05b-draft/overlay.yaml.draft`（mode 600） |
| 脱敏 | `…/overlay.yaml.draft.redacted` |
| 说明 | `…/NOTES.md` |
| 旧稿备份 | `…/overlay.yaml.draft.bak-20261106-125509` 等 |
| 预切流 live 副本 | `/data/hermes/c05b-draft/backups-pre-cutover/20261106-134142/`（见 §3） |

草稿要点：15 人卡；14 条 `user_profile_routes`（生产 ou→ldap_uid）；whitelist yangtb/wangtw；`default_profile=hermesxiyun`；补 **xiejd → 26042**。

---

## 3. 回退矩阵（备份 ↔ 怎么退）

> 原则：切流**前**保证下列副本存在；出问题按「停服务 → 还原文件 → checkout 回 tag → 再启」顺序。  
> **永不**在回退路径里 `rm` 掉仍可能需要的旧 patch。

### 3.1 已有 / 本轮已建备份

| 资产 | 现网路径 | 备份位置 | 出问题怎么退 |
|------|----------|----------|--------------|
| 代码 tip | `/data/hermes/hermes-agent` @ `d72008c5e6` | git tag **`owner-2026-11-06`**（远端已有）；副本记录 `backups-pre-cutover/…/repo/HEAD.txt` | `git fetch` → `git checkout owner-2026-11-06`（或 `d72008c5e6`）→ 重启 Hub+全部容器 |
| Hub systemd unit | `/etc/systemd/system/hermes-gateway.service` | `…/backups-pre-cutover/20261106-134142/systemd/hermes-gateway.service` | `cp` 回原路径 → `systemctl daemon-reload` → `restart hermes-gateway`（本窗若未改 unit，通常只需重启） |
| Hub `patch_feishu_profile.yaml` | `/root/.hermes/patch_feishu_profile.yaml`（与 `/data/hermes/patch_feishu_profile.yaml` 同内容现网） | `…/hub/root.hermes.patch_feishu_profile.yaml` + `…/hub/data.hermes.patch_feishu_profile.yaml` | 若被改写：从备份 `cp -a` 回 `/root/.hermes/`（及 `/data/hermes/` 若也改过）；**切流默认不删原文件** |
| Hub `patch.yaml` 软链 | `/root/.hermes/patch.yaml` → `hermes-agent/owner/config/patch.yaml` | 软链路径记在 `…/hub/root.hermes.patch.yaml.symlink-path.txt`；目标文件副本 `…/hub/repo.owner.config.patch.yaml` | 若软链断了：按记录重建软链；若目标被改：从备份还原 `owner/config/patch.yaml`（checkout 回 tag 通常一并还原） |
| 仓内 patch 回落稿 | `/data/hermes/hermes-agent/owner/config/patch.yaml`、`patch_feishu_profile.yaml` | 同上 `repo.owner.config.*`；亦随 git tag | checkout tag / 从备份 cp |
| Hub `.env` | `/root/.hermes/.env` | `…/hub/root.hermes.env`（含密，目录已收紧权限） | `cp -a` 回 `/root/.hermes/.env` → 重启 Hub |
| overlay 安装与否 | 现网 **ABSENT**（`/root/.hermes/overlay.yaml` 无） | `…/hub/root.hermes.overlay.yaml.ABSENT.txt` | 回退时：**删除或挪走**新装的 `/root/.hermes/overlay.yaml`（例如 `mv` 到 `c05b-draft/overlay.yaml.failed-$TS`），让 loader 回落旧 patch；**不要**删 patch |
| 各 profile compose | `/data/hermes/profiles/<fullname>/docker-compose.yml`（15 个；`HERMES_PROFILE=<fullname>`） | `…/profiles/<fullname>/docker-compose.yml` + `HERMES_PROFILE.txt` | 从备份还原 compose → `docker compose up -d`（或等价重启该容器） |
| profile 目录 `.env` | 仅 **lixin** 有 `/data/hermes/profiles/lixin/.env` | `…/profiles/lixin/dot-env` | 从备份还原 |
| 各用户 home `.env` | `/home/<fullname>/.hermes/.env`（15 人） | `…/homes/<fullname>/dot-env` | 从备份还原 → 重启对应容器 |
| B1 草稿世代 | `c05b-draft/overlay.yaml.draft*` | `overlay.yaml.draft.bak-20261106-125509` 等 | 只影响草稿；装正式 overlay 前再拷一份带时间戳 |

预切流总目录：

```text
/data/hermes/c05b-draft/backups-pre-cutover/20261106-134142/
  MANIFEST.txt
  hub/  profiles/  homes/  repo/  systemd/
```

### 3.2 维保窗开始前再确认 / 再备一份（checklist）

切流操作**启动前**再跑一遍（可新建 `backups-pre-cutover/$新TS/`，只复制不删）：

- [ ] `/root/.hermes/patch_feishu_profile.yaml`
- [ ] `/root/.hermes/patch.yaml` 软链目标与 `ls -la`
- [ ] `/root/.hermes/.env`
- [ ] 确认仍无 `/root/.hermes/overlay.yaml`（或若已有试验文件先挪走并备份）
- [ ] `/data/hermes/patch_feishu_profile.yaml`、`/data/hermes/patch.yaml` 软链
- [ ] 全部 `/data/hermes/profiles/*/docker-compose.yml`（及存在的 `.env`）
- [ ] 全部 `/home/<fullname>/.hermes/.env`
- [ ] `systemctl cat hermes-gateway.service`
- [ ] `git -C /data/hermes/hermes-agent rev-parse HEAD`（须仍为 `d72008c5e6` 或已记录的 tip）
- [ ] 记录当时 `docker ps` 与各容器 `HERMES_PROFILE`

### 3.3 一键回退口令（逻辑顺序；维保窗执行）

1. **停 / 重启准备**：`systemctl stop hermes-gateway`；按需 `docker stop` 各 `hermes-*`（或 compose down）。  
2. **卸 overlay**：若已安装 → `mv /root/.hermes/overlay.yaml /data/hermes/c05b-draft/overlay.yaml.failed-$(date +%Y%m%d-%H%M%S)`（**保留** patch）。  
3. **还原 compose / home `.env`**：从 `backups-pre-cutover/20261106-134142/`（或更新的那份）按 profile 拷回；确保 `HERMES_PROFILE` 回到**全名**。  
4. **代码**：`cd /data/hermes/hermes-agent && git checkout owner-2026-11-06`。  
5. **启**：`systemctl start hermes-gateway`；各 profile `docker compose up -d`。  
6. **验**：Hub 收消息；白名单留 Hub；抽一条非白名单转发；确认无 409。

---

## 4. B2+B3 同窗步骤（摘要；执行另开操作单）

1. 再跑 §3.2 checklist；需要则新建时间戳备份目录。  
2. 确认 LDAP 缺口处置（§6）：`gaor` / `wuyj`。  
3. `git fetch` + checkout `v2` / `7be19213ff`（处理 untracked bak；**不**强推改写远端）。  
4. host `venv` / `venv-docker` 依赖差量快速检查（import `owner.feishu.profile_routing` 等）；缺件再 pip。  
5. 晋升草稿 → `/root/.hermes/overlay.yaml`（`cp` + `chmod 600`）；**留下** patch 文件不动。  
6. 改 15 份 compose（及 home `.env`）：`HERMES_PROFILE=<ldap_uid>`；加 `FEISHU_CONNECTION_MODE=send_only`。  
7. 重启 Hub + 全部容器。  
8. §5 冒烟；失败走 §3.3。

> 硬约束：overlay 人卡键必须等于容器 `HERMES_PROFILE` / `container_profile_identity()`，否则 inbound **409 profile_mismatch**。

---

## 5. 冒烟检查清单

- [ ] Hub systemd active；飞书 WS 连上  
- [ ] Hub 能收 DM / 群消息  
- [ ] whitelist ou（yangtb / wangtw）→ **留 Hub**（不转发）  
- [ ] 非白名单已知 ou → HTTP 转发到对应 port；子侧有 `inject_inbound`  
- [ ] 子容器日志见 `send_only`（不抢 Hub WS）  
- [ ] 至少 1 个已改 uid 的人卡 E2E（发消息 → 正确 profile 回复）  
- [ ] `xiejd` / 26042 可达  
- [ ] default 未匹配 ou → `hermesxiyun`  
- [ ] 无大面积 409 / profile_mismatch  
- [ ] （抽测）飞书关键路径：会话续聊、卡片回调若常用则点一条  

---

## 6. 开放缺口

| 缺口 | 说明 | 建议 |
|------|------|------|
| **gaor** | live 路由有；LDAP `cn=people` 今日查无（legacy `gaorong`） | 切流前向目录管理员确认真实 uid；或临时用人卡键 `gaorong` 并同步 `HERMES_PROFILE`（偏离拍板，需明示） |
| **wuyj** | 同上（legacy `wuyongjin`） | 同上 |
| **xiaof vs xiaofan** | 目录 uid 为 `xiaofan`；若仍有 `xiaof` 别名需 C06 侧处理 | 飞书路由已用 `xiaofan`；记录即可 |
| **passwd /home** | Linux 用户与 `/home` 仍全名 | 本窗不改名；compose 继续挂 `/home/<fullname>`（草稿 `legacy_*`） |
| **preview worktree** | `/data/hermes/hermes-agent-v2-preview` 仍停在旧 tip | 可选快进作对照；**不是**生产切流前置 |

---

## 7. 人卡映射（ldap_uid ↔ 现网）

| ldap_uid | 现网 HERMES_PROFILE / 容器 | port | hub_only.feishu | LDAP |
|----------|---------------------------|------|-----------------|------|
| hermesxiyun | hermesxiyun | 26026 | 否 | n/a（默认服务号） |
| yangtb | yangtianbao | 26027 | 是 | 有 |
| liry | liruiyang | 26028 | 否 | 有 |
| sunqf | sunqifei | 26029 | 否 | 有 |
| xiaofan | xiaofan | 26030 | 否 | 有 |
| wuyj | wuyongjin | 26031 | 否 | **缺** |
| lizg | lizigao | 26032 | 否 | 有 |
| yanwh | yanwanhui | 26034 | 否 | 有 |
| ruify | ruifengyun | 26035 | 否 | 有 |
| gaor | gaorong | 26037 | 否 | **缺** |
| wangtw | wangtingwei | 26038 | 是 | 有 |
| zhangwg | zhangwenguo | 26039 | 否 | 有 |
| caocan | caocan | 26040 | 否 | 有 |
| lixin | lixin | 26041 | 否 | 有 |
| xiejd | xiejiedan | 26042 | 否 | 有 |

---

## 8. 现网快照（2026-11-06 只读复核）

| 项 | 现状 |
|----|------|
| Hub | systemd `hermes-gateway.service`；`HERMES_HOME=/root/.hermes`；飞书 WS |
| 代码 | `owner` @ `d72008c5e6`（tag `owner-2026-11-06`） |
| 子网关 | 15× Docker `hermes-<fullname>`；`hermes-profile:latest`；`network_mode: host` |
| 挂载 | 整挂 `/home/<name>:/root` + 代码/venv RO（**非**三层） |
| `HERMES_PROFILE` | 写在各 `docker-compose.yml`，值为**全名**；多数无 profile 目录 `.env`（真 `.env` 在 `/home/<name>/.hermes/`） |
| 路由主源 | `/root/.hermes/patch_feishu_profile.yaml` |
| `patch.yaml` | 软链 → 仓内 `owner/config/patch.yaml` |
| overlay | **不存在** |

---

## 9. 文档与清单同步

- 本文件：切流计划正文（本版）。  
- `README.md` / `owner改动清单-todo.md` / `v2实现顺序.md`：注明「C05b 计划已更新 + tip/拍板；**未**切流」。

---

## 10. 明确本轮（写计划时）不做

- 不停生产、不切 `owner`→`v2`、不写正式 `/root/.hermes/overlay.yaml`、不改 compose、不删任何 patch、不重启。  
- 已做：B0 tag、B1 草稿刷新、预切流 **copy-only** 备份、本文档。
