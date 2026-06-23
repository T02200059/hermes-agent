# Hermes Dev Flow — 需求变更端到端工作流架构设计

> 适用于 `hermes-agent` fork 仓库的定制功能开发，从"宝哥提出需求"到"代码入仓可推"的端到端 SOP。
> 最后更新：2026-06-22（v1 初稿，待第一次实测后迭代）

---

## 一、目的与痛点

### 1.1 背景

过去 4 周（2026-05 → 2026-06）宝哥与琳姐的合作模式逐渐稳定成一条**5 阶段工作流**：

1. 宝哥在飞书/CLI 提出 hermes 源码修改需求
2. **琳姐**做前期调研（读源码、查 skill/历史 session、出初步方案）
3. 调研结论交给 **kimi-cli / grok / zcode-cli** 做二次核实 + 详细方案设计
4. **琳姐**评审 CLI 产物，**有不确定的当场问宝哥**
5. 结合 `owner/docs/二次开发规范.md` + 方案设计，再交给 **kimi-cli / grok / zcode-cli** 做实际代码实现
6. **琳姐**对抗性 code review 质量，有问题交给 CLI 修复

这条工作流跑了约 20+ 次（如 v16 改动清单里的飞书 auto-card、approval cards、sender_name_cache、schema_patches 等），**质量明显好于"琳姐一人单干"或"直接派 CLI 一把梭"**。

### 1.2 当前模式的痛点

跑多了以后，5 个老毛病反复出现：

| # | 痛点 | 典型场景 | 后果 |
|---|------|---------|------|
| **P1** | **手动调度开销大** | 每次"调研→派活→等结果→再派活"全靠琳姐脑子记步骤 | 漏步骤、错顺序、跨 session 上下文断 |
| **P2** | **CLI 派活模板不统一** | kimi 的"打实际 patch"prompt 模板反复改改改，每轮都现写 | 同一段反偷懒招数（"不要再写报告"）经常漏 |
| **P3** | **人在回路点散乱** | 评审阶段的不确定点有时用 `clarify` 问、有时在主 session 直接问、有时直接派 CLI 接着干 | 决策点没留痕，复盘困难 |
| **P4** | **review-fix 循环无上限** | 碰到 CLI 改不对，反复派 fix + re-review 5-6 轮 | 模型互啄、token 浪费、宝哥失去耐心 |
| **P5** | **过程产物不存档** | 调研报告、设计文档、review findings 散落在 `/tmp/` 和 session 里 | 跨 session 复盘靠 `session_search` 反查，效率低 |

### 1.3 解决目标

把"5 阶段口头 SOP"**沉淀成可复用、有审计、有人在回路、有限循环**的 hermes 层工作流：

- **可复用**：5 阶段固定下来，每次新 feature 走同一套流程
- **有审计**：每阶段的产物落到固定路径，每张 kanban 卡留痕
- **人在回路**：明确"哪一阶段必须宝哥拍板、怎么拍板"
- **有限循环**：review-fix 最多 3 轮，超了自动 escalate

---

## 二、工作流架构

### 2.1 5 阶段总览

