# owner → owner-v16 迁移规范

> 启动日期：2026-06-12
> 状态：进行中
> 最后更新：2026-06-13（加入实战经验）

---

## 一、迁移目标

将 `owner` 分支中积累的所有定制改动，按照新规范（`owner/docs/二次开发规范.md`）重新迁移到 `owner-v16` 分支。

**不是**简单的 cherry-pick 或 merge，而是**按新规范重新审视每一项改动**，决定其在 owner-v16 中的归宿。

---

## 二、参考文档体系（按优先级排序）

迁移过程中，以下文档构成决策依据，**按顺序优先参考**：

| 优先级 | 文档 | 作用 |
|--------|------|------|
| **P0** | `owner/docs/二次开发规范.md` | 最终开发规范，所有迁移决策以它为准 |
| **P1** | owner 分支当前代码形态 | 实际运行的代码，是第一参考实现 |
| **P2** | `owner/docs/原有改动清单.md` | 功能点需求清单，确保不遗漏 |
| **P3** | `owner/docs/our-commits-inventory.md` | 522 条 commit 记录，辅助追溯每项改动的来龙去脉 |

**关键原则**：当规范（P0）与原有实现（P1）冲突时，以规范为准，必要时重新设计实现方式。

---

## 三、迁移流程

### Step 1：逐项审视

从 `our-commits-inventory.md` 中，按时间顺序从最老的未处理 commit 开始：

- 这个 commit 的改动**在 owner-v16 上还需要吗**？
- 是否已被上游覆盖或废弃？
- 如果保留，按新规范应该放在 `owner/` 的哪个子目录下？

### Step 2：专项评估

对于需要迁移的功能，做专项调研：

1. **改动清单**：找出该功能在 `原有改动清单.md` 中的所有相关条目
2. **Commit 链**：找出 owner 分支上该功能的所有相关 commit（不只是单个 commit）
3. **最终代码形态**：用 `git show owner:<file>` 查看 owner 分支上的最终实现
4. **Owner-V16 现状**：检查 owner-v16 上已有哪些能力、缺哪些能力
5. **输出评估文档**：存到 `/tmp/<feature>-migration-assessment.md`

### Step 3：分类决策

每项改动对应一个决策：

| 决策 | 说明 |
|------|------|
| ✅ **迁移** | 功能有效，按新规范重新实现或直接迁移 |
| 🔄 **重构** | 功能有效但实现方式需调整（如从改源码改为 hook/import 编排） |
| ⏭️ **跳过** | 已过时或不再需要，不迁移 |
| ❓ **待定** | 需要进一步评估，暂不做决定 |

### Step 4：逐步迁移

- 每次迁移一个功能区或一个独立功能
- 每个功能迁移后立即 commit，commit message 标注 `[migrate]` 前缀
- 迁移过程中发现新规范未覆盖的情况，先记录到文档，不擅自决定

---

## 四、Commit 规范（迁移期间）

| 类型 | 前缀 | 说明 |
|------|------|------|
| 迁移 | `migrate(owner):` | 从 owner 分支迁移功能到 owner-v16 |
| 重构 | `refactor(owner):` | 迁移时调整了实现方式 |
| 文档 | `docs(owner):` | 更新迁移规范或相关文档 |

---

## 五、注意事项

1. **owner 分支保持不动**——它是只读参考，不在上面做任何修改
2. **每次迁移前先 sync main**——确保 owner-v16 基于最新的 upstream/main
3. **不确定的先标记待定**——宁可多一轮确认，不要贸然迁移一个不确定的功能
4. **迁移后验证**——如果功能可以本地测试，迁移后跑一遍确认没坏

---

## 六、明确忽略的功能

以下功能在本次迁移中**不迁移、不评估**，直接标记废弃：

| 功能 | 原因 |
|------|------|
| **定价相关**（pricing 条目、pricing.yaml、双币种、currency 字段等） | 上游已内置完整定价引擎，外部配置方式已足够，无需在代码层面维护 |
| **AGENTS.md 相关**（翻译、内容修改等） | 纯文档改动，无功能价值，不迁移 |

