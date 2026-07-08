# Owner 分支改动清单

> 本文档是对 `owner` 分支 82 个 commit 的完整梳理，按功能模块组织，
> 区分「owner/ 纯新增模块」与「官方文件薄胶水侵入」，标注每个侵入点的类型，
> 作为后续上游同步、回滚定位、以及 hook/plugin 化迁移的参考地图。

## 元数据

| 项目 | 值 |
|------|-----|
| 分支 | `owner` |
| 基点 | `upstream/main` @ `f53ba9bb5`（`fix(s6): dot-prefix gateway staging dir`，2026-06-29） |
| Commit 数 | 31（基点后 owner 个人定制，无 merge commit） |
| 改动文件总数 | 172（去重后） |
| owner/ 纯新增 | ~75 个文件 |
| 官方文件侵入 | ~70 个文件（含 ~20 个测试文件） |
| 范围 | 模型归因 / patch.yaml 配置 / 审批安全 / 飞书深度定制 / TUI 皮肤 / Cron 运维 / Gateway 稳定性 / Checkpoint 预测 |
| 最后更新 | 2026-07-08 |
| 来源 | 从 `owner-v17`（500+ commit）清洗迁移而来；本分支是重新整理后的最小叠加版本 |

### 侵入类型图例

- **try-import / lazy import** — 官方文件用 `try: from owner.x import y` 或 `_owner_import(...)` 延迟加载，owner/ 缺失时降级。最干净、sync 冲突最小。
- **import 编排**（runtime patch）— 官方模块加载后，由 `owner/patches/*` 或 `owner/tools/schema_patches.py` 动态修改已注册对象（schema、常量、方法）。官方源码字面定义不变。
- **薄胶水 / 委托**（`[owner]` / `[owner-patch]` 标记）— 官方文件中 1~5 行 import + 委托调用，所有实现在 owner/。短标记 + 指向 owner/ 位置。
- **inline 逻辑** — 官方文件中直接嵌入的实现逻辑（非委托）。最重，sync 冲突最大，是后续 hook/plugin 化的重点候选。

---

## 一、基础设施：patch.yaml 配置系统与 owner_provider_name 归因

这一组是整个 owner 分支的地基，几乎所有其他模块都依赖它们。迁移顺序为：先建包 → 引入归因 → 引入配置加载器 → 模型级 extra_body → 审批白名单。

### 1.1 owner 包初始化 + 归因骨架

- **背景**：owner/ 需要作为独立包存在；每轮 API 调用需要知道真实自定义 provider 名（`owner_provider_name`），用于计费、审计、召回、多 profile 路由。这是其他所有模块的共同依赖。
- **方案**：
  - `owner/__init__.py`（空包）、`owner/attribution.py`（`get_current_attribution` + `inject_attribution_into_message`）、`owner/utils.py`（如 `normalize_bare_domain_base_url` 等工具）。
  - `AIAgent.__init__` 增加 `owner_provider_name` 参数 → 存为属性 → 透传到 `init_agent` → `append_message` → session DB（新增列）。
  - 官方代码在构造 assistant 消息持久化时调用 `inject_attribution_into_message(agent, msg)`，统一盖三个字段（model / provider / owner_provider_name）。
- **涉及文件**：
  - 纯新增：`owner/__init__.py`、`owner/attribution.py`、`owner/utils.py`
  - 侵入（薄胶水 + 列扩展）：`run_agent.py`、`agent/agent_init.py`、`agent/agent_runtime_helpers.py`、`agent/chat_completion_helpers.py`、`agent/codex_runtime.py`、`agent/conversation_loop.py`、`cli.py`、`gateway/run.py`、`hermes_cli/runtime_provider.py`、`hermes_state.py`
- **侵入类型**：薄胶水 + 委托（属性透传链），`hermes_state.py` 加 DB 列属 inline schema 扩展（不可避免）
- **Commit**：`a6dcd6ed8`（§2.1）、`6eba93f33`（patch: acp_args 空列表 → None，与归因无关但同属基础设施首批）

### 1.2 patch.yaml 统一加载器

- **背景**：owner 的所有行为配置（审批、飞书卡片、OpenViking、checkpoint 预测、extra_body、image_gen、display 覆盖等）原本散落在各模块各自实现 YAML 加载，重复且易错。
- **方案**：`owner/patch_config.py` 提供统一 fail-open 加载器，支持：
  - `~/.hermes/patch.yaml`（`owner:` 段）与 `~/.hermes/patch_feishu_profile.yaml`（顶层）
  - mtime 失效 + 60s TTL（防止网络挂载/外部编辑不更新 mtime 时的陈旧缓存）
  - `load_patch_config()` 作为官方代码的公开入口（替代各处私有的 `_load_patch_owner_config`）
  - 便捷访问器 `get_model_extra_body(owner_provider_name, model)`
- **配置文件**（实际在用，软链接到 `~/.hermes/`）：`owner/config/patch.yaml`、`owner/config/patch_feishu_profile.yaml`
- **侵入类型**：纯新增（加载器在 owner/），官方文件只是 import + 调用
- **Commit**：`f181c7cad`（§2.2）、`6154c7474`（§2.2/§17.9: 迁入完整 patch.yaml 配置内容）

### 1.3 模型级 extra_body 注入

- **背景**：需要在 chat_completions 传输层按 provider+model 注入 extra_body（如 xfyun/damodel 的 `enable_thinking`、glm-5/5.1 的 `thinking.type=enabled`），但不想污染全局 config。
- **方案**：`owner/extra_body_injection.py` 从 patch.yaml 的 `owner.model_extra_body` 读取配置，在 `agent/transports/chat_completions.py` 的请求构造处注入（provider profile 的 extra_body 之后、请求 override 之前）。`owner_provider_name` 作为查找 key，在 chat_completion_helpers 剥离时保留。
- **涉及文件**：
  - 纯新增：`owner/extra_body_injection.py`
  - 侵入：`agent/transports/chat_completions.py`、`agent/chat_completion_helpers.py`、`hermes_cli/oneshot.py`、`tools/delegate_tool.py`
- **侵入类型**：薄胶水（传输层插入一处注入调用）
- **WR-02 加固**：`54522c59b` — 对 `model_extra_body` 的 key 做 allowlist 过滤，防止注入任意 key。
- **Commit**：`6cb908115`（§2.3）、`54522c59b`（§11.x WR-02 allowlist）

### 1.4 审批命令白名单（patch.yaml 合并）

- **背景**：飞书「Always」永久审批按钮需要一组允许的命令白名单；官方 config.yaml 已有 `command_allowlist`，owner 需要叠加自己的允许列表。
- **方案**：`tools/approval.py` 在读取 allowlist 时合并 `owner.approvals.command_allowlist`（来自 patch.yaml）。配合 `allow_permanent` 开关控制是否显示永久按钮。
- **侵入类型**：薄胶水 + 委托（`tools/approval.py` 加 `[owner] approval: merge patch.yaml allowlist` 标记 + 调用 `owner.patch_config`）
- **Commit**：`5dd9580b4`（§2.4）

---

## 二、模型 Provider 与 API 适配

### 2.1 per-turn 归因 + credential 合并 + Layer 1/2/3 重构

- **背景**：`owner_provider_name` 需要贯穿整个 API 调用链；同时 owner 自定义 provider 的 credential 解析逻辑需要集中化（之前散落在 model_switch、chat_completion_helpers 等多处）。
- **方案**：将归因逻辑重构为三层：
  - Layer 1（agent 层）：`agent.owner_provider_name` 属性 + 归因注入
  - Layer 2（消息层）：`inject_attribution_into_message` 统一盖戳
  - Layer 3（持久层）：hermes_state 的 owner_provider_name 列
  - credential 合并：`hermes_cli/model_switch.py` 集中处理 owner provider 的 token 校验（GitHub token 过期检测等）
- **侵入类型**：薄胶水 + inline（model_switch.py 中的 token 校验属 inline 逻辑）
- **Commit**：`a887e62b0`（§3.8+§3.12）、`8b2ba9680`（§17.15: partial agent 上 guard owner_provider_name 防 AttributeError）

### 2.2 credential_helpers + 飞书模型选择器卡片

- **背景**：owner provider（如 GitHub Copilot）需要 token 有效性检测；飞书上需要一个交互卡片让用户切换模型/provider。
- **方案**：
  - `owner/providers/credential_helpers.py`：`has_valid_github_token`、`is_token_expired` 等，model_switch.py 薄调用。
  - `owner/feishu/model_picker.py`：`build_provider_card`、`handle_picker_action` — 飞书交互卡片（provider/model 列表 + 切换回调）。adapter.py 通过 `_owner_import` 委托。
- **涉及文件**：
  - 纯新增：`owner/providers/__init__.py`、`owner/providers/credential_helpers.py`、`owner/feishu/model_picker.py`
  - 侵入：`hermes_cli/model_switch.py`（薄调用 credential_helpers）、`plugins/platforms/feishu/adapter.py`（薄胶水 + `_owner_import`）
- **侵入类型**：薄胶水 + try-import
- **Commit**：`e0230f90a`（§3.4+§3.9）

> **⚠️ BUG 强调（2026-07-03）：credential pool env seeding 不校验 key 格式 — 跨 provider 污染**
>
> **根因**：`_seed_from_env()` 只检查 env var 存不存在（`has_usable_secret` = 长度≥4 + 非占位符），不看 key 格式。导致：
> - `GITHUB_TOKEN=ghp_*`（git 操作用的 classic PAT）被误采集到 copilot credential pool → `/providers` 显示 copilot 可用，但实际调 API 返回 403
> - `DASHSCOPE_API_KEY=sk-*`（百炼按量计费 key）被误采集到 alibaba-coding-plan pool → `/providers` 显示 coding-plan 可用，但 key 格式不对
>
> **修复**：
> 1. `ProviderConfig` 新增 `api_key_prefixes: tuple = ()` 字段（`hermes_cli/auth.py`）
> 2. `copilot` 配置 `api_key_prefixes=("gho_", "github_pat_", "ghu_")` — 排除 `ghp_` classic PAT
> 3. `alibaba-coding-plan` 配置 `api_key_prefixes=("sk-sp",)` — coding plan 专用前缀，排除标准 `sk-` 百炼 key
> 4. `_seed_from_env()` 在 suppress 检查后、upsert 前加前缀门控（`agent/credential_pool.py`）
> 5. `has_valid_env_credential()` 泛化旧 `has_valid_github_token`，支持按 provider 检查前缀（`owner/providers/credential_helpers.py`）
> 6. `_owner_check_env_creds()` 加 `provider` 参数透传（`hermes_cli/model_switch.py`）
>
> **设计原则**：`_seed_from_singletons` 已有 copilot token 校验（`validate_copilot_token` 拒绝 `ghp_`），但 `_seed_from_env` 没有 — 两个 seed path 的校验不对称是 bug 根源。`api_key_prefixes` 是通用机制，不只针对 copilot，任何 provider 都可以声明期望的 key 前缀。
>
> **涉及文件**：`hermes_cli/auth.py`、`agent/credential_pool.py`、`hermes_cli/model_switch.py`、`owner/providers/credential_helpers.py`
> **参考**：`skills/hermes/hermes-source-patching-pattern/references/credential-pool-seed-path-asymmetry.md`