```
┌─────────────────────────────────────────────────────────────────────────┐
│  宝哥 (飞书/CLI)                                                        │
│  ↓ "加一个 X 功能" / "改 Y 行为" / "修 Z bug"                          │
└─────────────────────────────────────────────────────────────────────────┘
                                  ↓
┌─────────────────────────────────────────────────────────────────────────┐
│  阶段 0: 入口判定 (主 session, 琳姐直干)                                │
│  - 轻量任务 (1行 hotfix / 配置项) → 走快路径                             │
│  - 复杂任务 → 走完整 dev-flow                                            │
└─────────────────────────────────────────────────────────────────────────┘
                                  ↓
┌─────────────────────────────────────────────────────────────────────────┐
│  阶段 1: 调研 (主 session, 琳姐直干)                                    │
│  - 工具: read_file / search_files / session_search                      │
│  - 产出: /tmp/dev-flow/<feature>/01-research.md                         │
│  - 关键: 行号必须有本会话工具输出佐证 (反脑补规则)                       │
└─────────────────────────────────────────────────────────────────────────┘
                                  ↓
┌─────────────────────────────────────────────────────────────────────────┐
│  阶段 2: 方案设计 (kanban, 1 个 worker 派给选定的 CLI)                   │
│  - 宝哥选 CLI (kimi / grok / zcode 选一个)                              │
│  - 后续阶段 4/5 沿用同一 CLI (保证连贯性)                                │
│  - 产出: /tmp/dev-flow/<feature>/02-design.md                           │
│  - 机制: --idempotency-key dev-flow-design-v1                           │
└─────────────────────────────────────────────────────────────────────────┘
                                  ↓
┌─────────────────────────────────────────────────────────────────────────┐
│  阶段 3: 评审 + 人在回路 (主 session, 琳姐+宝哥多轮对话)                │
│  - 读 02-design.md, 跟宝哥多轮讨论                                       │
│  - 收敛后: 写 /tmp/dev-flow/<feature>/03-synth-design.md                 │
│  - 关键: 决策点在主 session 文字讨论, 不用 kanban_block                   │
│  - 理由: 多轮讨论 > 卡片锁定选项 (宝哥原话)                              │
└─────────────────────────────────────────────────────────────────────────┘
                                  ↓
┌─────────────────────────────────────────────────────────────────────────┐
│  阶段 4: 实施 (kanban, 同一 CLI worker)                                 │
│  - 投入: 03-synth-design.md + 二次开发规范.md + 01-research.md          │
│  - 产出: 实际 diff + pytest 输出                                        │
│  - 防御: prompt 头部加粗"打实际 patch, 不要再写报告"                     │
│  - 防御: "不要自动 commit" 单独成行                                     │
└─────────────────────────────────────────────────────────────────────────┘
                                  ↓
┌─────────────────────────────────────────────────────────────────────────┐
│  阶段 5: 对抗性 review + 修复循环 (≤3 轮, 琳姐 + CLI 交替)              │
│  - 5a: 琳姐用 adversarial-code-review skill 审查                        │
│  - 5b: 派同一 CLI 修 (按 P0→P1→P2 优先级)                              │
│  - 5c: 琳姐再 review                                                     │
│  - 3 轮上限: 超了自动 escalate 给宝哥决策                                │
│    (选项 A: 手动修 / B: 接受现状标 known-issue / C: 放弃 feature)        │
└─────────────────────────────────────────────────────────────────────────┘
                                  ↓
┌─────────────────────────────────────────────────────────────────────────┐
│  宝哥最终 review git diff → 手动 commit → 推送                          │
│  (commit 推送规则按 USER.md: 多 remote 时先问宝哥)                       │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.2 关键设计决策（与宝哥确认过）

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 阶段 1 调研是否走 kanban | **不走**，琳姐本 session 直干 | 调研跟主 session 上下文耦合深，套 kanban 反而割裂 |
| 阶段 2 是否多 CLI 并行 | **不并行**，选定 1 个 CLI 贯穿 | 3 个 CLI 投票/对比成本 3×，且后续阶段要保持连贯 |
| 阶段 5 修复循环上限 | **3 轮** | 模型互啄 5 轮通常无解，3 轮后强制宝哥决策 |
| 入口是否做飞书消息自动触发 | **不做**，琳姐主动调起 | 复杂任务需要"判断走不走 dev-flow"这一步，自动化误判代价高 |
| 阶段 3 人在回路是否用 kanban_block | **不用**，主 session 文字 | 多轮讨论比卡片选项更灵活（宝哥原话） |
| 人在回路决策点 | **阶段 0 选 CLI / 阶段 3 拍板 / 阶段 5 轮后决策** | 其他阶段琳姐可自行收敛 |

### 2.3 与现成 hermes 机制的对应关系

| 阶段 | 用的机制 | 关键 skill / 命令 |
|------|---------|------------------|
| 0 判定 | 主 session 思维 | — |
| 1 调研 | `delegate_task` + 直接工具 | `session_search`, `read_file`, `search_files` |
| 2 设计 | `hermes kanban create` | `--assignee kimi/grok/zcode profile` |
| 3 评审 | 主 session 多轮对话 + `clarify` | — |
| 4 实施 | `hermes kanban create` | `--skills kimi-cli` |
| 5 review | `hermes kanban create` | `--skills adversarial-code-review` |
| 5 fix 循环 | `hermes kanban create` × N | 同阶段 2 同一 assignee |

**没有引入新机制** —— 全部复用现有 `kanban` + `delegate_task` + 现有 skills。

---

## 三、hermes 层具体实现方案

### 3.1 不需要写新代码

**关键判断**：当前 5 阶段流程在 hermes 现成机制上**完全可跑**。需要做的是：

1. **沉淀 SOP**（写文档 + skill 模板）—— 本文档就是这一步
2. **创建专用 profile**（如缺 kimi/grok/zcode profile）
3. **写 skill 模板**（5 个阶段的 prompt 模板，落到 `~/.hermes/skills/devops/hermes-dev-flow/`）

**不需要**：
- 新增 hermes 核心代码
- 新增 plugin 或 hook
- 新增 CLI 子命令
- 改 gateway / dispatcher / kanban_db

### 3.2 profile 前置条件（必须先有）

按 `kanban-orchestrator` skill 的"Profile prerequisites"段，dispatcher 派活前**必须**确认 assignee profile 存在，否则任务静默卡在 `ready` 永不被领取。

**需要的 profile**（与宝哥选定的 CLI 绑定）：

| Profile 名 | 模型 | 创建命令（参考） |
|-----------|------|----------------|
| `kimi-coder` | kimi-for-coding | `hermes profile create kimi-coder --clone --clone-from coder` + 配 kimi API |
| `grok-coder` | grok-4 | `hermes profile create grok-coder --clone` + 配 grok API |
| `zcode-coder` | zcode (Z.AI/GLM) | `hermes profile create zcode-coder --clone` + 配 zcode API |

**验证命令**：
```bash
hermes profile list | grep -E "kimi-coder|grok-coder|zcode-coder"
```

**任一 profile 缺失 → 整个 dev-flow 不能跑**（因为阶段 2/4/5 都要派给同一 CLI）。

**Profile 配置陷阱**（来自 `kanban-orchestrator` §Pitfalls）：
- clone profile 时 `model.base_url` 会继承源 profile 的 URL → 必须验证与目标 provider 一致
- `providers:` 段不继承 → 子 profile 缺 provider 定义 → worker 启动报 `Unknown provider`
- 验证脚本：`bash ~/.hermes/skills/devops/kanban-orchestrator/scripts/check-profile-consistency.sh`

### 3.3 阶段 0: 入口判定（主 session 直干）

**判断逻辑**（琳姐内部决策，不入代码）：

```python
# 伪代码, 实际由琳姐判断
if "1 行 hotfix" or "纯配置/参数调整" or "文档/注释更新" or 宝哥明确说"快速搞一下":
    → 轻量路径: 直接派 CLI 改 → review → 完