---

## 七、实战经验（2026-06-13 auto-card 迁移总结）

### 7.1 推荐工作流：tmux + kimi 后台迁移

**核心思路**：主 agent 负责决策和 review，kimi 负责代码实现，tmux 让两者不互相阻塞。

**步骤**：

1. **主 agent 做专项调研**（~5 分钟）
   - 读改动清单、commit 链、owner 最终代码、owner-v16 现状
   - 输出评估文档到 `/tmp/<feature>-migration-assessment.md`
   - 确定迁移方案（分阶段、明确每个阶段的改动点）

2. **写 prompt 文件**（主 agent）
   - 把评估文档路径、项目路径、分支信息、具体任务写到 `/tmp/kimi-<feature>-prompt.md`
   - 明确告知 kimi：源分支只读、目标分支、测试命令、输出文件路径

3. **tmux 启动 kimi**（主 agent）
   ```bash
   # 写 prompt 到文件（避免 heredoc 转义问题）
   cat > /tmp/kimi-<feature>-prompt.md <<'EOF'
   你的任务描述...
   EOF

   # 启动 tmux session
   tmux new-session -d -s kimi-<feature> \
     "bash -c 'cd ~/projects/ai/hermes-agent && kimi --yolo --print --thinking < /tmp/kimi-<feature>-prompt.md > /tmp/kimi-<feature>.log 2>&1'"

   # 立即返回，不阻塞
   echo "tmux session 'kimi-<feature>' started"
   ```

4. **轮询检查进度**（用户问时）
   ```bash
   tmux has-session -t kimi-<feature> 2>/dev/null && echo "Running" || echo "Finished"
   tail -30 /tmp/kimi-<feature>.log
   ```

5. **Review kimi 输出**（主 agent）
   - 检查 `git diff --stat` 确认改动范围
   - 检查代码是否符合二次开发规范（见 7.2）
   - 跑测试确认无回归

### 7.2 Review 检查清单（二次开发规范合规性）

kimi 完成代码后，主 agent 必须检查以下几点：

| 检查项 | 要求 | 不符合时的处理 |
|--------|------|---------------|
| **P0 Hook 优先** | 能用 hook 实现的功能是否用了 hook？ | 评估是否能改为 hook 实现 |
| **P1 import 编排** | 需要插入自定义逻辑时，是否用 import 而非内联？ | 重构：核心逻辑搬到 owner/，源码只留 import + 调用 |
| **P2 源码改动最小化** | 源码改动是否只限于必要的集成点？ | 精简源码改动，把逻辑移到 owner/ |
| **owner/ 目录** | 自定义文件是否放在 owner/ 下？ | 移动文件到 owner/ 对应子目录 |
| **可移除性** | 删除 owner/ 下的功能目录后，其余部分能否正常运行？ | 解耦依赖 |
| **[owner-patch] 注释** | 源码中的改动点是否标注了 `[owner-patch]`？ | 补充注释 |

**反例**（auto-card 第一次 kimi 改法）：
- ❌ 181 行新功能代码全部内联到 feishu.py
- ❌ 6 个新方法直接加在 FeishuAdapter 类里
- ❌ 没有放在 owner/ 目录下

**正确做法**（重构后）：
- ✅ 核心逻辑 446 行在 `owner/feishu/auto_card.py`
- ✅ feishu.py 只加了 import + send_card() + 5 行调用（共 87 行）
- ✅ 删除 `owner/feishu/` 即可移除整个功能

### 7.3 [owner-patch] 注释规范

**所有在官方源码中的改动点**，必须在改动行附近添加 `[owner-patch]` 注释，方便后续 sync fork 时快速识别定制改动。

**格式**：
```python
# [owner-patch] auto-card: try auto-card before plain-text fallback
auto_card_result = await try_auto_card(self, formatted, metadata)
if auto_card_result is not None:
    return auto_card_result
```

