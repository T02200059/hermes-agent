# C05b · node010 切流计划与验收（2026-11-06）

> 状态：**B2+B3 切流、B4 三层挂载及 `liry` / `wuyj` 停容器已完成**（2026-11-06）。正式 overlay 已启用，13 个 LDAP uid 短名 Linux 用户/容器已对齐；Viking 保持方案 B。
> 三层验收：`/home/<uid>` → `/root` + `/data/hermes/profiles/<uid>` → `/root/.hermes`（后叠挂）+ 代码/venv RO；`/data/hermes/compose/docker-compose.fleet-<uid>.yml` 软链已建；叠挂探针通过，`/health` **13/13 = 200**。切流/三层窗口内未无故重启 Hub。
> 切流时代码 tip：`7be19213ff`；后续 PM 兼容修复 `8cfb9d975b` 已进 gitlab。冻结 tag：`owner-2026-11-06` → `d72008c5e6`。
> 下文保留原计划、全名映射和回退矩阵。「本窗」「写计划时」及当时的非目标均为历史操作约束；当前状态以本段与 §2 执行结果为准。飞书 ou / user_id 仍禁止混入 Mac 本机 overlay。

---

## 0. 已拍板（2026-11-06）

| 项 | 决定 |
|----|------|
| 目标 tip | 直接 Mac 现 tip `7be19213ff`（不先快进 preview 再切生产） |
| B2 / B3 | **同维保窗**；同窗必须激活 overlay `fleet_profiles`（**不**接受以 `patch_feishu_profile` 回落作主路径过渡） |
| 人卡主键 | **LDAP uid**；同窗改容器 `HERMES_PROFILE`（全名 → uid） |
| Linux 用户 / 家目录 | **同窗一次做齐**：Linux 用户改为 ldap 短名（例 `yangtianbao`→`yangtb`）；`/home/<全名>/.hermes`（**含 state.db / skills 等尽量全量**）rsync 到 `/home/<uid>/`；compose 挂载改 `/home/<uid>:/root` |
| Viking / OpenViking | **走 B（已拍板）**：不改 OpenViking；`OPENVIKING_USER` + per-user API key **仍用全名**；MCP Bearer 随旧 key；**只迁 Linux/Hermes**。不 rename 服务端 `user/<全名>/`，不重签 key |
| liry / wuyj | **不迁**；overlay 已去掉；容器已在后续窗口停止，数据仍保留 |
| gaor LDAP | **已建**（2026-11-06：`uid=gaor` / displayName=高蓉 / uidNumber=1100） |
| 183 owner-only | 默认信任 v2 已覆盖；只抽测飞书关键路径 |
| 三层挂载 | **后续窗口已完成并验收**：O3 三层 compose、叠挂探针、compose 软链与 `/health` 13/13 = 200；原计划的后置项已关闭 |
| 旧 patch 文件 | **先不删除**；保留作回落材料 |

---

## 1. 目标与非目标

### 目标（本窗 B2+B3；已实施）

1. `/data/hermes/hermes-agent` checkout → `v2` @ `7be19213ff`。
2. 安装 `/root/.hermes/overlay.yaml`（由 B1 草稿晋升；人卡键 = LDAP uid）。
3. **Linux 短名 + 家目录搬家**（迁移名单，不含 liry/wuyj）：用户改为 ldap 短名；新建或改名 `/home/<uid>`；将 `/home/<全名>/.hermes` **尽量全量** rsync 到 `/home/<uid>/`（含 `state.db`、skills、`.env`、config 等）。
4. 现网子容器 `HERMES_PROFILE` 与 compose：改为 ldap_uid；挂载改为 `/home/<uid>:/root`（见 §7；草稿 **13** 人卡，不含 wuyj/liry）。
5. 子网关钉 `FEISHU_CONNECTION_MODE=send_only`（home `.env` 或 compose env）。
6. **Viking 保持 B**：各家 `.env` 的 `OPENVIKING_USER` / API key / MCP Bearer **仍为全名**（与短名 Linux 用户可暂时双名）。
7. 全量重启 Hub systemd + 迁移名单内 `hermes-*` 容器；按 §5 冒烟。

