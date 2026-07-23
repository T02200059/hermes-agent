# 上游同步 × Kanban（K0 及后续观察）

> 产品路线仍是 **S′ → T**（见 `hermes-upstream-sync-prd.md`）。  
> Kanban **不替代** no_agent 自动 merge，只承接「硬闸之后」的人工闭环。

相关代码：

| 路径 | 作用 |
|------|------|
| `owner/sync/kanban_ticket.py` | K0 建卡逻辑 |
| `owner/config/upstream_sync.yaml` → `kanban:` | 开关与 tenant/workspace |
| `owner/scripts/upstream_sync.py` | MANUAL 路径 best-effort 建卡 |
| `owner/scripts/upstream_sync_cron.sh` | QQ 摘要附带 task id |
| `~/.hermes/kanban/workspaces/owner-upstream-sync/` | 共享材料目录 |

---

## 1. K0 做了什么（第一版）

### 1.1 行为

当同步决策为 **`MANUAL_REVIEW`**（分级硬红线 / high 指纹 / D6·D7 失败回滚）时：

1. 将 manual 报告 + meta JSON 写入 workspace  
2. 调用 `hermes kanban create … --json`  
3. **`--initial-status blocked`**（默认）→ **不自动派 worker**  
4. **idempotency-key** = `owner-upstream-{YYYY-MM-DD}-{upstream_sha12}`  
   - 同一天同一上游 HEAD 重复跑 → 复用已有卡，不刷屏  
5. 成功则把 `task_id` 写入：  
   - `SyncReport.kanban_task_id` / 摘要行 `kanban=t_…`  
   - `.sync_state.json`  
   - workspace `latest-task.json`  
6. 建卡失败 **不阻断** 同步主流程（只记 `kanban_error`）

### 1.2 默认配置

```yaml
kanban:
  enabled: true
  create_on: [MANUAL_REVIEW]
  tenant: owner-upstream-sync
  workspace: ~/.hermes/kanban/workspaces/owner-upstream-sync
  assignee: ""              # 空 = 不指派 profile
  initial_status: blocked
  priority: 20
  created_by: upstream-sync
```

### 1.3 人工关单流程

```bash
# 1) 看板上看卡
hermes kanban list --tenant owner-upstream-sync
hermes kanban list --tenant owner-upstream-sync --status blocked
hermes kanban show <task_id>

# 2) 在干净 owner 上完成 merge / 适配 / health check / tests

# 3) 清同步 pending
cd ~/.hermes/hermes-agent
.venv/bin/python owner/scripts/upstream_sync.py --resolve

# 4) 关看板
hermes kanban complete <task_id> --summary "merged + health ok: <一句话>"
```

**禁止**：无 D6 通过就 complete；自动 push；盲合不看改动清单。

### 1.4 与 Viking 的对应

| Viking | 上游同步 K0 |
|--------|-------------|
| cron 只 scan | cron 只分诊 + 安全 AUTO |
| 有量才 fan-out | **有 MANUAL 才建卡** |
| T4 人审不自动 | **blocked 卡 = 人闸**，无 worker |
| tenant + dir workspace | 同左 |

---

## 2. 明确不做的事（K0）

| 不做 | 原因 |
|------|------|
| 派 agent 自动解冲突 / 改胶水 | S′ 怕合坏；K0 只建工单 |
| SKIPPED（脏工作区 / pending）建卡 | 会噪音；先修工作区 |
| ERROR（错分支等）建卡 | 可后续按观察再开 |
| soft 信号建卡 | 观测即可 |
| 替代 no_agent 自动合 | 吞吐与确定性仍靠脚本 |

---

## 3. 观察清单（K0 跑 1–2 周后填写）

> 目的：决定要不要上 K1（只读分析 worker）/ K2（adapt + review-required）。  
> 建议每周扫一次 `hermes kanban list --tenant owner-upstream-sync`（可加 `--status blocked`）+ `owner/logs/upstream-sync/*.jsonl`。

### 3.1 量与节奏

| # | 观察项 | 如何量 | 记录位 | 决策含义 |
|---|--------|--------|--------|----------|
| O1 | 每周 MANUAL 天数 / 有上游更新的天数 | JSONL `decision=MANUAL_REVIEW` | | 是否常态化工单 |
| O2 | 每周新建卡数 vs 复用 idem 次数 | 看板 created_at / 同 key | | 刷屏？idem 是否够 |
| O3 | 卡平均存活时间（create → complete） | kanban show 时间线 | | 积压是否恶化 |
| O4 | 仍只有 QQ、人没关卡的比例 | blocked 长期未 complete | | 工单是否被当噪音 |