> **⚠️ 注意要点（2026-07-03）：anthropic 无条件强制探测 + Layer 1 串行网络请求 + 共享 models.dev ID 的显示名退化**
>
> **问题 1 — anthropic 无条件探测**：
> `list_authenticated_providers()` 中有硬编码 `_cred_signal_slugs.add("anthropic")`，使 anthropic 绕过所有预筛，始终进入 Layer 2/3 候选。`_has_auth_creds` 会对 anthropic 专门调用 `read_claude_code_credentials()`，后者读 macOS Keychain `"Claude Code-credentials"` 条目——只要用户装过 Claude Code CLI 且 Keychain 里有 OAuth token，anthropic 就会被判定为有凭证，触发 `_fetch_anthropic_models()` 发 HTTPS 请求到 `api.anthropic.com/v1/models`（5s timeout），拖慢 `/providers` 命令。
>
> **修复**：注释掉该行。anthropic 仍可通过正常信号（env var、auth store、config.yaml provider）进入发现流程，只是不再被无条件强制探测。
>
> **问题 2 — Layer 1 串行 fetch_api_models**：
> Layer 1（config.yaml `providers:` 段）对每个 `should_probe=True` 的条目同步调用 `fetch_api_models()` 发 `/models` 请求。9 个 provider 串行跑，每个最多 5s timeout = 最坏 45s。
>
> **修复**：`should_probe` 改为 `not has_explicit_models`——config 里已列 `models:` 的 provider 直接信任配置，不再发网络请求。Layer 1 是 config-first 设计，本就应以配置为准。
>
> **问题 3 — 共享 models.dev ID 的显示名退化**：
> `kimi-coding` 和 `kimi-coding-cn` 在 `ALIASES` 中都映射到同一个 models.dev ID `kimi-for-coding`。Layer 2/3 用 `_mdev_pinfo(mdev_id).name` 取显示名，两个 slug 返回同一个 "Kimi For Coding"，无法区分。`get_label()` 虽有 `_LABEL_OVERRIDES` 但在 `normalize_provider()` 之后才查，override key `kimi-coding` 被 normalize 成 `kimi-for-coding` 后查不到。
>
> **修复**：(1) `_LABEL_OVERRIDES` 加 `kimi-coding` 和 `kimi-coding-cn` 条目；(2) `get_label()` 改为先查原始 slug 的 override，再 normalize；(3) Layer 2/3 的 `display_name` 从 `_mdev_pinfo(mdev_id).name` 改为 `get_label(hermes_id)`。
>
> **涉及文件**：`hermes_cli/model_switch.py`、`hermes_cli/providers.py`
> **Commit**：`47ff21f04`

### 2.3 运行时 schema patches + credential pool base_url override

- **背景**：`send_message` 卡片和 `image_generate` 的 model 参数需要扩展 schema，但不能改官方 toolsets 的字面定义（sync 冲突）。同时 credential pool 的 base_url 需要能被 model.base_url 覆盖（NewAPI 多 endpoint 场景）。
- **方案**：
  - `owner/tools/schema_patches.py`：模块加载后，在已注册的 tool schema 上 post-registration patch（运行时修改）。当前由 `owner-extensions` plugin 的 `register(ctx)` 统一 import/apply，不再占用 `gateway/run.py` 侵入点。
  - `owner/patches/pool_base_url_override.py`：`config_base_url_override()` — 当 model 配置了 base_url 时，覆盖 credential pool 的 base_url。`hermes_cli/runtime_provider.py` 两处薄胶水调用。
  - **env-var template 泄露防护**（§11.2）：`hermes_cli/runtime_provider.py` + `agent/model_metadata.py` + `tui_gateway/server.py` 三处 `[owner-patch] P29` 防止 `${VAR}` 模板字符串泄露到运行时。
- **涉及文件**：
  - 纯新增：`owner/tools/schema_patches.py`、`owner/patches/pool_base_url_override.py`
  - 侵入：`agent/credential_pool.py`、`hermes_cli/runtime_provider.py`（两处 `[owner-patch] P29` + base_url override 薄胶水）、`run_agent.py`、`agent/model_metadata.py`（`[owner-patch] P29`）、`tui_gateway/server.py`（`[owner-patch] P29`）
- **侵入类型**：import 编排（schema_patches 是 runtime patch）、薄胶水（P29 三处 + base_url override）
- **Commit**：`7f1a80ddb`（§3.10+§3.11）、`e78e53a71`（§11.2 P29 三处防泄露）、`de2295c0c`（补 schema_patches import 让 send_message card + image_generate model 参数生效）、`2c592b7ad`（upstream-native 检测）、`7b54ff5e8`（迁入 `owner-extensions` plugin）

### 2.4 reasoning 显示转义 + MiniMax thinking-block + i18n 硬编码翻译

- **背景**：(1) reasoning_content 中的特殊字符在 CLI/TUI 显示时需要转义；(2) MiniMax 的 Anthropic endpoint 需要支持 thinking-block 格式；(3) gateway 中有大量硬编码英文提示需要中文化。
- **方案**：
  - `agent/anthropic_adapter.py`：MiniMax thinking-block 解析支持（inline）
  - `gateway/run.py`、`gateway/slash_commands.py`：硬编码英文字符串改走 i18n（locales/）
  - 新增/补全 `locales/*.yaml`（zh、en、ja、ko 等全套）
  - `owner/tips_zh.py`：中文 tips 数据源（CLI tips 中文化）
- **侵入类型**：inline（anthropic_adapter thinking-block）+ 薄胶水（i18n 调用 + tips_zh）
- **Commit**：`8d4eb626d`

### 2.5 damodel prompt cache 白名单

- **背景**：`anthropic_prompt_cache_policy()` 按白名单决定是否注入 `cache_control` 标记。damodel（genai.damodel.com）走 OpenAI-wire 但不在任何分支里 → 返回 `(False, False)`，qwen3.6-27b 等 0% 缓存命中，每轮重算全量 prompt。
- **方案**：新增 damodel 分支：`provider=='damodel'` 或 base_url host 匹配 `genai.damodel.com` → `(True, False)` envelope layout（同 opencode/alibaba qwen 路径）。
- **侵入类型**：narrow if-else（agent_runtime_helpers.py，11 行新增）
- **Commit**：`f07fcb736`

---

## 三、审批、安全与风控

这是侵入最深的区域之一（`00-REVIEW.md` 标注多个 P0/P1 blocker，后续 CR-001~CR-006 已修）。

### 3.1 飞书审批卡片重构 + sender_name 缓存 + user_store

- **背景**：飞书审批卡片逻辑复杂（CallBackCard、按钮状态、resolved 更新、open_id→中文名缓存预热+TTL），原官方 adapter 内联了太多逻辑，sync 冲突严重。
- **方案**：按二次开发规范 §2.2「复杂交互/缓存的封装示例」重构：
  - `owner/feishu/approval.py`：`FeishuApprovalContext` 类（correlation 状态 + 卡片构建 + 回调处理）
  - `owner/feishu/sender_name_cache.py` + `owner/feishu/sender_name_helpers.py`：open_id→中文名缓存（pre-warm + TTL）
  - `owner/feishu/user_store.py` + `owner/feishu/user_cache.py`：`ChatIdCacheDebouncer` + 用户身份存储
  - 官方 `feishu/adapter.py` 只保留 `_approval_state` + 薄薄的 send_exec_approval / handler 委托 + pre_warm 调用 + build_xxx(data) + 短 `[owner] approval:` 标记
  - `locales/*.yaml` 增加审批相关 i18n
- **侵入类型**：薄胶水 + try-import（adapter 从 ~250 行审批逻辑压到 ~20-30 行委托）
- **Commit**：`fa6995bc9`（§4.2）、`4a4b13226`（补 [owner] 标记到 sender_name TTL 注释行）、`d7c487275`（fix tests: group_policy=allowlist 显式设置）

### 3.2 飞书 inbound context 用户身份注入

- **背景**：飞书消息进入时需要把用户身份（open_id/chat_id/user_name）注入到 agent context，用于审批签名、归因、多 profile 路由。
- **方案**：
  - `owner/gateway/inbound_context.py`：`append_inbound_context()` — 提取并注入用户身份
  - `gateway/run.py` 在消息接入处薄胶水调用
  - `owner/feishu/inbound_context.py`：飞书专用身份提取
- **侵入类型**：薄胶水（gateway/run.py 一处调用）
- **Commit**：`2f913a40d`（§4.4）

### 3.2a inbound context + cron prompt 注入 session_id

- **背景**：模型在每个 turn 需要看到当前 session 标识，用于 session_search 召回定位、跨平台会话追踪。gateway 飞书路径和 cron 路径各自独立注入，不碰 system prompt（避免破坏 prompt caching）。
- **方案**（两条路径独立实现）：
  - **Gateway 飞书**（参数透传）：`_prepare_inbound_message_text` 加 `session_id` 参数 → 透传 `append_inbound_context` → `build_feishu_inbound_context_block`，在现有 `[Inbound context]` 块尾部加 `session_id:` 行。两个调用点（主消息 + queued follow-up）都传 `session_entry.session_id`。
  - **Cron job**（prompt 追加）：在 `_cron_session_id` 生成后、`run_conversation` 调用前，往 prompt 追加 `[Cron context]` 块。
  - session_id 为运行时值，不写入 `SessionSource` dataclass，作为可选参数透传。
- **涉及文件**：
  - 侵入：`gateway/run.py`（签名 + 2 调用点 + 透传）、`cron/scheduler.py`（prompt 追加）
  - owner/：`owner/gateway/inbound_context.py`（3 函数加参数）、`owner/feishu/inbound_context.py`（输出 session_id 行）
- **侵入类型**：薄胶水（参数透传链 + prompt 追加）
- **Commit**：已合入（无独立 commit，散在 `2f913a40d`、`f9f3c39e5` 及 cron/scheduler 多提交中）
- **Commit**：待提交

### 3.3 多平台审批签名统一

- **背景**：不同平台（QQ、飞书、Discord）审批时传的 sender 身份字段不一致，导致审批记录无法关联到真实用户。
- **方案**：`gateway/run.py` 统一传 `sender_open_id`/`sender_is_bot`；QQ adapter 用 `**kwargs` 吸收额外字段；Discord adapter 用 `get_choice_display` 渲染 clarify 按钮。
- **侵入类型**：薄胶水（run.py 一处传参 + adapter **kwargs 吸收）
- **Commit**：`72e6b4be9`（§4.3 QQ 审批签名统一）

### 3.4 Guardrail 提示信息增强

- **背景**：tool guardrail（连续失败次数超阈值时 block/halt/warn）的消息太简略，用户不知道是哪个计数器、阈值多少、在哪改。
- **方案**：`agent/tool_guardrails.py` 的 warn/block/halt 消息增加计数器名、阈值、config.yaml 路径；warn 消息换 emoji（🐍→🛠️）。
- **侵入类型**：inline（消息字符串增强，逻辑不变）
- **Commit**：`2ad5aa2fb`（§4.7 block/halt）、`5e73d395f`（§4.8 warn + emoji）、`4661db389`（§4.8 验证 ChatIdCacheDebouncer 已存在，无代码变更）

### 3.5 Skill 脚本自动审批 + YOLO 模式

