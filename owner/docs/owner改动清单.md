# Owner 分支改动清单

> 本文档是对 `owner` 分支改动的完整梳理，按功能模块组织，
> 区分「owner/ 纯新增模块」与「官方文件薄胶水侵入」，标注每个侵入点的类型，
> 作为后续上游同步、回滚定位、以及 hook/plugin 化迁移的参考地图。

## 零、文档导航与元数据

这份文档按“先定位，再深挖”的方式维护：

1. **功能正文**（§1-§12）说明 owner 分支改了什么、为什么改、侵入了哪些官方文件。
2. **附录 A/B** 是 merge 后排查入口：先看 owner 模块索引，再看官方文件侵入点。
3. **附录 C** 记录 hook/plugin 化判断，避免每次 merge 后重复争论同一个迁移问题。
4. **附录 E** 只记录阶段性变更日志；新功能仍应先归入正文对应章节。

### 0.1 元数据

| 项目 | 值 |
|------|-----|
| 分支 | `owner` |
| 基点 | `upstream/main` @ `f53ba9bb5`（`fix(s6): dot-prefix gateway staging dir`，2026-06-29） |
| Commit 数 | 1573（基点后累计，含上游 merge commits + owner commits） |
| 改动文件总数 | 172（去重后） |
| owner/ 纯新增 | ~75 个文件 |
| 官方文件侵入 | ~70 个文件（含 ~20 个测试文件） |
| 范围 | 模型归因 / patch.yaml 配置 / 审批安全 / 飞书深度定制 / TUI 皮肤 / Cron 运维 / Gateway 稳定性 / Checkpoint 预测 / Desktop 窗口透明度 |
| 最后更新 | 2026-07-28 |
| 来源 | 从 `owner-v17`（500+ commit）清洗迁移而来；本分支是重新整理后的最小叠加版本 |

### 0.2 章节索引

| 阅读目标 | 对应章节 |
|----------|----------|
| 先判断某个 owner 能力属于哪里 | §1-§13 功能正文 |
| 看模型/provider/API 调用链 | §1、§2、§10 |
| 看审批、安全、自动审批、cron 上下文 | §3、§7.4、§11 |
| 看飞书平台定制 | §4 |
| 看 Desktop 桌面端改动 | §13 |
| 看 Gateway merge 后最容易丢的胶水 | §7、附录 B、附录 C |
| 看脚本、cron、运维能力 | §11 |
| 看 owner/ 模块到官方侵入点的映射 | 附录 A、附录 B |
| 看后续是否值得 hook/plugin 化 | 附录 C |
| 看最近阶段性变化 | 附录 E |

### 0.3 维护规则

- 新增 owner 能力：先放入 §1-§13 的功能正文，再补附录 A 的模块索引。
- 修改官方文件：同步更新正文的“涉及文件/侵入类型”，并补附录 B 的侵入点速查。
- 迁移到 hook/plugin：正文保留能力描述，附录 C 记录迁移结论，附录 E 追加阶段日志。
- merge 后验证项：能静态检查的放入 `owner/validation/`，再在正文或附录中标出对应 owner 能力。

### 0.4 侵入类型图例

- **try-import / lazy import** — 官方文件用 `try: from owner.x import y` 或 `_owner_import(...)` 延迟加载，owner/ 缺失时降级。最干净、sync 冲突最小。
- **import 编排**（runtime patch）— 官方模块加载后，由 `owner/patches/*` 或 `owner/tools/schema_patches.py` 动态修改已注册对象（schema、常量、方法）。官方源码字面定义不变。
- **薄胶水 / 委托**（`[owner]` / `[owner-patch]` 标记）— 官方文件中 1~5 行 import + 委托调用，所有实现在 owner/。短标记 + 指向 owner/ 位置。
- **inline 逻辑** — 官方文件中直接嵌入的实现逻辑（非委托）。最重，sync 冲突最大，是后续 hook/plugin 化的重点候选。

---

## 一、核心基础设施：patch.yaml 配置系统与归因链

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

## 二、模型 Provider / API / 请求适配

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

#### 2.2.1 已修复：credential pool env seeding 不校验 key 格式

- **问题**：`_seed_from_env()` 只检查 env var 存不存在（`has_usable_secret` = 长度≥4 + 非占位符），不看 key 格式。导致：
  - `GITHUB_TOKEN=ghp_*`（git 操作用的 classic PAT）被误采集到 copilot credential pool → `/providers` 显示 copilot 可用，但实际调 API 返回 403
  - `DASHSCOPE_API_KEY=sk-*`（百炼按量计费 key）被误采集到 alibaba-coding-plan pool → `/providers` 显示 coding-plan 可用，但 key 格式不对
- **修复**：
  1. `ProviderConfig` 新增 `api_key_prefixes: tuple = ()` 字段（`hermes_cli/auth.py`）
  2. `copilot` 配置 `api_key_prefixes=("gho_", "github_pat_", "ghu_")` — 排除 `ghp_` classic PAT
  3. `alibaba-coding-plan` 配置 `api_key_prefixes=("sk-sp",)` — coding plan 专用前缀，排除标准 `sk-` 百炼 key
  4. `_seed_from_env()` 在 suppress 检查后、upsert 前加前缀门控（`agent/credential_pool.py`）
  5. `has_valid_env_credential()` 泛化旧 `has_valid_github_token`，支持按 provider 检查前缀（`owner/providers/credential_helpers.py`）
  6. `_owner_check_env_creds()` 加 `provider` 参数透传（`hermes_cli/model_switch.py`）
- **设计原则**：`_seed_from_singletons` 已有 copilot token 校验（`validate_copilot_token` 拒绝 `ghp_`），但 `_seed_from_env` 没有 — 两个 seed path 的校验不对称是 bug 根源。`api_key_prefixes` 是通用机制，不只针对 copilot，任何 provider 都可以声明期望的 key 前缀。
- **涉及文件**：`hermes_cli/auth.py`、`agent/credential_pool.py`、`hermes_cli/model_switch.py`、`owner/providers/credential_helpers.py`
- **参考**：`skills/hermes/hermes-source-patching-pattern/references/credential-pool-seed-path-asymmetry.md`

#### 2.2.2 已修复：provider discovery 慢探测与显示名退化

- **问题 1 — anthropic 无条件探测**：`list_authenticated_providers()` 中有硬编码 `_cred_signal_slugs.add("anthropic")`，使 anthropic 绕过所有预筛，始终进入 Layer 2/3 候选。`_has_auth_creds` 会对 anthropic 专门调用 `read_claude_code_credentials()`，后者读 macOS Keychain `"Claude Code-credentials"` 条目；只要用户装过 Claude Code CLI 且 Keychain 里有 OAuth token，anthropic 就会被判定为有凭证，触发 `_fetch_anthropic_models()` 发 HTTPS 请求到 `api.anthropic.com/v1/models`（5s timeout），拖慢 `/providers` 命令。
- **修复 1**：注释掉该行。anthropic 仍可通过正常信号（env var、auth store、config.yaml provider）进入发现流程，只是不再被无条件强制探测。
- **问题 2 — Layer 1 串行 fetch_api_models**：Layer 1（config.yaml `providers:` 段）对每个 `should_probe=True` 的条目同步调用 `fetch_api_models()` 发 `/models` 请求。9 个 provider 串行跑，每个最多 5s timeout = 最坏 45s。
- **修复 2**：`should_probe` 改为 `not has_explicit_models`；config 里已列 `models:` 的 provider 直接信任配置，不再发网络请求。Layer 1 是 config-first 设计，本就应以配置为准。
- **问题 3 — 共享 models.dev ID 的显示名退化**：`kimi-coding` 和 `kimi-coding-cn` 在 `ALIASES` 中都映射到同一个 models.dev ID `kimi-for-coding`。Layer 2/3 用 `_mdev_pinfo(mdev_id).name` 取显示名，两个 slug 返回同一个 "Kimi For Coding"，无法区分。`get_label()` 虽有 `_LABEL_OVERRIDES` 但在 `normalize_provider()` 之后才查，override key `kimi-coding` 被 normalize 成 `kimi-for-coding` 后查不到。
- **修复 3**：`_LABEL_OVERRIDES` 加 `kimi-coding` 和 `kimi-coding-cn` 条目；`get_label()` 改为先查原始 slug 的 override，再 normalize；Layer 2/3 的 `display_name` 从 `_mdev_pinfo(mdev_id).name` 改为 `get_label(hermes_id)`。
- **涉及文件**：`hermes_cli/model_switch.py`、`hermes_cli/providers.py`
- **Commit**：`47ff21f04`

