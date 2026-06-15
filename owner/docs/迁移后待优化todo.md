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

- 修复 Feishu 名称缓存提取后的回归测试失败（2026-06-14，commit `489b7f886`）
  - `owner/feishu/sender_name_cache.py`: 修正 `lark_oapi` import 路径（`AccessTokenType`/`HttpMethod` 在 `lark_oapi.core`，不在 `.const`）。
  - `gateway/platforms/feishu.py`: 在懒加载 `FeishuSenderNameCache` 之前先检查 legacy/test 预热的 `_sender_name_cache`；绑定新 cache 时保留已存在的条目。
  - `tests/gateway/test_feishu.py`: 为 `__new__` 构造的测试 adapter 补 `config` 属性；将 `user_id` 优先期望更新为 `open_id` 优先（与 owner approval callback/cache 对齐）。
  - 结果：`tests/gateway/test_feishu.py` 205 项全部通过（此前 16 项失败）。

- 批量评审并处理 5 个未迁移 commit（2026-06-14，commit `e5a2c968d` 记录 inventory 状态）
  - `478b66a`: 迁移 `owner/scripts/todo-scan.sh`（owner 分支最终形态已有，macFUSE 超时保护）。
  - `f796063`: 仅采纳 `.gitignore` 的 `.claude/settings.local.json` + `.local/`；`patch.yaml` 的 backup excludes 已由 `owner/scripts/backup-hermes-config.py` 的 DEFAULT_CONFIG 覆盖，无需重复添加。
  - `38aa3ce`: 废弃（owner-v16 官方文件已无 yangtb 残留）。
  - `5311fe2`: 跳过（owner/ 目录迁移已由其他 commit 覆盖）。
  - `10d296e`: 跳过（owner-v16 使用 Qdrant，无 Viking prefetch 需求）。

- 批量评审并处理下一批 5 个未迁移 commit（2026-06-14）
  - `5ac061b`: 已迁移 patch.yaml approval allowlist 合并（`tools/approval.py` + `owner/config/patch.yaml` + 测试）。
  - `49f6a6d`: 废弃（owner-v16 无 viking-auto-commit.py）。
  - `9ef510c`: 废弃（pricing.yaml 不迁移；backup-configs.sh 已由 backup-hermes-config.py 替代）。
  - `d31f26b`: 标记为 i18n 统一处理（approval 文案中文化）。
  - `b7a199b`: 完成-取部分（`9589b4940`）——TUI Cmd+C fix 已提取为独立 commit；Viking health report 废弃。

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

  - 低优先级问题 1-4 已逐个处理（2026-06-14）：
    - #1（docstring 瘦身）：从模块 docstring 中移除大段 "Patch.yaml integration" 描述（保留 resolution order），owner 特定说明改用函数内短 [owner] 注释承载，减少官方文件文字 diff。
    - #2（invalidate 联动）：在 `owner/display_overrides.py` 末尾添加 `invalidate_per_chat_display_cache` re-export（包装 patch_config），并在模块 docstring 说明。支持用户在编辑 patch.yaml 后立即使 per_chat 生效。
    - #3（收敛 run.py 重复）：将 gateway/run.py 中所有使用 `chat_id=...chat_id` 的 resolve_display_setting 调用（含之前遗漏的 busy_ack_detail 通知循环）迁移到 `resolve_display_setting_for_source(..., source=...)`。更新了对应 local import。重复模式大幅减少。
    - #4（CLI/gateway 边界）：在 helper docstring、main 函数 chat_id 参数文档、以及 patch.yaml 示例注释中明确 "primarily for gateway messaging chats; CLI sessions usually do not participate / pass None"。
  - 验证：import、相关测试通过，grep 确认无遗漏 chat_id 直接写法，[owner] 标记一致。

