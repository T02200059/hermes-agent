# owner 改动清单

> **范围**：owner 分支个人定制改动（主体为 owner-v16，v17 起增量追加）  
> **最后更新**：2026-06-23（新增 §18 owner-v17 飞书 terminal bash fence；补充 §17 遗漏项梳理）  
> **说明**：本清单替代 `原有改动清单.md`，按改造主题组织，只记录功能代码改动。`docs(owner)` / `docs(inventory)` 等纯清单维护提交不逐条列出。

---

## 一、v16 迁移与代码治理

### 1.1 owner-v16 迁移工程启动
- **背景问题**：owner 分支积累了大量个人定制 patch，与 upstream 源码高度耦合，每次同步 upstream 都产生大量冲突，难以长期维护。
- **解决方案**：建立独立的 `owner/` 目录作为所有个人定制的物理隔离层；引入 `our-commits-inventory.md` 机制，对历史 commit 按「已迁移 / 废弃 / 延迟 / 跳过」分类管理。
- **相关 commit**：`17e4a81a8`

### 1.2 上游同步清理与薄胶水模式
- **背景问题**：个人定制直接侵入 `run_agent.py`、`gateway/platforms/feishu.py` 等官方大文件，导致同步时冲突面过大。
- **解决方案**：
  - 将 Feishu 审批卡片、diff 卡片、发件人 name cache 等从官方 adapter 提取到 `owner/feishu/` 模块；
  - 在官方文件中只保留带 `[owner]` / `[owner-patch]` 标记的薄胶水调用；
  - 集中凭证注入、模型归因等公共逻辑到 `owner/` 辅助模块。
- **相关 commit**：`0604660cb`, `0bfca811e`, `71e3d39e7`, `50f3c93b6`, `595bb58f1`, `fc9294df9`

---

## 二、配置与补丁系统（patch.yaml）

### 2.1 `owner_provider_name` 保持真实自定义供应商身份
- **背景问题**：Hermes 内部会把自定义 provider（如 `kimi-coding`）解析成底层供应商（如 `moonshot`），导致计费和日志丢失用户实际配置的 provider 名称。
- **解决方案**：新增 `owner_provider_name` 字段贯穿请求链路；在复制 `api_messages` 时剥离该字段，既保护 prompt 缓存稳定性，又满足下游计费与日志需要。
- **相关 commit**：`8f8ec858e`, `0eb690b8d`, `1db67cfbd`, `75a88f19c`

### 2.2 patch.yaml 统一加载与热更
- **背景问题**：原 patch.yaml 通过分散在各地的临时读取逻辑生效，缓存 5 分钟，配置更新后生效慢；个人脚本和 model 选择也各自硬编码。
- **解决方案**：
  - 统一 patch.yaml 加载器，默认 5 分钟周期刷新；
  - 将 `image_gen.model` 选择迁移到优先读取 patch.yaml；
  - 备份脚本 `backup-hermes-config.py` 改用统一加载器；
  - 缓存 TTL 从 300 秒降到 60 秒，提升热更响应。
- **相关 commit**：`1465ec988`, `f02a7bfdc`, `98c60d63e`, `7c6f8683e`

### 2.3 模型级 `extra_body` 注入
- **背景问题**：某些自定义模型需要在请求体注入额外字段（如 thinking 参数），官方没有按模型配置 extra_body 的机制。
- **解决方案**：从 patch.yaml 读取 `model_extra_body`，按模型名注入到 API 请求的 `extra_body`。
- **相关 commit**：`b84b43927`

### 2.4 审批命令白名单（patch.yaml）
- **背景问题**：`config.yaml` 的 `command_allowlist` 是静态白名单，无法表达 Tirith 规则等复杂审批策略，也无法针对 DANGEROUS_PATTERNS 描述永久免审批。
- **解决方案**：新增 `patch.yaml → owner.approvals.command_allowlist`，与 config.yaml 原白名单合并生效，支持规则表达式和永久免批。
- **相关 commit**：`1601e6c8c`, `0a3a339b6`

---

## 三、模型提供者与 API 适配

### 3.1 裸域名 base_url 自动补 `/v1`
- **背景问题**：OpenAI SDK 对自定义 base_url 不会自动拼 `/v1`，用户填写裸域名时常返回 404。
- **解决方案**：`normalize_bare_domain_base_url()` 检测无 path 的裸域名并追加 `/v1`；在主 Agent 和辅助客户端两处入口生效，排除 `anthropic_messages` 模式避免双重 `/v1`。
- **相关 commit**：`e60299375`

### 3.2 kimi-coding 自定义 Provider 修复
- **背景问题**：`kimi-coding` 自定义 provider 的 `base_url` 和 `api_mode` 配置在迁移过程中丢失或解析错误。
- **解决方案**：修正 `kimi-coding` 的 `base_url` 与 `api_mode` 解析逻辑，确保自定义 provider 能正确路由到 Moonshot 兼容端点。
- **相关 commit**：`75a88f19c`

### 3.3 DashScope / 自定义图像生成模型支持
- **背景问题**：官方 image_generate 工具对 DashScope 等国内 provider 支持不完善，且使用了错误的 `DASHSCOPE_COMPANY_API_KEY` 环境变量名。
- **解决方案**：增加 `image_generate` 的 model 参数透传；新增 DashScope provider 插件；修正为 `DASHSCOPE_API_KEY`。
- **相关 commit**：`e5a9297bf`, `0a5948548`

### 3.4 MiniMax 与自定义 provider 目录治理
- **背景问题**：`minimax-cn` 目录与模型列表杂乱；`/v1/models` 对自定义 provider 缺乏校验和去重。
- **解决方案**：收敛 `minimax-cn` catalog，新增 `M2.7-highspeed` 等模型；`/providers` 接口增加 credential 校验、模型列表覆盖和去重。
- **相关 commit**：`f29fcf6e7`, `9272784d0`

### 3.5 Thinking 模式与工具推理内容适配
- **背景问题**：xfyun/damodel/GLM 等国产端点在 function call 时返回 reasoning content 的格式与 OpenAI 标准不一致，导致思考内容丢失或解析错误；Kimi `xhigh` reasoning effort 与官方映射不兼容。
- **解决方案**：新增 `_needs_*_tool_reasoning` 检测器，按端点转换 reasoning 字段；将 kimi `xhigh` 降级为 `high`，避免无效参数。
- **相关 commit**：`0f291d4bd`, `a1e242548`

### 3.6 MiniMax Anthropic endpoint thinking-block 支持
- **背景问题**：MiniMax 部分 endpoint 返回 Anthropic 格式的 thinking block，官方没有解析。
- **解决方案**：在 provider 适配层增加 thinking-block 解析。
- **相关 commit**：`6e04772b0`

### 3.7 `async_call_llm` 硬超时兜底
- **背景问题**：OpenAI SDK 默认 `max_retries=2`，在 provider hang 场景下单次重试可能拖到 30+ 分钟，阻塞压缩、摘要、vision 等所有走辅助 LLM 的任务。
- **解决方案**：在 SDK 重试外层加 `asyncio.wait_for(timeout = effective_timeout * 3)` 硬超时；超时归类为 connection error，走 fallback chain 切换到下一个 provider。
- **相关 commit**：`8e433d5ab`

### 3.8 每轮模型/Provider 归因
- **背景问题**：`messages` 表只记录会话级 model/provider，无法按 turn 追踪实际调用的模型和供应商。
- **解决方案**：在 `build_assistant_message` 和 `append_message` 中捕获每轮实际使用的 model/provider，写入 messages 表的对应列。
- **相关 commit**：`54ca17325`