#### 2.2.3 已修复：env-only providers 纳入显示列表

- **问题**：仅有环境变量凭证的 provider（无 config.yaml `providers:` 段配置）不出现在 `/providers` 显示列表中，用户不知道这些 provider 可用。
- **修复**：`hermes_cli/model_switch.py` 在构建 provider 显示列表时，将 env-only providers 与 configured rows 合并。
- **涉及文件**：`hermes_cli/model_switch.py`
- **Commit**：`83576b22c`

#### 2.2.4 已修复：飞书 model_picker 卡片 stale session 卡 loading

- **问题**：飞书 model_picker 卡片在 stale session / unknown step 下返回空响应，导致飞书客户端卡在 loading 态；同时 Feishu SDK 版本差异使 `action_value` 有 JSON-string 和 dict 两种形态，dispatch 路径未处理 string 形态，`isinstance(action_value, dict)` 全部跳过，表单提交表现为「卡住」。
- **修复**：
  - `440d5b023` — `owner/feishu/model_picker.py` 在 stale session / unknown step 下改为返回 `CallBackToast` 提示；归一化 `action_value` 的 JSON-string→dict 两种形态；dispatch 包 try/except 防止静默失败。涉及 `owner/feishu/model_picker.py`（+142/-47）+ `plugins/platforms/feishu/adapter.py`（+39）。
  - `5251db809` — `adapter.py` card action handler 中 `_normalise_card_action_value` 调用漏传 `self`（调成了模块函数而非方法），导致 form 提交的 `action_value` 未被归一化、下游 `isinstance(action_value, dict)` 全部跳过、卡片表现为「卡住」。1 行修复：`_normalise_card_action_value(...)` → `self._normalise_card_action_value(...)`。
- **涉及文件**：`owner/feishu/model_picker.py`、`plugins/platforms/feishu/adapter.py`

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

### 2.5 iteration budget 耗尽提示 i18n

- **背景**：`agent/conversation_loop.py` 和 `agent/turn_finalizer.py` 中 iteration budget 耗尽提示是硬编码英文，需要中文化并支持多 locale。
- **方案**：硬编码字符串改走 `_t("iteration.budget_exhausted")` / `_t("iteration.budget_exhausted_summary")`；`locales/en.yaml`、`locales/zh.yaml` 新增对应 key。代码默认 `max_turns` 保持 90；用户若需 120 在 `~/.hermes/config.yaml` 的 `agent.max_turns` 覆盖。
- **侵入类型**：inline（字符串替换为 i18n 调用）
- **Commit**：`45598ce6a`

### 2.6 Qwen thinking debris 清理

- **背景**：上游 merge 后 OpenCode Go 上所有 `qwen*` 模型走 `anthropic_messages` 模式，`qwen3.7-plus` 启用 thinking 后 visible content 开头经常残留孤立反引号（有时后接 CJK 标点/空白）。`_strip_think_blocks` 只剥 `<think>` 标签，残留反引号进入 state.db 后，gateway 把 reasoning 用 code block 拼到响应前面，导致飞书等消息平台 markdown 渲染错位，出现“截断 thinking”外观。
- **方案**：`agent/chat_completion_helpers.py` 新增 `_clean_leading_thinking_debris()`，在 `_strip_think_blocks(...).strip()` 后调用，清理开头孤立反引号及紧随的 CJK/西文标点、空白，同时保留合法 inline code 和 code fence。新增回归测试 `tests/run_agent/test_qwen_thinking_debris.py`。
- **侵入类型**：inline（builder 内增加一次清理调用）+ 纯新增测试
- **Commit**：`a8808d65e`

### 2.7 damodel prompt cache 白名单

- **背景**：`anthropic_prompt_cache_policy()` 按白名单决定是否注入 `cache_control` 标记。damodel（genai.damodel.com）走 OpenAI-wire 但不在任何分支里 → 返回 `(False, False)`，qwen3.6-27b 等 0% 缓存命中，每轮重算全量 prompt。
- **方案**：新增 damodel 分支：`provider=='damodel'` 或 base_url host 匹配 `genai.damodel.com` → `(True, False)` envelope layout（同 opencode/alibaba qwen 路径）。
- **侵入类型**：narrow if-else（agent_runtime_helpers.py，11 行新增）
- **Commit**：`f07fcb736`

### 2.8 damodel NewAPI proxy provider + 共享 MiMo thinking wire format

- **背景**：owner 需要一个多模型代理 provider（`genai.damodel.com` NewAPI）路由到 MiMo / GLM / DeepSeek / Qwen / MiniMax 等。MiMo 的 `thinking.type` 官方 wire 格式此前内联在 xiaomi provider 里，damodel 代理 MiMo 时需要复用同一协议，避免两处实现漂移。
- **方案**（3 commit）：
  - **共享 MiMo thinking wire**（`1edf4ad4d`）：抽取 `providers/mimo_thinking.py`（`build_mimo_thinking_extras`），把官方 `thinking.type=enabled` wire 格式做成共享模块；xiaomi provider 从普通 `ProviderProfile` 重构为 `XiaomiProfile` 子类，委托 thinking extras 给共享 builder。直连 xiaomi 与 damodel 代理的 MiMo 模型走同一上游协议。新增 `tests/providers/model_providers/test_mimo_thinking_wire.py`（204 行）。
  - **damodel provider 插件**（`b17aac54b`）：`plugins/model-providers/damodel/`（`__init__.py` + `plugin.yaml`），多模型代理；MiMo 流量复用共享 mimo_thinking wire format，其余模型透传不做 extra_body 改写。
  - **owner providers 优先于 custom fallback**（`ba51085f6`）：`hermes_cli/models.py` 的 `_PROVIDER_MODELS` 静态目录新增 damodel（glm-5.1 / glm-5.2 / mimo-v2.5）；新增 `_OWNER_PROVIDERS = frozenset({'damodel'})`，让 `_is_custom_current` guard 跳过 owner providers。否则 `/model` 切换到 damodel 模型目录时，若 current provider 为 `custom` 会绕过静态目录检查，停留在 custom。
- **涉及文件**：
  - 纯新增：`providers/mimo_thinking.py`、`plugins/model-providers/damodel/__init__.py`、`plugins/model-providers/damodel/plugin.yaml`、`tests/providers/model_providers/test_mimo_thinking_wire.py`
  - 侵入：`plugins/model-providers/xiaomi/__init__.py`（重构为 XiaomiProfile 子类）、`hermes_cli/models.py`（静态目录 + `_OWNER_PROVIDERS`）
- **侵入类型**：纯新增（provider 插件 + 共享模块）+ inline（`hermes_cli/models.py`：静态目录扩展 + owner providers 豁免）
- **配置迁移**（`912c7af85` 部分）：`owner/config/patch.yaml` 的 `owner.model_extra_body` 中 xfyun 相关条目迁到 damodel（上游模型相同），统一走 damodel 代理。
- **Commit**：`1edf4ad4d`（共享 MiMo thinking + XiaomiProfile 重构）、`b17aac54b`（damodel provider）、`ba51085f6`（route owner providers over custom）

### 2.8.1 已修复：damodel `/model` 校验时 env-var 模板未展开导致 crash