else:
    → 走完整 dev-flow (阶段 1-5)
```

**不进 dev-flow 的信号**（入 skill 模板）：

| 任务类型 | 示例 | 处理 |
|---------|------|------|
| 单文件 < 10 行 | "改一下 X 的 log 格式" | 轻量路径 |
| 纯配置/参数 | "把 timeout 从 5s 改成 10s" | 轻量路径 |
| 文档/注释 | "补一下这个函数的 docstring" | 轻量路径 |
| 宝哥明示 | "快速搞一下" / "别走流程" | 轻量路径 |
| 其他 | 多数 feature/bug | dev-flow |

### 3.4 阶段 1: 调研（主 session 直干）

**工具调用**：
- `read_file` / `search_files` / `execute_code` / `terminal`
- `session_search`（查历史 session 有无类似 case）
- `viking_search`（如知识库有相关文档）

**产出**：`/tmp/dev-flow/<feature>/01-research.md`

**格式模板**：
```markdown
# 调研: <feature 简述>

## 背景
- 宝哥原始需求: <原文>
- 涉及模块: <agent/gateway/owner/...>

## 现状
- 关键文件: <路径>
- 关键函数/类: <带行号>
- 当前行为: <简述>

## 约束
- 二次开发规范: <哪些 P0-P3 条款相关>
- 上游兼容: <是否要避免改官方源码>
- 性能/安全: <任何红线>