### 3.9 模型选择器交互卡片
- **背景问题**：在飞书等消息平台切换模型缺少直观的交互界面。
- **解决方案**：新增交互式 model picker 卡片，支持 reason_label 等 i18n 提示。
- **相关 commit**：`1b1e09660`

### 3.10 运行时 schema patches
- **背景问题**：部分私有工具扩展（model/card 类）需要在运行时动态修改 tool schema，官方没有扩展点。
- **解决方案**：在 schema 注册后做运行时 patch，动态注入私有扩展字段。
- **相关 commit**：`6a075d7f0`

### 3.11 Credential pool base_url 尊重 model.base_url 配置
- **背景问题**：当 `model.provider` 匹配内置 provider（如 `xiaomi`）且 `model.base_url` 指向不同端点（如 Token Plan `token-plan-cn.xiaomimimo.com`）时，credential pool 种子使用 provider 的硬编码默认 URL（`api.xiaomimimo.com`）。pool rotation 和 delegate_task 子代理继承错误的 base_url，导致 401。
- **解决方案**：在 `owner/patches/pool_base_url_override.py` 新增 `config_base_url_override()` helper，在 4 条受影响链路（`_seed_from_env`、`_resolve_runtime_from_pool_entry` copilot 分支、`_resolve_explicit_runtime` 通用分支、`_swap_credential`）追加 2-3 行 `[owner]` 调用。优先级：env var > config `model.base_url` > 硬编码默认值。
- **相关 commit**：`5d7267894`

---

## 四、审批、安全与风控

### 4.1 Copilot 环境拒绝 Classic PAT
- **背景问题**：GitHub Copilot 环境 seeding 时会使用 classic PAT（`ghp_*` / `github_pat_*`），权限过大容易触发 GitHub 安全告警。
- **解决方案**：在 credential pool seeding 阶段检测并拒绝 classic PAT，仅接受 fine-grained PAT（`github_pat_pat_*`）。
- **相关 commit**：`9c06ee972`

### 4.2 飞书审批卡片重构
- **背景问题**：原 Feishu 审批卡片使用普通消息，点击后无法内联更新状态；且发件人中文名需要同步等待 API，首帧卡顿 5 秒。
- **解决方案**：
  - 改用 CallBackCard，点击后原地更新为「已批准/已拒绝」；
  - 将 `open_id → 中文名` 缓存提取到 `owner/feishu/sender_name_cache.py`，发卡片前异步 pre-warm；
  - 将卡片构建逻辑提取到 `owner/feishu/approval.py`；
  - 支持 `patch.yaml → owner.approvals.allow_permanent` 隐藏「永久允许」按钮。
- **相关 commit**：`e64a1aeac`, `aa68db184`, `7a0c05cf0`, `0e6ecad4d`, `489b7f886`, `b5de8d774`, `20f7db1a1`, `560086323`, `1d9499434`

### 4.3 多平台审批签名统一
- **背景问题**：Feishu 审批卡片改造引入了 `sender_open_id` / `sender_is_bot` 参数，但 Matrix/QQ/Slack/Telegram/WhatsApp 的 `send_exec_approval` 签名未同步，调用时触发 `TypeError`，被降级为文字审批。
- **解决方案**：统一 5 个平台的 `send_exec_approval` 签名，未使用的参数通过 `**kwargs` 吸收，保持接口一致。
- **相关 commit**：`3676aa6ce`, `05b39f89a`, `c60eb7755`, `fe200af2a`, `38fb9e228`, `1e2aeee28`, `d87993b31`, `36d0bb3fa`, `f8a08df4d`, `1e1f3c84f`

### 4.4 Current User 注入
- **背景问题**：系统提示词中缺少当前用户身份，模型在群聊中无法区分说话人；审批回调也无法知道请求者是谁。
- **解决方案**：在 volatile system prompt 中注入 `Current user: {agent._user_name}`；在 gateway 消息包装层把 sender identity 传递给各平台审批 adapter。
- **相关 commit**：`9fbba42b6`, `6fbccb357`, `18a0bb873`

### 4.5 记忆提案审批系统
- **背景问题**：原记忆写入缺少人工确认机制，模型自动写入的记忆可能污染长期记忆。
- **解决方案**：引入 memory proposal 审批系统，记忆写入前发送交互式卡片让用户确认/拒绝；修复 WR-10/WR-08 等边界问题；为卡片缓存增加 TTL 防止无限增长。
- **相关 commit**：`09a91bb94`, `b6abd7e54`, `288f8e2b6`, `477c9a8bb`, `5eaa9949f`（propagate_context_to_thread 工具）
- **补充说明**：memory_propose 审批串台修复（QQ + 飞书并发场景）—— 5 个 bug：
  - **Bug 1**：bg-review daemon 线程用裸 `threading.Thread` 不继承 ContextVar，`_get_session_key()` 回退到被污染的 `os.environ`；修复：用 `propagate_context_to_thread` 包装（`agent/background_review.py` + `# [owner]` 标记）。
  - **Bug 2**：`gateway/run.py` 的 `run_sync` 里 `os.environ["HERMES_SESSION_KEY"]` 是进程级写入，并发 executor 线程互相覆盖；修复：删除该写入，ContextVar 已由 `_set_session_env` + `copy_context` 隔离。
  - **Bug 3**：`_run_background_task` 路径的 `run_sync` 缺少 `set_current_session_key` / `setup_gateway_memory_routing` / `register_gateway_notify` 三件套，memory_propose 卡死或串台；修复：补全三件套（`gateway/run.py` + `# [owner]` 标记）。
  - **Bug 4**：`delegate_task` 批量并发 `ThreadPoolExecutor.submit(_run_single_child)` 未包 `propagate_context_to_thread`（`tool_executor.py` 已修但 `delegate_tool.py` 漏修）；修复：对齐 `tool_executor.py:606` 模式（`tools/delegate_tool.py`）。
  - **Bug 5**：bg-review 线程的 terminal approval callback 与 memory notify 回调是独立状态，装了也白装；修复：新建 `owner/memory/bg_review_auto_approve.py`，bg-review 线程临时注册自动批准回调，memory_propose 静默落盘不弹卡片，从根本上消除串台。
  - **Bug 5 补强（隔离 key）**：初版把 auto-approve 回调直接注册在**共享的父 session key `K`** 上。由于 `owner/memory/gateway._memory_notify_cbs` 是 *每 key 单槽* 的 dict 且 `unregister_memory_notify` 带 `clear_memory_proposal` 副作用，当 bg-review 仍在跑、用户又发下一轮（同一 session）时会反向串台：bg-review 提案弹给用户 / 用户真实提案被静默自动批准或被 `clear_memory_proposal(K)` 误 deny / cleanup 后无回调挂到超时。修复：`setup_bg_review_memory_auto_approve()` 把当前线程的 approval session-key ContextVar **重绑到隔离 key `<parent>#bg-review`**（新增 `_derive_bg_review_key`，幂等、空 parent → `default`），auto-approve 注册在该隔离 key 下，review agent 的每次 memory_propose 经 `_get_session_key()` 都落隔离队列，父 session 的 K 槽/队列完全不被触碰；cleanup 只清隔离 key 并 reset ContextVar，幂等。回归测试见 `tests/owner/test_memory_propose_concurrency.py`（16 用例全绿）。
- **相关 commit**：`31c91b59b`（5 bug 初版）, 本次（Bug 5 隔离 key 补强 + 回归测试）