- per-chat display overrides 迁移后规范合规收尾（2026-06-14，按 review 建议逐个修复）
  - `gateway/slash_commands.py`：补齐 `_handle_verbose_command`（tool_progress cycle）中唯一的遗漏 `resolve_display_setting` 调用点，传入 `chat_id=event.source.chat_id` 并加标准 `# [owner] per-chat display override` 短注释 + 说明。
  - `gateway/display_config.py`：
    - 移除顶层 `from owner.display_overrides` 直接 import，改为函数内 **lazy + try/except 保护** 的安全加载；except 路径提供 no-op fallback（merge 返回原 cfg，per_chat 返回 None）。这样即使 `rm -rf owner/display_overrides.py`（或整个 owner/），`import gateway.display_config` 仍成功，功能优雅降级。
    - 新增 `resolve_display_setting_for_source(..., source=..., chat_id=...)` 辅助函数（带详细 [owner] 注释），集中处理 source → chat_id 提取，未来 gateway/run.py 新调用或重构时可使用它，减少重复 `chat_id=xxx.chat_id` 噪音和 merge 面积。
  - 生产路径全量验证（grep）：只有 `gateway/run.py`（已带 chat_id）和 `gateway/slash_commands.py`（本次补齐）两处；所有 tests/ 调用均不传 chat_id（合理，默认 None）。
  - 经验教训（记录供后续迁移参考）：
    - 即使“看起来只改了 8 处”的 migration，也必须 grep 整个 gateway/（包括 slash_commands.py）找所有 resolve_display_setting 调用。
    - 可移除性不只是“逻辑放 owner/”，顶层 import 会导致模块加载即崩溃；必须用 lazy import + 保护性 fallback。
    - 在 gateway/run.py 这种超大核心文件里重复添加 kwarg 是高成本的；提供 source 包装器 + 集中注释是降低长期 sync 冲突的好实践。
    - 官方 display_config.py 的 docstring 改动要克制（新 tier 说明尽量放代码注释）。
    - 每轮 owner 迁移后都要更新本 TODO，并做“调用点全覆盖 + removability 验证” checklist。

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

**状态**：✅ 已完成（P2 2026-06-15）— `FeishuApprovalContext` + `handle_approval_card_action` / `resolve_approval` in `owner/feishu/approval.py`；`feishu.py` 仅保留 ctx + property + 委托。

### 1b. Update-prompt 状态管理封装（P3 2026-06-15）

**状态**：✅ 已完成 — `FeishuUpdatePromptContext` + i18n 卡片构建/回调在 `owner/feishu/update_prompt.py`；`feishu.py` 薄委托 + `_update_prompt_state` property。

### P3 其他收尾（2026-06-15）

- ✅ `ui-tui/src/owner/` — spinner / branding / statusBar 模块化
- ✅ `owner/gateway/messages.py` — run.py owner i18n 收敛
- ✅ `memory_proposal` — `_TEXT` 迁至 `locales/{en,zh}.yaml` + `t()`

---

### 2. current-user 注入架构收敛

**状态**：✅ 飞书路径已完成（2026-06-15）— Feishu 改为 per-message append（`owner/feishu/inbound_context.py` + `owner/gateway/inbound_context.py`），含 `user_name` / `open_id` / `chat_id` / `chat_type`；`system_prompt.py` 对 Feishu 跳过 `Current user:`；其他渠道保持原 system-prompt + Telegram observed wrap 行为。

**遗留（可选）**：非 Feishu 平台若也要去掉 system prompt 注入，需逐平台评估后再扩。

---

## 其他低优先级想法（可选记录）

- ✅ `FeishuSenderNameCache` 复用收敛（2026-06-15）— `owner/feishu/sender_name_helpers.py` 统一 lazy bind / legacy compat / pre-warm；`approval.py`、`update_prompt.py`、`model_picker.py`、`bot_menu.py` 与 `feishu.py` 薄委托共用。
- ✅ **FeishuUserStore Phase A**（2026-06-15）— `owner/feishu/user_store.py` 统一 open_id 作用域状态（名称 TTL + p2p chat_id 磁盘缓存）；`FeishuAdapter` 持有 `_user_store`，`_client` / `_name_cache` / `_sender_name_cache` / `_feishu_user_cache` 为薄转发（`__new__` 测试路径保留 legacy fallback）。**Phase B/C 待办**：B) resolve 时同步 `display_name` 到 user record、弃用 `FeishuUserEntry.name`；C) 磁盘格式升级、移除 `_sender_name_cache` shim、内聚 `FeishuSenderNameCache`。
- ✅ `BasePlatformAdapter.send_exec_approval(**kwargs)` 默认 stub（2026-06-15）— 返回 `interactive_approval_not_supported`，`run.py` 统一 contract；有按钮 UX 的平台继续 override。
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