## 不确定点
- [未验证] <X 字段是否真的存在>（按 SOUL.md 反脑补规则标注）

## 初步方向
- <2-3 个可能方案 + 各自优劣>
```

**不阻塞**：写完立刻进阶段 2。

### 3.5 阶段 2: 方案设计（kanban, 1 worker）

**关键命令**：
```bash
hermes kanban create "design: <feature> 方案" \
  --assignee kimi-coder \  # 或 grok-coder / zcode-coder
  --body "$(cat <<'EOF'
# 任务: <feature> 方案设计

## 输入
- 调研结论: /tmp/dev-flow/<feature>/01-research.md
- 二次开发规范: ~/.hermes/hermes-agent/owner/docs/二次开发规范.md

## 输出 (写到 /tmp/dev-flow/<feature>/02-design.md)
1. 总体方案 (架构图、模块划分)
2. 关键改动清单 (文件:行号 + before/after)
3. 边界场景 / 异常传播 / 并发安全
4. 备选方案对比 (至少 2 个, 含成本/风险)
5. 测试方案
6. commit 拆分建议

## 约束
- 用 --yolo --print --thinking 模式
- 输出纯 markdown 报告, **不要改任何代码**
- 引用行号必须用 read_file 验证
EOF
)" \
  --workspace ~/.hermes/kanban/workspaces/<feature>/ \
  --idempotency-key dev-flow-design-v1
```

**关键机制**：
- `--idempotency-key dev-flow-design-v1` 固定 → 同一 dev-flow 实例的所有卡共享 key
- `--workspace` 路径让产物集中
- `--assignee` 必须是已存在 profile
- `parents=[]`（本卡无前置依赖，是 root）

**Tmux 模式**（如 kimi worker 跑后台）：
```bash
tmux new-session -d -s kimi-<feature>-r1 \
  "bash -c 'cd ~/.hermes/hermes-agent && kimi --yolo --print --thinking < /tmp/kimi-prompt.md > /tmp/kimi-stdout.log 2>&1'"
# 不阻塞主 session, 宝哥问"看进度"时 tmux capture-pane
```

### 3.6 阶段 3: 评审 + 人在回路（主 session）

**为什么不用 kanban_block**：
- 阶段 3 决策点常需要**多轮对话**才能收敛（宝哥原话）
- kanban_block 把决策锁在飞书卡片选项里，反而不灵活
- 拍板后**手动写 03-synth-design.md** 作为阶段 4 的输入契约

**流程**：

```
循环 1 (主 session, 宝哥 + 琳姐多轮文字讨论):
  - 琳姐读 /tmp/dev-flow/<feature>/02-design.md
  - 跟宝哥多轮对话讨论 (用 clarify 或直接文字)
  - 讨论收敛 → 得出合成方向

循环 2 (如需要):
  - 派 CLI 做 R2 细化 (基于讨论结果)
  - 产出 /tmp/dev-flow/<feature>/03-design-refined.md

最后:
  - 琳姐手写 /tmp/dev-flow/<feature>/03-synth-design.md
  - 宝哥最后拍板 (主 session 文字确认, 不是 kanban_block)
  - 拍板后才进阶段 4
```

**03-synth-design.md 模板**：
```markdown
# 合成方案: <feature>

## 来源
- 调研: 01-research.md
- CLI 方案: 02-design.md (或 03-design-refined.md)

## 决策记录
- 备选 A vs B → 选 A, 因为 <理由>
- 边界场景 X → 处理方式: <方案>
- 性能/安全取舍: <记录>

## 最终方案
- 改动清单 (文件:行号 + before/after)
- commit 拆分
- 验证步骤