### 原计划非目标（后续变化见各项）

- **不删除** `/root/.hermes/patch.yaml` 软链、`/root/.hermes/patch_feishu_profile.yaml`、`/data/hermes/patch*.yaml`、仓内 `owner/config/patch*.yaml`。稳定前一律保留。
- 原切流窗**不做**三层挂载；后续窗口已完成 `profiles/<uid>` 叠 home 的三层迁徙与验收，不再是待办。
- **不改 OpenViking**（走 B）：不 rename `user/<全名>/`、不重签 per-user key、不把 `OPENVIKING_USER` 改成 ldap_uid。
- **不** rebuild `hermes-profile` 镜像（代码/venv 为 bind mount；入口不兼容再议）。
- **不**清 Hub 白名单两人（yangtb / wangtw 继续 `hub_only.feishu` 留 Hub）。
- **不**把 Mac 本机飞书 ou 写入生产。
- **不**开 C05b 以外的 C06 enforce 变更（现网 LDAP 段可随 overlay 带入，但不改认证策略为本切片主目标）。
- **不迁** liry / wuyj；原切流窗不 stop，后续窗口已停止其容器，数据未删。

---

## 2. 切片

| 切片 | 状态 | 内容 |
|------|------|------|
| **B0** 冻结 tag | **已做** | `owner-2026-11-06` @ `d72008c5e6`，双推 gitlab + GitHub |
| **B1** 配置准备 | **已做** | overlay 草稿刷新（含 xiejd:26042；主键 ldap_uid；ou 来自生产 live） |
| **B2+B3** 同窗切流 | **已完成** | 代码切 v2 + 正式 overlay + Linux 短名/家目录迁移 + `HERMES_PROFILE`/compose 改 uid + send_only + **Viking 保持全名** + 13 容器运行 |
| **B4** Ops 后置 | **核心已完成** | 三层挂载、13/13 `/health`、liry/wuyj stop 已完成；清白名单、镜像 rebuild、OV rename 仍按独立需求处理 |

### 2.1 执行结果与验收

- [x] 正式 overlay：路由主源已切到 `fleet_profiles` / `user_routing`，旧 patch 文件保留作回退材料。
- [x] 13 个 LDAP uid 短名 Linux 用户、`HERMES_PROFILE` 与容器已对齐；`liry` / `wuyj` 不迁且已停。
- [x] O3 三层挂载：home → `/root`，随后 `profiles/<uid>` 叠到 `/root/.hermes`，代码/venv 只读；home 下无迁移数据泄漏。
- [x] `/data/hermes/compose/docker-compose.fleet-<uid>.yml` 已建到各 profile compose 的软链，与 `xy-user-onboarding` / `fleet_add` O3 对齐。
- [x] profiles 写入探针容器内可见；13/13 `/health` 返回 200；切流/三层窗口内未无故重启 Hub。
- [x] Viking 方案 B：`OPENVIKING_*` 继续按原全名租户，不在本次迁移中 rename。
- [x] 后续 PM tar 兼容修复 `8cfb9d975b` 已提交并走 gitlab 对齐；旧全名容器/家目录暂时保留，稳定后另单清理。

### 2.2 B1 产物（node010，勿入库密钥稿）

| 文件 | 路径 |
|------|------|
| 含密草稿 | `/data/hermes/c05b-draft/overlay.yaml.draft`（mode 600） |
| 脱敏 | `…/overlay.yaml.draft.redacted` |
| 说明 | `…/NOTES.md` |
| 旧稿备份 | `…/overlay.yaml.draft.bak-20261106-125509` 等 |
| 预切流 live 副本 | `/data/hermes/c05b-draft/backups-pre-cutover/20261106-134142/`（见 §3） |