- **背景**：owner 的 xy-* 系列 skill 频繁执行脚本，每次都审批太烦；需要一个「当脚本来自本 session 已加载的 skill 时自动批准」的机制 + YOLO 开关。
- **方案**：
  - `owner/approval/skill_script_approval.py`：`is_skill_script_allowed()`（匹配逻辑：命令中所有脚本文件名都来自本 session 已加载 skill 时自动批准）+ `track_session_skill_view` / `reset_session_skills_viewed`（per-session 隔离）
  - `owner/cli/yolo.py`：YOLO on/off/status 命令实现
  - `tools/approval.py`：多处薄胶水调用 `is_skill_script_allowed`（约 3 处：主审批 + reset + cron helper）
  - `tools/skills_tool.py`：view skill 时 `track_session_skill_view`
  - 配置：`owner.approvals.skill_script_allowlist`（patch.yaml，列出哪些 skill 的脚本可自动审批）
  - **per-session 隔离**（CR-01）：每次会话清空已 view 的 skill 列表
  - **fail-closed on dangerous full command**（CR-02）：检测到完整危险命令时拒绝自动审批
  - **session boundary 清理**（WR-05）：会话边界时 reset
- **侵入类型**：薄胶水（tools/approval.py、tools/skills_tool.py 多处 import + 委托）+ 安全逻辑集中 owner/
- **Commit**：`82fe8c962`（§4.6）、`0d7c08d59`（§17.9 集成测试）、`d4484aee4`（§17.9 per-session 隔离 CR-01）、`cb1d01678`（§17.9 fail-closed CR-02）、`a07cf733f`（§17.9 session boundary WR-05）、`01f158e59`（§17.12.1 narrow owner/scripts/ cron exemption WR-03）

### 3.6 安全加固（CR 修复）

这是 `00-REVIEW.md` 发现的 6 个 critical blocker 的修复，全部在 2026-07-02 由 gsd-code-fixer 完成。

| CR | 问题 | 修复 | 文件 | Commit |
|----|------|------|------|--------|
| CR-001 | home-prefix fold 正则的 path-token 终止符缺 `\n`/`\r`，多行可绕过前缀检查 | `_PATH_TOKEN_STOP_TAIL` 加 `\n\r` | `tools/approval.py` | `99a374f64` |
| CR-002 | cron `owner/scripts/` 白名单只在首次使用时构建并冻结，运行时新增脚本不生效 | 改为 mtime-based re-scan + 文档化 cron-vs-terminal 不对称 | `tools/cronjob_tools.py` | `890869693` |
| CR-003 | `_auth_pool_refresh_counts` 在 per-turn prologue 初始化而非 `__init__`，delegated subagent 首次 401 触发 AttributeError | `init_agent` 中加 `agent._auth_pool_refresh_counts = {}` | `agent/agent_init.py` | `02a0c02b5` |
| CR-004 | `_GATEWAY_RAW_TEXT_PLATFORMS` 含 api_server/webhook/msgraph_webhook，扩大了 redaction 旁路 | 缩减为只含 `{"local"}` | `gateway/run.py` | `eb49d3b18` |
| CR-005 | MoA context 注入修改 user message body，破坏 prompt cache | 改为插入独立 user message（system prompt 之后） | `agent/conversation_loop.py` | `362304bc8` |
| CR-006 | skill-script 自动审批可被含 `;`/`&`/`|` 的复合命令绕过 | 加两个 quote-aware 安全门（unquoted compound operator + quoted metachar） | `owner/approval/skill_script_approval.py` | `010186818` |

- **报告**：`f4e82eba5`（docs(00): add code review fix report）、`f160dd359`（owner(§review): code review REPORT.md）

### 3.7 其他安全修复

- **SSRF 防护**（§17.8）：`1b0b3fce1` — `save_url_image` 拒绝非 http(s) scheme（WR-02）
- **Feishu user_name sanitize**（§17.16）：`f28061959` — 注入 user turn 前清洗 Feishu user_name（CR-03）

---

## 四、飞书平台深度定制

这是 owner 分支体量最大的功能区（~16 个 owner/feishu/ 模块 + adapter.py 64 处 owner 标记）。

### 4.1 飞书多 profile 路由

- **背景**：一个飞书 bot 需要把不同用户/群路由到不同 hermes profile（各自独立 HERMES_HOME、独立 model/API key），实现「一个 bot 入口，多 profile 后端」。
- **方案**（3 commit 拆分迁移）：
  - T1（纯新增模块）：`owner/feishu/profile_routing.py`（核心路由逻辑 + `try_route_card_action`）、`owner/feishu/default_target.py`（默认目标解析）、`owner/feishu/agent_end.py`（agent:end 钩子）、`owner/feishu/resume_card.py`（resume 卡片）
  - T2（adapter 接线）：`plugins/platforms/feishu/adapter.py` 核心接线 + `_owner_import` 路由调用
  - T3（api_server 端点 + config）：`gateway/platforms/api_server.py` 端点 + `send_only` config
  - 配置：`owner/config/patch_feishu_profile.yaml`（`feishu.bots.<bot_id>.user_routing.{whitelist,chat_profile_routes,user_profile_routes,default_profile,profile_endpoints}`）
- **侵入类型**：薄胶水 + try-import（adapter）、import 编排（profile_routing 全在 owner/）
- **涉及文件**：`a0636e1ef`（T1）、`4839cd605`（T2）、`c06de158c`（T3）、`f9a38e9f0`（§5.9 `_standalone_send` 支持 extra_metadata 保留 chat_type/open_id）

### 4.2 长文本自动卡片（auto-card）

- **背景**：飞书长文本回复体验差，需要超过阈值时自动转交互卡片（可展开/折叠），并预提取 MEDIA 标签。
- **方案**：
  - `owner/feishu/auto_card.py`：`try_auto_card()` — 阈值判断 + 卡片构建 + 异常安全退避（失败回退纯文本）
  - `owner/feishu/card_sender.py`：卡片发送封装
  - `plugins/platforms/feishu/adapter.py`：agent:end 时 `_owner_import("owner.feishu.auto_card", "try_auto_card")` 薄胶水
  - `gateway/run.py`：agent:end 时调用 `owner.feishu.agent_end.try_auto_card_on_end`
  - 配置：`owner.feishu_card.{auto_card_threshold, split_enabled, split_max_chars}`
- **侵入类型**：薄胶水 + try-import
- **Commit**：`aa70fd675`（§5.3）

### 4.3 输入中反应（early-typing）

- **背景**：用户发消息后 agent 思考期间飞书没有即时反馈，体验差。
- **方案**：飞书 adapter 在持有 `chat_lock` 时立即显示 Typing reaction（不等 API 响应）。
- **侵入类型**：薄胶水（adapter.py 一处）
- **Commit**：`ed20649ce`（§5.4）

### 4.4 Diff 卡片

- **背景**：agent 输出的 diff 在飞书纯文本里难读，需要交互式可展开/折叠/全屏卡片；QQ 上需要 markdown diff。
- **方案**：
  - `owner/diff_card/` 包：`dispatcher.py`（平台分发）、`feishu.py`（飞书交互卡片）、`qqbot.py`（QQ markdown）、`common.py`（共享逻辑）
  - adapter 通过 `_owner_import("owner.diff_card.feishu", "handle_feishu_diff_action")` 等委托
- **侵入类型**：薄胶水 + try-import
- **Commit**：`e927a6adf`（§5.5）

### 4.5 Clarify 交互卡片

- **背景**：clarify（向用户提问）在飞书上需要交互卡片（按钮选择），而非纯文本；choices 语义从 `List[str]` 归一化为 `List[{display, key}]`。
- **方案**：
  - `owner/clarify/choice_normalizer.py`：`normalize_choices()` — `List[str]` → `List[{display, key}]`
  - `owner/clarify/gateway_helpers.py`：`get_choice_display()` — 渲染 choice display
  - `owner/feishu/clarify_card.py`：`send_clarify` / `expire_clarify` / `handle_clarify_card_action`
  - `tools/clarify_tool.py` + `tools/clarify_gateway.py`：调用 `normalize_choices`（薄胶水，注释说明由 owner 归一化）
  - `plugins/platforms/feishu/adapter.py`：clarify 卡片发送/过期/回调委托
- **侵入类型**：薄胶水 + try-import（clarify_tool/gateway_helpers/adapter 多处）
- **Commit**：`e823335b3`（§5.6 clarify card migration）、`2f012fc31`（§5.6 test: 适配 choices 归一化语义）

### 4.6 Bot 菜单事件处理

- **背景**：飞书 bot 菜单点击事件需要映射到斜杠命令/提示词，并有 dedup + ack（慢命令时即时反馈）。
- **方案**：
  - `owner/feishu/bot_menu.py`：`handle_bot_menu_event()` + 3 秒 per-(open_id, event_key) dedup + ack
  - `plugins/platforms/feishu/adapter.py`：薄胶水调用
  - 配置：`owner.feishu.bot_menu.{key→command 映射}` + `owner.feishu.bot_menu_dedup.{enabled, default_ack, per_key}`
- **侵入类型**：薄胶水 + try-import
- **Commit**：`a8aab3b30`（§5.7）

### 4.7 飞书编辑上限轮转 + 进度 dedup

- **背景**：(1) 飞书消息编辑次数达上限（错误码 230072/230075）时需要轮转到新 progress bubble；(2) progress dedup 的 `×N` 计数器会污染 markdown 代码块（插在代码块中间）。
- **方案**：
  - `owner/feishu/`（编辑上限轮转逻辑）+ adapter 薄胶水
  - `gateway/platforms/base.py`：progress dedup 计数器改为只在代码块外插入
- **侵入类型**：inline（base.py 的 dedup 计数器逻辑）+ 薄胶水（adapter）
- **Commit**：`f6d0c6030`（§11.9 编辑上限轮转）、`2be0af638`（§11.8 progress dedup 避免污染 code fence）、`add176e9b`（§11.10 extract_local_files 跳过双反引号 inline code）

### 4.8 飞书 context-compression 中文摘要

- **背景**：上下文压缩时飞书需要显示中文摘要反馈。
- **方案**：`owner/feishu/compression_summary.py` + `owner/gateway/hygiene_compression_notice.py`（hygiene 压缩通知）+ gateway/run.py 薄胶水。
- **侵入类型**：薄胶水
- **Commit**：`d80705074`（§17.16）、`ed6667dd4`（fix: move Feishu summary after `_compressed_est` is assigned）

### 4.9 /providers 斜杠命令

- **背景**：需要在飞书上查看可用 provider/model 列表，用交互卡片展示（纯文本 fallback）。
- **方案**：`owner/commands/providers.py` + `gateway/run.py` 的 `canonical == "providers"` 分支 + 飞书卡片渲染。
- **侵入类型**：薄胶水（run.py 一处命令分发）
- **Commit**：`ed20e193d`（§9.1）

### 4.10 Memory write-approval 飞书交互卡片

- **背景**：memory 工具的  功能默认只返回 staged 文本提示，用户需要手动执行 `/memory approve` 或 `/memory reject`。在飞书上需要交互卡片（按钮点击）来提升体验。
- **方案**：
  - `owner/feishu/memory_approval.py`：卡片构建（紫色头部、✅ Approve / 🟥 Deny 按钮）+ 点击路由（合成 `/memory approve|reject <id>` 命令）+ card inline 更新（绿/红头部、按钮移除）+ `extract_feishu_chat_id` + `build_preview`
  - `owner/owner-extensions/memory_feishu_bridge/__init__.py`：plugin hook 注册（`pre_gateway_dispatch` 缓存 gateway/adapter + `post_tool_call` 检测 staged 结果 + 异步发送卡片）
  - `plugins/platforms/feishu/adapter.py`：4 行 `_dispatch_card_action` 分支（匹配 clarify/model_picker/resume 卡片模式）
  - `tests/owner/test_memory_approval_card_routing.py`：31 个测试