### 4.5.1 memory_propose 批量提案（对齐官方 v0.17 `apply_batch`）
- **背景问题**：官方 v0.17 `memory` 工具引入 `operations[]` 批量数组 + `MemoryStore.apply_batch` 原子写入（PR #48507），鼓励 LLM 用一次调用清理 stale 条目腾空间 + 添加新条目（all-or-nothing，char limit 按 FINAL result 校验）。但 owner 的 `memory_propose` 审批壳停留在 v0.16 单条形态——LLM 只能拆成 N 次 `memory_propose`，导致飞书发 N 张审批卡、用户点 N 次同意、中途失败会出现"前半 batch 已落盘 + 后半 batch 被 limit 拒"的半写入状态，无法原子。
- **解决方案**（拆两个 commit 落地）：
  1. **数据通路**：`owner/memory/schema.py` 的 `MEMORY_PROPOSE_SCHEMA` 扩展为双 shape（`required` 收窄到 `["target"]`，新增 `operations` 数组）；`owner/memory/gateway.py` 的 `_MemoryApprovalEntry` 加 `operations: Optional[List[Dict]]` 字段 + `submit_memory_proposal(operations=...)` 入参 + 从 `operations[0]` 派生单条字段以保持旧 card 渲染代码兼容；`owner/memory/tool.py` 加 `_validate_operations` + `conflicting_shape`/`invalid_operations` 入口校验 + 批准后分支调用 `store.apply_batch(target, operations)`。`agent/tool_executor.py` 的 `_execute_memory_propose` 加 1 行 `operations=next_args.get("operations")` 透传（已加 `# [owner]` 标记）。
  2. **UI + i18n**：`owner/feishu/memory_proposal.py` 的 `build_memory_proposal_card` 扩双 shape —— 批量标题 + 遍历 N 条 op（add 显示 content 预览、replace 显示 old→new、remove 显示 old_text；N>5 时折叠前 3 + footer）；`gateway/platforms/{base,feishu}.py` 的 `send_memory_approval` 签名加 `operations: Optional[list] = None` 透传（已加 `# [owner]` 标记）；`owner/memory/gateway._notify_callback` 把 `operations` 透传到 adapter；`locales/{zh,en}.yaml` 加 5 个 i18n key（`card_title_batch` / `card_summary_label` / `card_op_index` / `card_more_ops` / `card_char_budget`）。
- **关键约束**：官方 `tools/memory_tool.py` 零改动；`owner/memory/setup.py` 的 deregister + toolset 替换逻辑未动；`handle_memory_card_action` → `resolve_memory_approval(session_key, choice)` callback 路径未动。char 预算暂不在卡片上显示（card builder 没有 store 访问权，扩张 adapter 契约换取的信息增益不高；后续如需可加）。
- **回归测试**：`tests/owner/test_memory_proposal.py` 新增 `TestMemoryProposeBatchTool` 4 用例（approve → `apply_batch` 被调一次且参数正确 / deny → store 任何方法都不调 / `success=False` → `write_error` 且无单条 fallback / 20-op 大批量 schema + submit 链路通过），owner 全量 297/297 通过。
- **相关 commit**：见下方两个 `feat(owner): memory_propose batch …` commit。

### 4.6 Skill 脚本自动审批与 YOLO 模式
- **背景问题**：高频 skill 脚本调用需要反复人工审批，打断工作流；官方 YOLO 模式缺少按命令细粒度开关。
- **解决方案**：
  - 新增 `skill_script_allowlist`，白名单内 skill 脚本自动审批；
  - YOLO 开启时自动解决 pending approvals；
  - Gateway 支持 `/yolo on|off|status` 语法糖，并增加本地化提示。
- **相关 commit**：`a39478319`, `b733fd96d`, `822c41d49`, `98e6a0aac`, `fbf5f6bc4`

### 4.7 Guardrail 提示信息增强
- **背景问题**：工具 guardrail 触发 block/halt 时只给固定文案，用户不知道具体命中了哪个计数器、阈值是多少。
- **解决方案**：在 block/halt 消息中直接包含计数器名称和阈值；为 code_execution 等场景补充 emoji 提示。
- **相关 commit**：`a3ed7543e`, `ebe8ca9f0`, `6a977c56f`

---

## 五、飞书平台深度定制

### 5.1 频道级系统提示（channel_prompts）
- **背景问题**：官方飞书平台不支持按频道/群定制系统提示词。
- **解决方案**：通过 `resolve_channel_prompt()` 读取配置，按 chat_id 注入对应 channel prompt。
- **相关 commit**：`b84407b32`

### 5.2 回调卡片 NameError 修复
- **背景问题**：飞书回调卡片在特定场景下触发 `CallBackToast` 序列化 NameError。
- **解决方案**：临时注释掉 CallBackCard response，避免异常崩溃。
- **相关 commit**：`598197f91`

### 5.3 长文本自动卡片（auto-card）
- **背景问题**：飞书普通文本消息有长度限制，且长文本阅读体验差；streaming 关闭时长回复直接以纯文本发送。
- **解决方案**：streaming 关闭且文本超过阈值时，自动拆分为交互式卡片发送；`tool_progress` 类消息跳过 auto-card。
- **相关 commit**：`1a4aa7bf6`, `4d55e6b13`, `2ce09b3ca`, `5c6e37292`
- **补充说明（footer 横线，`5c6e37292`）**：`owner/feishu/agent_end.py` 从 response 中拆分 footer，`owner/feishu/auto_card.py` 提取 `_build_card_elements()` helper，footer 非空时追加卡片原生 `hr` + footer markdown；多 chunk 时仅最后一个 chunk 渲染 footer；`estimate_auto_card_json_bytes` 和 `_evaluate_card_feasibility` 同步计入 hr + footer 的 JSON 开销。

### 5.4 输入中反应（early-typing）
- **背景问题**：飞书群聊中机器人处理耗时较长时，用户无法感知到消息已被接收。
- **解决方案**：在 `chat_lock` 被持有时发送 early-typing reaction，提示用户正在处理。
- **相关 commit**：`3290a7d56`

### 5.5 Diff 卡片
- **背景问题**：代码修改后只返回文字结果，飞书用户无法直观看到 diff。
- **解决方案**：
  - patch / write_file / skill_manage / unified_diff_patch 完成后自动提取 diff；
  - 飞书端渲染为可折叠的交互式卡片，支持 compact → expanded → full 三阶段展开；
  - 发送逻辑和渲染逻辑提取到 `owner/feishu/card_sender.py` 和 `owner/diff_card/`。
- **相关 commit**：`1da7ada8e`, `53ea73eaa`, `72425d7b8`, `cfd8c305d`

### 5.6 Clarify 交互卡片
- **背景问题**：官方 clarify 在飞书以普通文本呈现，选项多时长文阅读体验差，点击「其他」后卡片状态异常。
- **解决方案**：将 clarify 升级为交互式卡片；修复「其他」选项的冻结按钮和等待文本输入逻辑。
- **相关 commit**：`47a8e5db6`, `e675719e1`

### 5.7 Bot 菜单与统一用户缓存
- **背景问题**：飞书单聊 bot 不支持聊天框菜单按钮；`_sender_name_cache` 与 `p2p_chat_id` 分散管理，存在重复和失效问题。
- **解决方案**：
  - 支持 `application.bot.menu_v6` 事件，通过 `patch.yaml → owner.feishu.bot_menu` 映射到 slash command；
  - 合并 name cache 与 p2p_chat_id 为统一的 `FeishuUserStore`，按 open_id 索引，支持 TTL 与惰性淘汰。
- **相关 commit**：`18cbfa7e7`, `d2c991d9a`, `51e7fccd2`, `56cd7fda1`, `dffbef6fe`, `16a89b32c`, `d9651f11b`, `fe767c5f9`

### 5.8 多 Profile 路由
- **背景问题**：单 Bot 需要服务多个业务 profile（工作/个人），官方没有按用户/群路由到不同 Hermes profile 的机制。
- **解决方案**：该功能在 v16 中已评估并推迟到后续批次实现，当前仅完成需求梳理与 defer 标记，未进入代码迁移。
- **相关 commit**：`6e185a9f7`, `f56462d9d`