- **问题**：`config.yaml` 中 `providers.damodel.base_url: ${DAMODEL_BASE_URL}`（或 `model.base_url: ${DAMODEL_BASE_URL}`）在 `DAMODEL_BASE_URL` 未加载到 `os.environ` 时，字面量 `${DAMODEL_BASE_URL}` 会保留到运行时。执行 `/model mimo-v2.5-pro --provider damodel` 时，`validate_requested_model()` → `fetch_api_models()` → `probe_api_models()` 把 `${DAMODEL_BASE_URL}/models` 直接传给 `urllib.request.urlopen()`，触发 `ValueError: unknown url type: '${DAMODEL_BASE_URL}/models'`，最终被 `model_switch.py` 格式化为 `无法验证 mimo-v2.5-pro：unknown url type: '${DAMODEL_BASE_URL}/models'`。
- **修复**：在 `hermes_cli/models.py:probe_api_models()` 入口增加 `${VAR}` 占位符展开（与 `agent/model_metadata.py:1926` 的 P29 patch 对齐）；展开后若仍残留未解析的 `${...}`，直接返回 `models=None` 视为 unreachable，不再让 urllib 抛错。这样 `validate_requested_model()` 会自然 fallback 到静态 catalog/警告路径，模型切换不再 crash。
- **涉及文件**：`hermes_cli/models.py`（`probe_api_models()` env-var 展开 + 占位符兜底）、`tests/hermes_cli/test_model_validation.py`（新增 `TestProbeApiModelsEnvPlaceholder`、`TestValidateRequestedModelEnvPlaceholder`）
- **侵入类型**：inline 逻辑修改（约 14 行，在官方 `hermes_cli/models.py` 内）
- **设计原则**：不硬编码 `mimo-v2.5-pro` 到 `_PROVIDER_MODELS["damodel"]`；只解决 env-var 模板泄露导致的 crash，模型识别仍由现有 catalog fallback 处理。
- **测试**：`pytest tests/hermes_cli/test_model_validation.py tests/hermes_cli/test_models.py tests/hermes_cli/test_custom_provider_model_switch.py tests/hermes_cli/test_provider_config_validation.py tests/test_minimax_model_validation.py` → 224 passed。
- **Commit**：`bd430ea81`（原附录 E 2026-07-13 条目以「当前未提交改动」记载，后提交为此 hash）

### 2.9 kimi-coding provider：模型目录隔离 + thinking 回显 + vision 标记

- **背景**：`sk-kimi-*` 直连 `api.kimi.com/coding` 的 key 此前会把 Moonshot 完整 curated catalog 一并合并进 coding-plan picker，导致非 Coding-Plan 模型（`kimi-k2.7-code` / `kimi-k2.6`）泄漏；同时 Kimi k2.7-code 需要原样 `reasoning_content` 回显，UI 此前用空格占位覆盖真实内容；且 kimi-coding 未声明支持 vision，图片被 `auxiliary.vision` 预描述而非原生路由。
- **方案**（4 commit）：
  - **模型目录隔离**（`0956317d2`）：`hermes_cli/models.py` 新增 `_KIMI_CODING_PLAN_MODELS` + `_is_kimi_coding_plan_endpoint` 助手，使 targeting `api.kimi.com/coding` 的 key 只暴露 `kimi-for-coding` / `kimi-for-coding-highspeed`；`cached_provider_model_ids` 清掉混入了 Moonshot ID 的 pre-fix 缓存行；kimi-coding 插件在 base_url 缺 `/v1` 时探测 `.../coding/v1/models`，避免 404 回退到 Moonshot catalog。新增 `tests/hermes_cli/test_provider_live_curated_merge.py`、`tests/plugins/model_providers/test_kimi_profile.py`。
  - **thinking 完整回显 + 隐藏占位**（`66a56b478`）：按 model id 及 host/provider 双重识别 Kimi，replay 时保留真实 `reasoning_content`（含前台 k2.7-code 及其 damodel/custom 代理），UI reasoning 显示跳过纯空白 stub；对常开 thinking 的 k2.7-code 不再下发 `thinking.disabled`。涉及 `agent_runtime_helpers.py` / `anthropic_adapter.py` / `chat_completion_helpers.py` / `turn_finalizer.py` / `cli.py` / `gateway/run.py` / `plugins/model-providers/kimi-coding/__init__.py` / `run_agent.py` + 3 测试。
  - **严格模型 allow-list**（`0ff98f296`）：`api.kimi.com/coding` 的 `/v1/models` 返回订阅外 ID 时，过滤 live 响应，使 `kimi-coding` / `kimi-coding-cn` picker 只暴露两条订阅模型；`cached_provider_model_ids` 改为走同一 allow-list 的刷新路径。新增回归测试注入额外 live 模型并验证被丢弃。
  - **vision 标记**（`cd47c815b`）：`kimi-coding` 与 `kimi-coding-cn` 两个 profile 设 `supports_vision=True`，附件图片直接原生路由到模型，而非经 `auxiliary.vision` 预描述。
- **涉及文件**：纯新增 `plugins/model-providers/kimi-coding/__init__.py`（隔离改造 + vision）、`tests/plugins/model_providers/test_kimi_profile.py`、`tests/hermes_cli/test_provider_live_curated_merge.py`；侵入 `hermes_cli/models.py`（`_KIMI_CODING_PLAN_MODELS` / `_is_kimi_coding_plan_endpoint` / allow-list）、`agent/*`、`cli.py`、`gateway/run.py`、`run_agent.py`。
- **侵入类型**：纯新增（kimi-coding provider 插件 + 测试）+ inline（models.py 目录隔离 + agent/gateway thinking 回显逻辑）。
- **Commit**：`0956317d2`（目录隔离）、`66a56b478`（thinking 回显）、`0ff98f296`（allow-list）、`cd47c815b`（vision 标记）

### 2.10 model-switch：显式模型白名单优先于 live `/models` 探测

- **背景**：`list_authenticated_providers` 此前把 lone model / default_model 也当成「白名单」来抑制 live discovery，导致 OpenRouter / Bifrost 类端点会用几百个 live ID 覆盖掉少量已配置子集，进而把 `/providers` picker 卡死。
- **方案**（`ee10d6230`）：只有 `providers.<name>.models` 列表才视为有意的白名单；lone model / default_model 是「当前选择」不应抑制 live discovery。无 api_key 且 collected model list 非空时保留显式子集；仅对裸端点、或 `discover_models` 开启且不存在 `models:` 白名单时才探测 live `/models`。测试分别断言 config-first 行为与无白名单 live 探测路径。
- **涉及文件**：`hermes_cli/model_switch.py` + `tests/hermes_cli/test_model_switch_custom_providers.py`、`tests/hermes_cli/test_user_providers_model_switch.py`
- **侵入类型**：inline 逻辑修改（`hermes_cli/model_switch.py`）
- **Commit**：`ee10d6230`

### 2.11 provider model 缓存 TTL 延长至 24h + 无变化时不写磁盘

- **背景**：`/providers` 命令和 agent 构造时，`_PROVIDER_MODELS_CACHE` 和 `models_dev` 两层缓存原先都是硬编码 3600s（1h）TTL。模型列表变化频率远低于 1h，每天白白 fetch 23 次浪费网络 I/O。
- **方案**（`c780e7a63`）：
  1. `agent/models_dev.py`：`_MODELS_DEV_CACHE_TTL` 3600 → 86400（24h），models.dev 社区数据库变化极少，纯 TTL 延长即可。
  2. `hermes_cli/models.py`：`_PROVIDER_MODELS_CACHE_TTL` 3600 → 86400（24h）。
  3. `hermes_cli/models.py`：`cached_provider_model_ids` 加 diff 逻辑 — TTL 过期后 fetch，但新旧模型 ID set 相同且 credential fingerprint 未变时，只刷新内存时间戳，**不写磁盘**。模型列表有增删或 fp 变化时才 `_save_provider_models_cache`。
  4. `force_refresh=True`（`/model --refresh`）路径不受影响，总是 fetch + 写磁盘。
- **涉及文件**：
  - 侵入（inline 逻辑修改）：`agent/models_dev.py`、`hermes_cli/models.py`
- **侵入类型**：inline 逻辑修改（常量 + 条件分支）
- **Commit**：`c780e7a63`

---

## 三、安全边界：审批、Guardrail 与自动审批

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