- **侵入类型**：薄胶水（adapter.py 4 行 card action 分支）+ plugin hook（零 upstream surface）
- **架构**：发送路径完全 out-of-tree（plugin hook + `card_sender.send_card_via_rest`）；点击路径 adapter 分支 -> `handle_card_click` -> 合成命令
- **合并说明**：原独立插件已合并入 `owner-extensions`，代码拆至 `memory_feishu_bridge/` 子目录
- **Commit**：`54dbc6320`（feat）、`9044b57d8`（merge into owner-extensions）、`49f52568f`（extract subdirectory）、`c8af97fe6`（move under `owner/` with symlink）
- **后续修复**：`5c2d2f092`（fix: forward `gateway_session_key` through hook chain，卡片不弹出）、`48fda1203`（fix: extract `operator.open_id` for auth）、`57c950e21`（fix: synthetic commands use empty `message_id` to avoid `reply_to`）、`8b76be146`（fix: remove backtick from card + i18n approve/reject responses）、`17072f048`（test: update assertions for i18n-driven labels）

### 4.11 /feishu-guide 对话引导交互卡片

- **背景**：飞书 bot menu 需要一个入口，让用户通过卡片选择并输入对话引导操作（`/queue`、`/steer`、`/goal`、`/subgoal`、`/background`），而不必记忆命令格式。
- **方案**：参照 `/providers`（plugin 命令注册 + 飞书卡片）+ clarify（form + input 输入框）+ model_picker（多步卡片 + 合成命令）三种现有机制组合：
  - `owner/feishu/steer_card.py`：两步交互卡片构建（5 按钮选择 -> form input 输入框 -> 提交/返回）+ 回调处理（`handle_guide_card_action` 按 `hermes_feishu_guide` step 分发：select/back/submit）+ 合成斜杠命令注入（`_route_guide_command` -> `MessageEvent(COMMAND)` -> `_handle_message_with_guards`）
  - `owner/commands/feishu_guide.py`：斜杠命令 handler（检测飞书平台 -> `adapter.send_guide_card()`；非飞书回退纯文本）
  - `owner/owner-extensions/__init__.py`：通过 `ctx.register_command("feishu-guide", ...)` 注册 plugin 斜杠命令
  - `plugins/platforms/feishu/adapter.py`：`_dispatch_card_action` 加 `hermes_feishu_guide` 路由（1 行 if）+ `send_guide_card` / `_handle_guide_card_action` 薄胶水方法 + `_guide_card_state` 字典
  - `gateway/run.py`：busy session 路径加 `/feishu-guide` plugin 命令拦截（与 `/providers` 同模式）
  - `owner/config/patch.yaml`：`bot_menu.feishu_guide: "/feishu-guide"` + `bot_menu_dedup.per_key.feishu_guide.ack`
- **侵入类型**：薄胶水（adapter.py card action 路由 1 行 if + 2 个薄胶水方法）+ plugin 命令注册（零核心源码改动）
- **Commit**：`46ac4fe73`
- **后续修复**：`0dbae9a40` — agent running 时点击 bot menu 触发 `/feishu-guide`，`should_bypass_active_session()` 只查 `resolve_command()`（仅含 `COMMAND_REGISTRY` 内置命令），plugin 命令不在其中，导致落入 busy-input 路径被当普通消息注入 agent。修复为同时检查 `is_gateway_known_command()`（覆盖 plugin 命令）。同 bug 影响 `/providers` 等所有 plugin 命令。

---

## 五、快捷命令与交互语法

### 5.1 链式快捷命令（;;分隔）

- **背景**：用户想在一个输入里串多个斜杠命令/提示，用 `;;` 分隔，全平台（CLI/Gateway/TUI/TS）支持。
- **方案**：在 4 个 Python 入口 + 3 个 TS 文件中增加 `;;` 分割 + 依次执行逻辑。
- **涉及文件**：`cli.py`、`gateway/platforms/base.py`（`[owner-patch] Chained quick commands`）、`gateway/run.py`、`tui_gateway/server.py`、`ui-tui/src/app/createSlashHandler.ts`、`ui-tui/src/gatewayTypes.ts`、`ui-tui/src/lib/rpc.ts`
- **侵入类型**：inline（4 处分割逻辑）+ TS inline
- **Commit**：`1d908072a`（§6.1）

### 5.2 Quick Alias 集中化

- **背景**：链式快捷命令的 `expand_chained_quick_alias` 逻辑在 4 个平台重复实现，需要集中到共享 helper。
- **方案**：抽取共享 `expand_chained_quick_alias` helper，4 个平台薄调用。
- **涉及文件**：`cli.py`、`gateway/platforms/base.py`、`gateway/run.py`、`tui_gateway/server.py`
- **侵入类型**：薄胶水（去重，集中到共享 helper）
- **Commit**：`31c4788ad`（§6.2）

---

## 六、TUI 与皮肤引擎

### 6.1 TUI skin engine 扩展

- **背景**：TUI 的 spinner/tagline/statusBar pipeline 需要可扩展；Mac 上 Cmd+C 复制 fallback；新增 ruolin 系列皮肤。
- **方案**：
  - TS 侧：`ui-tui/src/owner/{branding.ts, spinner.ts, statusBar.ts}`（owner 专属 TS 模块）、`ui-tui/src/theme.ts` 扩展、`createGatewayEventHandler.ts` / `createSlashHandler.ts` / `useInputHandlers.ts` / `appChrome.tsx` / `branding.tsx` 接线
  - Python 侧：`tui_gateway/server.py` 传递 skin 数据
  - YAML 皮肤：`owner/skins/ruolin.yaml`、`owner/skins/ruolin-light.yaml`、`owner/skins/README.md`
- **侵入类型**：inline（TS pipeline 扩展）+ 纯新增（owner TS 模块 + skin YAML）
- **Commit**：`4a7be0eef`（§7）、`e93f3148e`（§17.22 TUI async fix）

### 6.2 ruolin 皮肤更新 + redaction warning 移除

- **背景**：(1) `skin_engine.py` 自 2026-05-07 后新增了 6 个 color key（`selection_bg`、`voice_status_bg`、`completion_menu_bg/current_bg/meta_bg/meta_current_bg`），ruolin 系列皮肤缺失这些字段，补全菜单/选中/语音状态栏在樱花粉主题下的配色；(2) `ruolin-light.yaml` 丢失，从 skill reference `light-mode-skin-design.md` 恢复；(3) `security.redact_secrets: false` 时 CLI 和 Gateway 每次启动都打印 `⚠ Secret redaction is DISABLED` 警告，对有意关闭 redaction 的 owner 场景是噪音。
- **方案**：
  - `owner/skins/ruolin.yaml`：补 6 个新 color key（暗色配色：`selection_bg: #4A2845`、`completion_menu_bg: #1A0F1A` 等）
  - `owner/skins/ruolin-light.yaml`：从 reference 恢复完整亮色配色 + 补 6 个新 color key（亮色配色：`selection_bg: #FFD6E0`、`completion_menu_bg: #F8F0F5` 等）
  - `cli.py:13052`：删除 17 行 redaction disabled console 打印
  - `gateway/run.py:6535`：删除 22 行 redaction disabled logger.warning
- **侵入类型**：inline（删除启动警告代码）+ 纯新增（skin YAML 字段补全）
- **Commit**：`1731193cb`

---

## 七、Gateway 稳定性修复

### 7.1 QQ Bot WebSocket 重连链

- **背景**：QQ Bot 的 WebSocket 连接断线后重连不稳定（无 heartbeat/receive_timeout/stop_retry 机制）。
- **方案**：`gateway/platforms/qqbot/adapter.py` + `constants.py` 增加 heartbeat、receive_timeout、stop_retry、rebuild_http_client 重连链。
- **侵入类型**：inline（adapter 重连逻辑）
- **Commit**：`135c5a147`（§11.1）、`37f8a02f1`（fix: accept `is_reconnect` kwarg in `QQAdapter.connect()`）
- **Commit**：`135c5a147`（§11.1）

### 7.2 Memory synthetic guard（跳过合成系统消息的 recall/sync）

- **背景**：memory provider 的 recall/sync 不应该处理合成系统消息（如 MoA 注入的、压缩摘要等），否则会污染记忆。
- **方案**：
  - `owner/patches/memory_synthetic_guard_patch.py`：`apply_patch()` - 在 gateway/run.py 的 message-receive hook 处注入守卫，跳过合成系统消息
  - `gateway/run.py`：`# [owner] memory: skip recall/sync for synthetic system messages` + 薄胶水
  - `tests/owner/patches/test_memory_synthetic_guard_patch.py`
- **侵入类型**：import 编排（runtime patch）+ 薄胶水
- **Commit**：`a91689b08`（§9.3）
- **后续扩展**：`8a46ddea0` - 增加 `_is_non_recallable_command()` 拦截斜杠命令的 recall。所有 `/` 开头的消息默认跳过 `prefetch_all` / `queue_prefetch_all`，白名单 5 个对话引导命令（queue/steer/goal/subgoal/background）例外，因为它们携带用户输入的 prompt 值得召回。其余命令（status/model/providers/new/stop 等）是控制操作，无召回价值。

### 7.3 OpenViking 同步召回 + advisory + recall-card

- **背景**：OpenViking memory provider 需要同步召回（替代异步）+ advisory 提示词 + 召回结果可视化（飞书卡片/QQ 文本），并有线程池上限 + per-chat debounce。
- **方案**：
  - `owner/patches/openviking_owner_recall_patch.py`：`apply_patch()` — advisory 提示词、peer dedup、recall card 注入
  - `owner/patches/openviking_recall_config.py`：从 patch.yaml 读配置（`owner.openviking_sync_recall.*` / `owner.openviking_recall_card.*`）
  - `owner/owner-extensions/__init__.py`：plugin `register(ctx)` 中统一 apply（已从 `gateway/run.py` 顶层 try-import 迁出）
  - **WR-04**：`684de6981` — bound recall-card thread pool + per-chat debounce
- **侵入类型**：import 编排（runtime patch）+ 薄胶水
- **Commit**：`76fa75f36`（§11.6 精简迁移）、`684de6981`（§11.6 WR-04 bound thread pool + debounce）、`6a9e28b92`（迁入 `owner-extensions` plugin）

### 7.4 Cron env 隔离（ContextVar + restart scrub）

- **背景**：`HERMES_CRON_SESSION` 环境变量会从 cron 进程泄露到 gateway 的其他 session，导致非 cron 的 agent 误以为自己在 cron 上下文。
- **方案**：
  - `owner/cron/session_context.py`：用 ContextVar 隔离 `HERMES_CRON_SESSION`（而非环境变量）
  - `owner/cron/restart_scrub.py`：`owner_cron_scrub_process_env` / `owner_cron_scrub_watcher_env` — restart/startup 时清洗
  - `gateway/run.py`：3 处薄胶水（process env scrub + watcher env scrub × 2）
  - 多处接线：`cron/jobs.py`、`cron/scheduler.py`、`gateway/session_context.py` 等
- **侵入类型**：薄胶水（多处 import + 委托）
- **Commit**：`8eaf0cc10`（§17.4）、文档 `owner/docs/cron-session-env-leak-fix.md`

### 7.5 executor-shutdown 友好提示

- **背景**：gateway 的 loop executor 关闭时抛 RuntimeError，用户看不懂。
- **方案**：`gateway/run.py` 的 `[owner] §17.2` 把 RuntimeError 转成友好重启提示。
- **侵入类型**：inline（run.py 一处）
- **Commit**：`3c9ddba1d`（§17.2）

### 7.6 Clarify 清理路径返回 stop sentinel + 飞书 clarify 超时中断 agent