草稿要点：现 **13** 人卡（已去掉 **wuyj**、**liry**/离职不迁；保留 **gaor**）；`user_profile_routes` 对应生产 ou→ldap_uid；whitelist yangtb/wangtw；`default_profile=hermesxiyun`；补 **xiejd → 26042**。**gaor** LDAP 已建（见 §6）。

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
| 各用户整份 `.hermes`（state.db/skills 等） | `/home/<fullname>/.hermes/` | **切流前再备**：`…/homes/<fullname>/dot-hermes.tgz` 或 `rsync` 树（§3.2）；Linux 改名后主路径为 `/home/<uid>/.hermes/` | 回退：停容器 → 挂载改回 `/home/<fullname>` → 若已 rsync 可从 tgz/`/home/<uid>` 拷回全名家目录 → 还原 compose/`HERMES_PROFILE` 全名 |
| Linux passwd / 家目录名 | `/home/<fullname>` + 全名用户 | 切流前记录 `getent passwd` / `ls /home`；改名用 `usermod`/`useradd`+rsync（§4） | 回退：`usermod -l/-d` 改回全名或恢复挂载指回旧 `/home/<fullname>`（旧目录建议改名前 **rename 保留** 而非立刻 `rm`） |
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
- [ ] 迁移名单每人整份 `/home/<fullname>/.hermes/` 树备份（tgz 或 rsync 到 `backups-pre-cutover/$TS/homes/<fullname>/dot-hermes/`）
- [ ] `getent passwd` / `ls /home` 快照（全名→uid 对照）
- [ ] `systemctl cat hermes-gateway.service`
- [ ] `git -C /data/hermes/hermes-agent rev-parse HEAD`（须仍为 `d72008c5e6` 或已记录的 tip）
- [ ] 记录当时 `docker ps` 与各容器 `HERMES_PROFILE`

### 3.3 一键回退口令（逻辑顺序；维保窗执行）

1. **停 / 重启准备**：`systemctl stop hermes-gateway`；按需 `docker stop` 各 `hermes-*`（或 compose down）。
2. **卸 overlay**：若已安装 → `mv /root/.hermes/overlay.yaml /data/hermes/c05b-draft/overlay.yaml.failed-$(date +%Y%m%d-%H%M%S)`（**保留** patch）。
3. **还原 compose / home**：从 `backups-pre-cutover/…` 按 profile 拷回 compose 与 `.env`；挂载改回 `/home/<fullname>:/root`；`HERMES_PROFILE` 回到**全名**。若已短名化：把容器指回旧全名家目录（或从 tgz 恢复 `.hermes`）；**不要**动 OpenViking volume（B 方案下本就未改）。
4. **Linux 用户（若已改名）**：优先让服务先跑在旧 `/home/<fullname>`；短名用户可留着不清，避免误删。
5. **代码**：`cd /data/hermes/hermes-agent && git checkout owner-2026-11-06`。
6. **启**：`systemctl start hermes-gateway`；各 profile `docker compose up -d`。
7. **验**：Hub 收消息；白名单留 Hub；抽一条非白名单转发；确认无 409；抽测 viking 召回仍在全名租户。

---

## 4. B2+B3 同窗步骤（摘要；执行另开操作单）