## 给实施阶段 (CLI) 的明确指令
1. 改 file_A.py: <具体动作>
2. 新建 owner/<feature>/__init__.py: <导出什么>
3. ...
```

### 3.7 阶段 4: 实施（kanban, 同 CLI worker）

**关键命令**：
```bash
hermes kanban create "implement: <feature>" \
  --assignee kimi-coder \  # 必须同阶段 2
  --body "$(cat <<'EOF'
# 任务: 实际打 patch, 不要再写报告

## 输入
- 合成方案: /tmp/dev-flow/<feature>/03-synth-design.md
- 二次开发规范: ~/.hermes/hermes-agent/owner/docs/二次开发规范.md
- 调研结论: /tmp/dev-flow/<feature>/01-research.md

## 任务清单 (每个对应一个 commit)
1. 改 file_A: 加 X 函数 (按方案 §2.1)
2. 改 file_B: 改 Y 配置 (按方案 §2.2)
3. 新增 owner/<feature>/__init__.py
4. 写 tests/test_<feature>.py (覆盖方案 §5)
5. 跑 pytest tests/test_<feature>.py 验证全过

## 验证步骤
V1. python -c "from <新模块> import <X>"  # import smoke
V2. pytest tests/test_<feature>.py -v
V3. git diff --stat
V4. git diff <每个改动的文件>

## 输出格式
- git diff (完整)
- pytest 输出 (真实 stdout)
- 执行摘要

## 注意事项
- **不要自动 commit**, 改完让我 review 后再 commit
- 每个改动对应一个 commit 信息建议
- [owner] 注释严格按规范格式 (see 二次开发规范 §2.2)
EOF
)" \
  --workspace ~/.hermes/kanban/workspaces/<feature>/ \
  --idempotency-key dev-flow-design-v1
```

**关键防御招数**（防 CLI 偷懒, 来自 `kimi-cli` skill §3c）：

1. prompt **头部加粗**"打实际 patch, 不要再写报告"（kimi 在分析型 prompt 训练后倾向输出报告, 不显式打断会继续写报告浪费 30+ 分钟）
2. 任务清单**每项显式**"新建/修改"动作
3. **"不要自动 commit"** 单独成行（防 `--yolo` 模式自己 commit）
4. 验证步骤 V1-V4 给出具体 bash 命令（让 CLI 知道产物长啥样）

**parents 链**：
```bash
# 阶段 4 卡的 parent 必须是阶段 2 的 design 卡
# 这样 design 没 done 时, 阶段 4 永远在 todo, dispatcher 不跑
hermes kanban create "implement: <feature>" \
  --assignee kimi-coder \
  --parent <阶段 2 的 task_id> \
  ...
```

### 3.8 阶段 5: 对抗性 review + 修复循环（≤3 轮）

**5a: 初始 review**（kanban, 琳姐 worker）

```bash
hermes kanban create "review-r1: <feature> 规范+对抗性" \
  --assignee lin-jie \  # 或主 profile
  --skills adversarial-code-review \
  --body "$(cat <<'EOF'
# 任务: 对抗性 code review

## 输入
- 实施 diff: /tmp/dev-flow/<feature>/04-diff.patch
- 合成方案: /tmp/dev-flow/<feature>/03-synth-design.md
- 二次开发规范: ~/.hermes/hermes-agent/owner/docs/二次开发规范.md

## 输出
- 报告到 /tmp/dev-flow/<feature>/05-review-r1.md
- 按 CR-01/02/03... 编号
- 分级 Critical/Warning/Info
- 每条带 file:line + fix 代码片段

## 审查清单 (强制)
- [ ] 二次开发规范 P0-P3 全部检查
- [ ] 调研结论行号表 vs 实际改动 diff 是否对得上
- [ ] 跨文件重复 (cross-file-feature-duplication)
- [ ] import 路径幻觉 (feishu-synthetic-message-pitfalls)
- [ ] 错误处理完整性
- [ ] 单元测试覆盖边界场景
EOF
)" \
  --workspace ~/.hermes/kanban/workspaces/<feature>/ \
  --idempotency-key dev-flow-design-v1