### 3.3 inbound context + cron prompt 注入 session_id

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
- **后续修复**：`3dff78944` — `owner/gateway/inbound_context.py` 的 session_id 透传改为优先使用 session key（gateway 侧运行时 session 标识）。原 §3.3 描述的 session_id 透传链在多 session 并发场景下可能取到错误的 session 标识；改为 session-key-first 解析顺序后，session_search 召回定位与跨平台会话追踪更准确。

### 3.4 多平台审批签名统一

- **背景**：不同平台（QQ、飞书、Discord）审批时传的 sender 身份字段不一致，导致审批记录无法关联到真实用户。
- **方案**：`gateway/run.py` 统一传 `sender_open_id`/`sender_is_bot`；QQ adapter 用 `**kwargs` 吸收额外字段；Discord adapter 用 `get_choice_display` 渲染 clarify 按钮。
- **侵入类型**：薄胶水（run.py 一处传参 + adapter **kwargs 吸收）
- **Commit**：`72e6b4be9`（§4.3 QQ 审批签名统一）

### 3.5 Guardrail 提示信息增强

- **背景**：tool guardrail（连续失败次数超阈值时 block/halt/warn）的消息太简略，用户不知道是哪个计数器、阈值多少、在哪改。
- **方案**：`agent/tool_guardrails.py` 的 warn/block/halt 消息增加计数器名、阈值、config.yaml 路径；warn 消息换 emoji（🐍→🛠️）。
- **侵入类型**：inline（消息字符串增强，逻辑不变）
- **Commit**：`2ad5aa2fb`（§4.7 block/halt）、`5e73d395f`（§4.8 warn + emoji）、`4661db389`（§4.8 验证 ChatIdCacheDebouncer 已存在，无代码变更）

### 3.6 Skill 脚本自动审批 + YOLO 模式

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

### 3.7 安全加固（CR 修复）

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

### 3.8 其他安全修复

- **SSRF 防护**（§17.8）：`1b0b3fce1` — `save_url_image` 拒绝非 http(s) scheme（WR-02）
- **Feishu user_name sanitize**（§17.16）：`f28061959` — 注入 user turn 前清洗 Feishu user_name（CR-03）

---

## 四、飞书平台：深度定制与交互卡片

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
- **后续修复**：`fc6f2fbc4` — merge 冲突解决时同时保留了 owner 的 `setdefault(connection_mode)` 和上游 `.update()` 中的 `connection_mode`，`.update()` 无条件覆盖 `setdefault`，导致 `config.yaml` 中 `connection_mode: send_only` 的子 profile 容器被改写为 `websocket`。修复：从 `.update()` 中移除 `connection_mode`，仅靠 `setdefault` 维持 config.yaml > env 优先级。

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
- **后续修复**：`ff42d3601` - auto-card 全链路修复：send_card 响应校验 + 表格原子切分 + 降级路径 + 并发锁

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
- **后续修复**：`21004e4c3` - diff card 重复弹出 + terminal progress 被错误包装成 auto card

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
- **后续扩展**：
  - `ec3e6bb78` — 在 `owner/config/patch.yaml` 的 `feishu.bot_menu` 命令映射新增 `usage` / `insights` 两个菜单项，并在 `bot_menu_dedup.per_key` 配置 ack（`ack: null` = 不显示 typing 指示器，因为这两个命令是异步汇总，typing 反而误导）。
  - `912c7af85`（部分）— 补 `/usage` 和 `/insights` 的 ack 消息内容。

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
  - `ff29bbc54` — 新增 `transform_tool_result` hook。`post_tool_call` 异步发送审批卡片后，agent 看到的 tool result 仍是上游 CLI 文案（"review with /memory pending"），但这个 affordance 在飞书不存在。新增 transform hook 在卡片实际派发时（通过 `_SENT_CARD_IDS` 一次性集合追踪）把 staged result 改写为 "Approval card sent to chat - click to save or discard"；非飞书 session 下 transform 是 no-op，保持上游行为。含 6 个单测。
  - `e297792cd` — 修复 false-confirmation 竞态。`_on_post_tool_call` 异步派发卡片后立即写 `_SENT_CARD_IDS`，但异步派发可能在途失败（网络错误 / API 拒绝），此时 transform 会把消息改成「卡片已发送」——一个 agent 无法核实的虚假确认。改为 transform 不再依赖 `_SENT_CARD_IDS`，而是基于「这是带 staged memory write 的飞书 session」（从 gateway session key 推导飞书 chat id），并用进行时态 "Approval card being sent"（无论卡片是否最终送达都成立）。同时 `model_tools.py` 把 `gateway_session_key` 透传给 transform hook（与 post_tool_call 对齐）。
  - `8a9273b25`（test）— 补 `_SENT_CARD_IDS` 生产路径写入 + 派发失败路径（失败时不得写入）。
  - `e218fc7dd`（test）— `e297792cd` 的 follow-up：`tests/test_model_tools.py` 的 transform hook exact-match 断言加入新的 `gateway_session_key=''` 入参。

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
- **后续修复**：
  - `0dbae9a40` — agent running 时点击 bot menu 触发 `/feishu-guide`，`should_bypass_active_session()` 只查 `resolve_command()`（仅含 `COMMAND_REGISTRY` 内置命令），plugin 命令不在其中，导致落入 busy-input 路径被当普通消息注入 agent。修复为同时检查 `is_gateway_known_command()`（覆盖 plugin 命令）。同 bug 影响 `/providers` 等所有 plugin 命令。
  - `8c4c902e1` — `feishu_guide` bot menu 事件绕过普通命令管线直接发卡片。原路径经过 `_handle_message_with_guards` 会被 per-chat lock 阻塞，导致 ack 到卡片出现之间延迟数秒；现在 ack 后直接调用 `adapter.send_guide_card()` 并 return，提升响应速度。
  - `5b2f8ed74` — `feishu_guide` 引导卡片提交后，合成的 `/steer` `/queue` `/goal` 等命令没有注入到正在运行的 agent，而是被 LLM 当普通消息回复。根因：`bot_menu.py` 的 feishu_guide 快捷路径用 `SimpleNamespace` 构建 source，`chat_type` 字面量 `'p2p'` 未归一化为 `'dm'`，导致合成 event 的 session key 与运行中 agent 的不匹配，gateway runner 的 running-agent fast path 未命中。修复：`steer_card.py::_route_guide_command` 在 `_dispatch` 中重建 source、走 `_resolve_source_chat_type` 归一化路径（与普通 bot menu 命令一致）；`bot_menu.py` 的 `SimpleNamespace` 改用 `adapter.build_source()` 补全缺失字段；`adapter.py` 加 `form_value` JSON string 归一化（防御性）+ 诊断日志。端到端验证：steer 注入成功（chat_type=dm，session key 匹配）。
  - **queue 撤销队列 + 执行后冻结（个人 fork，仅飞书卡）** — queue 提交后 done 卡增加「撤销队列」；FIFO 开始执行时 REST patch 卡片为「▶️ 已开始执行」蓝底终态。**禁止**把 token 写入 `message_id`（会当 reply_to 导致 99992354）。实现：`owner/feishu/steer_card.py` + `owner/patches/queue_cancel_patch.py`（按 prompt 文本匹配入队、`event._owner_queue_token` 打标、包装 `_enqueue_fifo`/`_dequeue_pending_event`、`cancel_queued_by_token`；并 wait 在途 prefetch 以避免 queue 紧接上轮时跳过 openviking 召回卡）。注册于 `owner-extensions`。

### 4.12 飞书文件上传大小守卫

- **背景**：飞书文件上传超限时默认静默失败，用户不知道发生了什么。需要在超限时给出明确的错误提示。
- **方案**：`owner/feishu/` 模块中增加文件上传大小守卫，超限时向用户发送错误提示消息而非静默失败。
- **侵入类型**：薄胶水 + try-import
- **Commit**：`3ae4c4bbf`

---

## 五、交互语法：快捷命令与命令别名

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

## 六、终端体验：TUI 与皮肤引擎

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

## 七、运行稳定性：Gateway / Cron / Memory / Merge 修复

### 7.1 QQ Bot WebSocket 重连链