**规则**：
- 每个改动点（import、方法新增、逻辑插入）都要标注
- 注释放在改动行的**上一行**或**同一行行尾**
- 纯新增的方法（如 `send_card()`）在方法定义上方标注
- import 语句在同一行行尾标注

**示例**：
```python
# [owner-patch] auto-card: REST API card sending (owner/feishu/auto_card.py)
from owner.feishu.auto_card import try_auto_card

class FeishuAdapter(BasePlatformAdapter):
    # [owner-patch] auto-card: send_card() REST API method
    async def send_card(self, chat_id, card, metadata=None):
        ...

    async def send(self, chat_id, content, ...):
        formatted = self.format_message(content)
        # [owner-patch] auto-card: try auto-card before plain-text fallback
        auto_card_result = await try_auto_card(self, formatted, metadata)
        if auto_card_result is not None:
            return auto_card_result
        chunks = self.truncate_message(...)
```

### 7.4 Commit 工作流

每个功能迁移完成后，按以下顺序提交：

1. **代码 commit**：所有改动合并为一个 commit
   ```
   feat(feishu): auto-card — long text to interactive card when streaming off

   Phase A (core): ...
   Phase B (quality): ...
   Phase C (P64 split + feasibility): ...

   Architecture: P1 import 编排 — core in owner/, feishu.py only imports + calls.
   ```

2. **更新 our-commits-inventory.md**：将 owner 分支上对应的 commit 标记为已迁移
   ```
   - [x] ✅ 已迁移 `<new_commit>` `<old_commit>` | date | author | message | +N −M
   ```

3. **文档 commit**：单独提交 inventory 更新
   ```
   docs(owner): mark N auto-card commits migrated (hash1/hash2/... → new_hash)
   ```

### 7.5 Kimi Prompt 模板

写 kimi prompt 时，必须包含以下信息：

```markdown
## 项目信息
- 项目路径：~/projects/ai/hermes-agent/
- 当前分支：owner-v16（已 checkout）
- 源分支：owner（只读参考，不要在上面改任何东西）
- 迁移评估文档：/tmp/<feature>-migration-assessment.md

## 任务
（具体要做什么）

## 注意事项
- 先用 `git show owner:<file>` 查看源代码，不要直接改 owner 分支
- 核心逻辑放在 owner/ 下的对应子目录
- gateway/platforms/feishu.py 等官方源码只做 import 编排
- 改完后跑测试确认没破坏
- 每个文件改完后用 git diff 确认改动合理

## 输出要求
完成后把结果写到 /tmp/kimi-<feature>-result.md
```

### 7.6 常见陷阱

1. **kimi 可能直接改源码**：不加引导的话，kimi 会把所有代码内联到官方文件里。prompt 里必须明确说"核心逻辑放 owner/，源码只做 import 编排"。

2. **heredoc + bash -c 转义问题**：不要用 `bash -c '...' <<EOF` 单行包装，会被转义。正确做法：先 `write_file /tmp/prompt.md`，再 `< file`。

3. **kimi stdout 是事件流**：`--print` 模式下 stdout 不是纯文本，是 TurnBegin/ToolCall/TextPart 事件。让 kimi 把结果写到文件，不要解析 stdout。

4. **配置命名空间**：owner 分支用 `owner.feishu.card.*`，但 owner-v16 可能用 `owner.feishu_card.*`。迁移时保持与目标分支一致。

5. **send_card() 必须用 REST API**：不能用 lark_oapi SDK，否则会触发 WebSocket token 刷新导致断连。必须用 `message.create` API，不能用 `reply` API。

---

## 八、迁移进度

> 迁移进度统一在 `owner/docs/our-commits-inventory.md` 中维护。
> 每个 owner 分支 commit 的状态标记（✅ 已迁移 / ⚠️ 废弃 / ⏸️ 待定 等）
> 即为进度记录，不在本文档重复维护。