---

## 六、快捷命令与交互语法

### 6.1 链式快捷命令（;;）
- **背景问题**：官方 quick_commands 一次只能执行一条，无法一次性触发多个命令。
- **解决方案**：支持 `;;` 分隔的链式 quick_commands，CLI/Gateway/TUI 全平台生效。
- **相关 commit**：`faf90ea7c`

### 6.2 Quick Alias 集中化
- **背景问题**：CLI、Gateway、TUI Gateway 三处各自实现 quick alias 展开，逻辑重复且不一致。
- **解决方案**：在 `base.py` 中集中实现 `expand_chained_quick_alias()`，三处统一调用。
- **相关 commit**：`3692eac6d`, `d95d5a3c0`, `c21f45538`, `6371bd5b4`

---

## 七、TUI 与皮肤引擎

### 7.1 选中自动复制与窗口标题
- **背景问题**：TUI 中复制需要手动按 Ctrl+C，标题缺少品牌标识。
- **解决方案**：选中文字自动复制到剪贴板；窗口标题增加 `Hermes ·` 前缀；修复 macOS Cmd+C 无选择时的行为。
- **相关 commit**：`10e692f52`, `9589b4940`

### 7.2 皮肤引擎扩展
- **背景问题**：官方 spinner、statusBar、用户消息背景等样式硬编码，无法通过皮肤配置。
- **解决方案**：皮肤引擎支持 spinner faces、verb padding、statusBar 覆盖、用户消息背景色；新增 `ruolin` 系列皮肤；CJK 场景下 verb padding 自适应。
- **相关 commit**：`59ebc9954`, `03b254242`, `452fb72ee`, `75515d546`, `a5415bf64`

---

## 八、Diff / Patch 工具链

### 8.1 `unified_diff_patch` 工具
- **背景问题**：官方 `patch` 工具基于模糊匹配，容易改错行；缺少精确行号 patch 工具。
- **解决方案**：新增 `unified_diff_patch` 工具，基于统一 diff 精确行号进行替换；在相关 toolset 中完成注册；为 diff 卡片提供统一的 `result["diff"]` 提取。
- **相关 commit**：`7646add45`, `001e963d8`, `97b82f4cc`, `d55b57ff7`

### 8.2 Checkpoint mutation predictor (terminal 预测式快照)
- **背景问题**：`/rollback` 对 `terminal` 工具的文件改动有盲区 —— `python -c`、`tee`、`perl -i`、`npm run build` 等不命中 `_is_destructive_command` 正则的命令逃逸出快照；且原逻辑拍整个 cwd 有过度覆盖风险。
- **解决方案**：terminal 执行前用"静态解析优先 + LLM 兜底(task=approval)"预测目标文件，对其项目根 `ensure_checkpoint`。预测失败不降级拍 cwd，只报错。核心逻辑在 `owner/checkpoint_predictor/`，官方文件 `agent/tool_executor.py` 薄胶水委托。
- **相关 commit**：`9a6b9c0a9`（config reader）, `0c9f19b74`（static parser）, `79219c91f`（LLM fallback）, `a17b2ee7a`（orchestrator）, `965285f3b`（tool_executor 集成 + 删除 legacy）, `5e99d7aa7`（patch.yaml 配置 + 文档）

---

## 九、Hook 体系与记忆召回

### 9.1 Hook 配置与消息接收编排
- **背景问题**：hook 的 display 配置、消息接收逻辑与 gateway 主流程耦合，难以扩展。
- **解决方案**：将 hook config 和 receive orchestration 提取到 `owner/hooks/`；新增 `display_hook_message_receive` 等配置；增加 `/providers` 命令供 gateway 查询 provider 状态。
- **相关 commit**：`3ef673093`, `b83a87184`

### 9.2 Qdrant 记忆召回
- **背景问题**：官方记忆召回能力有限，无法基于向量库主动召回历史记忆。
- **解决方案**：新增 `qdrant-memory-recall` hook，从 Qdrant 向量库召回相关记忆并以飞书卡片展示；支持 patch.yaml 配置化与 bot_menu 命令跳过。
- **相关 commit**：`6bd8d4fe3`

### 9.3 Memory 合成消息 Recall Guard
- **背景问题**：`MemoryManager.prefetch_all`（recall）在每个 `run_conversation` turn 开始时无条件触发（`agent/turn_context.py:417-424`），唯一守卫是 `if agent._memory_manager`——不检查消息来源。但异步委托完成（`[ASYNC DELEGATION COMPLETE — …]`）、后台进程通知（`[IMPORTANT: Background process …]`）、watch pattern 命中、CLI→gateway handoff（`[Session was just handed off from CLI…]`）等**合成系统消息**会通过和真实用户消息相同的管道重新进入对话（gateway 的 `_inject_watch_notification` 构造 `MessageEvent(internal=True)` 走 `handle_message` → `run_conversation`；CLI 的 `drain_notifications` 塞进 `_pending_input` 同一队列），导致合成文本被原样当作用户意图喂给 recall——recall 相关性错误、浪费 provider 调用、`sync_all` 还会把合成消息当用户输入污染 memory 存储。
- **解决方案**：`owner/patches/memory_synthetic_guard_patch.py` 通过运行时 patch `MemoryManager` 的 4 个方法（`prefetch_all` / `queue_prefetch_all` / `on_turn_start` / `sync_all`），在入口处用前缀匹配拦截 4 类已知合成消息前缀（来自 `tools/process_registry.py::format_process_notification` 和 `gateway/run.py::_process_handoff` 的协议级稳定标记），命中则跳过 recall/sync/turn 通知。选择 patch `MemoryManager` 层（而非每个 provider）是因为它是所有 provider 的唯一 orchestrator，一次覆盖所有 provider 和所有路径（CLI/gateway/cron/TUI），无需改 `run_conversation` 官方签名。`gateway/run.py` 增加 4 行 apply glue（与 §11.6 OpenViking patch 同构），官方源码零行为改动。详见 `owner/docs/memory-synthetic-recall-guard.md`。
- **回归测试**：`tests/owner/patches/test_memory_synthetic_guard_patch.py`（25 用例：前缀检测全覆盖 + 4 方法各自 guard/透传 + apply/revert 幂等 + 还原 + 无 patch 基线无回归）。
- **相关 commit**：`826e62191`

---

## 十、显示与个性化

### 10.1 每会话显示覆盖
- **背景问题**：官方没有按 chat/session 覆盖显示配置的机制，所有会话共用同一套显示设置。
- **解决方案**：实现 per-chat display overrides，支持按 chat_id 覆盖显示配置；完善缓存失效、chat_id 提取 helper、slash command 接入等 glue。
- **相关 commit**：`3b07d0ab8`, `490b07219`, `cb7bc8417`, `d0f3e664f`, `2729c42a9`, `19ccd1917`

---

## 十一、Gateway 稳定性修复

### 11.1 QQ Bot WebSocket 重连链
- **背景问题**：WSL 睡眠唤醒后 QQ Bot WebSocket 出现僵尸连接，心跳失败也不重连。
- **解决方案**：
  - 连续 3 次心跳发送失败主动关闭 WS；
  - `_read_events()` 入口判断 `self._ws.closed`，避免关闭后继续读；
  - 每次重连前重建 `httpx.AsyncClient` 并清除 OAuth2 token 缓存；
  - `ws_connect()` 增加 `heartbeat=30` + `receive_timeout=120` 检测 TCP 假活。
- **相关 commit**：`0313593f2`