- **背景**：QQ Bot 的 WebSocket 连接断线后重连不稳定（无 heartbeat/receive_timeout/stop_retry 机制）。
- **方案**：`gateway/platforms/qqbot/adapter.py` + `constants.py` 增加 heartbeat、receive_timeout、stop_retry、rebuild_http_client 重连链。
- **侵入类型**：inline（adapter 重连逻辑）
- **Commit**：`135c5a147`（§11.1）、`37f8a02f1`（fix: accept `is_reconnect` kwarg in `QQAdapter.connect()`）

### 7.2 Memory synthetic guard（跳过合成系统消息的 recall/sync）

- **背景**：memory provider 的 recall/sync 不应该处理合成系统消息（如 MoA 注入的、压缩摘要等），否则会污染记忆。
- **方案**：
  - `owner/patches/memory_synthetic_guard_patch.py`：`apply_patch()` - 在 gateway/run.py 的 message-receive hook 处注入守卫，跳过合成系统消息
  - `gateway/run.py`：`# [owner] memory: skip recall/sync for synthetic system messages` + 薄胶水
  - `tests/owner/patches/test_memory_synthetic_guard_patch.py`
- **侵入类型**：import 编排（runtime patch）+ 薄胶水
- **Commit**：`a91689b08`（§9.3）
- **后续扩展**：`8a46ddea0` - 增加 `_is_non_recallable_command()` 拦截斜杠命令的 recall。所有 `/` 开头的消息默认跳过 `prefetch_all` / `queue_prefetch_all`，白名单 5 个对话引导命令（queue/steer/goal/subgoal/background）例外，因为它们携带用户输入的 prompt 值得召回。其余命令（status/model/providers/new/stop 等）是控制操作，无召回价值。
- **后续修复**：
  - `a0f37869e` — delegation framework 在部分 locale 下 emit `[ASYNC DELEGATION COMPLETE — ...]`（U+2014 em-dash），但 `_SYNTHETIC_PREFIXES` 只匹配 ASCII hyphen 变体 `[ASYNC DELEGATION COMPLETE - ...]`，合成消息未被 recall/sync 跳过。给 BATCH COMPLETE 和 single COMPLETE 两种前缀都补 em-dash 变体。
  - `2d4d05252`（test）— 加 emitter↔guard 契约回归测试：调用真实的 `format_process_notification`，断言 `_is_synthetic` 能识别其输出（single + batch fan-out 两种形态）；第三个测试把 emitter 的分隔符 pin 到 U+2014，未来若改回 ASCII hyphen 会在这里大声失败，而不是让 guard 静默失效。

### 7.3 OpenViking 同步召回 + advisory + recall-card

- **背景**：OpenViking memory provider 需要同步召回（替代异步）+ advisory 提示词 + 召回结果可视化（飞书卡片/QQ 文本），并有线程池上限 + per-chat debounce。
- **方案**：
  - `owner/patches/openviking_owner_recall_patch.py`：`apply_patch()` — advisory 提示词、peer dedup、recall card 注入
  - `owner/patches/openviking_recall_config.py`：从 patch.yaml 读配置（`owner.openviking_sync_recall.*` / `owner.openviking_recall_card.*`）
  - `owner/owner-extensions/__init__.py`：plugin `register(ctx)` 中统一 apply（已从 `gateway/run.py` 顶层 try-import 迁出）
  - **WR-04**：`684de6981` — bound recall-card thread pool + per-chat debounce
- **侵入类型**：import 编排（runtime patch）+ 薄胶水
- **Commit**：`76fa75f36`（§11.6 精简迁移）、`684de6981`（§11.6 WR-04 bound thread pool + debounce）、`6a9e28b92`（迁入 `owner-extensions` plugin）
- **后续修复**：`6a9383d38` — 移除 `plugins/memory/openviking/__init__.py` 中基于 `subprocess.Popen` 的本地 server auto-start。裸 Python `openviking-server`（未带 hotfix patch）会在 gateway restart 时与 Docker 容器抢端口 1933 并劫持端口。改为由 Docker 外部管理 server。同时删除对应的 `test_start_local_openviking_server_uses_endpoint_host_and_port` 测试。

### 7.4 Cron env 隔离（ContextVar + restart scrub）

- **背景**：`HERMES_CRON_SESSION` 环境变量会从 cron 进程泄露到 gateway 的其他 session，导致非 cron 的 agent 误以为自己在 cron 上下文。
- **方案**：
  - `owner/cron/session_context.py`：用 ContextVar 隔离 `HERMES_CRON_SESSION`（而非环境变量）
  - `owner/cron/restart_scrub.py`：`owner_cron_scrub_process_env` / `owner_cron_scrub_watcher_env` — restart/startup 时清洗
  - `gateway/run.py`：3 处薄胶水（process env scrub + watcher env scrub × 2）
  - 多处接线：`cron/jobs.py`、`cron/scheduler.py`、`gateway/session_context.py` 等
- **侵入类型**：薄胶水（多处 import + 委托）
- **Commit**：`8eaf0cc10`（§17.4）、文档 `owner/docs/cron-session-env-leak-fix.md`
- **后续修复**：`6e3a81897` — `tools/approval.py::_run_approval_gate` 仍用 `env_var_enabled("HERMES_CRON_SESSION")` 检测 cron session，但 §7.4 已把 cron 标记绑到 ContextVar（`owner/cron/run_job_hook.py::owner_cron_session_enter`），os.environ 的遗留写入早已因跨 scheduler worker 线程泄露而被移除。并发 gateway 中 ContextVar per-context 设置、os.environ 共享，`env_var_enabled()` 恒为 False → `_run_approval_gate` 的 cron 分支是死代码 → cron job 命中危险命令被静默 auto-approve（应为 `cron_mode=deny` 或走 cron policy）。改为 ContextVar-aware 的 `_is_cron_session()`，与同文件另三处调用点（238/2672/3055 行）对齐。新增回归测试，通过生产路径 `owner_cron_session_enter` 置位 cron flag、同时 os.environ 不设 `HERMES_CRON_SESSION`，覆盖 `check_dangerous_command` 与 `request_tool_approval` 两个入口。

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
- **回归测试**：`740571e9f` — `test_should_bypass_returns_true_for_every_registered_command` 原本只覆盖 built-in 命令。plugin 注册的斜杠命令（`/feishu-guide`、`/providers`…）走 `_iter_plugin_command_entries()` 而非 `resolve_command()`，依赖 `should_bypass_active_session` 里的 `is_gateway_known_command()` fallback。新增 case monkeypatch `_iter_plugin_command_entries` 返回 fake plugin 命令，断言 bypass 为 True、genuinely unknown 命令为 False，防止 fallback 被误删后 plugin 命令被注入运行中 agent turn（同 #5057 bug class）而无测试失败。

### 7.11 允许 /memory 和 /skills mid-turn 执行

- **背景**：`/memory` 和 `/skills` 是只读/管理型斜杠命令，不应被 running-agent guard 拦截，但之前不在白名单中，导致 agent 运行时无法查看记忆或技能列表。
- **方案**：将 `/memory`、`/skills` 加入 `GATEWAY_KNOWN_COMMANDS`（`hermes_cli/commands.py`）并在 `gateway/run.py` 的 running-agent guard 中豁免。
- **侵入类型**：inline（commands.py 2 行 + run.py 8 行）
- **Commit**：`d1325fc7e`

### 7.12 Gateway restart 前清理 `__pycache__`

- **背景**：gateway 通过 detached watcher 进程重启时，旧 `.pyc` 字节码可能引用已不存在的名字，导致 `ImportError`。之前只有 `hermes update` 会清理字节码缓存。
- **方案**：
  - `gateway/run.py`：在 `schedule_restart()` 生成的 shell watcher 命令中加入 `find ... -name __pycache__ -exec rm -rf {} +`，排除 `venv`/`node_modules`/`.git`。
  - `hermes_cli/gateway.py`：`_spawn_gateway_restart_watcher()` 中 Python 侧同样遍历项目根目录清理 `__pycache__`。
