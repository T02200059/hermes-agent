# hermes-agent 上游自动同步使用指南

> 每日凌晨 3:00 自动 fetch 上游 `main` 分支，按 D1-D5 分级判定后，普通 commit 自动 merge + 健康检查 + 测试；大功能变更自动暂停并通知人工确认。

## 1. 快速开始

### 1.1 验证 dry-run

首次使用建议先跑一次 dry-run，确认分级逻辑正常：

```bash
cd ~/.hermes/hermes-agent
.venv/bin/python owner/scripts/upstream_sync.py --dry-run
```

dry-run 只做 fetch + 分级判定（D1-D5 + 指纹检测），**不会执行 merge**。退出码：

- `0` — 分级判定为 AUTO_MERGE（可安全自动合并）
- `1` — 分级判定为 MANUAL_REVIEW（需人工确认）
- `2` — 跳过/错误（工作区不干净 / pending review / 异常）

### 1.2 安装 cron 定时任务

```bash
crontab -e
```

添加以下行（每日凌晨 3:00 执行）：

```cron
0 3 * * * /Users/yangtb/.hermes/hermes-agent/owner/scripts/upstream_sync_cron.sh
```

cron wrapper 脚本会自动完成：

1. `cd` 到仓库根目录
2. 通过 `flock` 获取并发锁（防止上一轮未完成时重复执行）
3. 激活 venv（设置 PATH）
4. 执行 `upstream_sync.py` 并重定向日志到 `owner/logs/upstream-sync/<date>.log`

### 1.3 人工确认后恢复

当收到 MANUAL_REVIEW 通知后，处理完人工事项，执行：

```bash
cd ~/.hermes/hermes-agent
.venv/bin/python owner/scripts/upstream_sync.py --resolve
```

这会清除 pending review 状态，下一轮 cron 将正常执行。

---

## 2. 完整流水线说明

```
cron 触发 → 前置检查 → fetch upstream → 变更检测 → 分级判定(D1-D5)
                                                              │
                              ┌───────────────────────────────┤
                              ▼                               ▼
                        AUTO_MERGE                      MANUAL_REVIEW
                              │                               │
                    D4 试合并已暂存                    回滚 D4 + 通知
                              │                         + 标记 pending
                      D6 健康检查                            │
                              │                         等待 --resolve
                    D7 测试套件
                              │
                    完成 merge commit
                              │
                    通知 + 清理状态
```

### 2.1 七个维度

| 维度 | 名称 | 检查内容 | AUTO 条件 | MANUAL 触发 |
|------|------|---------|----------|------------|
| D1 | 改动规模 | 总改动文件数 | ≤ 20 | > 20 |
| D2 | 锚点文件触及 | 是否修改 anchors.yaml 中的文件 | 未触及 | 触及任意 1 个 |
| D3 | 重度侵入文件触及 | 是否修改附录 B.1 文件 | 未触及 | 触及任意 1 个 |
| D4 | 试合并冲突预检 | `git merge --no-commit --no-ff` | 无冲突 | 有冲突 |
| D5 | commit 关键词 | message 含危险关键词 | 无 | 含 refactor/rewrite/architecture/remove/deprecate/rename/split/restructure |
| D6 | 健康检查 | merge_health_check.py 7 项 | 退出码 0 | 退出码 1 |
| D7 | 测试 | pytest tests/owner/ | 全部通过 | 有失败 |

> D1-D5 是 merge 前预判，D6-D7 是 merge 后验证。D6/D7 失败会自动回滚。

### 2.2 前置检查

- **commit 数量**：上游积累超过 100 个 commit → 直接 MANUAL_REVIEW（不执行 D1-D5）
- **pending review**：存在未解决的人工确认 → 跳过本轮
- **工作区干净**：`git status --porcelain` 非空 → 跳过本轮

### 2.3 Bug 重复修复检测

系统维护 `owner/validation/fix_fingerprints.yaml` 指纹库，记录 owner 已提前修复的 bug。每个上游 commit 与每个指纹计算相似度：

```
综合相似度 = 文件交集率 × 0.6 + 关键词命中率 × 0.4
```

- `> 0.8` → 高置信度疑似重复 → MANUAL_REVIEW
- `0.5 - 0.8` → 中置信度疑似重复 → MANUAL_REVIEW
- `< 0.5` → 不影响分级，仅记录日志

---