- **背景**：(1) clarify 清理路径需要返回 stop sentinel 而非继续；(2) 飞书 clarify 超时后需要中断 agent loop（不能继续等）。
- **方案**：
  - `tools/clarify_tool.py` + `owner/clarify/`：清理路径返回 stop sentinel
  - `plugins/platforms/feishu/adapter.py` + `owner/feishu/clarify_card.py`：超时中断 agent
  - **§17.3**：`4d1045fdd` — clarify 超时补发用户提示
- **侵入类型**：薄胶水 + inline（sentinel 逻辑）
- **Commit**：`e488cb348`（§15 stop sentinel）、`3de8ea088`（§15.1 飞书超时中断）、`4d1045fdd`（§17.3 超时补发提示）

### 7.7 _owner_import 不缓存瞬时 ImportError（WR-01）

- **背景**：`_owner_import` 缓存 None（owner/ 暂时不可用时），导致 owner/ 恢复后仍不重试。
- **方案**：改为首次 miss 告警 + 不缓存 None，下次调用重试。
- **侵入类型**：inline（helper 函数本身）
- **Commit**：`89ff61c4e`（§11.x WR-01）

### 7.8 补迁遗漏模块

- **背景**：从 owner-v17 迁移时遗漏了几个模块。
- **方案**：
  - `owner/api_error_hints.py`：API 错误提示增强
  - `owner/feishu/resume_card.py`：resume 卡片
  - `owner/gateway/hygiene_compression_notice.py`：hygiene 压缩通知
  - busy_drain i18n + tool_call_id 胶水
  - `agent/conversation_loop.py`、`gateway/run.py`、`gateway/slash_commands.py`、`plugins/platforms/feishu/adapter.py` 薄胶水接线
- **侵入类型**：薄胶水
- **Commit**：`9a05e50b4`

### 7.9 429 配额耗尽静默重试修复 + 长等待状态立即显示

- **背景**：部分 provider（如 opencode-go）对硬配额耗尽返回 HTTP 429（`GoUsageLimitError: Weekly usage limit reached. Resets in 2 days.`），但 `error_classifier.py` 的 429 处理路径不做 billing 检测，一律归类为 `rate_limit`（retryable=True）。同时 `conversation_loop.py` 对非 Z.AI 的 rate limit 重试用 `_buffer_status`（缓冲），用户在 600s × 3 次重试（30 分钟）内完全看不到任何提示。
- **方案**：
  - `agent/error_classifier.py`：429 handler 入口处加 billing/quota 检测（`[owner]` 标记）— 当 error_msg 含 "usage limit" 但无短时间窗口信号（minute/second/hour）且非 "rate limit" 时，归类为 `billing`（retryable=False），立即中止重试并显示错误
  - `agent/conversation_loop.py`：rate limit 状态显示逻辑加 `wait_time >= 60` 条件（`[owner]` 标记）— 长等待（≥60s）时用 `_emit_status` 立即显示，而非 `_buffer_status` 缓冲
- **侵入类型**：inline（两处各 ~10 行，`[owner]` 标记 + 委托已有分类逻辑）
- **文件**：`agent/error_classifier.py`、`agent/conversation_loop.py`
- **Commit**：`e81221af6`

### 7.10 Gateway 运行中 Agent 的插件命令隔离

- **背景**：当 agent 正在处理某条消息时，用户发送的斜杠命令会被当成普通文本注入 agent turn（busy-input 路径）。plugin 注册的命令（如 `/providers`）也不例外，导致命令被当作用户提示词的一部分而不是被网关分派执行。
- **方案**：`gateway/run.py` 的 catch-all running-agent guard 增加 `is_gateway_known_command()` 检查 —— 凡是 plugin 注册且被网关识别的命令，不再走 busy-input 注入路径，而是继续分派到命令 handler 执行。同时 `/providers` 加入 bypass whitelist（与 `/status` 同级），作为只读命令可安全 mid-turn 执行。
- **侵入类型**：inline（`gateway/run.py` 43 行，`[owner] §17.x` 标记）
- **Commit**：`71b5c9046`

### 7.11 允许 /memory 和 /skills mid-turn 执行

- **背景**：`/memory` 和 `/skills` 是只读/管理型斜杠命令，不应被 running-agent guard 拦截，但之前不在白名单中，导致 agent 运行时无法查看记忆或技能列表。
- **方案**：将 `/memory`、`/skills` 加入 `GATEWAY_KNOWN_COMMANDS`（`hermes_cli/commands.py`）并在 `gateway/run.py` 的 running-agent guard 中豁免。
- **侵入类型**：inline（commands.py 2 行 + run.py 8 行）
- **Commit**：`d1325fc7e`

---

---

## 八、Diff / Patch 工具链

### 8.1 Checkpoint Mutation Predictor（terminal 预测式快照）

- **背景**：`/rollback` 的盲区是 terminal 工具执行前没有预防性 checkpoint。需要在执行 terminal 命令前预测将要修改的文件，对其项目根做预防性 `ensure_checkpoint`。
- **方案**：
  - `owner/checkpoint_predictor/` 包：`predictor.py`（预测主逻辑）、`static_parser.py`（静态解析优先，提取命令中的文件路径）、`llm_predict.py`（静态失败时调 auxiliary LLM 兜底）、`config.py`（读 `owner.checkpoints.*`）
  - `agent/tool_executor.py`：terminal 执行前薄胶水触发预测
  - 行为：静态解析置信度 ≥ `predict_static_threshold` 直接用；否则 LLM 兜底（超时/失败/空时不降级拍 cwd，只报错提示无法回滚）；LLM 结果 LRU 缓存
  - 存储层/回滚层/`/rollback` 语义全复用 config.yaml 的 `checkpoints` 段
- **侵入类型**：薄胶水（tool_executor.py 一处触发）
- **Commit**：`6c41f5b63`（§17.11）、文档 `owner/docs/checkpoint-mutation-predictor.md`

### 8.2 read_file / search_files 单执行超时保护

- **背景**：read_file/search_files 读取超大文件或网络挂载时会无限阻塞。
- **方案**：
  - `owner/file_tool_timeout.py`：单执行超时守卫
  - `agent/tool_executor.py` + `agent/agent_runtime_helpers.py`：薄胶水接线
- **侵入类型**：薄胶水
- **Commit**：`8459eca7a`（§17.12）

---

## 九、显示与个性化

### 9.1 每会话显示覆盖（per-chat display overrides）

- **背景**：不同飞书群/会话需要不同的显示设置（tool_progress on/off、streaming、interim messages 等），不能全局一刀切。
- **方案**：
  - `owner/display_overrides.py`：`for_source(source)` 提取 chat_id + 查 patch.yaml 的 `owner.display.per_chat.<platform>.<chat_id>.*`
  - `gateway/run.py`、`gateway/display_config.py`、`gateway/slash_commands.py`：多处 `source=source` 透传 + `for_source` 薄调用（约 6+ 处）
- **侵入类型**：薄胶水（多处 `source=source` 透传 + `for_source` 调用）
- **Commit**：`eb96240a4`（§10）

---

## 十、归因与计费

### 10.1 集中式模型归因（billing records）

- **背景**：billing 记录需要用 owner_provider_name 做归因，而非直接读 agent 属性。
- **方案**：`agent/usage_pricing.py`（或相关 billing 模块）改用 owner/attribution helper。
- **侵入类型**：薄胶水（改用 helper）
- **Commit**：`ad8ea7fed`（§14.1）

### 10.2 逐消息 API token 明细落盘（per-message input/output/cache breakdown）

- **背景**：messages 表已有 `model`/`provider` 列（per-message），但 API 返回的 input/output/cache_read/cache_write token 明细只在 sessions 表做会话级累加（`update_token_counts`），不落盘到单条消息。无法做"第 N 次 API 调用花了多少 input token、命中多少 cache"粒度的分析。
- **方案**：参考 model/provider 的成功模式，4 步 additive patch：
  1. `hermes_state.py` SCHEMA_SQL messages 表加 4 列（`input_tokens`/`output_tokens`/`cache_read_tokens`/`cache_write_tokens`，均 `INTEGER DEFAULT 0`）— `_reconcile_columns` 启动时自动 `ALTER TABLE ADD COLUMN`
  2. `hermes_state.py` `append_message()` 签名加 4 个 `Optional[int]` 参数 + INSERT 语句同步
  3. `hermes_state.py` `_insert_message_rows()`（compact 重写路径）INSERT 同步加列
  4. `run_agent.py` `_flush_messages_to_session_db()` 从 `msg.get("input_tokens")` 等取值传入（仅 `role == "assistant"`）
  5. `agent/conversation_loop.py` 在 `update_token_counts` 调用后，将 `canonical_usage` 的 4 个字段 stamp 到最后一条 assistant message dict 上
- **侵入类型**：additive（SCHEMA_SQL 加列 + 签名尾部加参数 + INSERT 尾部加字段 + 1 处 stamp 赋值）
- **文件**：`hermes_state.py`、`run_agent.py`、`agent/conversation_loop.py`
- **兼容性**：旧消息新列默认 0；`append_message` 另两个调用方（`gateway/session.py`、`gateway/mirror.py`）不传新参数默认 None→0
- **Commit**：`43fddb615`（feat）、`e2a39ac68`（fix: stamp onto agent instance, not wrong message）

---

## 十一、Cron / 脚本 / 运维

### 11.1 owner/scripts 与 cron symlink 豁免

- **背景**：owner 的运维脚本（在 `owner/scripts/`）和 cron 用的 symlink 需要被 cron 工具路径校验豁免，否则 cron 无法执行它们。
- **方案**：
  - `tools/cronjob_tools.py`：`_get_owner_scripts_allowlist()` — 扫描 `owner/scripts/` 下脚本（**CR-002 后改为 mtime-based re-scan**，运行时新增脚本自动生效）
  - 豁免 cron symlink
  - `cron/scheduler.py`、`cron/jobs.py`：接线
  - 新增脚本：`owner/scripts/check_hermes_upstream.py`、`owner/scripts/cron-health-check.py`、`owner/scripts/todo-scan.py`
- **侵入类型**：inline（cronjob_tools.py 的 allowlist 逻辑）+ 薄胶水
- **Commit**：`8a8f42455`（§12.1）、`01f158e59`（§17.12.1 narrow to startup allowlist WR-03）、`890869693`（CR-002 mtime-based）

### 11.2 Cron job script args 参数支持

- **背景**：cron job 的 script 需要支持 CLI flags 参数。
- **方案**：`cron/jobs.py`（`# [owner-patch] cron job args support: normalize`）+ `cron/scheduler.py`（`# [owner-patch] map stored job args to CLI flags`）+ `tools/cronjob_tools.py`（`# [owner-patch] validate and normalize/store`）。
- **侵入类型**：薄胶水（`[owner-patch]` 标记的三处参数处理）
- **Commit**：`3163d17e8`（§12.3）

### 11.3 运维脚本迁移

- **背景**：owner 的运维脚本（备份、健康检查、todo 扫描、汇率更新）需要迁入 owner/scripts/。
- **方案**：纯新增脚本到 `owner/scripts/`：
  - `backup-hermes-config.py`（§12.5 SQLite-safe 备份）：`4ed22fa00`
  - `hermes-backup.sh` + mac 备份脚本（§17.4）：`dfccdf06e`
  - `update_newapi_exchange_rate.py`（§17.4 NewAPI 汇率更新 cron）：`003ed849e`
  - `todo-scan.py` / `todo-scan.sh`（§12.4 todo 扫描，含 timeout-safe 版本）：`0bed11194`、`56679f899`、`d7a06ca47`（drop 被上游覆盖的版本）