```

**5b: 修复循环**（最多 3 轮, 伪代码）

```python
# 由琳姐在主 session 执行, 不入代码
for round in 1..3:
    review_report = read(f"/tmp/dev-flow/<feature>/05-review-r{round}.md")
    
    if "✓ No issues found" in review_report or "clean" in review_report:
        log(f"阶段 5 第 {round} 轮 review 通过, dev-flow 结束")
        break
    
    # 派 CLI 修
    hermes_kanban_create(
        title=f"fix-r{round}: <feature>",
        assignee=<同阶段 2 的 CLI>,  # 保持连贯
        body=f"""
        读 /tmp/dev-flow/<feature>/05-review-r{round}.md
        按 P0→P1→P2 优先级修
        每条改完单独 commit
        """,
        workspace=f"~/.hermes/kanban/workspaces/<feature>/",
        idempotency_key="dev-flow-design-v1"
    )
    
    # 等 fix done
    wait_for_task_done(f"fix-r{round}")
    
    # 再 review
    hermes_kanban_create(
        title=f"re-review-r{round}: <feature>",
        assignee="lin-jie",
        skills=["adversarial-code-review"],
        body=f"""
        验证 fix-r{round} 的修复
        重点对比 05-review-r{round}.md 的 findings 是否都处理
        输出到 /tmp/dev-flow/<feature>/05-review-r{round+1}.md
        """,
        workspace=f"~/.hermes/kanban/workspaces/<feature>/",
        idempotency_key="dev-flow-design-v1"
    )

# 3 轮上限
if round == 3 and issues_still_exist:
    escalate_to_baoge(
        message=f"""
        阶段 5 跑了 3 轮还有未解决问题:
        - 最新 review: /tmp/dev-flow/<feature>/05-review-r3.md
        - 剩余 issues: <列表>
        
        请决策:
        A. 手动修剩下的 (琳姐/你)
        B. 接受当前状态, 标 known-issue
        C. 放弃整个 feature
        """
    )
```

**3 轮上限的语义**：
- 不是"3 轮后强行收工"
- 是"3 轮后**自动 escalate** 给宝哥决策, 避免模型互啄无限循环"
- 宝哥决策后再继续 (选项 A/B/C)

### 3.9 阶段 5 之后: 宝哥收尾

dev-flow 跑完后, **手动**进入收尾流程（不在 kanban 里）：

1. 宝哥 review git diff (`git diff <branch>..HEAD`)
2. 手动 commit（如阶段 4 没 commit）或调整 commit 信息
3. 按 `USER.md` 推送规则:
   - 单 remote → 直接 push
   - 多 remote → 先 `git remote -v`, 再问宝哥推哪些
4. 跑 `viking_add_resource` 把整套产物入库（如有需要）

---

## 四、SOP 落地: skill 模板

### 4.1 skill 目录结构

```
~/.hermes/skills/devops/hermes-dev-flow/   # 本机私有, 不入 owner 仓
├── SKILL.md                                # 触发条件 + 5 阶段总览 (本文件精简版)
├── references/
│   ├── stage-0-triage.md                   # 何时进/不进 dev-flow
│   ├── stage-1-research.md                 # 调研 SOP
│   ├── stage-2-design.md                   # design 派活模板
│   ├── stage-3-synthesize.md               # 主 session 评审流程
│   ├── stage-4-implement.md                # 实施派活模板
│   ├── stage-5-review-loop.md              # review+fix 循环
│   └── profile-setup.md                    # 怎么创建 kimi/grok/zcode profile
└── templates/
    ├── 01-research.md                      # 调研报告模板
    ├── 02-design-prompt.md                 # 喂给 CLI 的设计 prompt
    ├── 03-synth-design.md                  # 合成方案模板
    ├── 04-implement-prompt.md              # 喂给 CLI 的实施 prompt
    └── 05-review-prompt.md                 # 喂给 adversarial-code-review 的 prompt