### 11.2 环境变量模板 base_url 泄露防护
- **背景问题**：gateway 消息模板中可能意外暴露含 env-var 的 base_url。
- **解决方案**：在模板渲染和文件提取路径中过滤/跳过环境变量占位，防止 API key 或内部 URL 泄露。
- **相关 commit**：`f8db9659b`, `01ad8b7b1`

### 11.3 API 静默断连提示
- **背景问题**：API 返回空响应时，用户无法区分是内容为空还是连接已静默断开。
- **解决方案**：检测 silent disconnect 场景，返回专门的提示文案。
- **相关 commit**：`f94fe4719`

### 11.4 `append_message` 语法错误修复
- **背景问题**：`run_agent.py` 中 `append_message` 内联 import 位置错误导致 SyntaxError。
- **解决方案**：移除错误位置的 inline import。
- **相关 commit**：`3863c1199`

### 11.5 ACP 适配器参数序列化
- **背景问题**：ACP 适配器在处理 `acp_args` 时，空列表被错误地存为 `None`，导致后续调用异常。
- **解决方案**：修正 `acp_args` 空列表的序列化行为，保持空列表不变。
- **相关 commit**：`23980e47d`

### 11.6 OpenViking 同步召回 + advisory 提示词
- **背景问题**：官方 `OpenVikingMemoryProvider.prefetch` 是异步预热（后台线程 + `_prefetch_result` 消费上一轮结果），导致 recall 串台（看到的是 T-1 的记忆）；`build_memory_context_block` 措辞是 "authoritative reference data … should inform all responses"，让 LLM 强行引用无关记忆。
- **解决方案**：`owner/patches/openviking_sync_recall_patch.py` 通过运行时 post-registration patch 替换 3 个方法——`prefetch` 同步 `POST /api/v1/search/find`（timeout 10s，httpx 异常全兜底）；`queue_prefetch` 替换为 noop（同步化后不再需要后台线程）；`build_memory_context_block` 改写为 advisory 融合版（"may help inform" + "only when relevant" + "helpful hints, not authoritative facts"）。Feature flag 保护：`OPENVIKING_SYNC_RECALL`（默认 1）/ `OPENVIKING_ADVISORY_MEMORY`（默认 1）/ `OPENVIKING_SEARCH_TIMEOUT`（默认 10），设置 0 即可秒级回滚。官方源码 0 改动；`gateway/run.py` 增加 9 行薄胶水（[owner] 注释 + try/import + 异常兜底），参照已有 `display_config` 委托模式。详见 `owner/docs/openviking-sync-recall-design.md`。
- **相关 commit**：`a4e6e2b95`（初始实现）, 本 commit（新增 Feishu/QQ 可视化召回卡片）
- **补充说明**：本 commit 在保留 provider 内 LLM 注入（`## OpenViking Context`）的前提下，通过新增 `owner/patches/openviking_recall_card_patch.py` 给 Feishu 发送 compact 召回卡片（schema 2.0，无展开/折叠按钮），给 QQ Bot 发送 markdown 纯文字摘要（`msg_type=0`），其他平台 no-op；后台 daemon thread 异步发送、token 模块级缓存、所有失败均 fail-silent 不影响 LLM。Feature flags：`OPENVIKING_RECALL_DISPLAY`（总开关，默认 1）、`OPENVIKING_RECALL_FEISHU_CARD`（默认 1）、`OPENVIKING_RECALL_QQBOT_TEXT`（默认 1）。详见 `owner/docs/openviking-recall-card-design.md`。

### 11.7 OpenViking Memory Provider 全面增强
- **背景问题**：官方 `OpenVikingMemoryProvider` 只实现了 Viking API 约 20% 的能力（50+ 端点用了 10 个，5 个 tool），存在多个问题：`viking_search` 用 `top_k` 而非 `limit`（API 拒绝额外字段）；`viking_remember` 走 `content/write` 旁路，embedding 异步不可靠，agent 验证搜索找不到结果；`on_session_switch()` 未实现导致 `/reset` `/new` 后 session 污染；`viking_read`/`viking_browse` 参数缺失（无分页、无递归、硬编码 cap）。
- **解决方案**：
  - **Bug fix**：`top_k` → `limit`（search + prefetch 两处）；新增 `context_type` 过滤参数；
  - **Remember 重构**：从 `content/write` 旁路改为 ephemeral session + commit + `system/wait` + DELETE cleanup，走 Viking 主管线，embedding 更可靠；
  - **Lifecycle hook**：实现 `on_session_switch()` — flush sync_thread、rotate session_id、clear prefetch（不 commit，core 已负责）；
  - **参数增强**：`viking_read` +offset/limit/raw；`viking_browse` +recursive/node_limit/level_limit；`viking_add_resource` 返回 task_id/queue_status；
  - **4 个新 tool**：`viking_delete`（DELETE /fs）、`viking_grep`（POST /search/grep）、`viking_move`（POST /fs/mv）、`viking_mkdir`（POST /fs/mkdir）；
  - `_VikingClient` 新增 `delete()` 方法；`handle_tool_call` 重构为 dispatch table；10 个新单元测试。
  - Tool schema 从 5 增至 9 个（plugin tool，非 core tool，token 成本可控）。
- **补充说明（remember 非阻塞）**：重构版 remember 的 `system/wait(15s)` + DELETE cleanup 原为同步执行，会阻塞 agent 工具线程最长 ~15s，而返回文案已声明"background processing finishes 后可搜索"——阻塞与文案矛盾。改为：commit 拿到 task_id 后立即返回，wait + cleanup 移入 daemon 线程（保留 wait→delete 顺序，避免过早删 ephemeral session 中断抽取）。
- **相关 commit**：`4177645d0`（初始实现）, 本次（remember 非阻塞化）
- **sync 复盘（2026-06-20，merge upstream b88d0007c）**：upstream 对 openviking 做了大规模重构（deferred commit 机制、`_inflight_writers`、`on_session_switch` 完整实现、`sync_turn` 批量写入），**部分覆盖了本节方案**：
  - `top_k`→`limit`：upstream 已修复，合并后对齐 ✅；
  - `context_type` 过滤、4 个新 tool（delete/grep/move/mkdir）：upstream 未实现，合并后完整保留 ✅；
  - `on_session_switch`：采用 upstream 完整版（含 rewind 处理、`_finalize_session_async`、prefetch invalidation），删除 owner 旧版（其依赖的 `_sync_thread` 已被 theirs 的 deferred commit 机制取代，保留会 AttributeError）；
  - **Remember 重构**：本节的 ephemeral session + `system/wait` 方案被 upstream 的 `content/write` + deferred commit 取代。合并后采用 upstream 实现。原方案解决"content/write embedding 不可靠"的初衷待重新评估——upstream 的 deferred commit 是否已用不同方式缓解该问题，需后续验证。**标记待评估**。