### 3.2 触发原因分布

| # | 观察项 | 如何量 | 记录位 | 决策含义 |
|---|--------|--------|--------|----------|
| O5 | 硬红线分布：D2 / D3 / D4 / D6 / D7 / 指纹 high | 报告维度表 / meta.json | | 哪类最常挡 |
| O6 | 「仅 D1/D5 soft」却进 MANUAL 的次数 | 应为 0（S′） | | 若非 0 → 回归 bug |
| O7 | 指纹 high 中「真·官方已修」占比 | 人工标注 | | 指纹词表是否过宽 |
| O8 | D6 失败里「真丢胶水」vs 误报 | 人工标注 | | anchors 是否要扩 |

### 3.3 安全与质量（S′ 主 KPI）

| # | 观察项 | 如何量 | 记录位 | 决策含义 |
|---|--------|--------|--------|----------|
| O9 | AUTO 后 24h 内发现清单缺失次数 | 应为 ≈0 | | 安全带是否够 |
| O10 | 手搓 merge 时是否仍对照附录 B | 自检 | | 模板是否够用 |
| O11 | 建卡失败次数（`kanban_error`） | JSONL / 报告 | | hermes PATH / gateway |
| O12 | 错分支 / 脏树 SKIP 频率 | JSONL SKIPPED | | 开发习惯干扰 |

### 3.4 人机体验

| # | 观察项 | 如何量 | 记录位 | 决策含义 |
|---|--------|--------|--------|----------|
| O13 | QQ 告警是否带上可点的 task id | 看推送 | | cron wrapper |
| O14 | 卡 body 是否够直接开工 | 主观 | | 要不要加 diff 摘录 |
| O15 | complete 时是否记得 `--resolve` | 若忘则次日 SKIP pending | | 要不要把 resolve 写进 complete 检查清单 / 脚本 |

### 3.5 升级门槛（写死，避免冲动上 agent）

**进入 K1（只读分析 worker）** 建议同时满足：

1. K0 已跑 ≥2 周，O9 ≈ 0  
2. O3 显示人工读报告成本高（卡存活久主要卡在「理解重构」而非「敲命令」）  
3. 已有可信 profile，且模板能 **禁止写 git**

**进入 K2（adapt + review-required）** 建议同时满足：

1. K1 结论有用且无乱改仓库事故  
2. O5 显示适配类（D2/D3/D4）占 MANUAL 大头  
3. 愿意用 worktree 隔离，且坚持 review-required 人闸  

**进入「序贯 merge / T」** 仍以 PRD §1.3 为准，与 Kanban 阶段独立。

### 3.6 周记模板（可复制）

```markdown
## 上游同步 × Kanban 周记 YYYY-Wxx

- MANUAL 天数 / 有更新天数：
- 新建卡 / idem 复用：
- 打开卡平均天数：
- 主因 Top3（D2/D3/D4/D6/指纹…）：
- AUTO 后清单事故：
- 建卡失败：
- 备注 / 是否考虑 K1：
```

---

## 4. 后续阶段草案（未实现，仅规划）

### K1 — 只读分析

- assignee = 代码向 profile  
- 模板：对照 anchors + 附录 B，输出「建议手搓步骤」到 workspace  
- **禁止** `git merge` / 改官方文件  
- complete 后仍由人 merge  

### K2 — 适配 + 人审

- T2 adapt → `block(review-required: …)`  
- 人 review → comment → unblock  
- T3 只跑 D6/D7  
- 仍禁止静默 push  

### K3 — 与吞吐 T 联动

- 卡上记录已合 range / 未合 range  
- 适配完成后触发 no_agent「从断点继续」  

---

## 5. 运维速查

```bash
# 列表
hermes kanban list --tenant owner-upstream-sync
hermes kanban list --tenant owner-upstream-sync --status blocked

# 最近材料
ls -lt ~/.hermes/kanban/workspaces/owner-upstream-sync/ | head

# 关同步门闩
.venv/bin/python owner/scripts/upstream_sync.py --resolve

# 临时关闭建卡
# 编辑 owner/config/upstream_sync.yaml → kanban.enabled: false
```

### 开关与调参

| 配置 | 含义 |
|------|------|
| `kanban.enabled` | 总开关 |
| `kanban.create_on` | 哪些 decision 建卡 |
| `kanban.assignee` | 非空则指派 profile（K0 建议仍 blocked） |
| `kanban.initial_status` | `blocked`（推荐）/ `running`（勿用于 K0） |

---

## 6. 变更记录

| 日期 | 内容 |
|------|------|
| 2026-07-16 | K0 落地：MANUAL → blocked 卡 + 观察清单本文档 |