- **侵入类型**：inline（两处 watcher 清理逻辑）
- **Commit**：`207fbde65`（同时顺手修复 `tests/gateway/test_restart_notification.py` 中过时 emoji ♻️ → 🏙）

### 7.13 上游 merge 后死代码/变量引用修复

- **背景**：上游重构后 merge 带入的死代码和未定义变量引用。
- **方案**：
  1. `tools/approval.py`：`check_dangerous_command` 删除与上游 `_run_approval_gate` 重复的 owner 内联 gateway/cron 分支；`_run_approval_gate` return 后的死代码删除；cron deny message 改走 `t("approval.cron_blocked", ...)` 而非硬编码英文。
  2. `gateway/run.py`：`_append_inbound_context` 调用参数从 `session_id=session_id` 改为 `session_id=session_key`（上游参数重命名）。
  3. `gateway/run.py`：两处 `resolve_display_setting()` 改为 `resolve_display_setting_for_source(..., source=source)`，恢复 per-chat display override。
- **侵入类型**：inline（死代码删除 + 变量修复）
- **Commit**：`dd0b8aa5d`

---

## 八、工具链：Diff / Patch / Checkpoint

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

### 8.3 delegate_task batch 模式 ACP 变量引用修复

- **背景**：上游 commit `e4dbb67bf` 删除了 delegate_task 的 `acp_command`/`acp_args` 函数参数以消除模型可控 ACP 传输风险，但 batch task 构造子 `_build_child_agent_for_task()` 中仍引用已不在作用域的 `acp_command`、`acp_args`、`task_acp_args`，导致 batch 模式下构造子 agent 时 `NameError`。
- **方案**：`tools/delegate_tool.py` 中 fallback chain 仅使用 `t.get("acp_command")` / `t.get("acp_args")`（task dict）和 `creds.get("command")` / `creds.get("args")`（delegation config），删除未定义局部变量引用。
- **侵入类型**：inline（batch task 调用点 4 行修复）
- **Commit**：`ff88f6063`（先删 `acp_command`）、`2f455b63a`（再删 `task_acp_args`/`acp_args`）

---

## 九、显示策略与个性化

### 9.1 每会话显示覆盖（per-chat display overrides）

- **背景**：不同飞书群/会话需要不同的显示设置（tool_progress on/off、streaming、interim messages 等），不能全局一刀切。
- **方案**：
  - `owner/display_overrides.py`：`for_source(source)` 提取 chat_id + 查 patch.yaml 的 `owner.display.per_chat.<platform>.<chat_id>.*`
  - `gateway/run.py`、`gateway/display_config.py`、`gateway/slash_commands.py`：多处 `source=source` 透传 + `for_source` 薄调用（约 6+ 处）
- **侵入类型**：薄胶水（多处 `source=source` 透传 + `for_source` 调用）
- **Commit**：`eb96240a4`（§10）
- **测试整改**：`a5a7fdc20` — `test_gateway_long_running_surface_keeps_source_aware_display_resolver` 原本读取 `GatewayRunner._run_agent_inner` 源码文本，断言精确子串切片（确切的 `_long_running_mode = _display_surface_mode(\n"long_running_notifications"` 行 + 220 字符固定窗口的 `allow_generic=True`），是典型的 change-detector——任何无关的空白/参数排版调整都会破坏测试而不改变行为。按 AGENTS.md 的 change-detector 指引，改为语义断言：验证 wiring 契约（helper closure 存在、引用 per-chat resolver、long-running 设置 key 流经其中），不冻结源码格式。per-chat 路由行为本身已由上方行为测试覆盖（真实 config 过 `resolve_display_setting_for_source`）。

---

## 十、归因、计费与用量落盘

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

## 十一、运维：Cron / owner/scripts / 同步脚本

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

## 十二、治理与文档杂项

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
- **Commit**：`f806b7aaa`（§17.24）

### 12.4 merge 后 owner 验证入口

- **背景**：上游 main 更新频繁，merge 后最常见风险是 owner 胶水变成死代码，或自动 merge 丢掉关键逻辑。需要一个专用入口把 owner 清单中的关键锚点、patch target、import 链、静态合约跑起来。
- **方案**：`owner/validation/merge_health_check.py` + `anchors.yaml` + `inventory.yaml`，覆盖 `_owner_import`、direct `from owner.*`、runtime patch target、`[owner]` 标记、merge diff dead-marker、关键 anchors 与轻量 inventory static checks。
- **运行方式**：`python3 owner/validation/merge_health_check.py`
- **侵入类型**：纯新增（owner 专用验证目录，不放 `scripts/`）
- **Commit**：`872ffe0ce`、`b5aa55c65`、`b50da840b`、`d6757b656`、`ca80a4957`
- **补充说明**（`ca80a4957`）：新增 `tests/owner/test_contract_entrypoints.py`（7 个 P1 contract test，验证 owner 逻辑确实接到 upstream entrypoint：gateway inbound session_key 透传、per-chat display override、long-running surface source-aware resolver、build_api_kwargs 透传 owner_provider_name、chat_completions transport extra_body、cron scheduler run_job 设置 HERMES_CRON_SESSION contextvar、owner-extensions plugin apply memory_synthetic_guard patch）；同时 `owner/validation/inventory.yaml` 扩充 11 项 inventory（pool base_url override、credential prefix gate、feishu auto-card、diff card dispatch、approval card、feishu-guide command、cron job args、message token breakdown、qwen thinking debris、damodel prompt cache policy、rate-limit quota classification、gateway restart pycache cleanup）。

### 12.5 owner/examples 参考文档（base config 模板）

- **背景**：需要一个仓库内的参考点，记录脱敏后的 Hermes base config，便于新节点初始化和对照排查。
- **方案**：纯新增 `owner/examples/`：
  - `owner/examples/config.base.example.yaml`（539 行，脱敏 base config）
  - `.gitignore` 增加规则，把 `owner/examples` 从 repo-wide `examples/` ignore 中 allowlist 出来
- **侵入类型**：纯新增（参考文档目录）
- **Commit**：`c83fbf923`

---

## 十三、Desktop 桌面端：窗口透明度曲线

Desktop 桌面端（`apps/desktop/`）此前未出现在改动清单中——本分支在此区域的改动自此节起记录。

### 13.1 Windows 透明度档位过激修复（平台感知曲线）

- **背景**：Desktop 设置里的「窗口透明」滑块按 5% 档位（`step={5}`），0–100 映射到 `BrowserWindow.setOpacity`。`windowOpacity()` 对 macOS / Windows 用同一条线性曲线 `1 - (intensity/100) * 0.7`，但窗口选项只给 macOS 设了 `vibrancy: 'sidebar'`（磨砂玻璃 NSVisualEffectView），Windows 是 `undefined`（无 `backgroundMaterial`）。结果：macOS 上 vibrancy 柔化了 `setOpacity` 的衰减，5%（0.965）读起来「稍微透明」属正常；Windows 上 `setOpacity` 是裸的整窗 alpha 直接糊在不透明背景上、无模糊柔化，同样的 0.965 读起来「几乎半透明」。同一个数、两种渲染机制——`*0.7` 斜率是按 macOS 的 vibrancy 柔化调的，直接套到 Windows 过激。
- **方案**：把 0–100 → opacity 的转换抽成纯函数 `opacityForIntensity(intensity, isWindows)`（新建 `apps/desktop/electron/translucency.cjs`，遵循仓库 `zoom.cjs` / `window-state.cjs`「主进程把纯计算抽到兄弟模块」的既有模式），Windows 走更缓的曲线：floor 0.75（原 0.30）+ `*0.25` 斜率（原 `*0.7`）。macOS 逐字节不变（同样的 `*0.7`、同样的 vibrancy）。

  | 档位 | macOS（不变） | Windows（修复后） |
  |---|---|---|
  | 0%  | 1.000 | 1.000 |
  | 5%  | 0.965 | 0.988（原 0.965）|
  | 10% | 0.930 | 0.975 |
  | 50% | 0.650 | 0.875 |
  | 100%| 0.300 | 0.750 |

  Windows 5% 只衰减 1.2%，与 macOS「稍微透明」视觉对齐；满档仍能透过看桌面但不影响阅读（opacity 0.75）。