### 11.8 Progress dedup (×N) 计数破坏 markdown 代码块结构
- **背景问题**：飞书（及任何 `supports_code_blocks=True` 平台如 Slack）下连续调用 terminal 工具执行相同命令时，进度消息 dedup 逻辑会把 `(×N)` 计数内联追加到闭合 ``` fence 后（如 ` ``` (×3)`），CommonMark 不再识别为合法闭合 fence，代码块永不闭合，后续 terminal 进度行被吞入代码块或降级为纯文本。触发条件：terminal + supports_code_blocks + 连续 ≥3 次相同命令（第 1-2 次因 header 折叠使 msg 文本不同，第 3 次起触发 dedup）。
- **解决方案**：`gateway/run.py` 两处 dedup 拼接（主循环 + CancelledError drain 镜像）改为条件拼接 —— `base_msg` 以 ``` 结尾时用 `\n(×N)` 换行追加，否则保留内联 ` (×N)`。纯逻辑 bug，2 处单行改动 + `[owner]` 标记。
- **相关 commit**：本次

### 11.9 飞书编辑上限（230072/230075）轮转到新 bubble
- **背景问题**：飞书对单条消息有 ~20 次编辑上限（错误码 `230072` / `230075`）。gateway 进度循环把这类失败当作永久失败，`can_edit = False` 一刀切关闭，导致后续所有进度消息无法合并成一条已编辑消息，每个 terminal 进度都拆成独立 bubble。一度被误判为「⏳ Working」长时运行提示触发的并发问题 —— 实为时间相邻的巧合（~20 min 编辑次数累积 vs ~20 min 心跳首次触发），`_notify_long_running()` 是独立 task，从未触碰 `progress_msg_id` / `can_edit`。
- **解决方案**：引入平台无关的 `rotate` 语义契约（区别于既有 `retryable`）：
  - `gateway/platforms/base.py` `SendResult` 新增 `rotate: bool = False`，适配器在「此 bubble 已不可编辑、但可开新 bubble 继续」时返回 `rotate=True`。
  - `gateway/platforms/feishu.py` `edit_message` 在 post→text 降级 fallback **之后**识别错误码 `230072`/`230075`，置 `result.rotate = True`（编辑上限是 message_id 维度，降级无法绕过）。
  - `gateway/run.py` 进度循环在 `retryable` 之后、`flood`/`can_edit=False` 之前插入 `rotate` 分支：清空 `progress_msg_id`、用当前全量 `progress_lines` 发新消息开新 bubble、捕获新 message_id、保持 `can_edit=True`、`continue`。后续 edit 作用于新 bubble，再次触上限时链式轮转。
  - 错误码识别只发生在飞书适配器内，gateway 完全平台无关。
- **相关 commit**：本次

---

## 十二、Cron / 脚本 / 运维

### 12.1 owner/scripts 与个人脚本
- **背景问题**：个人定时脚本和运维脚本没有统一存放位置，cron scheduler 对 symlink 处理不友好。
- **解决方案**：建立 `owner/scripts/` 目录存放个人脚本；cron scheduler 对 owner/scripts 下的 symlink 豁免处理。
- **相关 commit**：`cc392905d`, `ea97e3f54`

### 12.2 备份与缓存清理
- **背景问题**：缺少自动备份 Hermes 配置和清理 macOS 缓存的脚本。
- **解决方案**：迁移 `backup-hermes-config.py`、`mac/cache-cleanup.py`、`daily-report.py`；`disk-watch-cron.py` 调用新的 cache-cleanup 脚本。
- **相关 commit**：`8145bef6f`, `62ed15ef4`, `73191a903`

### 12.3 Cron 任务参数支持
- **背景问题**：cron job 脚本无法接收参数。
- **解决方案**：为 cron job 增加 `args` 参数透传。
- **相关 commit**：`7284b1c83`

### 12.4 运维脚本迁移
- **背景问题**：`todo-scan.sh`、`inspect_gpu_cluster` 等脚本散落在旧分支。
- **解决方案**：迁移 `todo-scan.sh` 与 ack 脚本；launchd 重启改用 `launchctl kickstart -k` 保证原子生命周期。
- **相关 commit**：`f87240356`, `18cbfa7e7`, `44d7189c5`

---

## 十三、性能监控与归档

### 13.1 `hermes_mon` 性能监控
- **背景问题**：缺少对 Hermes 各进程资源占用的持续监控。
- **解决方案**：迁移 `hermes_mon` 性能监控脚本，修复 pgrep 精度与进程隔离问题。
- **相关 commit**：`c62b28866`, `9620e9386`

### 13.2 Session Archiver 插件
- **背景问题**：会话历史缺少自动归档机制，长期运行后 SQLite 膨胀。
- **解决方案**：新增 `session-archiver` 插件，定期归档旧会话。
- **相关 commit**：`45ab4a0f0`

---

## 十四、归因与计费

### 14.1 集中式模型归因
- **背景问题**：billing 记录和消息重建时各自计算 model/provider，容易不一致。
- **解决方案**：提取 `owner/attribution.py` 作为唯一归因来源；`build_assistant_message` 和 billing 记录统一调用。
- **相关 commit**：`a107cb99c`, `14d3f0453`, `16a9c77b5`

---

## 附录：废弃 / 暂不迁移项（了解边界）

以下旧 owner 分支的功能在 v16 中被明确废弃或推迟，故未出现在上文章节：

| 功能 | 决策 | 原因 |
|------|------|------|
| TF-IDF 技能过滤生态 | 推迟 | 代码尚未迁移到 owner-v16，需后续整体评估 |
| OpenViking 同步召回 + advisory 提示词 | 复活并加强 | 以 owner-only patch 形式重新引入，详见 § 11.6 |
| rate limiter 系统 | 推迟 | owner-v16 尚无该系统 |
| auditor-guard / audit-agent | 废弃 | 由 P66 Intent Guard 替代 |
| pricing.yaml / token_stats | 废弃 | 非 v16 核心能力 |
| `inline_code_ref` | 废弃 | 功能未进入 owner-v16 |



## 十五、Clarify 超时行为改造

### 15.1 超时后直接中断 Agent Loop
- **背景问题**：`clarify` 工具超时后，各平台 callback 把决策权交回 LLM（"Use your best judgement..."），导致在用户未响应时 LLM 可能继续执行不可逆操作。
- **解决方案**：
  - 在 `tools/clarify_tool.py` 定义 `ClarifyTimeout` 异常与统一 sentinel `__CLARIFY_TIMEOUT__`；callback 返回 sentinel 时抛异常，其它异常仍转 error JSON。
  - 在 `agent/tool_executor.py` 的 sequential clarify 分支和 `agent/agent_runtime_helpers.py` 的 `invoke_tool` 入口 catch `ClarifyTimeout`，调用 `agent.interrupt()`（**无 message**）并 append synthetic tool result。
  - 将决策逻辑集中到新增的 `owner/clarify/timeout_handler.py`；官方源码仅保留带 `[owner]` 注释的薄委托，删除 `owner/clarify/timeout_handler.py` 后仍有 inline fallback 可继续中断 agent。
  - 统一 `gateway/run.py`、`hermes_cli/callbacks.py`、`cli.py`、`tui_gateway/server.py` 的超时返回为 `CLARIFY_TIMEOUT_SENTINEL`。
  - `tools/clarify_gateway.py` 的 `clear_session` 改用独立 sentinel `__CLARIFY_SESSION_CLEARED__`，`gateway/run.py` 识别并区分处理。
- **补充说明（幻影轮修复）**：初版用 `agent.interrupt("clarify timed out")` 传了 message，而 `interrupt_message` 会被 gateway（`gateway/run.py` 的 `_CONTROL_INTERRUPT_MESSAGES` 未收录该串）与 CLI（`cli.py`）当作**下一轮用户输入**重新喂给 LLM —— 不但没停 agent，反而让模型对 "clarify timed out" 作答，比旧行为更糟。修复：`handle_clarify_timeout` 及两处 inline fallback 一律改为**无 message 的 `agent.interrupt()`**（仅置 `_interrupt_requested`，`interrupt_message` 保持 None，gateway/CLI 都不会生成幻影轮）。同时在 `gateway/run.py` 的 `_clarify_callback_sync` 超时分支补发一条用户提示（"未在 N 分钟内收到回复，已停止当前操作"），避免 agent 静默退出后用户侧无任何反馈；session-cleared 分支不发提示。
- **相关 commit**：`62aa54950`（初始实现）, 本次（幻影轮修复 + 超时用户提示）

---

## 十六、Sync upstream 复盘

### 16.1 sync fork — merge upstream/main b88d0007c（2026-06-20）
- **操作**：本地 `main` reset 到 `upstream/main`（纯跟踪），`origin/main` fast-forward 同步；`owner-v16` merge upstream 445 commits。
- **规模**：10 个冲突文件 / 22 个冲突块。绝大多数交集文件（56 个双方都改的）被 Git 自动三方合并——验证了"薄胶水 + `[owner]` 标记 + 运行时 patch"规范的有效性。
- **关键决策记录**：
  - **gateway/run.py（8 块）**：owner 的 message_receive hook 放在 upstream message_timestamps 处理**之后**（hook context 只富化 model 看到的 message_text，不污染 persist_user_message）；保留 owner 的 session_key ContextVar 修复（§4.5 Bug2，删除 upstream 的 `os.environ` 进程级写入）；扩展 upstream 的 `_resolve_gateway_display_bool` 增加 `source=` 参数以兼容 owner 的 per-chat display override。
  - **openviking（§11.7）**：接受 upstream 大规模重构（deferred commit）。见 §11.7 sync 复盘。**remember ephemeral 方案被取代，待评估**。
  - **clarify choice normalize**：保留 owner 的 `normalize_choices`（`{display, key}` dict，支持 Feishu 回传稳定 key）作为主路径，吸收 upstream `_flatten_choice` 作为共享 helper + legacy fallback（即使 owner/ 移除也不会泄漏 dict repr）。语义差异：owner 不丢弃 `{"name","value"}`-only dict（value 是认可的 body field），upstream 的 `_flatten_choice` 丢弃——两者都保证无 repr 泄漏。
  - **image_generation_tool（§3.3）**：owner 的 `model_from_args` 与 upstream 的 `image_url`/`reference_image_urls` 正交，融合为 `_dispatch_to_plugin_provider` 同时支持。
  - **createSlashHandler.ts（§6.1）**：采用 upstream 的 `handleDispatch` 重构，补回 chain type 处理（upstream 重构时遗漏）。
- **相关 commit**：`a2703ab86`（sync merge commit）

---

## 十七、遗漏项补充（2026-06-23 梳理）

> 本节补充 2026-06-22 及之前未在正文中逐条记录的功能代码改动。这些提交同样需要在 merge 官方代码时保留或重新评估。

### 17.1 飞书平台深度定制

- `97dd0d8b0` fix(auto_card): reserve footer size from split budget for final chunk (IN-05)
- `7b07cb11b` fix(feishu): correct _Entry.operations annotation to Optional[list] (IN-02)
- `2c5957a05` fix(gateway): rotate to fresh bubble on Feishu edit-limit instead of disabling edits
- `c5e986fcb` test(owner): add send_message sub-profile target auto-fill + extra_metadata tests
- `c7a655cd5` feat(owner): auto-fill feishu send_message target from session in sub-profiles [owner]
- `f2cf79806` feat(owner): resolve default feishu send target from session for sub-profiles
- `59da94339` chore(owner): add bot name comments and update whitelist in patch_feishu_profile.yaml
- `7f1d53fc4` chore(owner): add node010 bot routing config to patch_feishu_profile.yaml
- `fa6906ae3` chore(owner): update feishu profile config for routing test
- `2f10bdac7` refactor(feishu): migrate profile routing to inject_inbound transport
- `fa4f1505a` refactor(feishu): move api_key into profile_endpoints per-profile config
- `984cf648a` chore(profiles): add hermesxiyun profile runtime SOUL.md
- `8ea717389` feat(feishu): add hermesxiyun profile configuration template
- `f7a3554c6` feat(feishu): multi-bot routing support
- `8ced60ad9` feat(feishu): add send_only connection mode for multi-profile routing
- `2e692b449` fix(feishu): respect explicit platform disable in config.yaml
- `541c4bafe` feat(owner): add Feishu multi-profile routing with external containers
- `78578d368` fix(feishu): improve markdown table rendering by isolating tables into dedicated post rows
- `3afa0b303` refactor(owner): replace ~20-line auto_card block with delegation to owner/feishu/agent_end.py
- `7964f98bd` feat(owner): extract agent:end auto_card dispatch to owner/feishu/agent_end.py
- `da13b870f` feat(owner): add force param to try_auto_card for agent:end dispatch
- `0c4c5733d` fix(owner): patch.yaml 补充飞书 bot_menu_dedup 缺失的 ack 文案（对照 owner 分支完整配置）
- `46a6b6839` test(owner): 补全 card_sender resolver sender_open_id fallback、空 open_id 值、warning 带上下文日志测试（完成 auto-card DM follow-up #3）
- `b5f19b9b3` fix(官方模块): 向 try_auto_card 传递显式 chat_id（auto-card DM 路径 chat_id 退化修复配套）+ 规范文档示例对齐
- `938de6fde` fix(owner): auto-card 显式接收 chat_id 参数，消除对 adapter._chat_id 的退化依赖
- `9b2a6cc94` fix(官方模块): gateway/run.py _thread_metadata_for_target 支持 chat_type 单独存在（Feishu DM synthetic auto-card 必需）+ docstring 更新
- `b7255aad7` fix(owner): auto-card card_sender warning 日志补充定位上下文（B1 blocker）
- `94614b6e7` test(owner): 为 card_sender._resolve_receive_target 增加 None/空 metadata/缺 chat_type 边界测试（B2 blocker）
- `fa809e9ae` fix(owner): dedent bot_menu_dedup under existing feishu key
- `e24ec9bdd` fix(owner): restore bot_menu_dedup ack configs (lost in owner-v16 refactor)

### 17.2 Gateway 稳定性与进度编辑

- `066a0ec50` test(gateway): assert cross-room-blocked message content, not raw key substring
- `168038745` test(gateway): cover _loop_executor_unavailable + sentinel classification
- `b952d32ec` fix(gateway): proactively fast-fail _run_in_executor_with_context on dead loop
- `670e794e4` test(gateway): cover _is_executor_shutdown_error classifier
- `5de44619b` fix(gateway): treat executor-shutdown RuntimeError as restart, not agent error
- `883ca1acd` test(gateway): route rotate simulation through real _classify_edit_failure (WR-06)
- `bf59069dd` refactor(gateway): extract _classify_edit_failure for the progress-edit decision (WR-06)
- `4bf93c379` test(gateway): exercise production _append_dedup_counter, not a copy (WR-04)
- `a45f406e8` refactor(gateway): extract _append_dedup_counter helper, dedupe both sites (WR-05)
- `3d2846e10` fix(gateway): (×N) dedup counter breaks fenced code block on markdown platforms
- `c3a6500ec` fix(owner): gateway/run.py tool_progress_grouping 用回 resolve_display_setting_for_source
- `4a77d9510` fix(gateway): scrub session env on restart watcher
- `d6349869f` fix(gateway): use resolve_display_setting_for_source for busy ack detail

### 17.3 Clarify 超时与交互修复

- `958759cd0` fix(clarify): defend against premature-timeout race when entry vanishes during card send
- `c7bcb726c` test(owner): 更新 clarify choices 测试为 {display,key} 归一化格式
- `84f799bb6` fix(owner): 给 clarify_tool ClarifyTimeout/sentinel 补 [owner] 标记
- `da7dbb073` fix(owner): clarify 超时补发用户提示
- `94eefd86d` fix(owner): clarify timeout sequential 分支 fallback 对齐无 message interrupt
- `1bdce99a7` fix(owner): clarify timeout inline fallback 对齐无 message interrupt
- `f1ecdf1d3` fix(owner): clarify timeout 改用无 message interrupt 防幻影轮

### 17.4 Cron / 运维脚本

- `6f631d035` fix(owner): update_newapi_exchange_rate 内网域名 + review date 续期
- `54b72ec12` fix(gateway): scrub inherited HERMES_CRON_SESSION at process startup
- `43dcf2833` feat(owner/cron): add owner_cron_scrub_process_env for startup env scrub
- `b352980fa` fix(gateway): log instead of swallow owner.cron registration failure
- `f3c64c18e` feat(owner/cron): isolate HERMES_CRON_SESSION via ContextVar
- `4deb4fca3` feat(owner): add update_newapi_exchange_rate.py cron script
- `6557933cd` feat(scripts): add mac config backup scripts

### 17.5 Memory Proposal 批量审批与并发修复

- `36b5c27e5` test(memory): cover pre-approval rejection of incomplete batch ops (WR-07)
- `03de77ecc` fix(memory): reject structurally incomplete batch ops pre-approval (WR-07)
- `10a5ea2ce` feat(owner): memory_propose batch approval card + i18n
- `f983d9518` feat(owner): memory_propose batch schema + data path
- `34031dc4b` test(owner): memory_propose 并发回归测试 + 修正 4 处测试侧断言
- `4c1d2fe7d` fix(owner): bg-review memory auto-approve 改用隔离 key 消除同 session 串台

### 17.6 Unified Diff Patch 工具增强

- `68e5903a1` tools(file): temp enable official 'patch' alongside unified_diff_patch owner fork
- `0496f6e49` feat(owner): improve unified_diff_patch error messages (R4)
- `69b1caac0` fix(unified_diff_patch): skip _suggest_path probe on traversal paths (IN-04)
- `2d996bace` refactor(unified_diff_patch): hoist import os to module scope (IN-03)
- `b1706fe60` fix(unified_diff_patch): show resolved path + cwd + Did-you-mean on missing files
- `f7655f1ee` chore(owner): rename unified_diff_patch tool emoji 🩹 → 🧩

### 17.7 OpenViking 记忆召回增强

- `fd8db307e` fix(openviking): remember 改为非阻塞 — wait+cleanup 移入后台线程
- `9d8530b78` refactor(openviking-recall): move 6 OPENVIKING_* env vars to patch.yaml
- `f81f16b34` feat(openviking-recall): add Feishu card + QQ Bot text visualization for sync recall
- `76abc4ded` fix(openviking-sync-recall): replace top_k with limit in FindRequest
- `b6679bd4f` test(owner): add unit tests for openviking_sync_recall_patch

### 17.8 图像生成 / DashScope

- `f53d38b34` fix(image_gen): enforce reference-image cap + validate source URL scheme
- `6c7cbe6f0` fix(image_gen): reject non-http(s) schemes in save_url_image (WR-02 SSRF)
- `d89351d61` fix(image_gen): guard non-dict DashScope response elements to avoid AttributeError crash
- `d38f4c4a3` feat(owner): DashScope image editing support (image-to-image)
- `281085f28` fix(owner): DashScope image-gen plugin compat with v17 ABC interface

### 17.9 Skill 脚本自动审批

- `ec7573522` chore(owner): expand skill_script_allowlist with individual xy-* skills
- `66acc39fa` test(owner): add integration coverage for skill script bypass in check_all_command_guards
- `79b31f65e` fix(owner): skill_script_approval: update module header for accuracy and removability notes
- `15619c551` fix(官方模块): skill script auto-approval: wire bypass into check_all_command_guards (the live terminal guard)

### 17.10 工程/配置杂项

- `682b4f502` chore: ignore *.bak-YYYYMMDD editor/temp backup files
- `5d27ea00c` chore(owner): recover full owner-v16 development after git-filter-repo rewrite
- `1b4edfad5` chore: update package-lock.json
- `a435683af` chore: add Serena project configuration

### 17.11 Checkpoint Mutation Predictor

- `751e4b54b` feat(owner): document checkpoint predictor timeout + model routing
- `23461d762` test(owner): add e2e test for checkpoint predictor message isolation
- `b6f2d81b5` feat(owner): add checkpoints config + predictor docs

### 17.12 Read/Search 单执行超时保护

- `2e5d5a10a` test(agent): add unit tests for read_file/search_files single-execution timeout guards
- `e3afed52d` feat(agent): integrate single-execution timeout guard at _run_tool entry for read_file/search_files
- `b0502f299` feat(agent): add single-execution timeout protection for read_file/search_files in invoke_tool

### 17.13 Recall Card 可视化

- `6c99d5396` feat(recall-card): wire expand_recall/collapse_recall callbacks in _on_card_action_trigger
- `408f17709` feat(recall-card): add import bridge for hyphens-in-path hook directory
- `4beff2cfc` fix(recall-card): extract shared _extract_title and _sanitize_markdown_inline

### 17.14 i18n 补全

- `482868df7` fix(i18n): add the 17 missing gateway keys to zh.yaml
- `ef200216a` fix(i18n): add 17 missing gateway keys to en.yaml
- `b70109f93` refactor(i18n): route get_random_tip through agent.i18n.get_language()

### 17.15 Provider 名称归因修复

- `6a5317b85` fix(owner): owner_provider_name 改为 getattr 防 __new__ 构造对象 AttributeError
- `2e6ecd778` fix(delegate_tool): pass owner_provider_name to _build_child_agent

### 17.16 上下文压缩中文摘要

- `33c994231` feat(feishu): send context compression summary as plain interactive card
- `0e7f732d8` feat(compression): emit user-facing Chinese summary after context compression

### 17.17 Hook 体系薄胶水

- `0771db81e` refactor(owner): thin api_server.py hook glue per adversarial review

### 17.18 NewAPI Base URL 可覆盖

- `3b98ebe78` fix(owner): make NewAPI base URL env-overridable + plaintext-HTTP warning (WR-03, IN-01)

### 17.19 Owner 迁移/代码治理

- `436ec3775` fix(owner): add graceful degradation to _owner_import for removability

### 17.20 Patch 配置修复

- `f4437f5e8` fix(cli): correct import indentation for owner.tools.schema_patches

### 17.21 Qdrant 记忆召回

- `e3b50e206` feat(qdrant): add tenant_id isolation for multi-tenant knowledge base

### 17.22 TUI 修复

- `31709b9ed` fix(tui): mark slash command dispatch callback as async

### 17.23 模型选择器修复

- `dc7a2ff60` fix(model-picker): route confirm command through adapter loop instead of dead _running_runner

### 17.24 其他

- `296656b09` style(agent): format background review actions as multi-line bullets
- `5de861c10` fix(owner/scripts): harden newapi exchange-rate updater
- `5e9963e7b` fix(tests): update whatsapp send mock for new _send_to_platform signature
- `16f34c3ad` chore(owner): fix sync_git_hermes bot menu prompt to reference owner-v16
- `3fc04ba61` fix(owner): repair owner integration call sites (missing self/indent)
- `032dcbfe4` chore(owner): mark 0be2695 timestamp-pinning as deprecated

---

## 十八、owner-v17 更新

### 18.1 飞书 terminal 进度命令使用 bash 代码块
- **背景问题**：gateway 在渲染 terminal 工具进度时对所有 markdown 平台使用裸 ``` fence，因为 Slack mrkdwn 会把语言标签渲染成代码块首行字面文本；但飞书正确支持 ```bash 标签，缺失语言标签导致代码块缺少语法高亮提示。
- **解决方案**：在 `BasePlatformAdapter` 新增 `terminal_code_block_language` 能力属性（默认空串保持裸 fence），`FeishuAdapter` 覆盖为 `"bash"`；`gateway/run.py` 的 `progress_callback` 读取该属性，非空时生成 ```{language} 开头的 fenced code block。
- **相关 commit**：`343792ede`