1. 再跑 §3.2 checklist；需要则新建时间戳备份目录（含每人 `.hermes` 树）。
2. 复核 §6：`gaor` LDAP 已建；`wuyj`/`liry` 已从草稿移除（live patch 旧路由可留到后停容器；overlay 晋升以草稿为准）。
3. `git fetch` + checkout `v2` / `7be19213ff`（处理 untracked bak；**不**强推改写远端）。
4. host `venv` / `venv-docker` 依赖差量快速检查（import `owner.feishu.profile_routing` 等）；缺件再 pip。
5. 晋升草稿 → `/root/.hermes/overlay.yaml`（`cp` + `chmod 600`）；**留下** patch 文件不动。
6. **Linux 短名 + 搬家**（迁移名单）：对每人（例 `yangtianbao`→`yangtb`）——停对应容器 → 建短名用户（`uidNumber` 对齐 LDAP，能 `usermod -l/-d` 则改名，否则 `useradd` + rsync）→ `rsync -aHAX /home/<全名>/.hermes/ /home/<uid>/.hermes/`（**尽量全量**，含 state.db/skills）→ **旧 `/home/<全名>` 先保留不删**。
7. 改迁移名单 compose（及迁后 home `.env`）：`HERMES_PROFILE=<ldap_uid>`；挂载 `/home/<uid>:/root`；加 `FEISHU_CONNECTION_MODE=send_only`。
8. **Viking 校验（B）**：diff 各 `.env`，确认 `OPENVIKING_USER` / API key / MCP Bearer **仍为全名**（除已记录的 yangtianbao MCP 修复外不改 key）。
9. 重启 Hub + 迁移名单容器（liry/wuyj 本窗可不动）。
10. §5 冒烟；失败走 §3.3。

> 硬约束：overlay 人卡键必须等于容器 `HERMES_PROFILE` / `container_profile_identity()`，否则 inbound **409 profile_mismatch**。

---

## 5. 冒烟检查清单

- [x] Hub systemd active；飞书 WS 连上（切流/三层窗口内未无故重启 Hub）
- [ ] Hub 能收 DM / 群消息
- [ ] whitelist ou（yangtb / wangtw）→ **留 Hub**（不转发）
- [ ] 非白名单已知 ou → HTTP 转发到对应 port；子侧有 `inject_inbound`
- [x] 子网关使用 `send_only`（不抢 Hub WS）
- [ ] 至少 1 个已改 uid 的人卡 E2E（发消息 → 正确 profile 回复）
- [x] `xiejd` / 26042 可达（13/13 `/health` = 200 验收覆盖）
- [ ] default 未匹配 ou → `hermesxiyun`
- [ ] 无大面积 409 / profile_mismatch
- [x] 短名 home 与 `profiles/<uid>` 三层挂载探针通过；旧全名 `/home` 保留作回退。真人飞书路由与 Viking 召回抽测不因本清单自动判过
- [ ] Viking B：召回仍命中切流前全名租户记忆；`OPENVIKING_USER` 仍为全名
- [ ] （抽测）飞书关键路径：会话续聊、卡片回调若常用则点一条

---

## 6. 原开放缺口与后续项

| 缺口 | 说明 | 建议 |
|------|------|------|
| **gaor** | **已关闭（2026-11-06）**：LDAP `10.10.100.150` 已建 `cn=gaor,cn=people,dc=westhpc,dc=com`（`uid=gaor`，`displayName=高蓉`，`uidNumber=1100`，bind OK）；草稿人卡 **保留**；legacy 仍为 `gaorong` | 切流主键 `gaor`；同窗 Linux/`/home/gaor` + 全量搬 `/home/gaorong/.hermes`；初密见 NOTES（文档**不**写密码） |
| **liry** | **不迁**（用户 2026-11-06：李瑞阳离职）；OV `user/liruiyang` 数据保留；容器已停止；overlay 已去掉 |
| **wuyj** | **已关闭（草稿侧）**：用户确认不需要；已从 overlay 草稿 `fleet_profiles` / `user_profile_routes` 移除（legacy `wuyongjin`） | 旧 `patch_feishu_profile` 保留作回退材料；**不**再为人卡建 LDAP |
| **xiaof vs xiaofan** | 目录 uid 为 `xiaofan`；若仍有 `xiaof` 别名需 C06 侧处理 | 飞书路由已用 `xiaofan`；记录即可 |
| **passwd /home** | **拍板：同窗改短名**（原「后置」作废） | 迁移名单：`usermod`/`useradd` → `/home/<uid>`；rsync 全量 `.hermes`；compose 挂 `/home/<uid>`；旧全名家目录先留着 |
| **preview worktree** | `/data/hermes/hermes-agent-v2-preview` 仍停在旧 tip | 可选快进作对照；**不是**生产切流前置 |