## 3. 日志位置

所有日志位于 `owner/logs/upstream-sync/`：

| 文件 | 格式 | 用途 |
|------|------|------|
| `<date>.log` | 纯文本 | cron 运行记录（stdout/stderr 重定向） |
| `<date>-auto.md` | Markdown | 自动通过通知报告 |
| `<date>-manual-review.md` | Markdown | 人工确认详细报告 |
| `<date>-error.md` | Markdown | 跳过/错误报告 |
| `<date>.jsonl` | JSON Lines | 结构化日志（供周报统计） |
| `.sync_state.json` | JSON | 状态文件（pre-merge HEAD + pending review） |

### JSONL 每行格式

```json
{"timestamp": "2026-07-16T03:00:12Z", "decision": "AUTO_MERGE", "total_commits": 8, "pre_merge_head": "abc123", "upstream_head": "def456", "health_check_passed": true, "test_passed": true, "rolled_back": false, "fingerprint_matches": 0}
```

---

## 4. 退出码

| 退出码 | 含义 | 触发条件 |
|--------|------|---------|
| `0` | 成功 | AUTO_MERGE 完成 / 无新 commit / dry-run 完成 |
| `1` | 需人工确认 | MANUAL_REVIEW（D1-D5 红线 / D6-D7 失败 / 指纹高中置信度） |
| `2` | 跳过/错误 | 工作区不干净 / pending review / fetch 失败 / 异常 |

---

## 5. 手动操作

### 5.1 手动触发一次同步

```bash
cd ~/.hermes/hermes-agent
.venv/bin/python owner/scripts/upstream_sync.py
```

### 5.2 只看分级不合并

```bash
.venv/bin/python owner/scripts/upstream_sync.py --dry-run
```

### 5.3 标记人工确认完成

```bash
.venv/bin/python owner/scripts/upstream_sync.py --resolve
```

### 5.4 使用自定义配置

```bash
.venv/bin/python owner/scripts/upstream_sync.py --config /path/to/custom-config.yaml
```

### 5.5 查看状态

```bash
cat ~/.hermes/hermes-agent/owner/logs/upstream-sync/.sync_state.json
```

```json
{
  "pre_merge_head": "abc123def456...",
  "timestamp": "2026-07-16T03:00:12Z",
  "pending_review": false,
  "review_reason": null,
  "report_path": null
}
```

---

## 6. 配置文件

配置文件位于 `owner/config/upstream_sync.yaml`。关键配置项：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `repo.root` | `~/.hermes/hermes-agent` | 仓库根目录 |
| `cron.max_commits_threshold` | `100` | 超过则自动转 MANUAL_REVIEW |
| `classification.d1_max_files` | `20` | D1 文件数阈值 |
| `classification.d3_heavily_intruded_files` | 8 个文件 | D3 重度侵入文件列表 |
| `classification.d5_dangerous_keywords` | 8 个关键词 | D5 危险关键词列表 |
| `testing.timeout_seconds` | `600` | D7 测试超时（10 分钟） |
| `fingerprint.high_confidence_threshold` | `0.8` | 高置信度阈值 |
| `fingerprint.medium_confidence_threshold` | `0.5` | 中置信度阈值 |
| `notification.feishu_webhook` | `""` | 飞书 webhook（空=禁用） |

修改配置后无需重启，下一次 cron 运行自动生效。

---

## 7. 安全机制

### 7.1 不 push

自动 merge 仅在本地完成，**不执行 `git push`**。push 保持手动操作，确保安全。

### 7.2 回滚双重保障

任一阶段失败时：

1. 优先 `git merge --abort`（merge 暂存态可用）
2. 失败兜底 `git reset --hard <pre_merge_head>`（从状态文件读取）

### 7.3 并发锁

cron wrapper 使用 `flock -n` 非阻塞锁，防止上一轮未完成时重复执行：

```bash
flock -n /tmp/hermes-upstream-sync.lock
```

获取失败则输出"另一轮同步正在执行，跳过"并 `exit 0`。

### 7.4 幂等安全

状态文件追踪 pending review。有 pending 则跳过本轮，等待人工 `--resolve`。

### 7.5 工作区干净检查

执行前检查 `git status --porcelain`，不干净则跳过本轮并通知。

---

## 8. 常见问题

### Q1: cron 没有执行？

检查：