```

### 4.2 skill 位置选择

**本机私有** vs **owner 仓** 两种放法：

| 位置 | 路径 | 适用 |
|------|------|------|
| **本机私有** | `~/.hermes/skills/devops/hermes-dev-flow/` | 当前阶段, 边用边迭代, 不污染 owner 仓 |
| **owner 仓** | `~/.hermes/hermes-agent/owner/docs/skills/hermes-dev-flow/` | 成熟后, 随 fork 同步到多机 |

**当前选择**：本机私有（按宝哥"先不着急实现"的要求, 等第一次实测后再决定入不入 owner 仓）。

### 4.3 触发条件（SKILL.md 元数据）

skill 的 frontmatter `description` 应包含触发关键词：

```yaml
description: |
  Hermes 源码修改端到端工作流: 调研 → 设计 → 评审 → 实施 → review → fix
  触发词: "加一个 X 功能" / "改 Y 行为" / "修 Z bug" / "走 dev-flow" / "按 dev-flow 跑"
  不适用: 1 行 hotfix / 纯配置 / 文档更新 (走轻量路径)
```

---

## 五、与现有 skill 的引用关系

| 本工作流引用 | 引用方式 | 原因 |
|-------------|---------|------|
| `kanban-orchestrator` | `--idempotency-key`, `--assignee profile` | ad-hoc 模式 + 固定 key 复用拓扑 |
| `subagent-driven-development` | 阶段 5 的 spec-compliance + quality 两阶段 review | 2 阶段 review 范式直接套用 |
| `adversarial-code-review` | 阶段 5 强制 `--skills adversarial-code-review` | 对抗性立场 + 必查项 |
| `kimi-cli` §3c | 阶段 4 prompt 模板的"打实际 patch"反偷懒招数 | 6 条防 kimi 偷懒模板 |
| `kimi-cli` §3d | 阶段 2 单轮研究 → 委托 kimi 实施 | 7-section research.md 模板参考 |
| `kimi-cli` §3b | 阶段 3 如需 kimi 二次细化 | 多轮分析型委托 |
| `kanban-orchestrator` §Profile prerequisites | 阶段 2/4/5 前置 | dispatcher 静默卡死防护 |
| `kanban-orchestrator` §Anti-temptation rule | 阶段 4 防御 | "嘴上派活手上自干"反模式 |
| `二次开发规范.md` | 阶段 2/3/4/5 必读 | 规范约束贯穿所有阶段 |

---

## 六、待办与决策

| # | 待办 | 优先级 | 负责人 |
|---|------|--------|--------|
| T1 | 确认 kimi/grok/zcode profile 现状, 缺的创建 | P0 | 琳姐 |
| T2 | 写 skill 模板（5 个 reference + 5 个 prompt 模板） | P0 | 琳姐 |
| T3 | 第一次实测：选一个真 feature 跑完整套 | P1 | 琳姐+宝哥 |
| T4 | 验证 3 轮上限 + 人在回路都按预期工作 | P1 | 琳姐+宝哥 |
| T5 | skill 成熟后, 决定是否迁移到 `owner/docs/skills/` | P2 | 宝哥决策 |
| T6 | 跟 `v16改动清单.md` 维护规则对齐（产物是否入改动清单） | P2 | 宝哥决策 |

---

## 七、变更日志

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.0.0 | 2026-06-22 | 初稿。5 阶段 SOP + hermes 层实现方案。无代码改动, 纯文档。 |

---

## 八、参考

- `owner/docs/二次开发规范.md` — 自定义代码规范（P0-P3 + 薄胶水/委托）
- `owner/docs/飞书多profile路由与子profile-gateway架构设计.md` — 架构设计文档格式参考
- `~/.hermes/skills/devops/kanban-orchestrator/SKILL.md` — ad-hoc kanban + idempotency-key + 派活纪律
- `~/.hermes/skills/software-development/subagent-driven-development/SKILL.md` — 2 阶段 review 框架
- `~/.hermes/skills/software-development/adversarial-code-review/SKILL.md` — 对抗性审查清单
- `~/.hermes/skills/autonomous-ai-agents/kimi-cli/SKILL.md` — CLI tmux 模式 + 反偷懒招数
- `~/.hermes/USER.md` — commit 推送规则（多 remote 时先问）