- **涉及文件**：
  - 纯新增：`apps/desktop/electron/translucency.cjs`（`opacityForIntensity` + 两个 floor 常量）、`apps/desktop/electron/translucency.test.cjs`（9 个行为契约测试）
  - 侵入：`apps/desktop/electron/main.cjs`（import `opacityForIntensity`；`windowOpacity()` 改为 `opacityForIntensity(translucencyIntensity, IS_WINDOWS)`）
- **侵入类型**：薄胶水（main.cjs 一处 import + 一行委托；纯计算在兄弟模块）
- **测试**：9 个行为契约测试（非快照）：0 必为不透明、单调递减、垃圾输入钳制、满档触达各平台 floor、每个共享档位 Windows 都比 macOS 更不透明（正是本次防回归核心）、低档位保持在 0.95 以上。`cd apps/desktop && node --test electron/translucency.test.cjs` → 9 pass。
- **Commit**：`a8aa7e9a6`

---

## 附录 A：owner/ 模块职责索引

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
| `owner/validation/` | merge 后健康检查（anchors + inventory + import/patch/marker checks） | — |

## 附录 B：官方文件侵入点速查

按侵入深度排序，优先用于 merge 冲突解决和上游重构后的死代码排查。

### B.1 重度侵入（inline 逻辑为主，sync 冲突大，hook/plugin 化首选）