---

## 7. 人卡映射（ldap_uid ↔ 现网）

> 下表含 **迁移人卡 13**（`fleet_profiles`，已无 `wuyj`/`liry`）+ 离职注明行。`user_profile_routes` 为 **12**（不含 default `hermesxiyun`）。13 个现网 `HERMES_PROFILE` / 容器 / Linux 用户均已用短名；「原全名」列保留用于回退映射。`liry` / `wuyj` 容器已停。

| ldap_uid（现网名） | 原全名（回退映射） | port | hub_only.feishu | LDAP |
|-----------------|----------------------|------|-----------------|------|
| hermesxiyun | hermesxiyun | 26026 | 否 | n/a（默认服务号） |
| yangtb | yangtianbao | 26027 | 是 | 有 |
| liry | liruiyang | 26028 | 否 | 有；**不迁/已停容器**（离职；overlay 已去掉；数据保留） |
| sunqf | sunqifei | 26029 | 否 | 有 |
| xiaofan | xiaofan | 26030 | 否 | 有 |
| lizg | lizigao | 26032 | 否 | 有 |
| yanwh | yanwanhui | 26034 | 否 | 有 |
| ruify | ruifengyun | 26035 | 否 | 有 |
| gaor | gaorong | 26037 | 否 | **有**（2026-11-06 已建） |
| wangtw | wangtingwei | 26038 | 是 | 有 |
| zhangwg | zhangwenguo | 26039 | 否 | 有 |
| caocan | caocan | 26040 | 否 | 有 |
| lixin | lixin | 26041 | 否 | 有 |
| xiejd | xiejiedan | 26042 | 否 | 有 |

---

## 8. 切流前快照（2026-11-06 只读复核；历史记录）

| 项 | 现状 |
|----|------|
| Hub | systemd `hermes-gateway.service`；`HERMES_HOME=/root/.hermes`；飞书 WS |
| 代码 | `owner` @ `d72008c5e6`（tag `owner-2026-11-06`） |
| 子网关 | 15× Docker `hermes-<fullname>`；`hermes-profile:latest`；`network_mode: host` |
| 挂载 | 现网整挂 `/home/<name>:/root` + 代码/venv RO（**非**三层）；**切流后目标** `/home/<uid>:/root` |
| `HERMES_PROFILE` | 现网写在各 `docker-compose.yml`，值为**全名**；切流后改 ldap_uid；真 `.env` 随家目录迁到 `/home/<uid>/.hermes/` |
| Viking | 现网 `OPENVIKING_USER=<全名>`；**切流后仍全名（B）** |
| 路由主源 | `/root/.hermes/patch_feishu_profile.yaml` |
| `patch.yaml` | 软链 → 仓内 `owner/config/patch.yaml` |
| overlay | **不存在** |

---

## 9. 文档与清单同步

- 本文件：切流计划正文（本版）。
- `README.md` / `owner改动清单-todo.md` / `v2实现顺序.md`：均已同步为 C05b 切流、三层挂载与健康验收完成。

---

## 10. 写计划时的约束（历史，非待办）

- 当时仅做 B0 tag、B1 草稿、预切流 copy-only 备份、LDAP 建 `gaor` 与 Viking 隔离核对，不改生产、不写正式 overlay、不重启。
- 后续 B2+B3 与三层挂载均另行执行并完成；`liry` / `wuyj` 容器已停，旧 patch 与历史回退副本未随此清理删除。

## 11. Viking / OpenViking 隔离核对（2026-11-06 只读；**未**迁数据）