- **侵入类型**：纯新增（脚本文件）
- **Commit**：上述四个

### 11.4 HN Daily 新闻摘要脚本

- **背景**：每日抓取 Hacker News Top 20，生成中文一句话摘要，推送飞书群。原脚本硬编码，需要参数化以便复用。
- **方案**：纯新增 `owner/scripts/hn_daily.py`（438 行，含抓取、摘要、飞书卡片推送）。
- **重构**：`6ce327432` — 参数化 config（`config.json`）、分类模板（`categories.json`）、重试策略、输出格式（stdout / file / Feishu webhook）。
- **文件**：`owner/scripts/hn_daily.py`、`owner/scripts/hn_daily/README.md`、`owner/scripts/hn_daily/categories.json`、`owner/scripts/hn_daily/config.example.json`
- **侵入类型**：纯新增（脚本文件）
- **Commit**：`7d9cf95aa`（feat）、`6ce327432`（refactor: parameterize）

### 11.5 Skill 同步脚本

- **背景**：owner 的 skill 在 `westskill` 仓库维护，需要一套可移植、可测试的 diff/apply 脚本同步到各节点（如 `node010`）。
- **方案**：纯新增 `owner/scripts/skill_sync_*.py` + `tests/owner/test_skill_sync.py`：
  - `skill_sync_diff.py`：对比本地 skill 与远程仓库差异
  - `skill_sync_apply.py`：将差异应用到本地
  - `skill_sync_lib.py`：共享库（路径解析、过滤、备份）
- **侵入类型**：纯新增（脚本 + 测试）
- **Commit**：`f3a1b1fa4`

---

## 十二、代码治理与杂项

### 12.1 二次开发规范文档 + model_switch.py 标记

- **背景**：需要把 fork 的二次开发规范文档搬入 owner/docs/，并给 model_switch.py 补 `[owner]` 标记。
- **方案**：`owner/docs/二次开发规范.md` + `hermes_cli/model_switch.py` 标记。
- **Commit**：`e535ed29e`（docs(owner)）

### 12.2 i18n 补全 + tips 中文化 + TUI async fix + .gitignore

- **背景**：补全多个 locale 文件、tips 中文化、TUI async 修复、.gitignore 备份文件。
- **方案**：locales 全套补全 + `owner/tips_zh.py` + TUI fix + .gitignore。
- **Commit**：`e93f3148e`（§17.10/§17.14/§17.22）

### 12.3 background review actions 多行 bullet 格式

- **背景**：background review 的 actions 需要多行 bullet 格式。
- **方案**：`agent/background_review.py` 一处格式调整。
- **Commit**：`3c71db710`（§17.24）

---

## 附录 A：owner/ 目录模块索引

