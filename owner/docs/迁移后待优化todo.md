# 迁移后待优化 TODO

> 本文档记录在完成核心提取（如 diff cards、审批卡片 + open_id→中文名缓存）之后，计划在**后续迁移阶段**再处理的非 P0 优化项。
> 目标是持续降低官方文件（尤其是 gateway/platforms/）的 owner 痕迹，便于未来 upstream sync。
> 最后更新：2026-06-14（unified_diff_patch 迁移规范合规收尾）

## 当前已完成（参考）

- 审批卡片核心逻辑 + open_id → 中文名缓存（仅名称部分）完整提取到 `owner/feishu/`
  - `sender_name_cache.py` + `approval.py`
  - feishu.py 只剩薄胶水 + 委托 + 统一短 `[owner]` 标记
  - 5 个非飞书 adapter 已改用 `**kwargs` 减少显式污染（本次 1+3 项完成）
  - 测试已清理对 legacy `_sender_name_cache` 的直接依赖

- unified_diff_patch 迁移后规范合规收尾（2026-06-14，按 review 建议逐个补齐）
  - `agent/display.py`：在 `extract_edit_diff` 两处 if 条件上补短 `# [owner]` 标记（说明 inline diff 支持来自 owner/tools/unified_diff_patch/）
  - `agent/tool_guardrails.py`：在三个 block/halt 消息增强点（exact_failure / no_progress / same_tool_failure）各加 `# [owner] guardrails UX` 短标记 + 说明来源
  - `toolsets.py`：补齐 hermes-acp（ACP/编辑器 coding 姿势）列表中的 "unified_diff_patch" + 对应 `[owner]` 注释（此前遗漏）
  - `tools/file_tools.py`：在 legacy patch register 注释处补充说明“保留死代码是为了最小化未来 upstream sync 的 textual diff”
  - 所有改动均遵循《二次开发规范》“官方文件字面干净 + 短统一 [owner] 标记 + 指向 owner/”要求
  - 经验教训（记录供后续迁移参考）：
    - 即使是迁移后的小 polish fix（fix(agent):），只要触碰 agent/、toolsets.py 等官方文件，必须**立即**加标记，不能裸奔。
    - 大迁移 commit 后必须全量 grep 扫描所有显式 toolset 列表（包括 hermes-acp、各种 posture），不能只改 _HERMES_CORE_TOOLS 和 "file"。
    - legacy 实现留在官方文件（只禁注册）是权衡 sync 冲突 vs. 可移除性的结果；删除需谨慎。
    - per-file commit 纪律和迁移 checklist（规范 7.2）在收尾阶段同样适用。

## 待办项（按推荐优先级）

### 1. 审批卡片状态管理封装（中优先级，推荐下一个小阶段处理）

**问题描述**：
- `_approval_state`（approval_id → {session_key, message_id, chat_id, command}）和 `_approval_counter` 仍直接挂在 `FeishuAdapter` 实例上。
- 审批卡片的 send / callback / resolve 逻辑虽已大部分外移，但状态读写仍散在 feishu.py 里。
- 与 `DiffCardContext` 的封装模式不一致。

**建议做法**：
- 在 `owner/feishu/` 下新建或扩展 `approval.py`，增加一个轻量 `FeishuApprovalContext`（或 `ApprovalCardManager`）。
- 负责：
  - 状态存储与 pop
  - approval_id 生成
  - 与 `build_resolved_approval_card` / `make_callback_response` 的配合
  - 必要时暴露 `register_approval(...)` / `resolve_approval(...)` 等方法
- `FeishuAdapter` 只持有 `self._approval_ctx = FeishuApprovalContext(...)`，send 和 handler 里做极薄委托。
- `_resolve_approval` 的调用可以保持（或进一步桥接）。

**收益**：
- feishu.py 里审批相关代码进一步变薄（目标：只剩 10 行以内 glue + 路由）。
- 状态生命周期高内聚，未来想完整移除审批卡片功能只需删 owner 模块。
- 与 diff cards 的 `DiffCardContext` 形成统一模式，便于 review 和新人上手。

**预估改动量**：中等（新建 context 类 + 调整 feishu.py 内部调用 + 更新少量测试）。
**风险**：中（需确保 approval_id 关联、chat 校验、权限检查等行为 100% 不变）。
**依赖**：当前已有的 `owner/feishu/approval.py` 和 name cache。

**状态**：待迁移一个阶段后处理。

---

### 2. current-user 注入架构收敛（低优先级，建议等更稳定阶段或有实际痛点时再碰）

**问题描述**（来自 9fbba42b6 相关审查）：
- 在 `agent/system_prompt.py` 的 volatile 部分注入 `Current user: xxx`（读取 `agent._user_name`）。
- 同时在 `gateway/run.py` 的 `_wrap_current_message_with_observed_context` 里为 group chat 额外加 `[Current user: ...]` 前缀。
- 双路径设计有一定道理（系统提示 per-session 缓存），但增加了文本重复和维护点，也轻微增加了核心 prompt 构造路径的 owner 痕迹。

**建议做法**（如果要做）：
- 评估是否可以把“当前用户”信息完全收敛到 per-message wrap 路径（对 prompt cache 更友好）。
- 或抽象一个通用的 `observed_user_context` / `participant_hint` 机制，供所有平台使用，而非 Feishu 特化。
- 最小化对 `system_prompt.py` 的改动（该文件属于 narrow waist）。

**收益**：代码更整洁、减少一点点重复、潜在的 group chat UX 改进。
**风险**：高（直接影响系统提示构建和 prefix cache 稳定性，必须极度小心 + 大量测试）。
**当前状态**：注释已统一。功能可用，不作为 P0。

---

## 其他低优先级想法（可选记录）

- 推动 `FeishuSenderNameCache` 在更多地方复用（auto_card、diff cards、bot menu、profile router 等需要显示真实中文名的场景），减少潜在重复解析逻辑。
- 考虑在 `gateway/platforms/base.py` 或一个公共 mixin 里提供默认的 `send_exec_approval(**kwargs)` 空实现（带文档），进一步降低各平台 adapter 的样板代码。
- 定期扫描所有 `[owner]` 注释，确认是否还能继续薄化或完全移除（通过 hook / 更上层的编排）。

## 工作原则

- 任何进一步改动仍需遵循《二次开发规范》：优先 owner/ 封装、薄胶水、短统一 `[owner]` 标记、per-file commit。
- 改动前更新本 TODO，改动后在 inventory.md 或规范文档中记录经验。
- 涉及 prompt cache、message alternation、核心 agent 路径的改动，必须先在 owner/docs/ 里写清楚理由 + 风险缓解措施。

---

**如何使用本文件**：
- 每次准备新迁移阶段（切 owner-v* 分支）时，review 本 TODO，挑选 1~2 项作为该阶段的“收尾优化”。
- 完成后把对应条目移到“已完成”或单独的完成记录里。

贡献者：按审查意见 + 用户决策（2026-06 当前阶段仅完成 1+3，2 记录于此）。