| 文件 | 侵入内容 | owner/ 对应模块 | 相关 commit |
|------|----------|-----------------|-------------|
| `gateway/run.py` | cron env scrub ×3、executor-shutdown、inbound context、hygiene notice、auto-card、per-chat display、chained quick command | owner/cron/、owner/gateway/、owner/feishu/、owner/display_overrides.py | 几乎所有 §11/§17 commit |
| `plugins/platforms/feishu/adapter.py` | 64 处 `[owner]` 标记：approval/auto_card/bot_menu/clarify/diff_card/model_picker/profile_routing/resume_card/sender_name/early-typing 委托 | owner/feishu/*（16 模块） | §4.2/§5.3-5.7/§17.1 |
| `agent/conversation_loop.py` | MoA 注入（CR-005 已改为独立 message）、content-filter fallback、adaptive backoff、thinking-timeout、attribution 重建、tool_call_id 胶水 | owner/attribution.py、owner/api_error_hints.py | a6dcd6ed8、9a05e50b4、362304bc8 |
| `tools/approval.py` | home-prefix fold（CR-001 修复）、skill script 自动审批（3 处委托）、patch.yaml allowlist 合并、cron active helper | owner/approval/、owner/patch_config.py、owner/cron/approval_helper.py | 82fe8c962、5dd9580b4、99a374f64 |
| `gateway/platforms/base.py` | per-profile cache roots、SendResult rotate/retry_after、chained quick command（`[owner-patch]`）、progress dedup code-fence 守卫 | — | 1d908072a、2be0af638 |
| `tools/cronjob_tools.py` | owner/scripts allowlist（mtime-based）、cron job args 三处 `[owner-patch]` | — | 8a8f42455、3163d17e8、890869693 |
| `cron/jobs.py` / `cron/scheduler.py` | cron job args `[owner-patch]` 参数 normalize + map | — | 3163d17e8 |

### B.2 中度侵入（薄胶水 + 列扩展，sync 冲突中）

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

### B.3 轻度侵入（import 编排 / 单行，sync 冲突小）

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

### B.4 与附录 C 的交叉覆盖

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
| `tools/skills_tool.py` | 中度 | ❌ 未单项评估 | 间接覆盖：归 §3.6 skill 脚本自动审批（1 行 track 调用，无迁移价值）|
| `gateway/platforms/qqbot/adapter.py` | 中度 | ❌ 未单项评估 | 未评估：WS 重连链是 inline 逻辑，但属平台适配器内部实现，无 plugin hook 可迁；保持现状 |
| 轻度侵入全部（13 文件）| 轻度 | ❌ 未单项评估 | 无需评估：均为 1-3 行 import / 透传 / 字符串，迁移收益为零 |

**结论**：附录 B 列出的 ~35 个侵入文件中，附录 C 单独评估了 10 项主线；剩余文件要么被间接覆盖（归因链、extra_body、clarify 等已归入对应章节），要么是 1-3 行薄胶水 / 字符串 / 平台适配器内部逻辑，迁移收益为零，无需单独评估。**附录 B 无遗留未决项。**

---

## 附录 C：迁移与治理路线图

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

_本清单基于 2026-07-02 的 owner 分支状态生成。后续 commit 请先放入正文对应章节；如涉及 owner 模块、官方侵入点或迁移判断，再同步更新附录 A/B/C 与元数据表的「最后更新」日期。_

---

## 附录 E：变更日志

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
- **commit**：`fedc96b56`（`/providers` -> plugin slash command）
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
- **后续修复**：`779b87265` — `feishu_client_utils.py` / `feishu_doc_tool.py` 的 code review 修复：W1 把 `_col_letter` 提为模块级 helper（原在循环内重复定义）；W3 `do_request` 解析 `raw.content` 失败时加 `logger.debug`；W4 `do_request` method 映射改为显式、不支持的方法抛 `ValueError`；W2 docstring 文档化 `read_bitable_as_text` 的 100 表上限；I7 tool description 补 sheet 支持；I9 错误消息统一英文；I6 新增 13 个测试覆盖 `read_sheet_as_text`、多页分页、`/bitable/` URL 提取、不支持方法校验、列字母生成。

### 2026-07-08：ruolin 皮肤更新 + redaction warning 移除

- **类型**：皮肤字段补全 + 启动噪音清除
- **Commit**：`1731193cb`
- **变动**：
  - `owner/skins/ruolin.yaml` + `owner/skins/ruolin-light.yaml`：补全 skin_engine 新增的 6 个 color key（`selection_bg`、`voice_status_bg`、`completion_menu_*`），ruolin-light 从 skill reference 恢复
  - `cli.py`：删除 17 行 `Secret redaction is DISABLED` console 打印
  - `gateway/run.py`：删除 22 行 `Secret redaction: DISABLED` logger.warning
- **验证**：`python -m py_compile` 两文件通过；`pytest -k "redact or secret"` 450 passed / 1 pre-existing failure（`test_empty_body_fallback_redacts_secrets`，stash 验证确认与本次改动无关）；`load_skin('ruolin')` / `load_skin('ruolin-light')` Python 加载验证 29 colors 全部就位

### 2026-07-09：上游 merge 后修复集（8 commits）

- **类型**：merge 后续 bug fix + i18n + 性能/稳定性优化
- **Commits**：`dd0b8aa5d`、`fc6f2fbc4`、`ff88f6063`、`2f455b63a`、`207fbde65`、`a8808d65e`、`45598ce6a`、`8c4c902e1`
- **概要**：
  1. 修复 `tools/approval.py` 重复 gateway/cron 分支死代码 + `gateway/run.py` `session_id` 变量名与 `resolve_display_setting_for_source` 修复（`dd0b8aa5d`）。
  2. 修复 `gateway/config.py` 中 `connection_mode` 被 `.update()` 覆盖，恢复 `send_only` 子容器配置生效（`fc6f2fbc4`）。
  3. 修复 `tools/delegate_tool.py` batch task 中未定义 `acp_command`/`acp_args` 引用（`ff88f6063`、`2f455b63a`）。
  4. gateway restart watcher 清理 `__pycache__`，避免陈旧字节码导致 `ImportError`；同时修复 steer-ack 分支 `source` 未定义与 import 顺序（`207fbde65`）。
  5. 清理 Qwen 在 `anthropic_messages` 模式下产生的 thinking debris（开头孤立反引号 + CJK 标点），加回归测试（`a8808d65e`）。
  6. iteration budget 耗尽提示 i18n 化（`45598ce6a`）。
  7. 飞书 bot menu `feishu_guide` 事件直接发送引导卡片，绕过命令管线 lock 延迟（`8c4c902e1`）。

### 2026-07-10：terminal timeout 从 180s 调整到 300s

- **类型**：运维配置调整（chore）
- **Commit**：`912c7af85`（部分）
- **变动**：`cli-config.yaml.example` 的 terminal timeout 从 180s 提升到 300s，避免长耗时命令误触超时。

### 2026-07-11：改动清单漏写补录（15 条）

- **类型**：文档补录（无代码变更）
- **背景**：对 `git log --since="3 days ago"` 的 45 个 commit 与改动清单逐条比对，发现 15 个功能/修复/chore commit 漏写（已排除纯 docs commit 与轻量 test 修复）。
- **补录条目**：
  - 新增子节 §2.8（damodel NewAPI proxy provider + 共享 MiMo thinking wire，3 commit）、§12.5（owner/examples 参考文档，1 commit）
  - §2.2 新增 §2.2.4（飞书 model_picker 卡片 stale session 修复，2 commit）
  - §3.3 / §4.6 / §4.10 / §4.11 / §7.2 / §7.3 / §7.4 / §7.10 / §9.1 各追加后续修复/扩展/回归测试/测试整改
  - §12.4 Commit 列表扩充 `ca80a4957`（P1 contract tests + inventory 扩充）
  - 附录 E 的 feishu_doc_read 条目追加 `779b87265` code review follow-up；新增 terminal timeout 调整日志
  - 混合 chore `912c7af85` 拆分归属 §4.6（ack）/ §2.8（xfyun→damodel 迁移）/ 附录 E（timeout）
- **涉及 commit**：`1edf4ad4d`、`b17aac54b`、`ba51085f6`、`4a2f7572c`、`3dff78944`、`ec3e6bb78`、`440d5b023`、`5251db809`、`ff29bbc54`、`e297792cd`、`8a9273b25`、`e218fc7dd`、`5b2f8ed74`、`a0f37869e`、`2d4d05252`、`6a9383d38`、`6e3a81897`、`c83fbf923`、`ca80a4957`、`779b87265`、`912c7af85`、`740571e9f`、`a5a7fdc20`
- **审计来源**：`/tmp/zcode-audit-result.md`

### 2026-07-13：damodel `/model` 校验时 env-var 模板未展开导致 crash

- **类型**：bug fix
- **Commit**：`bd430ea81`（原始记载为「当前未提交改动」，后提交为此 hash）
- **背景**：`config.yaml` 中 `providers.damodel.base_url: ${DAMODEL_BASE_URL}` 在环境变量未加载时，字面量会传到 `probe_api_models()`，urllib 因 unknown url type 抛错，最终显示 `无法验证 mimo-v2.5-pro：unknown url type: '${DAMODEL_BASE_URL}/models'`。
- **修复**：`hermes_cli/models.py:probe_api_models()` 入口增加 `${VAR}` 展开；展开后仍残留未解析占位符时返回 `models=None`，不再 crash。不硬编码 `mimo-v2.5-pro` 到 catalog。
- **涉及文件**：`hermes_cli/models.py`、`tests/hermes_cli/test_model_validation.py`
- **侵入类型**：inline（官方文件内约 14 行逻辑）
- **测试**：`pytest tests/hermes_cli/test_model_validation.py tests/hermes_cli/test_models.py tests/hermes_cli/test_custom_provider_model_switch.py tests/hermes_cli/test_provider_config_validation.py tests/test_minimax_model_validation.py` → 224 passed

### 2026-07-14：Desktop Windows 透明度档位过激修复（平台感知曲线）

- **类型**：bug fix
- **Commit**：`a8aa7e9a6`
- **背景**：Desktop「窗口透明」滑块（5% 档位）在 macOS 上 5% 看起来「稍微透明」属正常，但在 Windows 上 5% 已「几乎半透明」。根因：`windowOpacity()` 对两平台用同一条线性曲线 `1 - (intensity/100) * 0.7`，但窗口选项只给 macOS 设了 `vibrancy: 'sidebar'`（磨砂玻璃柔化衰减），Windows 无 backdrop material，`setOpacity` 是裸整窗 alpha，同样 0.965 读起来远比 macOS 激进。`*0.7` 斜率是按 macOS 的 vibrancy 调的，套到 Windows 过激。
- **修复**：把转换抽成纯函数 `opacityForIntensity(intensity, isWindows)`（新建 `apps/desktop/electron/translucency.cjs`），Windows 走更缓曲线（floor 0.75 / `*0.25`），macOS 逐字节不变。详见 §13.1。
- **涉及文件**：`apps/desktop/electron/translucency.cjs`（新增）、`apps/desktop/electron/translucency.test.cjs`（新增）、`apps/desktop/electron/main.cjs`（import + 委托）
- **测试**：`cd apps/desktop && node --test electron/translucency.test.cjs` → 9 pass

### 2026-07-15：补录遗漏功能点（kimi-coding / model-switch / model-validation hash）

- **类型**：文档补录（无代码变更）
- **范围**：本机作者「杨天宝」最近 7 天 commit，排除 `owner/scripts/` 与 `patch.yaml` 后，对照本清单发现的遗漏功能点（yangtb provider 移除按约定不记、不补「已退役」）。
- **新增 §2.9 kimi-coding provider**（4 commit）：`0956317d2`（模型目录从 Moonshot 开放 API 隔离）、`66a56b478`（thinking 完整回显 + 隐藏占位）、`0ff98f296`（严格模型 allow-list）、`cd47c815b`（vision 标记）。
- **新增 §2.10 model-switch 白名单优先**（`ee10d6230`）：显式 `models:` 白名单优先于 live `/models` 探测，防止 OpenRouter/Bifrost 类端点用几百个 live ID 覆盖已配置子集、卡死 `/providers` picker。
- **§2.8.1 补录 hash**：`bd430ea81`（原 2026-07-13 条目记作「当前未提交改动」，现已提交为此 hash，功能描述一致）。

### 2026-07-23：feishu_doc_read 下载文档内嵌图片（修复 image.png 占位）

- **类型**：bug fix
- **背景**：`feishu_doc_read` 仅调用 docx `raw_content` API，飞书会把 image block 压成文本 `image.png`。agent 看不到真实截图；完整链路是 blocks 取 `image.token` → `drive/v1/medias/{token}/download` → 本地文件 → `vision_analyze`。
- **方案**：
  - `tools/feishu_client_utils.py`：新增 `list_docx_image_tokens`（分页读 blocks，`block_type=27`）、`download_media`、`download_docx_images`（落盘 `$HERMES_HOME/cache/feishu_doc_images/<doc>/`）、`inject_image_paths_into_content`（按序替换 `image.png` 为 `[Image N: /path]`）、`read_docx_with_images` 编排。上限 40 张 / 10MiB 每张。
  - `tools/feishu_doc_tool.py`：docx 分支改走 `read_docx_with_images`；返回 `content` + `images[]` + `image_count`；schema 说明可把本地路径交给 `vision_analyze`。
- **涉及文件**：`tools/feishu_client_utils.py`、`tools/feishu_doc_tool.py`、`tests/tools/test_feishu_client_utils.py`
- **测试**：`scripts/run_tests.sh tests/tools/test_feishu_client_utils.py tests/tools/test_feishu_tools.py` → 54 passed
- **后续（同日）**：用户反馈 `[Image N: path]` 仍被视为占位符。补 `analyze_docx_images`：下载后自动 auxiliary vision OCR，正文嵌入转录文字；返回增加 `vision_analyzed`。并发 3 / 上限 40。测试 59 passed。

### 2026-07-24：feishu_doc_read 图片上限 40→500 + 429 退避重试

- **类型**：体验调参 / 可靠性
- **变动**：`_DOCX_MAX_IMAGES` / `_DOCX_MAX_VISION_IMAGES` 从 40 提到 500；并发仍为 3。媒体下载与 vision OCR 共用 `_call_with_rate_limit_retry`（识别 HTTP 429 / Feishu 99991400 / rate limit 文案，指数退避最多 5 次，上限 60s）。
- **涉及文件**：`tools/feishu_client_utils.py`、`tests/tools/test_feishu_client_utils.py`