> 结论先说：**记忆隔离键是共享 OpenViking 上的租户 `default/<OPENVIKING_USER>`（主要靠每人一把 per-user API key），不是 `HERMES_PROFILE`，也不是 Linux 家目录本身。**
> 同窗只把 `HERMES_PROFILE` 改成 ldap_uid、**保持**各家 `.env` 里 `OPENVIKING_*` 与 MCP Bearer **仍为全名租户** → 隔离不断、不串号。
> 若误把 `OPENVIKING_USER` / per-user API key 改成 `yangtb`/`gaor` 且不做服务端 rename → **旧记忆留在全名目录，新 uid 租户是空的**（丢映射，不是串号）。
> overlay 草稿 **不含** viking 字段。
> **拍板（2026-11-06）：走 B** — 不改 OV；`OPENVIKING_*` 仍全名；只迁 Linux/Hermes（短名家目录 + 全量 `.hermes`）。不采用「改 OV 用户名 / 迁 viking 数据」。

### 11.1 现在怎么连、怎么隔

| 层 | 现状（node010） |
|----|-----------------|
| 共享服务 | Docker `openviking`（`ghcr.linkos.org/volcengine/openviking:v0.4.7`）；host `0.0.0.0:1933`（API）+ `:8020`（console）；数据卷 `openviking_data` → `/app/.openviking` |
| 子容器入口 | 各 `hermes-<全名>` env：`OPENVIKING_ENDPOINT=http://host.docker.internal:1933`；整挂 `/home/<全名>:/root` 因而读到该用户 `.hermes/.env` / `config.yaml` |
| 身份 env | 几乎人人：`OPENVIKING_ACCOUNT=default` + `OPENVIKING_USER=<全名>` + **每人不同的** `OPENVIKING_API_KEY`（key 内嵌 id `default/<全名>`，指纹互异） |
| MCP | `config.yaml` → `mcp_servers.openviking.url=http://host.docker.internal:1933/mcp`；Authorization Bearer **通常与** 该用户 `OPENVIKING_API_KEY` **相同**（见异常） |
| 插件 | `plugins/memory/openviking`：有 API key 时默认 **不**带 `X-OpenViking-Account/User`（租户由 key 断言）；trusted 缺身份时才补头。`OPENVIKING_USER` 另作 ChatLog display/peer slug 兜底；**assistant 标签**走 `get_active_profile_name()`（≈ `HERMES_PROFILE`） |
| 服务端落盘 | `/…/data/viking/default/user/<OPENVIKING_USER>/`（memories/sessions/…）。现有目录全是**全名**：`yangtianbao`、`gaorong`、…；**无** `yangtb` / `gaor` |
| 家目录本地 | 部分用户有 `/home/<名>/.hermes/openviking/{pending_sessions,runs}` —— 仅客户端缓存，随 home 走，不是主库 |
| Hub overlay/patch | 现网路由 **不**决定 viking 租户；`c05b-draft/overlay.yaml.draft` **无** viking 键 |

服务端用户目录体量（只读，示意）：`sunqifei` ~63M、`gaorong` ~4.5M、`yangtianbao` ~2.3M、…；另有大户 `default` ~307M（共享/历史，**不是**某人 ldap_uid）。`wuyongjin` 服务端目录仍在（~56K），虽 overlay 草稿已去掉 wuyj 路由。

### 11.2 与 `HERMES_PROFILE` / LDAP uid 的关系

| 改什么 | 对 viking 隔离的影响 |
|--------|----------------------|
| 只改 `HERMES_PROFILE` 全名→ldap_uid（本窗计划） | **主库不断**：仍用原 `OPENVIKING_API_KEY` / `OPENVIKING_USER=<全名>` → 仍进 `user/<全名>/`。副作用：写入 Viking 的 **assistant peer 标签**可能变成 `yangtb`/`gaor`（读库仍是原租户；召回标签风格变化，不是串号） |
| 顺带把 `OPENVIKING_USER` 改成 ldap_uid，但 **不**换 key、**不**迁目录 | 有 API key 时租户仍由 key 决定（多数路径仍进全名）；display slug 变 uid。避免半吊子 |
| 换成 `default/<ldap_uid>` 的新 API key（或 mint 新用户）且服务端无 `user/<uid>/` | **丢映射**：旧记忆留在 `user/<全名>/`，新租户空。**不会**自动读到别人的库（不串号），但本人像失忆 |
| 服务端 `mv user/yangtianbao → user/yangtb`（及 gaorong→gaor 等）+ 同步换 key/`OPENVIKING_USER` + MCP Bearer | 才能「租户名=ldap_uid」；**本窗默认不做**，若做需单独操作单与备份 |
| 三层挂载 / 改 `/home` 名（后置） | 只要 `.env` 里 `OPENVIKING_*` 与 MCP Bearer 跟着同一份 profile 配置走，主库仍在共享 OV；勿在挂载迁移时漏拷 `.env` |