| 路径 | 职责 | 侵入官方文件 |
|------|------|--------------|
| `owner/__init__.py` | 空包 | — |
| `owner/patch_config.py` | patch.yaml 统一 fail-open 加载器（mtime+60s TTL） | tools/approval.py 等 import 调用 |
| `owner/attribution.py` | per-turn 归因（owner_provider_name 盖戳） | run_agent.py 等 10+ 文件透传 |
| `owner/utils.py` | 工具函数（normalize_bare_domain_base_url 等） | — |
| `owner/extra_body_injection.py` | 模型级 extra_body 注入 | agent/transports/chat_completions.py |
| `owner/api_error_hints.py` | API 错误提示增强 | conversation_loop.py / run.py |
| `owner/display_overrides.py` | per-chat 显示覆盖 | gateway/run.py 等 6+ 处 |
| `owner/file_tool_timeout.py` | read_file/search_files 超时守卫 | agent/tool_executor.py |
| `owner/tips_zh.py` | 中文 tips 数据源 | hermes_cli/tips.py |
| `owner/approval/skill_script_approval.py` | skill 脚本自动审批 + 安全门 | tools/approval.py / skills_tool.py |
| `owner/checkpoint_predictor/` | terminal 预测式 checkpoint（静态+LLM） | agent/tool_executor.py |
| `owner/clarify/` | clarify choice 归一化 + gateway helpers | tools/clarify_tool.py / clarify_gateway.py |
| `owner/cli/yolo.py` | YOLO on/off/status 命令 | — |
| `owner/commands/providers.py` | /providers plugin 斜杠命令实现 | owner-extensions plugin |
| `owner/cron/` | cron session 隔离 + restart scrub + run_job hook + approval helper | cron/* + gateway/run.py |
| `owner/diff_card/` | diff 卡片平台分发（飞书/QQ） | feishu/adapter.py |
| `owner/feishu/` | 飞书深度定制（16 模块） | feishu/adapter.py（64 处标记） |
| `owner/gateway/` | inbound_context + hygiene_compression_notice | gateway/run.py |
| `owner/patches/` | runtime patch（OpenViking recall + memory synthetic guard + pool base_url override） | owner-extensions plugin / hermes_cli/runtime_provider.py |
| `owner/providers/credential_helpers.py` | GitHub token 校验等 credential helper | hermes_cli/model_switch.py |
| `owner/scripts/` | 运维脚本（备份/健康检查/汇率/todo 扫描/**HN Daily 新闻摘要/skill 同步**） | — |
| `owner/skins/` | ruolin 系列皮肤 YAML | — |
| `owner/tools/schema_patches.py` | 运行时 schema patch（legacy send_message card + image_generate model） | owner-extensions plugin（import/apply） |

## 附录 B：官方文件侵入点速查（按侵入深度排序）

### 重度侵入（inline 逻辑为主，sync 冲突大，hook/plugin 化首选）

| 文件 | 侵入内容 | owner/ 对应模块 | 相关 commit |
|------|----------|-----------------|-------------|
| `gateway/run.py` | cron env scrub ×3、executor-shutdown、inbound context、hygiene notice、auto-card、per-chat display、chained quick command | owner/cron/、owner/gateway/、owner/feishu/、owner/display_overrides.py | 几乎所有 §11/§17 commit |
| `plugins/platforms/feishu/adapter.py` | 64 处 `[owner]` 标记：approval/auto_card/bot_menu/clarify/diff_card/model_picker/profile_routing/resume_card/sender_name/early-typing 委托 | owner/feishu/*（16 模块） | §4.2/§5.3-5.7/§17.1 |
| `agent/conversation_loop.py` | MoA 注入（CR-005 已改为独立 message）、content-filter fallback、adaptive backoff、thinking-timeout、attribution 重建、tool_call_id 胶水 | owner/attribution.py、owner/api_error_hints.py | a6dcd6ed8、9a05e50b4、362304bc8 |
| `tools/approval.py` | home-prefix fold（CR-001 修复）、skill script 自动审批（3 处委托）、patch.yaml allowlist 合并、cron active helper | owner/approval/、owner/patch_config.py、owner/cron/approval_helper.py | 82fe8c962、5dd9580b4、99a374f64 |
| `gateway/platforms/base.py` | per-profile cache roots、SendResult rotate/retry_after、chained quick command（`[owner-patch]`）、progress dedup code-fence 守卫 | — | 1d908072a、2be0af638 |
| `tools/cronjob_tools.py` | owner/scripts allowlist（mtime-based）、cron job args 三处 `[owner-patch]` | — | 8a8f42455、3163d17e8、890869693 |
| `cron/jobs.py` / `cron/scheduler.py` | cron job args `[owner-patch]` 参数 normalize + map | — | 3163d17e8 |

### 中度侵入（薄胶水 + 列扩展，sync 冲突中）

| 文件 | 侵入内容 | 侵入类型 |
|------|----------|----------|
| `run_agent.py` | owner_provider_name 参数+属性+透传、attribution 重建（`[owner-patch]`）、acp_args None 修复、schema patch import | 薄胶水 + 列扩展 |
| `agent/agent_init.py` | owner_provider_name 透传、acp_args 空列表→None（`[owner-patch]`）、owner_provider_name 保留（`[owner-patch]`）、`_auth_pool_refresh_counts` 初始化（CR-003） | 薄胶水 |
| `hermes_state.py` | sessions/messages 表加 owner_provider_name 列（INSERT/UPDATE/SELECT 全串联） | inline schema 扩展 |
| `agent/chat_completion_helpers.py` | owner_provider_name 剥离 + extra_body 注入点 | 薄胶水 |
| `agent/transports/chat_completions.py` | extra_body 注入 | 薄胶水 |
| `hermes_cli/runtime_provider.py` | pool base_url override ×2（`[owner-patch]`）、env-var template P29 防泄露（`[owner-patch]`） | 薄胶水 |
| `hermes_cli/model_switch.py` | credential_helpers 薄调用（GitHub token 校验） | 薄胶水 |
| `agent/model_metadata.py` | env-var template P29 防泄露（`[owner-patch]`） | 薄胶水 |
| `tui_gateway/server.py` | env-var template P29（`[owner-patch]`）、Cmd+C fallback、skin 数据传递 | 薄胶水 |
| `agent/tool_executor.py` | checkpoint predictor 触发、file tool timeout 接线 | 薄胶水 |
| `agent/tool_guardrails.py` | warn/block/halt 消息增强（计数器/阈值/路径） | inline（字符串） |
| `tools/clarify_tool.py` / `clarify_gateway.py` | normalize_choices 薄调用 + stop sentinel | 薄胶水 |
| `tools/skills_tool.py` | track_session_skill_view 薄调用 | 薄胶水 |
| `gateway/platforms/qqbot/adapter.py` + `constants.py` | WS 重连链（heartbeat/timeout/stop_retry/rebuild） | inline |

### 轻度侵入（import 编排 / 单行，sync 冲突小）

| 文件 | 侵入内容 | 侵入类型 |
|------|----------|----------|
| `agent/anthropic_adapter.py` | MiniMax thinking-block 解析 | inline |
| `agent/credential_pool.py` | base_url override 钩子 | 薄胶水 |
| `agent/agent_runtime_helpers.py` | `_auth_pool_refresh_counts` defensive getter + file timeout | 薄胶水 |
| `agent/codex_runtime.py` | owner_provider_name 透传 | 薄胶水 |
| `gateway/display_config.py` / `gateway/slash_commands.py` | per-chat display source 透传 + i18n | 薄胶水 |
| `gateway/session_context.py` | cron session 隔离接线 | 薄胶水 |
| `gateway/platforms/api_server.py` | `_owner_import` helper + 多 profile 路由端点 + send_only config | 薄胶水 + try-import |
| `plugins/platforms/discord/adapter.py` | clarify button `get_choice_display` | 薄胶水 |
| `plugins/platforms/telegram/adapter.py` | （sender 签名相关） | 薄胶水 |
| `cli.py` | owner_provider_name 透传 + chained quick command | 薄胶水 |
| `hermes_cli/oneshot.py` | extra_body 透传 | 薄胶水 |
| `agent/usage_pricing.py` | attribution helper for billing | 薄胶水 |
| `agent/background_review.py` | 多行 bullet 格式 | inline（字符串） |
| `tools/code_execution_tool.py` / `tools/delegate_tool.py` | extra_body 透传 | 薄胶水 |

### 附录 B 与附录 C 交叉覆盖标注

下表列出附录 B 中**未被附录 C 单独评估**的侵入文件，标注其是否被间接覆盖及迁移评估状态：

| 文件 | 侵入深度 | 附录 C 覆盖 | 迁移评估状态 |
|------|----------|-------------|-------------|
| `gateway/run.py` | 重度 | ✅ C#2（剩余薄胶水）+ C#7（per-chat display）| 已评估：保持现状 |
| `plugins/platforms/feishu/adapter.py` | 重度 | ✅ C#3 | 已评估：保持现状（薄胶水已规范）|
| `agent/conversation_loop.py` | 重度 | ❌ 未单项评估 | 间接覆盖：归因链归 C#1（保持现状）；MoA/content-filter/backoff 属 agent 内部逻辑，无独立 hook 可迁 |
| `tools/approval.py` | 重度 | ✅ C#4 | 已评估：保持现状（安全核心）|
| `gateway/platforms/base.py` | 重度 | 部分 C#2（chained quick command）| 间接覆盖：chained quick command 归 C#10（保持）；per-profile cache roots / progress dedup 是 1-3 行薄胶水，无迁移价值 |
| `tools/cronjob_tools.py` | 重度 | ✅ C#9 | 已评估：部分可迁移，维持现状 |
| `cron/jobs.py` / `cron/scheduler.py` | 重度 | ✅ C#9 | 已评估：同上 |
| `run_agent.py` | 中度 | 部分 C#1（归因链透传）| 间接覆盖：归因链归 C#1（保持）；acp_args None 修复是 1 行 bugfix；schema patch import 归 C#6（已迁 plugin）|
| `agent/agent_init.py` | 中度 | 部分 C#1（归因链）| 间接覆盖：归因链归 C#1；CR-003 修复是 1 行初始化；无迁移价值 |
| `hermes_state.py` | 中度 | 部分 C#1（DB 列）| 间接覆盖：C#1 已明确 DB 列不可避免 |
| `agent/chat_completion_helpers.py` | 中度 | ❌ 未单项评估 | 间接覆盖：归因剥离归 C#1；extra_body 注入归 §1.3（1 行薄胶水，无迁移价值）|
| `agent/transports/chat_completions.py` | 中度 | ❌ 未单项评估 | 间接覆盖：extra_body 注入归 §1.3（1 行薄胶水，无迁移价值）|
| `hermes_cli/runtime_provider.py` | 中度 | ❌ 未单项评估 | 未评估：P29 防泄露 ×3 + pool base_url override ×2 均为薄胶水；pool base_url override 已迁入 owner-extensions plugin（C#6 旁注），P29 防泄露是安全逻辑不宜 hook 化 |
| `hermes_cli/model_switch.py` | 中度 | ❌ 未单项评估 | 间接覆盖：credential 薄调用归 §2.2（1 行委托，无迁移价值）|
| `agent/model_metadata.py` | 中度 | ❌ 未单项评估 | 未评估：P29 防泄露 1 行薄胶水，同 runtime_provider.py，无迁移价值 |
| `tui_gateway/server.py` | 中度 | ❌ 未单项评估 | 未评估：P29 + Cmd+C + skin 数据传递均为 1-3 行薄胶水；TUI 侧无 plugin 体系，无法迁移 |
| `agent/tool_executor.py` | 中度 | ❌ 未单项评估 | 间接覆盖：checkpoint predictor 归 §8.1（1 行触发委托）；file tool timeout 归 §8.2（薄胶水）；均无迁移价值 |
| `agent/tool_guardrails.py` | 中度 | ❌ 未单项评估 | 未评估：warn/block/halt 消息增强是 inline 字符串，非逻辑变更，无迁移价值 |
| `tools/clarify_tool.py` / `clarify_gateway.py` | 中度 | ❌ 未单项评估 | 间接覆盖：归 §4.5 clarify 交互卡片（薄胶水 + try-import 已规范）|
| `tools/skills_tool.py` | 中度 | ❌ 未单项评估 | 间接覆盖：归 §3.5 skill 脚本自动审批（1 行 track 调用，无迁移价值）|
| `gateway/platforms/qqbot/adapter.py` | 中度 | ❌ 未单项评估 | 未评估：WS 重连链是 inline 逻辑，但属平台适配器内部实现，无 plugin hook 可迁；保持现状 |
| 轻度侵入全部（13 文件）| 轻度 | ❌ 未单项评估 | 无需评估：均为 1-3 行 import / 透传 / 字符串，迁移收益为零 |

**结论**：附录 B 列出的 ~35 个侵入文件中，附录 C 单独评估了 10 项主线；剩余文件要么被间接覆盖（归因链、extra_body、clarify 等已归入对应章节），要么是 1-3 行薄胶水 / 字符串 / 平台适配器内部逻辑，迁移收益为零，无需单独评估。**附录 B 无遗留未决项。**

---

## 附录 C：迁移与治理建议（面向未来 hook/plugin 化）

本附录是给后续工作的路线图参考，**非**当前分支承诺。

**治理原则**：所有迁移和 hook 化工作在 owner fork 内闭环完成，不考虑给 Hermes 官方提 PR。如果 Hermes core 缺少我们需要的扩展点（hook、ABC 方法等），在我们自己的 fork 里加，不等官方接受。上游同步时这些扩展点作为 owner diff 维护。

1. **owner_provider_name 归因链** — **已评估（2026-07-03）：不可迁移，保持现状。** 当前贯穿 10+ 官方文件的属性透传链是正确实现：(1) hook 时机无法覆盖所有消费点（传输层注入、billing 归因、recall 召回等多处需同步消费）；(2) `hermes_state.py` 的 DB 列扩展不可避免（`messages` 表无 JSON sponge 列，`sessions` 表可挪进 `model_config` JSON 但需改 6 个 row mapper，收益微薄）；(3) `inject_attribution_into_message` 在官方代码中只被调用 1 次（`chat_completion_helpers.py:1087`），已高度集中；(4) 归因链目前 0 直接测试覆盖，任何重构无回归网。发现的清理项：`run_agent.py:1731` 死代码（unused import）、`codex_runtime.py:209` vs `conversation_loop.py:2049` billing 归因口径不一致。评估报告：`/tmp/zcode-attribution-eval-result.md`（343 行，每条结论附行号引用）。
2. **gateway/run.py 剩余薄胶水** — **已评估（2026-07-03）：保持现状。** inbound context（`L9661-L9667`）、hygiene notice（`L10249-L10269`）、auto-card（`L10705-L10719`）、chained quick command（`L8660-L8692`）四项均位于 `discover_plugins()`（`L6142`）之后，但均需要访问函数局部状态或双向修改输入/输出；现有 plugin hook（`agent:start`、`agent:end`、`command:*`、`pre_llm_call` 等）均无法在不新增 hook 的情况下覆盖这些点。继续作为薄胶水委托给 `owner/` 模块，sync 冲突风险可控。评估报告：`/tmp/kimi-owner-eval-result.md`。
3. **plugins/platforms/feishu/adapter.py** — 64 处标记但大多是 1-3 行 `_owner_import` 委托，已是规范的薄胶水模式。保持现状即可；sync 冲突可通过 `_owner_import` 的 try-import 容错吸收。
4. **tools/approval.py** — home-prefix fold + skill script 自动审批是安全核心逻辑，建议保留在 owner/ 并继续薄胶水委托，不建议改成 hook（hook 时机不可靠）。
5. **patch.yaml 配置系统** — 已是干净的 owner/ 集中加载，官方文件只 import。无需迁移。
6. **runtime schema patches**（`owner/tools/schema_patches.py`）— 已迁入 `owner-extensions` plugin；验证依据：`model_tools.py` 先 `discover_builtin_tools()` 注册 schema dict 引用，再 `discover_plugins()`，plugin `register(ctx)` import 后可修改同一 dict；smoke test 已看到 `image_generate.model` 出现在工具 schema。
7. **per-chat display overrides**（`owner/display_overrides.py`）— 不迁 plugin。原因：它不是独立启动期 patch，而是各个 display 决策点必须传入当前 `source/chat_id` 后同步解析；已通过 `gateway.display_config.resolve_display_setting_for_source()` 集中 chat_id 提取，`gateway/run.py` 只保留必要调用点。进一步迁 plugin 需要新增 display hook 并改所有调用路径，收益低于现状。
8. **`/providers` command**（`owner/commands/providers.py`）— 已迁入 `owner-extensions` plugin command。Hermes plugin slash command API 已扩展 opt-in `hermes_ctx`（event/adapters/runner/platform），保留 Feishu interactive provider picker；`gateway/run.py` 的 `canonical == "providers"` 分支和 `gateway/slash_commands.py::_handle_providers_command()` shim 已删除。
9. **cron job args / owner/scripts allowlist** — **已评估（2026-07-03）：部分可迁移，人工决定维持现状。** args 链（4 处 `[owner-patch]`）可迁移但收益低（需 monkey-patch 3 个 core 函数：`cronjob`、`create_job`、`_run_job_script`，跨 tool 期/存储期/执行期 3 个生命周期；且 args 是通用功能更应提 upstream）；allowlist（2 处副本）不可迁移（cron 运行时零 hook——`invoke_hook` 在 scheduler/jobs 出现 0 次——加上安全边界 WR-03）。评估发现 CR-002 修复遗漏了 scheduler 副本 2（`scheduler.py:1556`，process-lifetime cache 永不刷新），已修复为 mtime re-scan 与副本 1 一致。评估报告：`/tmp/zcode-cron-args-eval-result.md`（291 行，每条结论附行号引用）。
10. **chained quick command（;;）** — 4 处 Python + 3 处 TS inline，是全平台语法增强，不适合 hook 化，建议保持。

---

## 附录 D：与旧清单（owner-v16/v17）的主要差异

本分支是从 owner-v17（500+ commit）清洗迁移而来，与旧清单（`/Users/yangtb/.hermes/hermes-agent/owner/docs/owner改动清单.md`）的主要差异：

- **已退役**：Mixture-of-Agents 去 OpenRouter 硬绑定（旧 §18.2，随上游迁移）、Qdrant 记忆召回（旧 §9.2/§17.21，被 OpenViking 取代）、Session Archiver 插件（旧 §13.2）、`hermes_mon` 性能监控（旧 §13.1）、memory_propose 批量提案（旧 §4.5/§17.5）、Copilot PAT 拒绝（旧 §4.1）、频道级系统提示 channel_prompts（旧 §5.1）。
- **已合并/重构**：飞书审批卡片（旧 §4.2 大段内联 → 现薄胶水 + owner/feishu/approval.py）、归因系统（旧 §3.8 分散 → 现 Layer 1/2/3 集中 + owner/attribution.py）、credential 逻辑（旧 §3.4 分散 → 现 owner/providers/credential_helpers.py）。
- **新增**：飞书多 profile 路由（§17.1，全新）、Checkpoint Mutation Predictor（§17.11，从旧 §8.2 精简迁移）、patch.yaml 统一加载器（§2.2，旧版散落）、skill 脚本自动审批（§4.6/§17.9，含 CR-001/CR-006 安全门）、CR-001~CR-006 代码审查修复（2026-07-02）。
- **保留并精简**：OpenViking（旧 §11.6/§11.7 → 现精简为 recall + advisory + recall-card）、auto-card / diff card / clarify card / bot menu / early-typing（旧 §5.3-5.7 → 现 owner/feishu/ 独立模块）。

_本清单基于 2026-07-02 的 owner 分支状态生成。后续 commit 请在对应章节追加并更新元数据表的「最后更新」日期。_

---

## 变更日志

### 2026-07-02：§9.3 Memory Synthetic Guard → owner-extensions plugin 迁移

- **类型**：首个 hook/plugin 化迁移试点（方案 C）
- **commit**：`63133c3f5`
- **变动**：`gateway/run.py` 删 8 行 try-import → `owner/owner-extensions/__init__.py` +29 行（plugin 骨架）
- **机制**：patch 通过 PluginManager `register(ctx)` 在 `discover_plugins()` 时 apply，早于任何 agent turn，无需挂 hook
- **验证**：25/25 测试全绿 + PluginManager 发现链路验证通过
- **治理原则确立**：所有 hook/plugin 工作在 owner fork 闭环，不考虑给官方提 PR

### 2026-07-02：OpenViking recall + runtime schema patches → owner-extensions plugin

- **类型**：第二/第三个 runtime patch plugin 化迁移
- **commit**：`6a9e28b92`（OpenViking recall），当前未提交改动（schema patches）
- **变动**：`gateway/run.py` 删 OpenViking 顶层 try-import + schema patch import；`owner/owner-extensions/__init__.py` 统一 apply `memory_synthetic_guard_patch` / `schema_patches` / `openviking_owner_recall_patch`
- **机制**：`model_tools.py` 先 `discover_builtin_tools()` 注册 tool schema dict 引用，再 `discover_plugins()`；schema patch 在 plugin register 阶段修改同一 dict，仍早于 `get_tool_definitions()` 暴露给模型
- **验证**：smoke test 看到 `image_generate` schema 包含 `model` 参数；`gateway/run.py` 不再含 `owner.tools.schema_patches` / `openviking_owner_recall_patch` 顶层 import

### 2026-07-02：附录 C 路线图审查 — §7.4 Cron env scrub 评估为不可迁移 plugin

- **类型**：plugin 迁移可行性评估
- **结论**：`gateway/run.py` 中 3 处 cron env scrub（L1270-1278 进程启动 scrub、L5604-5606/L5651-5653 watcher env scrub）**不能**迁入 owner-extensions plugin，保持现状
- **原因**：
  - L1270 是模块级代码，在 `discover_plugins()`（L6157）之前 ~4000 行执行，plugin register 时机太晚
  - L5604/L5653 操作 `schedule_restart()` 函数局部变量 `watcher_env`，plugin register 无法访问
- **风险评估**：低。3 处均为 `try-except` 包裹的薄胶水（~12 行），sync 冲突风险可控
- **下一步**：继续评估 `gateway/run.py` 剩余薄胶水：inbound context / hygiene notice / auto-card / chained quick command

### 2026-07-03：`/providers` → plugin slash command（带 hermes_ctx）

- **类型**：plugin command API 扩展 + owner command 迁移
- **commit**：`6dbaf6a74`（`/providers` → plugin slash command）
- **变动**：`hermes_cli/plugins.py` 增加 plugin command `accepts_ctx` 检测与 `make_plugin_command_context()`；`gateway/run.py` / `cli.py` 在 handler opt-in 时传 `hermes_ctx`；`owner-extensions` 注册 `/providers`；删除 `gateway/run.py` 内置 providers 分支与 `gateway/slash_commands.py` shim
- **机制**：旧插件 `fn(raw_args)` 调用形状不变；声明 `*, hermes_ctx` 或 `**kwargs` 的 plugin command 可拿到 gateway event/adapters/runner，保留 Feishu card 能力
- **验证**：`python3 -m pytest tests/hermes_cli/test_plugins.py tests/gateway/test_unknown_command.py tests/owner/test_providers_command.py -q -o 'addopts='` → 109 passed

### 2026-07-03：附录 C #1 owner_provider_name 归因链插件化可行性评估

- **类型**：plugin 迁移可行性评估（zcode 委托评估）
- **结论**：**不可迁移，保持现状**
- **核心发现**：
  1. **hook 时机无法覆盖所有消费点**：归因需在传输层注入（`chat_completions.py`）、billing 归因（`usage_pricing.py`）、recall 召回等多处同步消费，现有 hook（`on_session_start`/`pre_llm_call`）无法全部覆盖
  2. **当前属性透传链是正确的实现**：覆盖全部 3 条路径（gateway/subagent/cron）、cache-safe（`conversation_loop.py:838` 有 `pop()` 剥离，不进 LLM 请求体）、`inject_attribution_into_message` 在官方代码中只被调用 1 次（`chat_completion_helpers.py:1087`）已高度集中
  3. **DB 列不可避免**：`messages` 表无 JSON sponge 列；`sessions` 表可挪进 `model_config` JSON 但要改 6 个 row mapper，收益微薄
  4. **零测试覆盖**：归因链目前 0 直接测试，任何重构无回归网
- **发现的清理项**（不是迁移，是修 bug）：
  1. `run_agent.py:1731` 死代码（`from owner.attribution import get_current_attribution  # noqa: F401`，unused import）
  2. `codex_runtime.py:209`（静态 `getattr`）vs `conversation_loop.py:2049`（动态 `_get_current_attribution(agent)` wrapper）billing 归因口径不一致
- **评估报告**：`/tmp/zcode-attribution-eval-result.md`（343 行，每条结论附行号引用）

### 2026-07-03：附录 C #9 cron job args / owner/scripts allowlist 插件化可行性评估

- **类型**：plugin 迁移可行性评估（zcode 委托评估）
- **结论**：**部分可迁移，人工决定维持现状**
- **评估范围**：4 处 `[owner-patch]` args 链 + 2 处 allowlist 副本
- **核心发现**：
  1. **args 链（A1-A4）可迁移但收益低**：需 monkey-patch 3 个 core 函数（`cronjob`、`create_job`、`_run_job_script`），跨 tool 期/存储期/执行期 3 个生命周期；args 是通用功能更应提 upstream
  2. **allowlist 不可迁移**：cron 运行时零 hook（`invoke_hook` 在 scheduler/jobs 出现 0 次）+ 安全边界（WR-03）+ 两副本行为不一致
  3. **CR-002 遗漏**：副本 1（`cronjob_tools.py:540`）已改为 mtime re-scan，副本 2（`scheduler.py:1556`）仍是 process-lifetime cache 永不刷新——**已修复**
- **修复**：`cron/scheduler.py:1548-1576` 副本 2 改为 mtime re-scan，与副本 1 一致
- **评估报告**：`/tmp/zcode-cron-args-eval-result.md`（291 行，每条结论附行号引用）

### 2026-07-03：gateway/run.py 剩余薄胶水 plugin 迁移可行性评估

- **类型**：plugin 迁移可行性评估（kimi 委托评估）
- **结论**：**均不可迁移，保持现状**
- **评估范围**：
  - inbound context：`gateway/run.py:L9661-L9667`（`_prepare_inbound_message_text` 内，需修改入站文本）
  - hygiene notice：`gateway/run.py:L10249-L10269`（context compression 后，需压缩统计量）
  - auto-card：`gateway/run.py:L10705-L10719`（响应发送前，需双向修改 response/footer）
  - chained quick command：`gateway/run.py:L8660-L8692`（命令解析阶段，需递归分派）
- **核心原因**：四项均位于 `discover_plugins()`（`L6142`）之后（timing 可行），但均依赖函数局部状态或需要双向变形，现有 plugin hook（`agent:start`、`agent:end`、`command:*`、`pre_llm_call` 等）无法覆盖；迁入 plugin 需要在 `gateway/run.py` 新增 hook，侵入量不减反增
- **风险评估**：中（inbound context / hygiene notice / auto-card），低但改动风险高（chained quick command）
- **plugin 聚合评估**：已迁 plugin 的 4 项（memory synthetic guard、OpenViking recall、schema patches、`/providers`）暂不值得做统一抽象。只有 2 个是真 monkey-patch，`pool_base_url_override` 是 helper，`schema_patches` 是 import 自执行；为 2 个样本引入 `OwnerPatch` Protocol/registry 属于过早抽象，建议等 runtime patch ≥5 个再统一
- **评估报告**：`/tmp/kimi-owner-eval-result.md`（219 行）

### 2026-07-08：feishu_doc_read/drive tools 支持 DM 上下文 + wiki token 解析 + sheet/bitable 读取

- **类型**：bug fix + 功能增强
- **Commit**：`9246a191e`
- **背景**：`feishu_doc_read` 工具只在飞书文档评论事件触发时可用（`feishu_comment.py` 通过 `set_client()` 注入 lark client）。在 DM/群聊对话中 client 为 None，工具直接报错 `"Feishu client not available (not in a Feishu comment context)"`。此外只支持 docx `document_id`，无法解析 wiki node token，也不能读电子表格（sheet）和多维表格（bitable）。
- **方案**：
  - 新建 `tools/feishu_client_utils.py` 共享模块：fallback client（用 `FEISHU_APP_ID` + `FEISHU_APP_SECRET` 创建 tenant client，进程级缓存 + double-checked locking）、`do_request`、`extract_token`（从裸 token/URL 提取）、`resolve_wiki_node`（`/wiki/v2/spaces/get_node` 解析 obj_token + obj_type）、`read_bitable_as_text`（列 表 -> 分页读记录 -> 格式化纯文本，上限 50 表/500 记录）、`read_sheet_as_text`（v3 `/sheets/query` 列工作表 + v2 `/values/:range` 读数据，上限 500 行/50 列）
  - `tools/feishu_doc_tool.py`：`get_client()` 返回 None 时 fallback 到环境变量 client；handler 入口加 token 提取 + wiki 解析分支（docx -> raw_content；bitable -> read_bitable_as_text；sheet -> read_sheet_as_text）
  - `tools/feishu_drive_tool.py`：4 处 handler 同样加 fallback client；`_do_request` 移至共享模块（去重 ~45 行）
  - 评论上下文注入逻辑（`set_client`）完全不动，注入 client 优先于 fallback
- **涉及文件**：
  - 纯新增：`tools/feishu_client_utils.py`（350+ 行）、`tests/tools/test_feishu_client_utils.py`（19 个测试）
  - 侵入：`tools/feishu_doc_tool.py`、`tools/feishu_drive_tool.py`
- **侵入类型**：inline 逻辑修改（handler 内加 fallback 分支 + wiki/sheet/bitable 分支）
- **测试**：44 test passed, 0 failed（19 新增 + 5 feishu_tools + 20 feishu_comment）；`test_feishu.py` 8 failed 确认 pre-existing
- **E2E 验证**：DM 上下文读取真实飞书 wiki 电子表格（`https://skycloudsys.feishu.cn/wiki/CjhO...`），成功解析 wiki node -> sheet -> 5737 行数据
- **zcode 委托**：初始修复由 zcode-cli 完成（fallback client + wiki/bitable），sheet 读取由琳姐手动补充（API URI 修正：v3 `/sheets/query` 而非 `/spreadsheets/:token`）

### 2026-07-08：ruolin 皮肤更新 + redaction warning 移除

- **类型**：皮肤字段补全 + 启动噪音清除
- **Commit**：`1731193cb`
- **变动**：
  - `owner/skins/ruolin.yaml` + `owner/skins/ruolin-light.yaml`：补全 skin_engine 新增的 6 个 color key（`selection_bg`、`voice_status_bg`、`completion_menu_*`），ruolin-light 从 skill reference 恢复
  - `cli.py`：删除 17 行 `Secret redaction is DISABLED` console 打印
  - `gateway/run.py`：删除 22 行 `Secret redaction: DISABLED` logger.warning
- **验证**：`python -m py_compile` 两文件通过；`pytest -k "redact or secret"` 450 passed / 1 pre-existing failure（`test_empty_body_fallback_redacts_secrets`，stash 验证确认与本次改动无关）；`load_skin('ruolin')` / `load_skin('ruolin-light')` Python 加载验证 29 colors 全部就位