1. `crontab -l` 确认任务已安装
2. 查看 `owner/logs/upstream-sync/<date>.log` 是否有记录
3. 确认脚本有执行权限：`ls -l owner/scripts/upstream_sync_cron.sh`
4. macOS 需在「系统设置 → 隐私与安全 → 完全磁盘访问权限」中允许 cron 访问

### Q2: 收到 MANUAL_REVIEW 通知后怎么办？

1. 打开 `owner/logs/upstream-sync/<date>-manual-review.md` 查看详细报告
2. 根据报告中的「触发的分级红线」和「建议操作」处理
3. 手动完成 merge / 修复冲突 / 适配胶水代码
4. 处理完毕后执行 `.venv/bin/python owner/scripts/upstream_sync.py --resolve`
5. 下一轮 cron 将正常执行

### Q3: 自动 merge 失败了怎么办？

系统已自动回滚到 merge 前 HEAD，工作区是干净的。查看报告中的失败详情（D6 健康检查输出 / D7 测试输出），手动修复后 `--resolve` 恢复。

### Q4: 如何查看历史同步记录？

```bash
# 查看所有 cron 运行日志
ls -lt owner/logs/upstream-sync/*.log

# 查看 JSONL 结构化日志（便于统计）
cat owner/logs/upstream-sync/<date>.jsonl | python -m json.tool

# 查看最近一次人工确认报告
ls -lt owner/logs/upstream-sync/*-manual-review.md | head -1
```

### Q5: 如何调整分级阈值？

编辑 `owner/config/upstream_sync.yaml`：

- D1 文件数阈值：`classification.d1_max_files`
- 指纹相似度阈值：`fingerprint.high_confidence_threshold` / `medium_confidence_threshold`
- 测试超时：`testing.timeout_seconds`

### Q6: 如何添加新的 Bug 修复指纹？

编辑 `owner/validation/fix_fingerprints.yaml`，添加新条目：

```yaml
  - id: <唯一标识符>
    title: "<修复标题>"
    owner_commit: "<改动清单章节号>"
    fixed_files:
      - <文件路径>
    fix_keywords:
      - <关键词>
    fix_category: bugfix
    status: active
```

### Q7: 飞书通知怎么开启？

1. 获取飞书机器人 webhook URL
2. 编辑 `owner/config/upstream_sync.yaml`，填入 `notification.feishu_webhook`
3. 下一次运行自动启用 `FeishuNotifier`

> 注意：飞书通知当前为 P2 占位实现，`FeishuNotifier` 已注册但 HTTP 调用尚未实现。LogNotifier 始终生效。

### Q8: dry-run 模式会修改工作区吗？

不会。dry-run 会执行 D4 试合并（`git merge --no-commit`）以检测是否有冲突，但在返回前会立即 `git merge --abort` 回滚，确保工作区恢复到运行前的状态。dry-run 仅输出分级报告，不保留任何 merge 结果。

---

## 9. 文件结构

```
owner/
├── config/
│   └── upstream_sync.yaml          # 同步配置
├── scripts/
│   ├── upstream_sync.py            # 主编排器 + CLI
│   └── upstream_sync_cron.sh       # cron wrapper
├── sync/                           # 同步包
│   ├── __init__.py                 # 包初始化
│   ├── models.py                   # 数据结构
│   ├── config.py                   # 配置加载器
│   ├── gitops.py                   # Git 操作封装
│   ├── state.py                    # 状态管理
│   ├── classifier.py               # 变更分级 D1-D5
│   ├── fingerprint.py              # Bug 指纹检测
│   ├── merger.py                   # merge 执行 + 回滚
│   ├── health.py                   # D6 健康检查 + D7 测试
│   ├── notifier.py                 # 通知（LogNotifier + FeishuNotifier）
│   └── report.py                   # 报告生成
├── validation/
│   ├── merge_health_check.py       # 健康检查脚本（复用）
│   ├── anchors.yaml                # 锚点文件（复用）
│   ├── inventory.yaml              # 模块清单（复用）
│   └── fix_fingerprints.yaml       # Bug 修复指纹库
├── logs/
│   └── upstream-sync/              # 日志目录
│       ├── <date>.log
│       ├── <date>-auto.md
│       ├── <date>-manual-review.md
│       ├── <date>.jsonl
│       └── .sync_state.json
└── docs/
    └── upstream-sync-guide.md      # 本文档
```