**本机 Mac 对照（勿混）**：本机 `.env` 已是 `OPENVIKING_USER=yangtb`，属于**另一套**飞书机器人/环境；node010 生产仍是 `yangtianbao` 等全名租户。刷草稿/对线时不要用本机 viking 用户去改生产。

### 11.3 异常与切流注意

1. **`yangtianbao` MCP Bearer ≠ 其 `OPENVIKING_API_KEY`**：MCP auth 指纹与 **root_api_key** 一致，env 侧仍是 `default/yangtianbao` 用户 key。记忆插件主路径按 env key 隔离；**MCP 工具路径可能抬到 root 视野**。切流前建议把该用户 `config.yaml` MCP Authorization 改回与 `.env` 同 key（改前备份；**勿**把 root key 扩散到其他人）。
2. **`lixin`**：`OPENVIKING_*` 已 `#DISABLED_`，且 `HERMES_PROFILE`/`DISABLED_USER` 曾指向 `hermesxiyun`（配置脏）。本窗改 uid 时单独核对，避免误启用或误共用 xiyun 租户。
3. **`wuyongjin`**：容器与 OV `user/wuyongjin` 仍在；overlay 已无路由。不删数据；确认不再写入即可。
4. **密钥**：各家 per-user key 已在 home `.env` 备份目录中；回退用既有 `…/homes/<fullname>/dot-env`。**不要**为「配合 ldap_uid」批量重签 key，除非做了 §11.2 的目录 rename。
5. **冒烟**：切流后抽测至少 `yangtianbao→yangtb`、`gaorong→gaor`：同一人召回仍命中切流前记忆；互不看见对方 memories。

### 11.4 本窗决定（已拍板 = B）

- **已拍板走 B：不迁 viking、不 rename 服务端 `user/<全名>`、不改 `OPENVIKING_USER` / per-user API key /（除 yangtianbao MCP 修复外）MCP Bearer。**
- 与 Linux 短名可长期双名：系统用户/`HERMES_PROFILE`=`yangtb`，Viking 仍 `yangtianbao`。
- B2+B3 checklist：**diff** 各迁后 `.env`，确认 `OPENVIKING_USER` 与 key id 仍为全名（rsync 后应原样带过来，勿「顺手」改成 uid）。
- 若日后坚持租户名=ldap_uid：另开「OV 租户 rename」单（停写 → 备份 volume → `mv` 目录 → 重签/改 key + env + MCP → 冒烟）；**不**塞进本次同窗。

---

### 11.5 离职不迁：`liry` / `liruiyang`（李瑞阳）

- 用户 2026-11-06：`liry`（李瑞阳）**也离职了，不用迁移**；原切流窗未 stop，后续窗口容器已停止。
- Viking：服务端仍有 `…/user/liruiyang/`（~1.7M）；保持不动即可，**不要** rename 到 ldap_uid，**不要**为切流改其 `OPENVIKING_*`。
- Overlay 草稿：**已去掉** `fleet_profiles.liry` 与 ou→`liry`（backup `c05b-draft/backups-pre-liry-remove-20261106-140438`）；live patch 旧路由可留到后停容器时一并收。
- 与 `wuyj` 类似：数据保留、不迁 uid；二者均已从 overlay 去掉，容器均已停。
