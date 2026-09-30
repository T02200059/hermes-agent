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
| 基点 | `upstream/main` @ `00b2e03c80`（`fix(tui): a collapsed paste resolves before the slash command runs`，2026-09-01） |
| Commit 数 | 358（`00b2e03c80..HEAD`；含 6 个 merge commit，本机作者 355 = `杨天宝` 248 + `yangtb` 107） |
| 改动文件总数 | 415（去重后） |
| owner/ 纯新增 | 160 个文件（基点时 `owner/` 目录为空） |
| 官方文件侵入 | 120 个文件（不含 tests；另计 `tests/` 135 个，其中新增 61） |
| 范围 | 模型归因 / patch.yaml 配置 / 审批安全 / skill 写入审批 / 语义审计 / 飞书深度定制 / TUI 皮肤 / Cron 运维 / Gateway 稳定性 / Checkpoint 预测 / Upstream Sync / Viking 记忆治理 / Desktop 窗口透明度 / output_guard / API Server LDAP 身份准入 / 产物媒体与流式契约 |
| 最后更新 | 2026-09-20 |
| 来源 | 从 `owner-v17`（500+ commit）清洗迁移而来；本分支是重新整理后的最小叠加版本 |

_元数据统计口径：范围取「基点后未出现在上游 `00b2e03c80` 中的 owner 侧改动」，即 `git rev-list --count 00b2e03c80..HEAD`；文件数按 NUL 分隔去重统计（`git diff --name-only -z … | tr '\0' '\n' | sort -u`），避免含中文的路径被 git 加引号后漏计。数值截至 2026-09-10。_

### 0.2 章节索引

| 阅读目标 | 对应章节 |
|----------|----------|
| 先判断某个 owner 能力属于哪里 | §1-§14 功能正文 |
| 看模型/provider/API 调用链 | §1、§2、§10 |
| 看审批、安全、自动审批、语义审计、cron 上下文 | §3、§7.4、§11 |
| 看飞书平台定制 | §4（含 §4.14 @所有人） |
| 看 TUI / Ctrl+C 退出 | §6 |
| 看 Desktop 桌面端改动 | §13 |
| 看 LLM 输出复读/乱码折叠 | §14 |
| 看 API Server identity 路由、LDAP 认证、准入查询 | §15 |
| 看 API Server 产物媒体下载、流式事件契约 | §16 |
| 看本轮月度审查（2026-09-28）的逐项修复留档 | §16.7-§16.16（依次为 T2-10~T2-20） |
| 看 Gateway merge 后最容易丢的胶水 | §7、附录 B、附录 C |
| 看脚本、cron、备份、Upstream Sync、Viking 记忆治理 | §11 |
| 看 owner/ 模块到官方侵入点的映射 | 附录 A、附录 B |
| 看后续是否值得 hook/plugin 化 | 附录 C |
| 看最近阶段性变化 | 附录 E |

### 0.3 维护规则

- 新增 owner 能力：先放入 §1-§14 的功能正文，再补附录 A 的模块索引。
- 修改官方文件：同步更新正文的“涉及文件/侵入类型”，并补附录 B 的侵入点速查。
- 迁移到 hook/plugin：正文保留能力描述，附录 C 记录迁移结论，附录 E 追加阶段日志。
- merge 后验证项：能静态检查的放入 `owner/validation/`，再在正文或附录中标出对应 owner 能力。

### 0.4 侵入类型图例

- **try-import / lazy import** — 官方文件用 `try: from owner.x import y` 或 `_owner_import(...)` 延迟加载，owner/ 缺失时降级。最干净、sync 冲突最小。
- **import 编排**（runtime patch）— 官方模块加载后，由 `owner/patches/*` 或 `owner/tools/schema_patches.py` 动态修改已注册对象（schema、常量、方法）。官方源码字面定义不变。
- **薄胶水 / 委托**（`[owner]` / `[owner]` 标记）— 官方文件中 1~5 行 import + 委托调用，所有实现在 owner/。短标记 + 指向 owner/ 位置。
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
- **后续**：`88336be4f` — `/new` session 边界调用 `invalidate_patch_owner_config_cache()` + `invalidate_patch_feishu_profile_config_cache()`，新会话立即读到上一会话期间改过的 patch 配置，不必等 60s TTL。

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
  - `63fa17e1b` — idle session 下 model 切换合成命令改走 `_message_handler`（同步），避免经 `_handle_message_with_guards` 的 fire-and-forget 任务在无 active turn 时被静默丢弃（done 卡已成功、实际未切模型）。
- **涉及文件**：`owner/feishu/model_picker.py`、`plugins/platforms/feishu/adapter.py`

### 2.3 运行时 schema patches + credential pool base_url override

- **背景**：`send_message` 卡片和 `image_generate` 的 model 参数需要扩展 schema，但不能改官方 toolsets 的字面定义（sync 冲突）。同时 credential pool 的 base_url 需要能被 model.base_url 覆盖（NewAPI 多 endpoint 场景）。
- **方案**：
  - `owner/tools/schema_patches.py`：模块加载后，在已注册的 tool schema 上 post-registration patch（运行时修改）。当前由 `owner-extensions` plugin 的 `register(ctx)` 统一 import/apply，不再占用 `gateway/run.py` 侵入点。
  - `owner/patches/pool_base_url_override.py`：`config_base_url_override()` — 当 model 配置了 base_url 时，覆盖 credential pool 的 base_url。`hermes_cli/runtime_provider.py` 两处薄胶水调用。
  - **env-var template 泄露防护**（§11.2）：`hermes_cli/runtime_provider.py` + `agent/model_metadata.py` + `tui_gateway/server.py` 三处 `[owner] P29` 防止 `${VAR}` 模板字符串泄露到运行时。
- **涉及文件**：
  - 纯新增：`owner/tools/schema_patches.py`、`owner/patches/pool_base_url_override.py`
  - 侵入：`agent/credential_pool.py`、`hermes_cli/runtime_provider.py`（两处 `[owner] P29` + base_url override 薄胶水）、`run_agent.py`、`agent/model_metadata.py`（`[owner] P29`）、`tui_gateway/server.py`（`[owner] P29`）
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
- **后续**：`84418c339` — `get_compatible_custom_providers()` 把 `providers:<slug>` 转成 legacy list 时带 `provider_key=<slug>`，`_configured_provider_matches()` 再扫 `custom_providers` 会把同一 provider 计成 `'<slug>'` 与 `'custom:<slug>'`，误报 `#switch_multiple_providers`。matches set 已有该 `provider_key` 则跳过。

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
- **后续**：`8c00a813f` — `fetch_models_dev` 网络超时 15s → 5s，避免 models.dev 慢响应拖慢 `/providers` 探测。

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
- **后续**：`cd11a5ff8` — 点击失败路径（unauthorized / already_resolved / chat_mismatch / missing_id / submit_failed）改为返回冻结错误 CallBackCard + i18n 文案，不再空响应让客户端卡 loading；仅成功 resolve 才放行 agent。
- **后续**：`191e5a3287` — **审批卡 operator 中文名缓存中途失效**：卡片发送时预热 `ou_id → 中文名` 缓存，但 TTL 仅 10 分钟。用户超时点击时，`_read_ttl_name` 的过期路径会**破坏性清除**两层缓存（`pop _name_ttl` + 清空 `_users.display_name`），`operator_display_name` 随即 fallback 到原始 `open_id`，卡片显示「由 ou_xxx 操作」。症状是「启动正常、后续变 ou_xxx」，即 10 分钟 TTL 到期叠加破坏性清除；另有三处放大因素（`pre_warm` 对临近过期缓存直接跳过、回调同步路径无重试、`get_cached_display_name` 的二次 TTL 检查同样破坏性清除）。修复把 TTL 从 10 分钟提到 24 小时（用户名极少变化）并消除这三处放大因素。

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
| CR-006 | skill-script 自动审批可被含 `;`/`&`/`\|` 的复合命令绕过 | 加两个 quote-aware 安全门（unquoted compound operator + quoted metachar） | `owner/approval/skill_script_approval.py` | `010186818` |

- **报告**：`f4e82eba5`（docs(00): add code review fix report）、`f160dd359`（owner(§review): code review REPORT.md）

### 3.8 其他安全修复

- **SSRF 防护**（§17.8）：`1b0b3fce1` — `save_url_image` 拒绝非 http(s) scheme（WR-02）
- **Feishu user_name sanitize**（§17.16）：`f28061959` — 注入 user turn 前清洗 Feishu user_name（CR-03）

### 3.9 Semantic Audit Gate（工具分发前语义审计门）

- **背景**：现有 approval 只能按命令模式 block 危险操作。模型陷入激进幻觉时（用户说「看 nginx 状态」，模型执行 `systemctl restart nginx`）会换姿势绕路。需要在 **tool dispatch 之前** 增加语义层审计：用 cheap LLM 判断操作是否超出用户指令范围。
- **方案**：
  - 纯新增包 `owner/semantic_audit/`：`gate.py`（`maybe_audit_batch`）、`detector.py`（Tier0 hardline / Tier1 pattern / skip）、`auditor.py`（`call_llm(task="semantic_audit")`）、`policy.py`（strike 升级）、`notify.py`、`config.py`
  - 官方胶水仅 1 处：`run_agent.py` → `AIAgent._execute_tool_calls` 路径选择前 `# [owner] semantic audit gate`，`try: from owner.semantic_audit import maybe_audit_batch`（≤5 行 + fail-open）
  - **三档 verdict**：PASS 放行；BLOCK 拒绝本次 call 并注入 synthetic error（strike +1）；HALT 拒绝 + `agent.interrupt()`，整批 tool_call_id 注入 result
  - **Tier0 hardline**（reboot / `rm -rf /` / mkfs / dd / DROP…）直接 HALT，yolo 不可旁路
  - **Tier1**（approval dangerous + 敏感路径写）→ LLM 审计；只读工具 skip
  - **后续增强**（`0f28e4bde`）：`skill_context`（从本批/近期 `skill_view` 取 SOP 正文，~3k 预览，防误拦 skill 流程）；`batch_siblings`（整批 tool_calls 上下文）；process 工具分级（kill/write/submit/close → tier1，list/poll/log/wait → skip）
  - 默认 **关闭**；用户 `config.yaml` 设 `semantic_audit.enabled: true` 开启。辅助模型走 `auxiliary.semantic_audit`（timeout 默认 5s）
  - 设计文档：`owner/docs/semantic-audit-design.md`
- **涉及文件**：
  - 纯新增：`owner/semantic_audit/*`、`owner/docs/semantic-audit-design.md`
  - 侵入：`run_agent.py`（1 处薄胶水）
- **侵入类型**：薄胶水（fail-open try-import）+ 纯新增（审计实现全在 owner/）
- **Commit**：`f07bdf6b8`（feat 门禁）、`0f28e4bde`（skill_context + batch_siblings + process 分级）

### 3.10 Smart DENY 一次性说明 + QQ DM 审批按钮鉴权

- **背景**：(1) Smart approval 返回 DENY 时 owner 覆盖策略是 **once-only**（无 session/always），但飞书/QQ 卡片按钮集变少时用户不理解；(2) QQ 私聊 session key 使用 `chat_type=dm`（`agent:main:qqbot:dm:<uid>`），而 `_is_authorized_interaction_for_session` 只匹配 `c2c`，导致所有 DM 审批按钮点击被拒，agent 卡到审批超时（默认 3600s）。
- **方案**：
  - `ec98dff9b` — 飞书审批卡（`owner/feishu/approval.py`）与 QQ keyboard（`gateway/platforms/qqbot/keyboards.py`）在 Smart DENY 场景补充 one-shot 文案说明（i18n key，en/zh）
  - `ae912986f` — QQ adapter 把 `dm` 与 `c2c` 同等处理（operator == chat_id）
- **涉及文件**：`owner/feishu/approval.py`、`gateway/platforms/qqbot/adapter.py`、`gateway/platforms/qqbot/keyboards.py`、`locales/en.yaml`、`locales/zh.yaml` + 相关测试
- **侵入类型**：薄胶水 / inline（消息文案 + 1 行鉴权分支）
- **Commit**：`ec98dff9b`、`ae912986f`

### 3.11 skill 写入飞书审批门（skill_manage / skill_approval）

- **背景**：子 profile / 飞书会话上 agent 可直接 `skill_manage` 写 skills（create/edit/delete），无人类把关时易污染 skill 库；需要与 memory 审批类似的「写操作拦截 + 飞书卡片审批」，且仅对白名单 profile 生效。
- **方案**：
  - **v1**（`55b070fd8`）：`owner/approval/skill_manage_gate.py`（gate + monkey-patch 超时/抑制 bg skill review）+ `owner/owner-extensions/skill_manage_bridge/`（`pre_tool_call` 拦截写 action、`pre_gateway_dispatch` 缓存 gateway）；`skills_list` / `skill_view` / 普通文件工具 / terminal **不**门控；gate 开启时强制关 background skill review；配置初版在 `patch.yaml` 的 `owner.approvals.skill_manage`（profile 白名单、24h 超时、`approval_home_chat_id`）。
  - **v2**（`cd937b412`）：(1) **origin 会话通知** — 审批卡发到审批专属群时，原对话 chat 同步文本「⏳ skill_manage … 审批卡片已发送…」；(2) 配置迁到 `patch_feishu_profile.yaml` 的 `feishu.skill_approval`（profile 级，非全局），命名从 skill_manage 扩为 skill_approval；(3) **自建审批卡** `owner/feishu/skill_approval_card.py`（改动概要 / 模板风险初评 / 可复制审查 Prompt），替代 `send_exec_approval`；adapter 增 `hermes_action == "skill_approval_gate"` 点击路由。
- **涉及文件**：
  - 纯新增：`owner/approval/skill_manage_gate.py`、`owner/feishu/skill_approval_card.py`、`owner/owner-extensions/skill_manage_bridge/`、`tests/owner/test_skill_manage_gate.py`
  - 配置：`owner/config/patch_feishu_profile.yaml`（`feishu.skill_approval`）、`owner/config/patch.yaml`（v1 段已迁出）
  - 侵入：`plugins/platforms/feishu/adapter.py`（薄胶水 card action 分支）、`owner/owner-extensions` plugin hooks
- **侵入类型**：plugin hook（主路径零 upstream surface）+ adapter 薄胶水（点击路由）
- **Commit**：`55b070fd8`（v1 gate）、`cd937b412`（v2 自建卡 + origin 通知 + profile 配置）
- **后续**：`9ce7369dc` — 审批卡按钮 stamp 的是 UI 文案 `approve`/`deny`，gate 只认 `once`/`session`/`always`。点绿按钮卡片 resolve 了，agent 却当 false deny 硬停。加 `_GATEWAY_CHOICE_MAP` 把 UI label 映射到 gateway token；`handle_card_click` 走 `gateway_choice`；子 profile 按钮 stamp `hermes_profile`；gate 把陈旧 `approve` 归一成 `once`。
- **后续**：`5e9d88bc79` — gate 增加 `allow_skills` 白名单（精确名 + fnmatch glob，如 `xy-*`）。原则：仅审查**配置了的** `skill_manage` 写操作，空列表 = 全部不审；只 gate `skill_manage` 等 tool，不 gate terminal 直改或手动改文件。
- **后续**：`7515dd7e03` — **容器场景 profile 匹配修复**：每个用户进程的 `HERMES_HOME` 都是挂载的 `/root/.hermes`，`get_active_profile_name()` 全部推断为 `default`，`profiles` 白名单永远匹配不上。改动：`_current_profile()` 优先读 `HERMES_PROFILE` env（容器真实身份）、fallback 到路径推断；`is_gate_enabled()` 支持 `profiles` 通配 `*`（匹配所有 profile / 用户）；`patch_feishu_profile.yaml` 的 `profiles` 改 `*` 覆盖全部用户。
- **默认值调整**：`d7d4a0fd43` — 默认关闭人审门闩，`skill_manage` 写操作不再默认发卡等人审，需要时再把 `enabled` 改回 `true`。配套 `fa44610162` 修正 diff card 注释与该默认值一致。

### 3.12 2026-08-19 代码审查修复（P0/P1/P2）

第二次代码审查（基线 2026-08-19）的修复集，跨安全、稳定性、性能三类，共 2 个 commit、40 个文件。

| 级别 | 问题 | 修复 | 文件 | Commit |
|------|------|------|------|--------|
| P0 | `_mask_quoted_newlines` 未跟踪 `$(` 嵌套与反引号替换，命令替换内的换行（真实分隔符）被掩码，可绕过硬黑名单 | 跟踪嵌套层级；补 3 个回归测试 | `tools/approval.py` | `0c48c2a8b6` |
| P1 | queue token 被消费后未 retire，同文本重新排队被静默吞掉 | 消费后 retire | `owner/patches/queue_cancel_patch.py` | `0c48c2a8b6` |
| P1 | bitable 50 表上限是死代码，未真正截断 | `_BITABLE_MAX_TABLES` 变为强制截断并在 header 提示 | `tools/feishu_client_utils.py` | `0c48c2a8b6` |
| P1 | docx 图片 cap 500 过高且无缓存预算 | cap 500→100 + 缓存预算 LRU 清理 | `tools/feishu_client_utils.py` | `0c48c2a8b6` / `56fa158790` |
| P1 | Windows SIGINT absorber 被 merge 冲掉 | 恢复 | `cli.py` | `0c48c2a8b6` |
| P1 | inbound 准入无预算、媒体失败路径吞吐差；转发超时 10s 导致双进程重复处理 | 准入加 75s 预算、媒体失败降级文本仍返 202、转发超时 10s→90s；follow-up 进一步拆为「准入只建元数据（12s）后 202，媒体在 dispatch 再下（90s）」，发送端超时 90s→20s，纯图片失败不 dispatch | `gateway/platforms/api_server.py`、`owner/feishu/profile_routing.py` | `0c48c2a8b6` / `56fa158790` |
| P1 | `cron-health-check.py` 用 `or True` 恒真条件判断今日状态 | 去掉恒真条件，按最后一条 `completed` 行精确判断；单次扫描按 `job_id` 分组（O(N×体积)→O(N)）；`table_index` 不被 50 表帽挡住；恢复日志无日期不算今天 | `owner/scripts/cron-health-check.py` | `0c48c2a8b6` / `56fa158790` |
| P2 | queue 终态 token 无超时清理、文本匹配未按 session 隔离 | 终态 token 1h 清理 + 文本匹配按 session 隔离 | `owner/patches/queue_cancel_patch.py` | `0c48c2a8b6` / `56fa158790` |
| P2 | output_guard 压缩率用字符口径致中文失效；折叠后未二次截断；mojibake 文案不符 | 改字节口径 + 折叠后二次截断 + 文案对齐；mojibake 只留首段 | `owner/owner-extensions/output_guard/__init__.py` | `0c48c2a8b6` / `56fa158790` |
| P2 | docx blocks 扫描无上限、wiki 子文档无上限 | blocks 2 万块硬上限、wiki 子文档 200 上限 | `tools/feishu_client_utils.py` | `0c48c2a8b6` |
| P2 | 凭据池过期后短路了 anthropic 外部凭据检查 | 不再短路 | `hermes_cli/model_switch.py` | `0c48c2a8b6` |
| P2 | `_CHATLOG_RE` 无日期分支会误截断 Summary 正文 | 要求后跟 `[角色]:` 行；abstract 路径同样截 ChatLog | `plugins/memory/openviking/__init__.py` | `0c48c2a8b6` / `56fa158790` |
| P2 | provider 模型缓存无主动失效入口 | 挂到 session reset；follow-up 删除挂在 `/new` 上的错误钩子，凭证写入与 model/custom_providers 配置变更改走既有 `clear_provider_models_cache` | `hermes_cli/models.py`、`gateway/slash_commands.py` | `0c48c2a8b6` / `56fa158790` |
| P2 | lark SDK 缺失时队列卡点击后静默无响应 | 仍处理队列卡并回传 raw card | `owner/feishu/queue_card.py`、`plugins/platforms/feishu/adapter.py` | `56fa158790` |
| P2 | `find_scheduled_token_for_text` 省略 `session_key` 时匹配到已绑定 token | 只匹配未绑定 token | `owner/patches/queue_cancel_patch.py` | `56fa158790` |
| P2 | 短文件尾部 U+FFFD 被误判为非法字节 | 按真非法字节处理 | `owner/patches/file_binary_detection_patch.py` | `56fa158790` |

- **涉及文件**（官方树 intrude）：`tools/approval.py`、`tools/feishu_client_utils.py`、`cli.py`、`gateway/platforms/api_server.py`、`gateway/slash_commands.py`、`hermes_cli/model_switch.py`、`hermes_cli/models.py`、`plugins/memory/openviking/__init__.py`、`plugins/platforms/feishu/adapter.py`
- **涉及文件**（owner 侧）：`owner/patches/queue_cancel_patch.py`、`owner/patches/file_binary_detection_patch.py`、`owner/owner-extensions/output_guard/__init__.py`、`owner/feishu/profile_routing.py`、`owner/feishu/queue_card.py`、`owner/scripts/cron-health-check.py`
- **侵入类型**：inline（安全/边界修复）+ owner/ 内部
- **验证**：hardline 186 / queue 13 / feishu 73 / profile transport 8 / openviking 5 全部通过；改动文件 `py_compile` 全过
- **未纳入**：`gateway/run.py` 与 `patch_feishu_profile.yaml` 的无关本地改动
- **Commit**：`0c48c2a8b6`（P0/P1/P2 首轮）、`56fa158790`（follow-up 收口）

### 3.13 2026-09-28 审批历史挖掘改按结构标记判定（T2-1）

`hermes_cli/approvals_suggest.py` 从审批历史中挖掘「隐含批准」建议时，原本用**英文文案**判定某次工具调用是否被拦截：`_BLOCK_MARKERS` 表（11 条英文片段）+ SQL `LIKE` 粗筛。i18n commit `5d85ec89ac` 把 `tools/approval.py` 的拦截文案搬进 `locales/*.yaml`，但对该文件只做了一行点状修补（补 `"正在请求用户批准"`）。于是中文环境下**双重漏检**：`t()` 返回的「已拦截：…」既不在 marker 表内，也过不了 SQL 粗筛，被用户明确拒绝的命令因此被读成「隐含批准」并进入建议列表。

| 级别 | 问题 | 修复 | 文件 | Commit |
|------|------|------|------|--------|
| P1 | 拦截判定依赖英文文案，本地化后判定表与 SQL 预过滤**同时失效**，被拒绝的命令被挖掘为「隐含批准」 | 判定改按**结构标记**，与文案语言解耦，三层：① 结果 `status` 字段（`blocked` / `pending_approval` / `approval_required` / `denied` / `rejected`）与 outcome（`denied` / `timeout` / `transport_*`）；② `locales/*.yaml` 的 **key**（语言无关结构标识，覆盖 17 种语言 44 个 `approval.*` 键）；③ 硬编码兜底表（中英，fail-open）。SQL 预过滤锚点与判定判据**同源化**，并加超集断言焊死两处漂移 | `owner/approval/approval_history_policy.py`（新建）、`hermes_cli/approvals_suggest.py`、`tests/owner/test_approval_suggest_i18n_blocks.py`（新建） | `91007c9b58` |

- **判定对象的边界**：只读结论字段（`error` / `message`），**刻意不读 `output`**。真实数据标定显示，把 `output` 纳入判定会引入 55 条误报 —— `status: "success"` 的 `cat` / `diff` 输出里恰好含 "BLOCKED" 字样（用户在讨论这些文案）。
- **标记提取口径**：从 catalog 模板取**首个**含锚点的静态片段（非最长、非按句拆分），兼顾 SQL 语义与描述自带的括号/标点。实测产出 82 个 marker，锚点未覆盖率 0。
- **涉及文件**（官方树 intrude）：`hermes_cli/approvals_suggest.py`（module 级薄委托 + `_blocked_tool_call_ids` 按 owner 锚点动态拼 LIKE；原 `_BLOCK_MARKERS` 保留为 fail-open 兜底）
- **涉及文件**（owner 侧）：`owner/approval/approval_history_policy.py`（439 行）、`tests/owner/test_approval_suggest_i18n_blocks.py`（27 例）
- **侵入类型**：薄委托（module 级 try-import + 判定/锚点两处转发）
- **验证**：真实库（`~/.hermes/state.db`，46,582 条 tool 结果）标定 —— 真拦截漏检 **0 条**、误报 **0 条**、命中 92 条，全量判定 **1.04s**（对照英文文案匹配口径：漏检 79 条、误报 55 条）。变异验证两条：还原上游文件 → `zh` 参数化用例失败并**量化错位**（`count=8` 而非 3，被拒 5 次全混入）而 `en` 仍通过，精确印证「只有本地化触发」；抽掉 catalog 文案层 → 3 例失败，证明结构层单独不够。回归：`scripts/run_tests.sh` 57 文件 / 788 例全通过（16.8s）。
- **同类普查**：全仓库按英文 `BLOCKED` 文案做**匹配判定**的生产代码仅此一处；其余出现处均为消息生产者（`owner/approval/skill_manage_gate.py`、`tools/file_tools.py`、`hermes_cli/plugins.py`）或结构化字段（`tools/skills_guard.py` 的 `status = "BLOCKED"`）。普查另得测试侧缺口：约 12 文件 40 处 `assert "BLOCKED" in result["message"]` 的英文硬断言（`HERMES_LANGUAGE=zh` 下 3 failed / 246 passed），已单独立项 **T2-22**。

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
- **后续修复**：
  - `fc6f2fbc4` — merge 冲突解决时同时保留了 owner 的 `setdefault(connection_mode)` 和上游 `.update()` 中的 `connection_mode`，`.update()` 无条件覆盖 `setdefault`，导致 `config.yaml` 中 `connection_mode: send_only` 的子 profile 容器被改写为 `websocket`。修复：从 `.update()` 中移除 `connection_mode`，仅靠 `setdefault` 维持 config.yaml > env 优先级。
  - `bc1feb536` — **harden Feishu profile transport**：加固多 profile 下消息/卡片往返传输路径。`gateway/platforms/api_server.py` 端点校验与错误路径、`owner/feishu/profile_routing.py` 路由边界、`plugins/platforms/feishu/adapter.py` 接线同步加固；新增 `tests/owner/test_feishu_profile_transport.py`（约 400 行）锁定 transport 契约，防止 merge 后子 profile 投递丢 `chat_type`/`open_id` 或错误落到 default profile。
  - `31a8005791` — **`send_card` 序列化前补 `hermes_profile` 标签**：`send_model_picker_card`（`/providers` 选择器）与 clarify 卡片走 `send_card` → lark SDK 路径，而该标签此前只在 REST 路径（`send_card_via_rest`）打上。`send_only` 容器的卡片因此未带标签到达用户，点击落在主网关（唯一 WebSocket）上，其 adapter 没有对应 `_model_picker_state` 条目 → 报「会话已过期，请重新执行 /providers」。修复：把打标签动作移入 `send_card` 本体（**序列化之前**，之后 card 已成 JSON 字符串无法再遍历/修改），门控 `_connection_mode == "send_only"`（主网关上为 no-op）；`owner/feishu/card_sender` 缺失时 fail-open，卡片照发（不带标签，旧行为）。新增 `tests/owner/test_feishu_send_card_profile_tag.py`（约 220 行）。

    该修复依赖 §7.14 的 `get_active_profile_name()` env 优先修正——容器内路径推断恒为 `default` 时，标签本身也是错的。

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
- **后续**：`5c750982d` — streaming 开关读取改为统一 `load_config_readonly()`（mtime 缓存），去掉手写 `yaml.safe_load`。

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
- **后续**：`c27120b97e` — diff card 增加 patch.yaml 开关（master + 平台级），可在配置层整体关闭而不改代码。

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
  - `ee1e29084` — `bot_menu` 新增 `agents` 菜单项与 ack（映射 `/agents`，与 usage/insights 同模式）。
  - `195996b48` — `bot_menu` 新增 `viking_human_review` 菜单项与 ack（对接 §11.6 Viking 记忆质量人工复核入口）。
  - `c6156c16f` — `/new` `/stop` 与 `/status` 对齐 `ack: null`，关掉 bot-menu dedup ack（流水线本身已有即时反馈，再 ack 是重复提示）。
  - `b83d1da12c` — `bot_menu` 新增 xy-damodel 系列模型切换菜单：8 个菜单项覆盖 `xy-damodel` / `xy-flash` / `xy-max` / `xy-pro` × session/global，配套 ack 文本。
  - `a1604a1b20` — `new` 键补 ack 文案：`/new` 重置会话耗时较长，原 `ack: null` 无即时反馈，改为 `🆕 重置会话中…` 让用户点击后立即看到响应（对 `c6156c16f` 的反向调整）。
  - `78269d5972` — **三层去重，修复网络卡死恢复后连续触发**：(1) `event_id` 精确去重（TTL 600s）拦飞书服务器对未 ACK 事件的重投递；(2) in-flight 状态机合并同 `(open_id, event_key)` 的后续点击，PENDING 超 120s 强制放行 + ERROR 日志兼作卡死探测器；(3) 保留 3s TTL 防手抖双击。`handle_bot_menu_event` 主体拆出 `_process_bot_menu_click`，`try/finally` 覆盖全部 early-return 释放 PENDING；release 带 `admit_ts` 属主校验防误释放；PENDING 条目不参与过期清理/容量驱逐；ack/fallback/guide 卡片包 `asyncio.wait_for` 15s 超时——DNS 挂起时放弃发消息但继续路由命令。背景：Clash Verge Rev TUN/fake-ip DNS 间歇抽风 → ack 网络挂起 → 用户重复点击。
  - `7c759411d9` — `bot menu` 路由 `NameError`：`try_route_bot_menu_command` 未定义 `chat_type`。

### 4.7 飞书编辑上限轮转 + 进度 dedup

- **背景**：(1) 飞书消息编辑次数达上限（错误码 230072/230075）时需要轮转到新 progress bubble；(2) progress dedup 的 `×N` 计数器会污染 markdown 代码块（插在代码块中间）。
- **方案**：
  - `owner/feishu/`（编辑上限轮转逻辑）+ adapter 薄胶水
  - `gateway/platforms/base.py`：progress dedup 计数器改为只在代码块外插入
- **侵入类型**：inline（base.py 的 dedup 计数器逻辑）+ 薄胶水（adapter）
- **Commit**：`f6d0c6030`（§11.9 编辑上限轮转）、`2be0af638`（§11.8 progress dedup 避免污染 code fence）、`add176e9b`（§11.10 extract_local_files 跳过双反引号 inline code）
- **后续修复**：`d510908961` — **接通 `_classify_edit_failure`，修复编辑上限后 tool progress 散列**。飞书 230072/230075 触发后适配器设置 `result.rotate=True`，但 `send_progress_messages` 的内联分类逻辑不检查 `rotate`，直接走到 `can_edit=False` 永久关闭编辑；AI 穿插文本回复后 `__reset__` 只清 `progress_msg_id`/`progress_lines` 而不重置 `can_edit`，导致后续 tool progress 全部散成独立消息。修复：主循环 + overflow 滚动的内联分类替换为调用已有的 `_classify_edit_failure`，新增 `rotate` 分支（丢弃旧 bubble、保持 `can_edit=True` 开新 bubble）；`CancelledError` drain 补 `progress_msg_id is None` 时的兜底发送，防止 rotate/reset 后 buffer 里的行被静默丢弃。

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
- **后续**：`04387001a` — `list_authenticated_providers` 卸到 `asyncio.to_thread`（对齐 `/model` #41289），只加载一次并用 picker 友好探测，避免 models.dev / 离线自定义端点卡死飞书 inbound。

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
  - `c812f9df5` — **卡片 invisible 根治**：post_tool_call 各 skip 路径打 WARNING；发送时从 `gateway.adapters` 解析 Feishu adapter（Platform enum + `'feishu'` 字符串）；`_submit_on_loop` 失败时 fallback `run_coroutine_threadsafe` 且不写 `_SENT_CARD_IDS`；core 透传 `agent.platform` / `agent._chat_id`；agent-loop 路径补跑 `transform_tool_result`（原先仅 gateway 路径执行）。生产证据 7/26–7/28 零发卡。

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
  - **queue 撤销队列 + 执行后冻结（个人 fork，仅飞书卡）** — `89fa171bc`：queue 提交后 done 卡增加「撤销队列」；FIFO 开始执行时 REST patch 卡片为「▶️ 已开始执行」蓝底终态。**禁止**把 token 写入 `message_id`（会当 reply_to 导致 99992354）。实现：`owner/feishu/steer_card.py` + `owner/patches/queue_cancel_patch.py`（按 prompt 文本匹配入队、`event._owner_queue_token` 打标、包装 `_enqueue_fifo`/`_dequeue_pending_event`、`cancel_queued_by_token`；并 wait 在途 prefetch 以避免 queue 紧接上轮时跳过 openviking 召回卡）。注册于 `owner-extensions`。同 commit 还补：openviking 召回全链路 INFO 诊断；各类飞书卡片发送/点击成功路径统一 `[Feishu card]` 日志。
  - `306fb0be8` — `queue_cancel_patch` 的 `_token_state` 在 cancel/enqueue/freeze 多线程并发读写，加 `_token_lock` 保护全部读写路径。
  - `354222f43` — **queue 状态卡**：入队后发飞书交互卡（原文 + 三个按钮：steer 进当前轮 / 立刻处理并打断 / 取消）；guide-card 提交的 queue 也变成同一张状态卡。非飞书保持纯文本 ack。实现：`owner/feishu/queue_card.py` + `queue_cancel_patch` 扩展 + adapter 薄胶水。
  - `7ce75a8df5` — **队首开始执行时补发底栏通知**：冻结态状态卡（REST patch）在流式输出推进后通常已被滚出可视区，队首真正开始执行时用户看不到。保留原冻结行为不变，额外在消息流底部发一张紧凑无按钮通知，列出剩余队列项。实现：`queue_card.build_queue_started_notify_card` + `queue_item_preview`；`queue_cancel_patch.notify_queue_started(adapter=)` 挂在 busy-FIFO dequeue 路径上，剩余快照在 overflow 提升**之前**取；idle 的 guide-dispatch 路径保持静默（卡片本就可见）；DM 发送时从存储的 `SessionSource` 解析 `open_id`。

### 4.12 飞书文件上传大小守卫

- **背景**：飞书文件上传超限时默认静默失败，用户不知道发生了什么。需要在超限时给出明确的错误提示。
- **方案**：`owner/feishu/` 模块中增加文件上传大小守卫，超限时向用户发送错误提示消息而非静默失败。
- **侵入类型**：薄胶水 + try-import
- **Commit**：`3ae4c4bbf`

### 4.13 feishu_doc_read：文档内嵌图片物化 + Vision OCR + 类型推断

- **背景**：`feishu_doc_read` 仅调 docx `raw_content` 时，飞书把 image block 压成文本 `image.png`，agent 看不到真实截图。完整链路需要 blocks 取 `image.token` → 下载媒体 → 本地缓存 →（可选）`vision_analyze`。另：`/sheets/`、`/base/` URL 提取 token 后若丢失类型，handler 默认 `docx` 会 1770002。
- **方案**：
  - `7230d71e9` — `tools/feishu_client_utils.py` 新增 `list_docx_image_tokens` / `download_media` / `download_docx_images` / `inject_image_paths_into_content` / `read_docx_with_images` / `analyze_docx_images`；docx 分支改走物化路径；返回 `content` + `images[]` + `image_count` + `vision_analyzed`；schema 说明可把本地路径交给 `vision_analyze`
  - `e5e90f874` — `_DOCX_MAX_IMAGES` / `_DOCX_MAX_VISION_IMAGES` 40→500；共用 `_call_with_rate_limit_retry`（HTTP 429 / Feishu 99991400 / rate-limit 文案，指数退避最多 5 次，上限 60s）
  - `4ca60433a` — `extract_token` 返回 3-tuple `(token, is_wiki, inferred_type)`：`/sheets/`→sheet，`/base|/bitable/`→bitable，`/docx|/doc/`→docx，避免 sheet URL 当 docx 读
  - `749f68abb` — `read_sheet_as_text` 去掉 grid `row_count` 尾部空行填充
  - `9cceec46f` — bitable 读取增强（防全量拉取 token 爆炸）：`read_bitable_as_text` 新增 `mode=structure`（只看表目录：表名/table_id/记录数/字段定义 + 公式标记，不拉记录）、`table_index`（1-based 单选单表，越界报错）、`limit`（覆盖默认 500 条/表）、`filter`（透传飞书 records API 过滤表达式，服务端过滤）；`_read_table_records` 返回 `(records, total)`，full 模式触顶时报告真实总数。新增 `_read_table_fields` / `_table_record_total` / `_list_bitable_tables`；`feishu_doc_tool.py` schema 加 4 参数（仅 bitable 生效，向后兼容）
  - `a1b607d2e` — wiki 文件夹节点返回一层子文档标题：`resolve_wiki_node` 改返回 3-tuple `(obj_token, obj_type, node_meta)`，`node_meta` 带 `has_child`/`space_id`/`title`（仅文件夹非 None）；新增 `list_wiki_children`（用 `wiki/v2/spaces/{space_id}/nodes` 分页 page_size=50 列一层子节点，标注 `[文件夹]`/`[文档]` + node_token，不用 `get_children` 因对深层子文件夹返回空）；handler 在 `has_child=true` 时返回 `=== 文件夹: <标题> ===` + 子项列表。普通 docx/bitable/sheet 不受影响；只列一层不递归
  - `c5e0f9beda` — **读取 docx 内嵌的多维表格块**：`feishu_doc_read` 会丢掉嵌在 docx 文档里的 bitable（多维表格）块——docx `raw_content` API 静默丢弃 `block_type=18`，而 `list_docx_image_tokens` 只扫图片。新增 `list_docx_bitable_blocks()`（从 block tree 提取 bitable token）与 `read_docx_embedded_bitables()`（按 `app_token` 去重，每表 50 条上限防 token 爆炸）；`read_docx_with_images()` 不再在 `raw_content` 为空时提前退出，并把内嵌 bitable 数据追加到返回文本。
- **涉及文件**：`tools/feishu_client_utils.py`、`tools/feishu_doc_tool.py`、`tests/tools/test_feishu_client_utils.py`
- **侵入类型**：inline（官方 feishu tools 内扩展读取路径）
- **Commit**：`7230d71e9`、`e5e90f874`、`4ca60433a`、`749f68abb`、`9cceec46f`、`a1b607d2e`、`c5e0f9beda`
- **附录 E**：2026-07-23 / 2026-07-24 条目与本节省略互补（E 偏时间线，本节钉 hash）

### 4.14 禁用 @所有人 自动响应

- **背景**：飞书群里有人 `@所有人` 时，官方 adapter 把 `@_all` 也当成「提到了机器人」，owner 的群聊策略下会自动开一轮回复。运维群、全员通知会被 bot 抢话。
- **方案**：`plugins/platforms/feishu/adapter.py` 的 `_mentions_self` 不再把 `@_all` 视为提到自己（注释保留原逻辑便于对照）。只响应**明确 @机器人**。同步改官方测试 `test_at_all_still_requires_policy_gate` 断言。
- **涉及文件**：`plugins/platforms/feishu/adapter.py`、`tests/gateway/test_feishu.py`
- **侵入类型**：inline（adapter 一处 mention 判定）
- **Commit**：`470148013`

### 4.15 合并转发消息展开（merge_forward）+ 消息分页读取

- **背景**：飞书「合并转发」消息在 adapter 里只被当作普通富文本处理，`_extract_message_content` 拿不到正文——官方行为是 `merge_forward` 类型消息需**二次拉取** `GET /im/v1/messages/{id}`（返回父消息 + N 条子消息，子消息带 `upper_message_id`）。工具侧 `feishu_doc_read` 也只认 docx/wiki/sheet/bitable token，无法读合并转发内容。
- **方案**（`2079a79fab`）：
  - **P1 接收侧**：`plugins/platforms/feishu/adapter.py` 的 `_extract_message_content` 对 `merge_forward` 消息二次拉取上述接口，用共享 renderer 渲染成可读聊天记录；失败静默回退占位文本。
  - **P2 工具侧**：`feishu_doc_read` 的 `doc_token` 支持 `om_` 前缀消息 ID，走同一 `GET` 接口拉取合并转发内容，支持 `offset` / `mf_limit` 分页；`tools/feishu_client_utils.py` 补对应读取函数。
- **共享渲染约定**（`adapter.py::_render_merge_forward_entries`）：
  - 格式 `[时间] sender短码: 正文`；`@用户名` 从 `mentions` 解析（key 与 `user_id`/`open_id` 双索引，post 的 `at` 段按 `user_id` 命中）
  - 截断上限 **100 条 / 40000 字符**，截断时保留 `message_id` + offset 续读提示（**不静默丢弃**）；分页窗口未覆盖全量时同样提示剩余
  - `image`/`file` 显示占位，嵌套合并转发显示 `[嵌套合并转发 om_xxx]`
  - dict 与 lark SDK 对象两种 `children` 形态均支持
- **涉及文件**：`plugins/platforms/feishu/adapter.py`（+202）、`tools/feishu_client_utils.py`（+33）、`tools/feishu_doc_tool.py`（+32）、`tests/owner/test_merge_forward_expansion.py`（新增 192）
- **侵入类型**：inline（adapter 接收路径 + 官方 feishu tools 扩展读取路径）
- **验证**：11 个用例（渲染 / mentions / post / 占位 / SDK 对象 / 截断续读 / 分页 / mock client 三态）；真实消息 E2E 已验证（5 条子消息全文 + `offset=3 limit=2` 分页 + 小字符上限截断提示）
- **Commit**：`2079a79fab`

---

## 五、交互语法：快捷命令与命令别名

### 5.1 链式快捷命令（;;分隔）

- **背景**：用户想在一个输入里串多个斜杠命令/提示，用 `;;` 分隔，全平台（CLI/Gateway/TUI/TS）支持。
- **方案**：在 4 个 Python 入口 + 3 个 TS 文件中增加 `;;` 分割 + 依次执行逻辑。
- **涉及文件**：`cli.py`、`gateway/platforms/base.py`（`[owner] Chained quick commands`）、`gateway/run.py`、`tui_gateway/server.py`、`ui-tui/src/app/createSlashHandler.ts`、`ui-tui/src/gatewayTypes.ts`、`ui-tui/src/lib/rpc.ts`
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

### 6.3 Ctrl+C /exit 与 graceful drain（CLI + TUI）

- **背景**：(1) prompt_toolkit 的 TUI 层 `c-c` 绑定只覆盖空闲/回合结束的常见路径；任何绕过按键层的 OS SIGINT（子 shell PTY 回弹、MCP reconnect 定时器、后台线程）会落到 Python 默认 handler，在 httpx recv 中途抛 `KeyboardInterrupt` 并逃出 `except Exception` 清理链；(2) `hermes --tui` 退出时若对 gateway 发 SIGTERM 或过早拆 MCP，任务会在 event loop 关闭后被 cancel，退出码与 `/exit` 不一致。
- **方案**：
  - `300160673` — CLI：OS SIGINT 路由到 `app.exit()`，使 Ctrl+C 语义对齐 `/exit`；顺带加固 openviking 与 `run_agent` 对中断路径的容错
  - `5d1539c99` — TUI：Python launcher 在 Node 持有 process-group SIGINT 时继续 wait；owned gateway 用 stdin EOF 关闭而非 SIGTERM；先 `session-end` 再 MCP teardown；standalone Ctrl+C 退出码 0（与 `/exit` 一致）
- **涉及文件**：`cli.py`、`hermes_cli/main.py`、`tui_gateway/{entry,server}.py`、`ui-tui/src/{entry.tsx,gatewayClient.ts,lib/gracefulExit.ts,app/useMainApp.ts}` + 对应测试
- **侵入类型**：inline（退出/中断路径）+ 纯新增测试
- **Commit**：`300160673`、`5d1539c99`

### 6.4 live compression sync 误清 providers per-model context_length

- **背景**（`efb42e6e39`）：`_apply_live_compression_config` 只读顶层 `model.context_length`。当 config 使用新版 `providers.<provider>.models.<model>.context_length` 结构、且顶层 `model` 段没有该字段时，**每轮 turn 的 sync 会把 compressor 的 override 清成 `None`**，下次 resolve 落到 256K fallback（`DEFAULT_FALLBACK_CONTEXT`）。症状：TUI statusbar 首次 resolve 显示 1m，`/new` 后欢迎信息显示 256k。
- **方案**：顶层 `model.context_length` 缺省时回退 `get_custom_provider_context_length`（按 agent 当前 model + base_url 精确匹配 `providers.*.models`），保留 per-model override；其他模型不被串值（如 `xy-damodel` 的 262144）。
- **涉及文件**：`tui_gateway/server.py`（+19）、`tests/tui_gateway/test_compression_config_hot_reload.py`（+66）
- **侵入类型**：薄胶水（TUI gateway 配置热重载路径）
- **验证**：新增 2 例（override 保留 + 多模型不串值），20/20 passed
- **Commit**：`efb42e6e39`

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
- **后续修复**：
  - `6a9383d38` — 移除 `plugins/memory/openviking/__init__.py` 中基于 `subprocess.Popen` 的本地 server auto-start。裸 Python `openviking-server`（未带 hotfix patch）会在 gateway restart 时与 Docker 容器抢端口 1933 并劫持端口。改为由 Docker 外部管理 server。同时删除对应的 `test_start_local_openviking_server_uses_endpoint_host_and_port` 测试。
  - `04b0b7ae8` — recall 注入内容截断 ChatLog，防止模型把历史对话误当当前上下文。根因：Viking memory 文件带 `YYYY-MM-DD ChatLog: [user]: ... [hermes]: ...` 段落，与 live 对话 turn 格式完全一致；长对话 + 多工具并行时 qwen3.7-max（2026-07-28 验证）会把召回的"damodel 400 排查"历史记录当成当前待办，主动开始排查并编造不存在的截图。方案：`plugins/memory/openviking/__init__.py` 加 `_truncate_chatlog_from_recall()`，按 `ChatLog:` / `Chat记录:` / 日期前缀正则截断，只保留 Summary，末尾追加 `→ For full conversation: viking_read(uri=..., level='full')` 提示；`owner/patches/openviking_owner_recall_patch.py` 改写 advisory System note，明确告知 agent "ChatLog 已被剥离，需细节时调用 `viking_read`，禁止凭 summary 编造内容"。
  - `2587260ca` — 写入端给 user/assistant 消息设置人类可读 peer_id，使 Viking 存储的对话记录不再与 live turn 格式混淆。新增 `_resolve_user_display_label()`：优先从飞书 Inbound context 提取 `user_name: \`杨天宝\`` 中文名，fallback 到 `"过去的用户"`；`_resolve_assistant_display_label()`：取 `get_active_profile_name()`（子 profile 如 `hermesxiyun`/`sunqifei`），主 profile `default` 映射为 `hermes`，fallback 到 `"过去的助手"`。两个 peer_id 通过 `_messages_to_openviking_batch(user_peer_id=..., assistant_peer_id=...)` 传入 payload，Viking 端 `MessageRange._speaker_for()` 返回 display label 而非裸 role string。测试 `test_sync_turn_structured_messages_include_assistant_peer_id` 断言同步更新。

  - `7733cabf7` — **`viking_add_resource` 超时 UX**：默认 HTTP timeout 提到 120s，client 尊重 wait timeout；超时返回可操作 payload，避免模型把 `wait=true` 超时当成硬写失败而重试/幻觉。
  - `89fa171bc`（部分）— openviking 召回全链路 INFO 诊断日志（与 §4.11 queue 撤销同 commit；见 steer_card / recall patch 侧）。
  - `2da7512f4` — 召回卡 header emoji 🧠→📚，蓝底上对比度更好。
  - `eb6a97beb2` — **peer_id slug 化，修复结构化同步 3 周降级**。根因：`2587260ca` 引入的 display label 把中文人名当 `peer_id` 发送，而 viking 服务端 `identifiers.py` 强校验 `^[a-zA-Z0-9_.@-]+$`（`peer_id` 是 peers 目录 URI 路径段 + 提取 speaker 标签）→ 每轮 batch 400 → 结构化同步降级到文本通道，自 2026-08-14 起持续（`errors.log` 日 8~52 次）。修复（对齐 viking `ingest/peer.py::safe_external_peer` 惯例）：新增 `_ascii_peer_slug()` —— 天然合法则小写原样、已知人名走登记表（杨天宝 → `yangtianbao`）、未登记非 ASCII → `ext-<sha1前10>`；user 侧 fallback 链 `Inbound 人名 → OPENVIKING_USER → unknown-user`，assistant 侧 `profile → _agent → hermes`（全 ASCII）；删除中文 fallback 值「过去的用户」/「过去的助手」（400 的另一半来源）。中文人名唯一锚点保留在 entities 实体文件，正文天然带中文名。

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

### 7.14 Gateway 生命周期消息打 active profile 标签

- **背景**：多 profile 并行跑 gateway 时，关机/重启/drain/上线等生命周期通知无法区分是哪个 profile，运维排查困难。
- **方案**：`gateway/run.py` 新增 `_gateway_profile_tag()` + `_t_gateway_lifecycle()`：default profile 的 `{profile_tag}` 为空；命名/custom profile 为 `" [<name>]"`；解析失败回退原文并 warning。生命周期相关 locale key（en/zh 等）统一加 `{profile_tag}` 占位（文案骨架变更，属功能而非纯翻译）。覆盖 shutdown/restart/drain busy-ack、model restart notices、recovered-reply markers 等。
- **涉及文件**：`gateway/run.py`、`gateway/delivery_ledger.py`、`locales/*.yaml`、`tests/gateway/test_restart_notification.py`
- **侵入类型**：inline（gateway 文案解析 helper）+ locale 占位符
- **Commit**：`8676ad980`
- **后续**：
  - `c0d01276f` — 优先读 `HERMES_PROFILE`，再从 `HERMES_HOME` 推断，多 profile 舰队显式设了 env 时标签才对。
  - `f348617f9` — 再优先 `HERMES_LIFECYCLE_LABEL`，关机/重启文案可用中文或带空格的昵称，不改 `HERMES_PROFILE` 路由 id。
- **后续修复**：`98236ad2ed` — **`get_active_profile_name` 改读 `HERMES_PROFILE` env 优先，修复容器化部署身份判定**。根因：node010 子 profile 容器把用户 `~/.hermes` 挂载为 `/root/.hermes`，路径推断恒返回 `default`，而容器身份由 compose 注入的 `HERMES_PROFILE` 声明；卡片按钮 `hermes_profile` 打标（card_sender）、skill gate、MCP identity、docker 环境标签等 **110 个调用点**全部拿到假 `default`。修法：env 值经 `_PROFILE_ID_RE` 白名单校验后直接返回（与 `gateway/run.py` 的 `_profile_label` 及 `skill_manage_gate` 既有 env-first 模式对齐）；空值 / 非法值（如 `pytest -p no:xdist` 类污染）回落路径推断，主网关 / CLI / Mac（无 env）行为逐字节不变。session key namespace 不受影响（`multiplex_profiles` 未开，`default`/`None` 均映射 `agent:main` 兼容键）。回归 936 项通过（profiles / feishu card tag / skill gate / mcp identity / docker env / kanban / gateway restart loop）。

### 7.15 Codex Responses：避免 reasoning 后空 assistant content

- **背景**：严格网关（如火山方舟 Ark）拒绝 `content:""` 为 missing `input.content`。当 reasoning 后紧跟 tool_calls 时，adapter 会产出空 assistant following item 导致整请求失败。
- **方案**：`agent/codex_responses_adapter.py` — 有 tool_calls 时跳过空 assistant following；否则发非空空格占位而非 `""`。
- **涉及文件**：`agent/codex_responses_adapter.py`、`tests/run_agent/test_run_agent_codex_responses.py`
- **侵入类型**：inline（adapter 边界）
- **Commit**：`952be6814`

### 7.16 merge 后保留 exhausted credential pool 语义

- **背景**：上游 merge 可能冲掉 owner 对「credential pool 已耗尽」的短路语义，导致继续探测/误报可用。
- **方案**：`hermes_cli/model_switch.py` 恢复 exhausted pool 的保留分支（不再把已确认空的 pool 当可重试）。
- **侵入类型**：inline
- **Commit**：`217bd8589`

### 7.17 恢复 owner display resolution wiring

- **背景**：merge 后 `gateway/run.py` 上 per-chat / long-running 显示解析又退回非 source-aware 路径，§9.1 display overrides 失效。
- **方案**：`6d5c00b51` 恢复 owner display resolution 接线（与 §7.13 第 3 点、`resolve_display_setting_for_source` 一致），并补 progress topics 相关测试。
- **涉及文件**：`gateway/run.py`、`tests/gateway/test_run_progress_topics.py`
- **侵入类型**：inline（薄恢复）
- **Commit**：`6d5c00b51`

### 7.18 Steer 模式 vision enrichment（飞书图片不丢弃）

- **背景**：`busy_input_mode=steer` 时，`_handle_active_session_busy_message` 只取 `event.text` 传给 `agent.steer()`，`event.media_urls` 被静默丢弃。飞书用户在 agent 运行期间发带图片的富文本消息（post 类型），图片被 adapter 下载到本地缓存后放入 `media_urls`，但 steer 分支不处理它们——agent 只看到用户的文字，看不到图片内容。`/queue` 路径不受影响（drain 时走完整 vision 管线），问题仅限 `/steer`。
- **方案**：
  - `owner/gateway/steer_vision.py`：`enrich_steer_with_vision(runner, steer_text, event, session_key)` — 检查 `event.media_urls`，有图片时调 `runner._enrich_message_with_vision()`（复用正常消息路径的 text-mode vision 管线，底层走 `auxiliary.vision`）把图片描述拼到 steer_text 前面。失败时 fallback 到原始 steer_text，不丢失 steer。
  - `gateway/run.py`：steer 分支加 3 行薄胶水委托（`# [owner]` 标记 + lazy import + 调用）
  - `tests/gateway/test_steer_vision_enrichment.py`：4 个测试覆盖有图/无图/失败 fallback/空文本
- **涉及文件**：`owner/gateway/steer_vision.py`（新增）、`gateway/run.py`（3 行薄胶水）、`tests/gateway/test_steer_vision_enrichment.py`（新增）
- **侵入类型**：薄胶水 / 委托（`[owner]` 标记 + lazy import + 委托到 owner/）
- **Commit**：`176b387a7`

### 7.19 lifecycle guard 遇二进制路径崩溃

- **背景**：gateway 会话里 `terminal` 执行前会扫命令，并顺着「像脚本的路径」递归打开，防止 `bash helper.sh` 里再藏 `hermes gateway restart`。用户在飞书里跑绝对路径二进制（如 `"/Applications/.../soffice" --version`）时，guard 把 Mach-O/ELF 当脚本读，整次 terminal 以 `ValueError: embedded null byte` 挂掉（2026-08-05 线上复现：soffice + Chrome）。
- **方案**（`e13cce770`，#76762 follow-up）：
  1. `_read_referenced_script` 认出 NUL 后返回 `("", False)` 而不是 `(None, False)`。`None` 表示「本地没读到」，会触发 `read_remote_script` fallback，把机器码 decode 后再递归。
  2. `terminal_tool._read_script_in_env` 自己加 NUL 检查，读到二进制立刻放弃。
  3. `Path.expanduser` / `os.open` 对带 `\x00` 的假路径吞 `ValueError`，当「不是合法路径」跳过——guard 自己不能把命令打挂。
- **涉及文件**：`cron/lifecycle_guard.py`、`tools/terminal_tool.py`、`tests/hermes_cli/test_gateway_restart_loop.py`
- **侵入类型**：inline（官方 guard / terminal 防护路径）
- **Commit**：`e13cce770`

### 7.20 后台插件发现超时死锁（启动空白屏）

- **背景**（`211614adf2`）：`_join_background_discovery()` 超时返回后，守护线程仍持有 `_discovery_lock`（RLock）；`discover_plugins()` 紧接着同步调用 `discover_and_load()`，在 `with self._discovery_lock` 上无限阻塞。表现为 hermes 启动后停在**空白屏**，只有 Ctrl+C 能退出——看起来像卡死，实为锁等待。
- **方案**：
  - `hermes_cli/plugins.py`：`discover_plugins()` 在 join 超时且后台线程仍存活时**直接返回，不抢锁**；`discover_and_load()` 改为 `acquire(timeout=15)` 限时等待，抢不到就让后台扫描自己跑完，不阻塞调用方（原 `with` 语句无超时）
  - `cli.py`：在滚动 / 清屏之前先打印 `Starting Hermes…` 并完成插件发现，让冷启动（checkout 大更新后 banner 快照失效）的等待有可见反馈
- **涉及文件**：`hermes_cli/plugins.py`（+116/-40）、`cli.py`（+12）、`tests/hermes_cli/test_plugin_discovery_join_timeout.py`（新增）
- **侵入类型**：inline（plugin 发现锁语义 + CLI 启动顺序）
- **验证**：新增测试覆盖「超时跳过」与「后台已结束则正常加载」两条分支
- **结构后续调整**（见 **§16.10**）：当时为套 `try/finally` 把上游 `with` 块内 40 行整体缩进 +4；现已改为「薄壳 + `_discover_and_load_scoped()`」，`with` 行与正文保持上游缩进，本条的早返回条件与取锁语义不变。官方文件级 diff 因此由 `+116/-40` 变为 `+123/-2`（纯缩进 39 行 → 0），并新增 `force=True` 上抛 `PluginDiscoveryLockBusy` 与 `_discovery_deferred` 可观测标志。
- **Commit**：`211614adf2`

### 7.21 出站 message_id 落库 + 全路径日志

- **背景**（`d74762a04e`）：发送成功后平台返回的 `message_id` 此前只存在于内存——日志不打、库里不存，想撤回 / 编辑 / 加表情回应都拿不到那个 ID，只能靠翻代码猜。
- **方案**：
  - `gateway/delivery_ledger.py`：`delivery_obligations` 加 `platform_message_id` 列 + 部分索引；`mark_delivered(oid, message_id=None)` 落库，传 `None` 表示「不覆盖已有值」（**两条 UPDATE，非 COALESCE**，语义不同）
  - **新列必须同时写进 `CREATE TABLE` 与 ALTER 对账循环** —— 只改 DDL 的话，`CREATE TABLE IF NOT EXISTS` 在已存在的 `state.db` 上是 no-op，列永远加不上
  - `gateway/platforms/base.py`：把 `SendResult.message_id` 透传给 `mark_delivered`
  - `plugins/platforms/feishu/adapter.py`：`_finalize_send_result` 统一打 `[Feishu] Sent chat_id=… message_id=…`，一处覆盖 text/post/edit/file 全部路径；8 个调用点透传 `chat_id`；删除死变量 `_sent_message_ids_to_chat` / `_sent_message_id_order`
  - `hermes_cli/send_cmd.py`：非 json 模式输出 `sent message_id=om_xxx`；无 id 时仍打 `sent`，向后兼容
- **迁移**：随代码自动生效（`_connect` 每次跑 schema 对账），其他环境 pull 后重启 gateway 即可，**无需手工 ALTER**；旧代码读已迁移的库不受影响
- **已知边界**：`_prune()` 只留 7 天 / 500 行——这是崩溃恢复账本不是审计日志；cron/CLI 的 `_standalone_send` 绕开 gateway，日志有 id 但库里没有
- **涉及文件**：`gateway/delivery_ledger.py`（+99）、`gateway/platforms/base.py`、`hermes_cli/send_cmd.py`、`plugins/platforms/feishu/adapter.py`（+76）、`tests/gateway/test_delivery_ledger.py`、`tests/plugins/platforms/feishu/test_finalize_send_result_logging.py`
- **侵入类型**：inline 列扩展 + schema 对账 + 薄胶水
- **验证**：feishu 日志 12 例 + ledger 8 例（含迁移、幂等、不覆盖、以及 `INSERT OR REPLACE` 会重置行的既有语义），本组 72 passed
- **Commit**：`d74762a04e`

### 7.22 Skills 索引 LRU 命中按磁盘 manifest 复验（手动落盘 skill 免重启可见）

- **背景**（`48f8a6e6f8`）：系统提示里的 `<available_skills>` 索引有进程级 LRU（key 只含配置态：目录路径/工具集/平台/禁用集/compact 类别，**不含任何磁盘状态**），命中直接返回——磁盘快照层（`.skills_prompt_snapshot.json`，manifest 校验本来能抓住文件变化）永远没机会执行。scp / git pull 手动落盘的 skill（node010 实例：kuaidi100-skill 10:37 落盘，11:09 新会话索引无此 skill，agent 自由发挥撞反爬）对长活网关内所有**新会话**不可见，只能重启。官方安装路径（skill_manage / skills_hub / web 面板 / Bot Chat 能力刷新）都主动调 `clear_skills_system_prompt_cache()`，所以上游自身没有这个盲区。
- **方案**：
  - `agent/prompt_builder.py` 3 处：`_SKILLS_PROMPT_CACHE` 值 `str` → `(manifest, prompt)`；LRU 命中时重建 manifest 比对——磁盘未变返回缓存对象（保留 `is` 同对象语义），磁盘变化弃缓存走快照/冷路径重建；写入时随 prompt 存 manifest
  - 成本：每次**新会话**建 prompt 多一次 os.walk + per-file stat（~200 skills 个位数毫秒）；延续会话不走此路径（逐字恢复存储的 prompt 字节），prompt cache 前缀不变量不破
- **侵入类型**：inline（缓存数据结构 + 读写点 3 处，均带 `[owner]` 标记，无缩进重排）
- **涉及文件**：`agent/prompt_builder.py`（+32/-4）、`tests/agent/test_prompt_builder.py`（+36：scp 语义落盘不清缓存 → 索引可见；磁盘未变 → 同对象复用）
- **验证**：`tests/agent/test_prompt_builder.py` 69 passed 1 skipped（含新用例）；node010 部署重启后实测：磁盘快照 137 → 138（恰好 +kuaidi100-skill），`build_skills_system_prompt()` 索引含该 skill，网关 active 无异常
- **Commit**：`48f8a6e6f8`

---

### 7.23 /stop 打在 runner 构造窗口期留下「孤儿轮次」（stop-orphan-run）

- **背景**：`/stop` 落在「槽位=sentinel、真 agent 还在后台线程异步构造」的窗口期时，`_interrupt_and_clear_session` 对 sentinel 只做「清槽 + bump generation」（`run.py:29168` 的 `is not _AGENT_PENDING_SENTINEL` 守卫），随后 `track_agent()` 因 generation 不匹配**只打一行日志就跳过提升**（`run.py:31285-31293`，`b7bdf32d4e` 引入，Closes #11016）——被跳过的那个 run 没人中止，继续在 executor 里跑 `run_conversation`，并在轮次开头就持有 durable session turn lease（`state.db::session_turn_leases`，TTL 300s / 等待上限 1800s）。于是同时出现：**内存槽空**（后续消息被判「会话不忙」→ 走冷路径起新轮次）+ **租约被占**（新轮次抢不到 → 排队，每 15s 一条「⏳ 仍在等待此会话上的另一个 Hermes 进程」）。单一飞书会话下整个 DM 被堵住（node010 2026-09-20 15:24 实测，holder `pid=3174368…platform=feishu` 就是网关自己）。
- **方案**：
  - `gateway/run.py::track_agent()` stale 分支：+8 行（3 行 `[owner]` 注释 + 5 行 try/except 委托），**不改动任何既有行**
  - `owner/patches/stop_orphan_run.py`（新增）：`cancel_stale_run()` = 判开关 → 去重（同一 `(session_key, run_generation)` 只补一次）→ `agent.interrupt_compat.request_hard_interrupt(agent, "Stop requested (stale run cancelled)")`（与 `/stop` 同一条 API）→ 孤儿在下一个检查点退出，轮次 finally 释放租约；全程 fail-open
  - 行为开关：`patch.yaml → owner.gateway_stop_orphan.enabled`（缺省 `true`，缺 section 也按 true）
- **为什么不是零源码改动（P1）**：判「这个 run 是不是孤儿」需要同时拿到「generation 已过期」和「agent 对象」，两者在 `track_agent()` 里都是闭包局部量（`run_generation` / `agent_holder`），外部拿不到；「/stop 时按 session_key 打标记、轮次入口消费」的替代方案会误伤 `/stop` 后紧接着发来的正常消息（用户常见操作），故在唯一精确位置做 5 行委托
- **上游状态**：`upstream/main @ 9573f44ca5`（2026-09-19）**未修** —— `gateway/run_turn.py::_run_agent_track_agent` 照样 skip+return；`gateway/run_agent_cache.py::_interrupt_running_turn` 照样对 sentinel 跳过中断（注释 "the pending-sentinel /stop has no in-flight work"）；`agent/` 全目录 0 处 `run_generation` 引用（run 自身无法感知过时）
- **涉及文件**：`gateway/run.py`（+8）、`owner/patches/stop_orphan_run.py`（新增）、`tests/owner/patches/test_stop_orphan_run.py`（新增 11 例）、`owner/docs/design/gateway-stop-orphan-run/stop-orphan-run.md`（新增）
- **侵入类型**：薄胶水 / 委托（`[owner]` 标记 + 全部实现在 `owner/`，**非 monkey-patch**）
- **验证**：`tests/owner/patches/test_stop_orphan_run.py` 11 passed；连同既有 `tests/owner/patches/` + `tests/owner/test_contract_entrypoints.py` 共 102 passed（1 failed 为既有失败 `test_cron_run_job_sets_cron_contextvar_on_real_agent_path`，已 `git stash` 复现确认与本改动无关）；契约测试 `test_gateway_glue_is_wired` 断言 5 行胶水仍在（merge 丢失立即红）。**生效需重启 gateway**：2026-09-20 只同步代码到 node010，未重启
- **回滚**：删除那 5 行 `[owner]` 委托即完全回滚；或 `patch.yaml` 开关秒级关闭
- **Commit**：`2110ea27eb`

---

### 7.24 沉默期进度旁白（progress_explainer）

- **背景**：网关长任务运行时用户「零信息」——工具面包屑在 QQ 上直接丢弃（无 `edit_message`）、reasoning 只在最终回复出现、心跳 `⏳` 间隔本机 600s 且优先原地编辑不弹新消息；上一对话跑 10 分钟全程静默即此因（progress-explainer 只提交了设计稿 `bfc514db0c`，未实现）
- **方案**：per-turn 装一个 tick 任务（默认 5s 周期）：连续 `silence_seconds`（60）无用户可读内容 → 调辅助模型（`auxiliary.progress_explainer`，未配置回落主模型）生成三段式说明（在做什么/依据/接下来），以独立消息投递（`🧭 系统提示：` 前缀 + 第二行实时事实，事实取 `get_activity_summary()` 不由模型生成）；四分支判定（工具型/生成型·有推理流/生成型·无推理流/停滞型）+ stream_guard tripped 让位 + digest 哈希去重 + `max_per_turn` 封顶
- **模块**：`owner/progress_explainer/`（config/tracker/digest/prompt/explain/dispatcher/__init__ 7 模块）；证据源 4 条：tool_progress 回调包装、`on_stream_delta`（经 owner-extensions 聚合器注册，同 stream_guard 模式）、tool_gen 回调（「正在生成 write_file 参数」）、interim 散文（重置静默计时）
- **侵入类型**：薄胶水（`gateway/run.py` 心跳创建点 +21 行安装 / finally +6 行停止，全部 `[owner]` 标记 + fail-open try/except；官方字面 diff 中注释占 10 行）
- **配置**：`patch.yaml → owner.progress_explainer.*`（enabled 默认 **false**，落地不改变现有行为；**模型 provider/model 也在本段**，未配置回落主聊天模型，不进 config.yaml auxiliary.\*）；三级查找 chats.platforms→platforms→enabled；`silence/stall/min_interval/max_per_turn/tick/events_in_digest/chars_per_event/reasoning_tail_chars/explainer_timeout_ms`；`config.yaml plugins.stream_reasoning_deltas: true` 为推理流证据源前置（本机已开，2026-09-17）
- **stream_guard 协作**：新增公开只读 `snapshot(session_id, turn_id)`（`_STATE` 锁内聚合 total_chars/tripped/signals），progress_explainer tick 时读，tripped → 静默让位不发
- **涉及文件**：`owner/progress_explainer/`（新增 7 模块 1249 行）、`gateway/run.py`（+27）、`owner/owner-extensions/__init__.py`（+14 聚合器接线）、`owner/owner-extensions/plugin.yaml`（+1 hooks 声明）、`owner/owner-extensions/stream_guard/__init__.py`（+34 snapshot）、`tests/owner/test_progress_explainer.py`（新增 18 例）、`owner/docs/design/silent-progress-narration/progress-explainer.md`（状态行改已实现）
- **验证**：`tests/owner/test_progress_explainer.py` 18 passed（打点/阈值边界 59-60-61/让位/静默失败/生命周期/三级查找）；`tests/owner/test_stream_guard.py` 20 passed（snapshot 无回归）；`gateway/run.py` py_compile 通过。E2E（真网关 + 临时 HERMES_HOME）未跑 [未验证]；启用需 patch.yaml + 网关重启
- **回滚**：删 run.py 两处 `[owner]` 胶水即完全回滚；或 patch.yaml `enabled: false` 秒关

---

### 7.25 审批卡命令解说（approval_explainer）

- **背景**：hermes 触发 approval 时审批卡上只有命令原文 + 官方规则 description，不懂具体命令的用户无从判断该不该批准；进度旁白（§7.24）解决了「过程零信息」，本功能解决「决策零信息」
- **方案**：审批卡投递时刻（两端 `send_exec_approval` 内、建卡前）调辅助模型生成 2-3 句「这条命令做什么 / 风险特征（是否删除/覆盖/杀进程、可不可逆、影响面）/ 批准前注意什么」，嵌入卡内 `📖 命令解读` 段（飞书 md 追加 + QQ `ApprovalRequest.explanation` 渲染）。**触发时机严格与 approvals 卡片 1:1**（并发相同命令由 `_await_gateway_decision` coalescing 保证单卡）——不是定时器、不是每条命令；审批不发卡的三条路径（纯文本 fallback / submit_pending 队列 / CLI）不在范围。prompt 硬约束：**绝不输出批准/拒绝建议**（决策权留用户）、绝不编造、≤3 句、temperature=0。输入已双重脱敏（`redact_sensitive_text` + `_redact_approval_command`），不含会话上下文
- **模块**：`owner/approval_explainer/`（config/prompt/explain/__init__ 4 模块，无 tick 无 tracker——比 progress_explainer 简单得多）；同命令 TTL 缓存（600s/128 条）；`explain_command` 永不抛（fail-open：超时/失败 → 空串 → 卡片照发无解说段）
- **侵入类型**：薄胶水（`plugins/platforms/feishu/adapter.py` +22 行、`gateway/platforms/qqbot/adapter.py` +19 行、`gateway/platforms/qqbot/keyboards.py` +10 行，全部 `[owner]` 标记 + fail-open try/except；`tools/approval.py` / `gateway/run.py` **零改动**）；飞书建卡复用既有 `owner/feishu/approval.py`（`build_approval_card` 加 `explanation` 参数，空串时卡片与原行为字节一致）
- **配置**：`patch.yaml → owner.approval_explainer.*`（enabled 代码默认 **false**，本机实配 true；timeout_ms 默认 30000；platforms feishu/qqbot；三级查找同 diff_card）。**模型（2026-09-20 定稿，与 progress_explainer 统一语义）**：provider/model 空（或 `auto`）→ 传 None → `call_llm(task="approval_explainer")` 走 auxiliary auto 链——config.yaml `auxiliary.approval_explainer` 任务段有配置按其生效，否则回落主聊天模型（承接 hermes 配置体系）；显式值直连最高优先
- **同批对齐 §7.24**（progress_explainer 顺手改）：`_DEFAULT_TIMEOUT_MS` 15000→30000；config 默认段加 provider/model（"auto"→空归一）；patch.yaml `provider/model: auto` + `explainer_timeout_ms: 30000`——旁白模型同样默认 auxiliary auto
- **涉及文件**：`owner/approval_explainer/`（新增 4 模块）、上述 3 个官方文件胶水、`owner/feishu/approval.py`（+explanation）、`locales/zh.yaml` / `locales/en.yaml`（各 +2 key：`feishu_explanation_label` / `qqbot_explanation_label`）、`owner/config/patch.yaml`（§7.25 段 + §7.24 修订）、`tests/owner/test_approval_explainer.py`（新增 20 例）、`owner/docs/design/approval-command-explainer/approval-explainer.md`（新增）、`owner/progress_explainer/{config,explain}.py`（对齐改动）
- **验证**：`tests/owner/test_approval_explainer.py` 20 passed（三级查找/auto 归一/非法回落/fail-open 异常+超时/缓存命中+不命中+TTL 过期/引号剥离/飞书卡嵌入+空串字节一致/QQ 渲染+空串跳过/i18n zh+en key 存在性）。回归全绿：`tests/tools/test_approval.py` 128、progress_explainer 25、`tests/owner/` 审批卡系列（fail_card/notice_card/patch_allowlist/skill_script 16/memory routing/send_card_profile/skill_manage_gate 93）、`tests/plugins/platforms/feishu/` 12、`test_slack_approval_buttons` 20。`tests/gateway/test_feishu_approval_buttons.py` 4 例为存量环境性失败（`git stash` 后同样失败，与本功能无关）。E2E（真网关触发一次审批观察 📖 段）[未验证]，生效需网关重启
- **回滚**：删 3 处 `[owner]` 胶水即完全回滚；或 patch.yaml `enabled: false` 秒关（卡片回到原样）

---

### 7.26 英文回复中文解说（english_explainer）

- **背景**：`display.language: zh` 时 agent 偶发整段英文终局回复，用户需要与进度旁白（§7.24）同形态的中文解说旁白（飞书 notice 卡）；中文里夹英文术语不应误触发
- **方案**：经 owner-extensions 的 `transform_llm_output` + `pre_gateway_dispatch` 接线（不改原文，始终 `return None`，避免抢 `output_guard` first-wins）；剥离代码块后用英文虚词/语气词密度 + 低中文占比判定整段英文 → 后台线程 `call_llm(task="english_explainer")` 带上下文翻译 → `adapter.send("🔤 系统提示："+译文)`；顶级约束 `get_language()` 须 `zh*`；配置仅 `patch.yaml`
- **模块**：`owner/english_explainer/`（config/detect/prompt/explain/hook/__init__ 6 模块）
- **侵入类型**：零官方源码侵入（仅 owner-extensions hook + `owner/feishu/auto_card.py` 默认 notice 规则）
- **配置**：`patch.yaml → owner.english_explainer.*`（enabled 代码默认 **false**，本机实配 true；provider/model 本机 `damodel` / `xy-flash`）；空/`auto` → `call_llm(task="english_explainer")` auxiliary auto 链（承接 hermes 配置体系）；三级查找同旁白；`feishu_card.notice_titles` 增英文解说规则（热读）
- **涉及文件**：`owner/english_explainer/`（新增 6 模块）、`owner/owner-extensions/{__init__.py,plugin.yaml}`、`owner/feishu/auto_card.py`（默认 notice）、`owner/config/patch.yaml`、`tests/owner/test_english_explainer.py`（新增 11 例）、`owner/docs/design/english-reply-explainer/english-explainer.md`
- **验证**：`tests/owner/test_english_explainer.py` 11 passed（判定/配置三级查找/前缀钉死/hook 不改原文）。E2E（真网关偶发英文回复观察 🔤 旁白）[未验证]；全新 hook 需进程加载 owner-extensions 后生效（本次按约定不重启 gateway）
- **回滚**：patch.yaml `enabled: false` 秒关；或撤 owner-extensions 两处 hook 声明/接线
- **Commit**：`9d4f17a6a1`

---


### 7.27 出站剥 DeepSeek BOS/EOS 泄漏（outbound_special_token_scrub）

- **背景**：damodel/`xy-pro` 等偶发把 DeepSeek 词表 BOS/EOS（`<｜begin▁of▁sentence｜>` / `<｜end▁of▁sentence｜>`）decode 成可见正文；本机 `interim_assistant_messages: true` 时会进飞书旁白。同根因还曾出现空工具名拒收、terminal 参数 JSON 漏进正文（JSON 另案，不在本条）
- **方案**：出站边界按**字面量**剥 BOS/EOS（全 provider，不限模型 id——该字形序列足够特异，且避免为 damodel 门控在出站链路补传 provider）；整段仅特殊符 → 空串不投递；夹在正文中 → 只删控制符
- **模块**：`owner/outbound_special_token_scrub.py`（`scrub_outbound_text`）
- **侵入类型**：薄胶水 fail-open（`gateway/run.py` `_sanitize_gateway_final_response` +1 委托；`run_agent.py` interim 两条出站路径各 +1 委托，全部 `[owner]`）
- **配置**：无（字面匹配即生效；无需 patch.yaml）
- **涉及文件**：`owner/outbound_special_token_scrub.py`（新增）、`gateway/run.py`、`run_agent.py`、`tests/owner/test_outbound_special_token_scrub.py`、`owner/docs/design/outbound-special-token-scrub/`
- **验证**：`tests/owner/test_outbound_special_token_scrub.py` 8 passed（纯 BOS/EOS→空、前缀剥留正文、sanitize 飞书面）。E2E（真网关再打出裸 BOS）[未验证]；需网关重启加载胶水
- **回滚**：删三处 `[owner]` 委托即回滚

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

### 8.4 verify-on-stop 对创意 / 视觉产物抑制 nudge

- **背景**：turn 结束 verify-on-stop 会在「改了代码却无验证证据」时注入 follow-up；`_NON_CODE_VERIFY_EXTENSIONS` 原先只覆盖 prose（`.md`/`.txt` 等），编辑 `.svg`/`.html`/`.png`/`.pptx` 等仍被当成 coding edit，连续 nudge 写 ad-hoc 校验脚本，与 CODING_VERIFY_GUIDANCE「创意 UI/视觉先等用户确认」矛盾。
- **方案**：`21543bcfc` - 扩展 `_NON_CODE_VERIFY_EXTENSIONS`（svg/html/png/jpg/pdf/pptx/fig/sketch 等），无运行时语义的视觉/文档产物直接 suppress nudge；单测 `tests/agent/test_verification_stop.py`。
- **涉及文件**：`agent/verification_stop.py`、`tests/agent/test_verification_stop.py`
- **侵入类型**：inline（扩展 allowlist 常量）
- **Commit**：`21543bcfc`

### 8.5 read_file UTF-8 边界误判 binary 修复

- **背景**：`read_file` 偶发把 `.py` 等文本文件当作二进制拒绝读取。根因是 `head -c 1000` 按字节采样，多字节 UTF-8 字符（CJK/emoji）横跨第 1000 字节边界时被切断，残缺尾字节解码成 `U+FFFD`；commit `021a07688` 引入的"样本含 U+FFFD 即判 binary"规则无法区分"真·非法字节"和"采样截断伪影"，导致合法 UTF-8 文件被误判。多字节字符越密命中率越高，表现为偶发。
- **方案**：运行时 monkey-patch `ShellFileOperations._is_likely_binary`——截断伪影只会出现在解码样本最后一个字符（只切一个字节位），据此剥离尾部 U+FFFD 后重新检查；中部 U+FFFD 仍判 binary（保留 `021a07688` 防 mojibake 意图）。官方源码零改动。
  - `owner/patches/file_binary_detection_patch.py`：补丁实现（apply/revert）
  - `owner/owner-extensions/__init__.py`：plugin register 时 apply
  - `owner/docs/read-file-utf8-boundary-fix.md`：设计文档
  - `tests/owner/patches/test_file_binary_detection_patch.py`：四场景 E2E 回归（边界截断/中文前缀/真垃圾字节/GBK）+ 幂等 apply/revert
- **侵入类型**：运行时 patch（官方文件零改动）
- **Commit**：`f457a0fb8`

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
- **方案**：`cron/jobs.py`（`# [owner] cron job args support: normalize`）+ `cron/scheduler.py`（`# [owner] map stored job args to CLI flags`）+ `tools/cronjob_tools.py`（`# [owner] validate and normalize/store`）。
- **侵入类型**：薄胶水（`[owner]` 标记的三处参数处理）
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

### 11.6 Viking 记忆质量治理流水线

- **背景**：OpenViking 中堆积多语言/重复/未审核偏好记忆，需要 **只读扫描 → 人工复核 → 可选修复** 的治理链，而不是静默 auto-write。
- **方案**（脚本均在 `owner/scripts/`，cron `no_agent=True` 友好）：
  - `f1d1fb109` — `viking-memory-quality-scan.py`：按 stopword 密度检测非中文记忆，经 LLM 译为 zh-CN
  - `1a1f0e7fa` — 拆为只读分析工具包：共享库 `viking_memory_lib.py`；`viking-memory-quality-scan.py` 改为 read-only；新增 `viking-memory-dedup-scan.py`（dense vector 近重）、`viking-memory-fix.py`（延后修复 worker，默认只 summary 不 auto-write）、`viking-memory-pipeline.py`（统一编排）、`viking-memory-quality/` CLI 入口 + README
  - `80434b966` — 治理标签 `human_reviewed` / `human_reviewed_at`；Layer-3 `scan_preference_candidates()`；translate 优先于 similar 的 defer 策略；`include_english` 默认改为 True
  - `573f7ac52` — pipeline tier3 preference 输出 + `--preference-limit`；`viking-quality-kanban-run.sh`（scan/apply/pref/status）；`viking-quality-pref-review.py`（人工复核打标 CLI）
  - 飞书入口：`195996b48`（§4.6 `viking_human_review` bot_menu）
- **涉及文件**：`owner/scripts/viking_memory_lib.py`、`viking-memory-*.py`、`viking-quality-*`、`viking-memory-quality/`
- **侵入类型**：纯新增（脚本；不进 agent 核心 tool schema）
- **Commit**：`f1d1fb109`、`1a1f0e7fa`、`80434b966`、`573f7ac52`、`195996b48`

### 11.7 Upstream Sync（上游同步流水线）

- **背景**：owner 分支需持续吸收 `upstream/main`，同时避免把 owner 专属修复/胶水冲掉或重复解决已 backport 的 bug。需要可配置的 **fetch → 分类 → dry-run → merge → 通知** 流水线，而不是手工 git 运气。
- **方案**：
  - 核心库 `owner/sync/`（`f05e2dd7e`）：classifier / config / fingerprint / gitops / health / merger / models / notifier / report / state
  - 配置与指纹库（`4e076c9b0`）：`owner/config/upstream_sync.yaml`（repo/cron/D1–D7 分类/fingerprint/通知）、`owner/validation/fix_fingerprints.yaml`（owner bugfix 指纹，检测上游 backport 重叠）
  - CLI + cron（`1f24486b5`）：`owner/scripts/upstream_sync.py`、`upstream_sync_cron.sh`
  - 文档与测试（`81afb5256`）：`owner/docs/upstream-sync-guide.md` + `tests/owner/test_upstream_sync/*`（13 文件）
  - 后续（`8ee7ca57d` 部分）：architecture / PRD / kanban 文档；`owner/sync/kanban_ticket.py` + 测试，把 sync 发现的工作项落到 kanban
- **涉及文件**：`owner/sync/*`、`owner/scripts/upstream_sync*`、`owner/config/upstream_sync.yaml`、`owner/docs/hermes-upstream-sync-*.md`、`owner/docs/upstream-sync-*.md`
- **侵入类型**：纯新增（不侵入官方运行时路径；运维侧工具）
- **Commit**：`f05e2dd7e`、`4e076c9b0`、`1f24486b5`、`81afb5256`、`8ee7ca57d`（docs + kanban_ticket）

### 11.8 增量备份体系（rsync / NewAPI / OpenViking / BACKUP_QUIET）

- **背景**：早期 `hermes-backup.sh` 为 tar+scp 全量，大目录与频繁 cron 成本高；NewAPI 与 OpenViking 数据也需独立日备。
- **方案**：
  - `8b443c20e` — `hermes-backup.sh` 改为 **rsync + hardlink 快照**；新增 `openviking-backup.sh`（`~/.openviking`）；支持重试与远端归档轮转
  - `79b2c5c71` — `newapi-backup.sh`：node010 NewAPI（MySQL docker backup + app/config tarball，保留最近 3 份，单 SSH 会话）
  - `5a5956baa` — `BACKUP_QUIET` 接入 backup log 函数（newapi/openviking），静默 cron 不刷屏
  - `30c449bd4` — 恢复 `hermes-backup.sh` 的 `BACKUP_QUIET` 静默模式（回归）
  - `8ee7ca57d`（部分）— newapi 备份目录迁至 `hermes-backup/yangtb/newapi`；`cron-health-check.py` 增加 node010 bifang-backup 巡检
  - `8c00a813f` — 三个备份脚本解析 cron 传入的 `--BACKUP_QUIET VALUE`（及 hermes 的 `--timeout_seconds` 透传忽略），与 scheduler 参数形态对齐
- **涉及文件**：`owner/scripts/hermes-backup.sh`、`openviking-backup.sh`、`newapi-backup.sh`、`cron-health-check.py`
- **侵入类型**：纯新增 / 脚本改写
- **Commit**：`8b443c20e`、`79b2c5c71`、`5a5956baa`、`30c449bd4`、`8ee7ca57d`（部分）、`8c00a813f`

### 11.9 飞书周会脚本、Swagger/Kanban 工具与 image_gen 预设

- **背景**：运维侧还有若干「不进 agent 核心、但进 owner 日常」的能力，集中记在此节。
- **方案**：
  - `3d53da788` — `owner/scripts/feishu_weekly_ops.py`：读飞书 wiki 周会表，按列抽取指定周（`--col` / `--list` / `--dump-json`）
  - `8ee7ca57d`（部分）— Swagger 变更采集与拆分：`swagger-change-collector.sh`、`swagger-split-blocks.sh`、`swagger-kanban-run.sh`；配合 §11.7 `kanban_ticket`
  - `8ee7ca57d`（部分）— `owner/config/patch.yaml` **image_gen 预设**：`qwen-pro`（dashscope qwen-pro）、`wan2-pro`（Wan 2.7 Pro）、`image-edit`（qwen-image-edit-plus，支持 mask/instruction 编辑）
  - `fde14c096d` — `swagger-kanban` scan 流水线增加 **T4 自修复卡**：T3 报告完成后自动创建 T4 fix 子卡（`parent: t3_id`），流水线从 T0→T1→T2→T3 扩展为 T0→T1→T2→T3→T4(fix)。
  - `ac1a3b9f4a` — `swagger-kanban-run.sh` 增加 **review 人审门闩模式**：从 T3 报告解析 `CONFIRMED` 数量，有问题才建 T4 人工门闩卡，worker 整理中文清单后 block 等人审；无 `CONFIRMED` 则跳过。
  - `61375e20c5` — 新增 `owner/scripts/token_cost_estimate.py`：从 `state.db` 统计近 N 天 token 用量，按北京时间高峰（9-12、14-18）/ 空闲分时计价估算费用。计价口径：`input_tokens` → 输入未命中，`cache_read_tokens` → 输入命中（独立计数），`output_tokens` → 输出；支持 `--assume-ark-cache`——ark 套餐渠道不返回缓存命中字段，按其他渠道平均命中率（94%）重算。实测 30 天：按原始口径命中率 79.3% / ¥452，重算后 94% / ¥191。
  - **`swagger-split-blocks.fixed.sh`（保留副本，2026-09-23，T0 `t_25290f2f`）** —— 与 `swagger-split-blocks.sh` 相同但修正两处缺陷，**是这两处修正的唯一副本**（2026-09-29 核实：正式脚本对 `FIX-1`/`changed_worktree` 关键词各命中 **0** 次）：
    - **FIX-1**：`route_snippet` 的 `func_names` 缺 6 个 `Register` 函数（`ChannelRegister` / `AgentRegister` / `BareMetalRegister` / `CloudDiskRegister` / `InboxRegister` / `SMSRegister`），连对应模块键（`agent` / `baremetal` / `cloud_disk` / `inbox` / `sms`）也没进 `other` 的 fallback ⇒ **244 条路由只有 204 条进入 snippet**，T1 无法交叉核对那 40 条 `@Router`。已对本仓正式脚本逐一核对，缺陷成立。
    - **FIX-2**：`changed_files` 只统计 **git 已提交**变更，**工作区未提交改动被忽略**（当时是 6 个 handler 文件）；改为 已提交 ∪ 工作区改动，并新增 `changed_committed` / `changed_worktree` 两个字段（`git status --porcelain`）。
    - **接线缺口（保留它的理由，也是它的现状）**：`swagger-kanban-run.sh:82` 调的仍是**正式名** `~/.hermes/scripts/swagger-split-blocks.sh` ⇒ **这两处修正目前不在生效路径上**。两文件 `bash -n` 均通过、差异 63 行，与 `~/.hermes/scripts/` 下同名副本逐字一致。落地方式二选一（需先能跑到 `starryshore-manager` 工程验证）：把两处并进正式脚本，或让 `swagger-kanban-run.sh` 改指 `.fixed.sh`。
- **涉及文件**：`owner/scripts/feishu_weekly_ops.py`、`owner/scripts/swagger-*.sh`（含 `swagger-split-blocks.fixed.sh`）、`owner/scripts/token_cost_estimate.py`、`owner/config/patch.yaml`
- **侵入类型**：纯新增（脚本 + 配置）
- **Commit**：`3d53da788`、`8ee7ca57d`、`fde14c096d`、`ac1a3b9f4a`、`61375e20c5`

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
- **后续**：`e21239389` — 新增 `owner/validation/merge_loss_audit.py`（合入后做 volume / glue-loss / arch / orphan 审计）；`anchors.yaml` + `inventory.yaml` 跟上游 main schema split 对齐（DDL 在 `hermes_state_common`，cron ContextVar 已是官方原生）。

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

## 十四、output_guard：LLM 输出复读/乱码/超长检测与折叠

- **背景**：2026-08-12 `ark-agent-plan-deepseek-v4-flash` 在 git 推送确认场景陷入复读死循环，单条输出 **265,518 字符**（"确认就推。默认不推 upstream。"反复数百遍）刷屏。根因是模型级输出退化 + 未设输出上限（无 `max_tokens` 时落到渠道超大默认值）。已加全局 `model.max_tokens: 16000` 在 API 层兜住膨胀；本功能补**第二道防线**：在响应发送给用户之前识别并修正退化输出。
- **方案**：owner-extensions 插件注册 `transform_llm_output` 钩子（`agent/turn_finalizer.py:556`，非流式响应发送前最后一环，返回非空字符串即替换最终响应）。多重信号判定（句子级 top-1 重复率 / 独有句占比 / zlib 压缩率 / U+FFFD 乱码占比 / 长度护栏），组合阈值防误伤；命中后段落级去重折叠或截断，并附警告标注（重复次数、占比、原始长度、模型）。fail-safe：任何异常返回 None，保持原样。
- **涉及文件**：
  - 纯新增：`owner/owner-extensions/output_guard/__init__.py`（检测 + 折叠 + 钩子注册）、`owner/owner-extensions/output_guard/selfcheck.py`（策略自检）、`owner/docs/output-guard-design.md`（设计文档）
  - 侵入：`owner/owner-extensions/plugin.yaml`（hooks 列表加 `transform_llm_output`）、`owner/owner-extensions/__init__.py`（register() 聚合注册）——均为 owner-extensions 插件自身，**无官方文件侵入**
- **侵入类型**：零（P0 hook/plugin 实现，官方源码零改动）
- **验证**：构造复读/低信息/乱码/超长样本跑策略单测（见设计文档）；`transform_llm_output` 为 VALID_HOOKS 独立钩子，不冲突现有 `post_tool_call` 等
- **后续（P2）**：检测到复读后 stop 下一轮 LLM 调用（阻断上下文回灌强化）——需核心 1 行桥接（turn_finalizer 钩子 context 传 agent），且须先确认 `_interrupt_requested` 跨轮 reset 语义，避免误伤下一轮正常对话
- **Commit**：`824c95d5d`

### 14.1 v2：degenerate 判定 + transcript 同步（切断乱码反馈环）

- **背景**（2026-09-01 事故）：xy-max 一次修图诊断回复后 2/3 内容崩坏——模板 token 泄漏（`<|im_end|>`/`<|im_start|>`/`[/CoT]`）+ 多语种语料乱拼 + 词级复读（`usually`×54）。v1 三检测器全漏判（无 U+FFFD、非复读形态、7819 字符 < 50000 截断线），且 `finish_reason=stop`（模型"正常"结束乱码，非超长截断）。更关键的结构性缺口：transform 钩子执行时 assistant 行已落库，**钩子只修发送文本，原始乱码留在历史里，下一轮作为上下文再污染模型**——诊断本次事故的会话亲历了这个正反馈（助手自身工具调用出现同款退化症状）。
- **方案**：
  - 插件侧新增第四类 `verdict="degenerate"`：**连续脏块**（200 字符/块，块内命中模板标记或垃圾模式 `</div>..`/`(</){3,}`/`\end{g` 为脏块，**连续**脏块 ≥3 判退化——核心特征是"连续"而非总数：事故本体 run=5，引用/讨论乱码的合法回复是散点 run=1，天然不误伤）+ **词级复读** `(\S+)( \1){5,}`；<400 字符不判；处理为截断到最早信号（`first_offense`）之前（区别于 v1 复读的折叠保留首段），事故样本 7819→323 字符，保住前段有效诊断。
  - 核心补丁 `agent/turn_finalizer.py`：钩子替换发生后（`_response_transformed` 为真且尾行内容仍为替换前原文）同步回写 transcript 尾行，落库与下一轮上下文拿到干净文本。仅在退化事件触发，正常回复零影响（hook 返回 None 时本补丁不生效）。
  - 判定先于 v1 repeat/mojibake 执行（degenerate 形态判定门槛更早）；真实样本回归 3/3（1 条事故本体 + 2 条合法引用）。
  - 部署事实：`~/.hermes/plugins/owner-extensions` 是仓内 `owner/owner-extensions/` 的**符号链接**（同 inode），改仓内即生效，无需拷贝同步；网关 launchd `ai.hermes.gateway` 重启需手动。
- **涉及文件**：
  - 修改：`owner/owner-extensions/output_guard/__init__.py`（+67）、`agent/turn_finalizer.py`（+14，[owner] 加法）、`owner/docs/output-guard-design.md`（§6.5）
  - 新增：`tests/agent/test_turn_finalizer_transform_transcript_sync.py`（2 用例）、`samples/` 真实样本 fixture（gitignored，fork 有公开镜像不进 git）
- **侵入类型**：薄胶水（turn_finalizer 钩子块后 14 行加法，[owner] 标注）+ 插件纯新增逻辑
- **验证**：selfcheck 9 场景全绿（含事故样本截断断言 + 合成连续脏块 + 散点标记不误伤）；定向 pytest 9 passed（`tests/owner/test_output_guard.py` 3 + transcript 同步 2 + cleanup_guard 回归 4）
- **Commit**：`9649e49275`（测试+样本）/ `6f042b3aac`（检测+截断）/ `ffc196ff8b`（transcript 同步）/ `57a886171e`（设计文档）

### 14.2 生成中退化闸门：stream_guard + 三处收口（thinking / 输出边界循环）

- **背景**（2026-09-17 事故）：会话 `20260917_122148_57701e`（cli / xy-max）单轮生成 30,742 字符不收敛，形态是**思考→输出阶段边界循环**——反复宣告"思考结束、现在输出"而永不输出，尾部 8% 全是 `END OF THINKING`(×49) / `THINKING`(×88) / `WRITING RESPONSE` / `(stop)(stop)(stop)`。生成持续 4 分 16 秒，最终由**人工 Ctrl-C** 结束（`agent.log`: `Turn ended: reason=interrupted_during_api_call ... response_len=30742`）。
  四道既有防线全部落空，且原因是结构性的：
  - `output_guard` 只在**整轮生成结束之后**判定（`transform_llm_output`）；
  - `_thinking_exhausted` / `is_repetition_dominated` 只在 `finish_reason=length` 的续写边界生效 —— 本轮从未到该边界；
  - `TurnLivenessWatchdog` 是**空闲**看门狗，而流式每 chunk 都 `_touch_activity("receiving stream response")`，活动时钟永远新鲜 → **永不触发**；
  - 钩子门槛 `if final_response and not interrupted:` —— 失控生成的典型结局就是被打断，**护栏恰在此失效**。
  缺的不是"活性（liveness）看门狗"，而是"进展（progress）看门狗"。
- **方案**：分 P0（三处收口）/ P1（闸门本体）两步。
  - **P0-C1**：`agent/turn_finalizer.py` 钩子门槛改为 `if final_response:`，载荷补 `interrupted`。
  - **P0-C2**：把"钩子调用 + transcript 尾行回写"整块**前移到 `_persist_session` 之前**。原先钩子在后，替换只改内存，state.db 保留退化原文并在下次会话加载时二次污染。（"弹 `_db_persisted` 标记后重跑 flush"这条路走不通：`_flush_messages_to_session_db` 是 append-only，`agent/transcript_repair.py` 对非空已落库行既不覆盖也不插入。）
  - **P0-C3**：载荷补 `reasoning_text`；`output_guard` 新增 `_scan_reasoning()` —— 正文健康而思考退化时**只追加告警、不替换正文**（思考不面向用户，裁它没有意义），门槛 8000 字符（正常长思考 2–6K）。
  - **P1-a（薄 seam）**：`run_agent.py::_stream_hook_base_payload()` 增加 `request_stop` 键；新增 `_request_stream_stop(reason, *, turn_id)` —— 轮次围栏（跨轮迟到观测不得误伤下一轮）+ 每轮一次 latch（按 `turn_id` 重挂）+ 已有中断时不抢 latch，然后置位 `_interrupt_requested`（流式消费循环每 chunk 已检查，**一个 chunk 内即中断**）。
  - **P1-b（插件）**：新增 `owner/owner-extensions/stream_guard/`，消费 `on_stream_delta`（正文 + 思考两通道），在 4096 字符滑窗上做三信号判定：**S1 阶段终止语密度**（`END OF THINKING`/`WRITING RESPONSE`/`思考结束`/`(stop)` 等"宣布即将输出"的元话语）、**S2 风格签名密度**（画像签名 token 如 `ฅ` 的密度相对静态基线的倍数）、**S3 零进展**（复用官方 `agent/repetition_guard.is_repetition_dominated`）。S1/S2 需互证（`vote_threshold=2`），S3 命中即触发。命中后按 `action` 中止本轮，并复用 `_emit_warning` 主动告知用户（CLI 立即可见 + 网关转平台消息）；agent 句柄经 `request_stop.__self__` 回溯（载荷里没有 agent，这是 route B 的唯一通道，且只在绑定方法名为 `_request_stream_stop` 时才认，否则安静降级）。
  - **P1-c（配置）**：`owner/config/patch.yaml` 新增 `owner.stream_guard` 段；`plugin.yaml` 声明 `on_stream_delta`；`owner-extensions/__init__.py` 聚合注册。
- **阈值标定**（真实数据，非先验）：**8 条正例** = 今日事故 + 5 条逐条核实的历史复读失控（`msg 93635` 265,518 / `93633` 262,157 / `33260` 12,180 / `33236` 12,159 / `33222` 11,813）+ `degenerate_9_01` 模板泄漏样本；**318 条负例** = `state.db` 中全部 >2000 字符的真实 assistant 正文（剔除上述已核实的历史失控）+ 2 条合法引用样本。

  | 信号 | 阈值 | 事故实测 | 负样本峰值 |
  |---|---|---|---|
  | S1 阶段终止语密度 | ≥3.0/KB | 3.17（首个命中窗口）→ 4.15 峰值 | 2.41（恰好是一条讨论本次事故、引用了这些字样的回复） |
  | S2 签名密度倍数 | ≥×8.0 | ×21.97 → ×25.88 | ×0.00（318 条中无一条出现 `ฅ`） |
  | S3 零进展 | 命中即触发 | 6/6 历史复读事故命中 | 0 |

  **结果：8/8 正例命中、0 误伤**。今日事故在**生成到 50%（15,360 字符）**处命中 —— 按该轮实测速率（30,742 字符 / 256 秒 ≈ 120 字符/秒）折算，比人工 Ctrl-C 早约 **2 分钟**。
- **涉及文件**：
  - 修改：`agent/turn_finalizer.py`（C1/C2/C3）、`run_agent.py`（[owner] 一个新方法 + 一个载荷键）、`owner/owner-extensions/output_guard/__init__.py`（C3）、`owner/owner-extensions/__init__.py`、`owner/owner-extensions/plugin.yaml`、`owner/config/patch.yaml`、`.gitignore`
  - 新增：`owner/owner-extensions/stream_guard/__init__.py`、`.../selfcheck.py`、`.../samples/`（gitignored）、`owner/docs/degenerate-stream-guard-design.md`、`tests/owner/test_stream_guard.py`、`tests/run_agent/test_request_stream_stop.py`
- **侵入类型**：薄 seam（`run_agent.py` 一个新方法 + 一个载荷键；放宽到此处的原因：流式观察钩子的返回值被 `agent/plugin_stream_hooks.py` 丢弃、载荷里也没有 agent，无 hook 级替代方案）+ 薄胶水（`turn_finalizer.py` 钩子块前移）+ 插件纯新增逻辑
- **部署事实**：`~/.hermes/plugins/owner-extensions` 是仓内 `owner/owner-extensions/` 的**符号链接**，新增子目录**改仓内即生效**、无需拷贝；但插件代码与 `max_tokens` 一样**只对新启动的 agent 进程生效**，网关/CLI 需重启。
- **验证**：
  - `tests/owner/test_stream_guard.py` 14 项通过（含事故原文端到端回放、grace/min_chars/warn_only/latch/跨轮重挂/异常吞掉/外部绑定方法不误认 agent）
  - `tests/run_agent/test_request_stream_stop.py` 7 项通过（载荷暴露、轮次围栏、latch、已有中断不抢）
  - `tests/agent/test_turn_finalizer_transform_transcript_sync.py` 4 项通过（新增 2 项：落库顺序、中断轮次仍触发）
  - `stream_guard/selfcheck.py` + `output_guard/selfcheck.py` 均通过；`tests/owner/` + 两个流式钩子测试文件合计 **630 passed / 1 failed**，该 failed 为**既有基线失败**（`test_contract_entrypoints.py::test_cron_run_job_sets_cron_contextvar_on_real_agent_path`，与本改动无关，已用 `git stash` 回退改动对照确认）
  - `tests/run_agent/` 全量 **8 failed / 2050 passed**；已把这 8 条逐个在**回退改动后的基线**上重跑，**同样 8 条失败**，确认全部为既有失败（`test_66267_multimodal_interim`、`test_deepseek_reasoning_content_echo`×2、`test_reasoning_echo_resolver_e2e`、`test_run_agent.py` 4 条），无一由本改动引入
- **后续（P2）**：先跑 `action: warn_only` 一周，收集 `agent.log` 中 `stream_guard trip` 行的 `signals` 分布与误伤数，零误伤后再切 `interrupt`；若要覆盖"纯思考空转"形态需同时开 `plugins.stream_reasoning_deltas: true`（每-delta 插件开销未实测）。P2 前置项：`_turn_exit_reason` 目前对"闸门中断"与"用户 Ctrl-C"**同样**记为 `interrupted_during_api_call`，精确归因需再接一处。
- **Commit**：`dd4ab46bfb`（P0 三处收口 + P1 闸门/配置）/ `1411019452`（测试）/ `8bed0660f8`（设计稿）

---

## 十五、API Server：LDAP 身份准入与多 profile 路由

本节记录 `gateway/platforms/api_server.py` 上形成的完整身份准入体系：从「按 `X-Hermes-Identity` 头反代到子 profile 容器」起步，依次加上 LDAP bind 二次认证、seen 灰度语义、代理转发加固与对外准入查询端点。此前该文件的 owner 改动只有附录 B 的一行记载，现独立成章。

### 15.1 API Server identity routing（能力起点）

- **背景**：多 profile 部署下每个 profile 跑独立容器的 API Server（`profile_endpoints` 已存在），但外部 OpenAI 兼容客户端不知道该打哪个端口——需要网关侧按调用者身份自动路由。
- **方案**（`6177923b26`）：
  - `owner/feishu/profile_routing.py` 新增 `resolve_api_identity_route(identity)`：在 `patch_feishu_profile.yaml` 的 `identity_routes` 段查找 LDAP uid → profile 映射，复用既有 `profile_endpoints` 解析出 `(profile_name, endpoint_url, api_key)`
  - `gateway/platforms/api_server.py` 新增 `_make_identity_routing_middleware`：读请求头 `X-Hermes-Identity`，命中后把请求 HTTP 反向代理到对应子容器的 API Server；不命中或身份未知则透传，行为不变
- **配置样例**（形态示意；**当前未落地**，见 §15.7）：

  ```yaml
  identity_routes:
    yangtianbao: yangtianbao
    wangtingwei: wangtingwei
  ```

- **接线状态**（2026-09-28 核实）：`patch_feishu_profile.yaml` 的 `user_routing` 段下**没有** `identity_routes` / `identity_whitelist` 键，故本节描述的解析路径不触发，链路为 dormant —— 详见 **§15.7**
- **涉及文件**：`gateway/platforms/api_server.py`（+95）、`owner/feishu/profile_routing.py`（+31）
- **侵入类型**：薄胶水（中间件注册）+ 路由逻辑全在 owner/
- **Commit**：`6177923b26`

### 15.2 LDAP bind 二次认证（一次成功免验 72h）

- **背景**：`X-Hermes-Identity` 是纯声明式头，任何人都能伪造，等于把 profile 选择权交给调用方。需要第二信任锚：拿密码去 LDAP 做 bind，验证该 uid 真实存在且密码正确。
- **方案**（`531508e317`）：在反代转发前过 `ldap_gate`（`owner/gateway/ldap_auth.py`）；接线走 `_owner_import` 惰性加载 —— owner/ 模块缺失即 fail-open（与既有架构惯例一致，`API_SERVER_KEY` 仍是第一信任边界）。
- **决策表（6 态）**：

  | verdict | 触发条件 | 网关行为 |
  |---|---|---|
  | `allow` | 密码 bind 成功；或无密码但 72h 缓存有效 | 放行（后者零 LDAP 调用，用户无感） |
  | `deny_bad_credentials` | bind 失败 | 401 `ldap_auth_failed`，清正缓存 |
  | `deny_reauth_required` | 无密码、`enforce=seen` 下缓存已过期但曾认证过 | 401 `ldap_auth_required` |
  | `deny_empty_password` | 空密码 | 401 `ldap_auth_required` |
  | `deny_invalid_login` | login 未过字符白名单 | 401 `ldap_identity_invalid` |
  | fail-open | LDAP 不可达且 `fail_open_on_error=true` | 放行 |

  `deny_bad_credentials` 与 `deny_reauth_required` 用不同 error code，调用方可区分「密码错」与「需要重新认证」。
- **缓存与驱逐**：正缓存 72h（内存 + `~/.hermes/ldap_identity_cache.json`，重启不丢）；负缓存 10s 防爆破；密码轮换时清正缓存，使旧密码「下个请求即失效」。
- **安全要点**：
  - login 经字符白名单（`^[a-zA-Z0-9._-]+$`）+ RFC4514 转义后构建 DN，防 DN 注入
  - 空密码先拒 —— LDAP 空密码等价匿名 bind，会「假成功」
  - DN 模板锚定 `cn=people`；离职账号（`cn=deleted`）天然被拒
  - `X-Hermes-Identity-Password` 在转发前从头上剥离，且永不落日志
- **配置**（`db78cdd871`，`owner/config/patch_feishu_profile.yaml`）：新增顶层 `ldap:` 节，与 `feishu:` **平级**——认证的是 api_server identity 流量，不与 `FEISHU_APP_ID` 耦合的 `user_routing` 混在一起。

  | 键 | 值 | 说明 |
  |---|---|---|
  | `host` | `10.10.100.150:389` | LDAPS 636 实测未开放 |
  | `user_dn_template` | 锚定 `cn=people` | 见上 |
  | `admin` | 凭据 | 供后续 group 校验，bind 主路径不用 |
  | `enforce` | `always` | 无密码且无有效缓存时的处置。`off` = 放行（灰度档）；`always` / `seen` = 拒绝（§15.8 起 `seen` 为 `always` 的遗留别名）；未识别取值按 `always` 处理 |
  | `cache_ttl_hours` | 72 | 正缓存窗口 |
  | `negative_cache_seconds` | 10 | 负缓存窗口 |
  | `fail_open_on_error` | `false` | **带密码**的请求在 LDAP 不可达时的处置（§15.9）。`false` = 拒绝，返回 503 `ldap_backend_unavailable`；`true` = 显式接受认证降级。`no_config` / `ldap3_missing` 属永久性配置错误，不受此开关影响，一律拒绝 |

- **调用位置与接线状态**（2026-09-28 核实）：`ldap_gate` 由中间件的独立步骤 `_owner_identity_gate_rejection` 调用，位置在**任何路由判定之前**（§15.10）——凡带 `X-Hermes-Identity` 的请求都先过门，与「该身份能否解析出路由」无关。就配置而言，`identity_routes` / `identity_whitelist` 仍缺键（§15.1），故**反代**链路为 dormant：请求过门后由 root 本体处理，不会被代理到子容器。详见 **§15.7**

- **依赖**（`6790f1ba6c`）：新增 `ldap3==2.9.1`，运行时惰性 import —— 缺包时 `ImportError` → fail-open，lean 安装不受影响；按仓库 pinning 规范 exact-pin + uv lock 重生成。
- **涉及文件**：`owner/gateway/ldap_auth.py`（新增，369 行）、`gateway/platforms/api_server.py`、`owner/config/patch_feishu_profile.yaml`、`pyproject.toml`、`uv.lock`、`tests/owner/test_ldap_identity_auth.py`（新增，424 行）
- **侵入类型**：薄胶水 + try-import（`api_server.py` 的 `_owner_import` 调用）；认证逻辑全在 owner/
- **验证**：16 个回归测试覆盖决策表全矩阵 / 缓存持久化 / 负缓存 / 中间件集成 / 密码头剥离；另对生产 LDAP（`10.10.100.150:389`）做真实 bind E2E（错密码 → `deny_bad_credentials`，不可达 → fail-open）
- **Commit**：`531508e317`、`6790f1ba6c`、`db78cdd871`

### 15.3 seen 语义与缓存状态机（权限提升修复）

- **背景**（`8f533aaa0c`）：`seen`（曾认证）标记原与 72h 有效窗口耦合在同一份 state file 条目里。`_cache_evict`（密码轮换驱逐）会把整条删除，**连带销毁 `seen`** —— 攻击者只要知道 uid，发一次错误密码触发驱逐，等 10s 负缓存过期后，无密码请求即可在 `enforce=seen` 下被放行，实现零密码完整冒充。
- **方案**：把 `seen` 与有效窗口解耦为独立的 `_seen_logins` 集合：
  - state file 升级 `version 2`：`{version, entries, seen}`；加载 v1 文件时把历史 `entries` 迁移进 `seen`，已部署缓存不降级
  - `_cache_put` 认证成功时写 `seen`；`_cache_evict` **只清有效窗口、保留 `seen`**
  - `_has_seen` 改查 `_seen_logins`（内存优先，不再重读文件）
- **涉及文件**：`owner/gateway/ldap_auth.py`、`tests/owner/test_ldap_identity_auth.py`
- **侵入类型**：纯 owner/ 内部（**零官方侵入**）
- **验证**：新增 `test_wrong_password_eviction_preserves_seen_marker` 覆盖完整攻击链（认证一次 → 错密码驱逐 → 负缓存过期 → 无密码请求仍 DENY）；2 个既有夹具升级 v2 格式；LDAP 17 项 + feishu profile 路由/传输 41 项通过
- **Commit**：`8f533aaa0c`
- **后续**（§15.8，`ed0c3dfb21`）：本节建立的 `seen` 语义已因该项改为 fail-closed 而**不再参与放行判定** —— `enforce=seen` 与 `always` 现同义。`_seen_logins` / `_has_seen` 保留（state-file v2 结构与诊断用途），但门不再依赖它们。本节的攻击链（错密码驱逐 → 无密码请求）在新语义下依然被拒，只是原因从「`seen` 标记存活」变为「严格档一律拒绝」

### 15.4 代理转发加固：头剥离 + SSE 逐 chunk 透传

- **自循环 503**（`311f553550`）：root 网关 identity 中间件转发时保留了 `X-Hermes-Identity`，而子 profile 容器 home 挂载同一份 `patch_feishu_profile.yaml`（`identity_routes` + `profile_endpoints` 齐全），子网关收到后再次按 identity 解析路由，把请求代理回自己 → 自循环直至超时/递归上限，对外表现为 `503 Sub-gateway unavailable`。实测：直打 26027 带 identity 头 → 503，容器日志单请求 6 条 503 爆发；不带 → 200。修复：转发头剥离列表加入 `x-hermes-identity`（与密码头同列）。
- **SSE 透传**（`4b6d187a2b`）：代理转发原把上游响应整段读完后一次性返回，SSE 长回合的首字节被推迟整轮 agent 时长；`total=120` 硬超时还会把合法长流中途杀掉。修复：SSE 请求（path 以 `/chat/stream` 结尾，或 body 带 `stream:true`）改走 `web.StreamResponse` 逐 chunk 转发，`total` 不设上限（`sock_read=600`、`connect=10`），客户端断连经连接重置自然传播；非流式 JSON 回复保留 120s 连接/读取预算。
- **涉及文件**：`gateway/platforms/api_server.py`、`tests/owner/test_ldap_identity_auth.py`
- **侵入类型**：inline（中间件转发路径）
- **验证**：`test_allowed_request_proxies_without_identity_headers` 断言 identity + password 双头均不出现在转发头中（17 项通过）；SSE 契约测试 16 项断言逐 chunk 不整段缓冲、非流式 timeout 仍为 120
- **Commit**：`311f553550`、`4b6d187a2b`

### 15.5 LDAP 身份准入查询端点 + identity_whitelist

- **背景**：外部消费方（智能巡检 `xy-portal`）需要在放行某个 LDAP 用户的对话入口之前，知道该身份是否被配置了专属容器；若双端各自维护白名单必然漂移。
- **方案**（`b14892be7c`）：新增 `GET /v1/ldap/identity/{identity}/access` 只读三态查询，白名单单一真源化；`identity_routing_middleware` 增加 `identity_whitelist` 短路；`owner/feishu/profile_routing.py` 新增 `is_api_identity_whitelisted()`；capabilities 端点广告新路由。
- **三态语义**：

  | 返回 | 含义 | 消费方应做 |
  |---|---|---|
  | `whitelisted=true` | LDAP 白名单身份，不反代子容器，由 root gateway 本体处理 | 放行对话；无需携带 `X-Hermes-Identity` 头（root 直达）。**若仍携带该头，则须通过 LDAP 门**——白名单只表示「不反代」，不表示「免认证」（§15.10） |
  | `routed=true` | 该身份有专属容器，聊天请求会被 `identity_routing_middleware` 代理到对应子 profile | 放行对话 |
  | 两者皆 false | 未知身份，聊天请求会 fall through 到 `default_profile`（共享实例） | **必须拒绝** —— 绝不能「试探式」发聊天请求来探测（那样会真的和共享 bot 聊上） |

- **约束**：`allowed = routed || whitelisted`；**绝不返回** `endpoint_url` / `api_key`，仅返回 profile 名；owner/ 路由模块缺失时返回 503（明确告知不可用，而非误判为「无权限」）；Bearer 鉴权与其他 API 路由一致。
- **消费方注意**（T2-3）：上表第三行的「必须拒绝」**以 `routing_dormant=false` 为前提**。当响应携带 `routing_dormant=true` 时，`allowed:false` 描述的是**网关未接线**这一状态、而非该 uid 的判定结果（所有 uid 取同值），消费方应视为「能力未上线」并退回自身默认策略 —— 否则会把「未接线」放大成「全员禁入」，且无法与真实的准入拒绝区分。响应另附 `routing_keys_present` 以区分「键缺失」与「键存在但为空」。当前实况见 **§15.7**
- **白名单优先级**：命中 `identity_whitelist` 者不反代子容器，由 root gateway 本体处理（对话落在 root 实例的 memory/会话），与飞书 `user_routing.whitelist` → 主网关同构，**优先级高于 `identity_routes`**——后者条目随之休眠，同飞书双列表语义。**作用范围仅限路由**：白名单不构成认证绕过，认证由 `ldap_gate` 在任何路由判定之前完成（§15.10）。
- **涉及文件**：`gateway/platforms/api_server.py`（+116）、`owner/feishu/profile_routing.py`（+35）
- **侵入类型**：薄胶水（路由注册 + 端点）+ 路由逻辑全在 owner/
- **Commit**：`b14892be7c`

### 15.6 流式 finish chunk 附带有效 session_id

- **背景**（`8d42e4c199`）：上下文压缩可在回合中途轮换 agent 会话代号，长连接客户端拿不到新代号就会跟丢上下文。
- **方案**：`chat/stream` 的 finish chunk `hermes` 段在 effective id 与请求 `session_id` 不一致时回传，客户端据此切换跟踪。
- **涉及文件**：`gateway/platforms/api_server.py`（+5）
- **侵入类型**：薄胶水
- **Commit**：`8d42e4c199`

### 15.7 未接线状态显式化（identity routing dormant）

- **问题**（T2-3）：§15.1–§15.5 构成的整套身份准入体系，触发前提是 `patch_feishu_profile.yaml` 的 `user_routing` 段存在 `identity_routes` / `identity_whitelist`。该键**从未写入**。2026-09-28 核实：`~/.hermes/patch_feishu_profile.yaml` 是指向本仓库 `owner/config/` 的符号链接（模板即现网）；`feishu.bots.<app_id>.user_routing` 下有 `whitelist` / `chat_profile_routes` / `user_profile_routes` / `default_profile` / `profile_endpoints`，唯独没有这两个键；`FEISHU_APP_ID` 与 `bots` 键一致，配置段本身加载正常。后果：

  | 环节 | 现网实况 |
  |---|---|
  | `resolve_api_identity_route()` | 恒返回 `None`（`identity_routes.get(identity)` 落空） |
  | 中间件 | 透传到 root，**不反代**子 profile |
  | `ldap_gate` | 照常执行 —— 调用点在**任何路由判定之前**（§15.10），与路由是否接线无关 |
  | `GET /v1/ldap/identity/{uid}/access` | 对任何 uid 返回 `allowed:false` |

  这类「门存在但未生效」比「门不存在」更危险：既不报错也不拒绝，日志里只有一句 `is unknown; falling through to default`，读起来像「这个 uid 没配」，而不是「整套机制是关的」。

- **决策**（2026-09-28）：**暂不接线，改为把未接线状态显式化**。理由是接线会把三处语义缺口从「不可达」变成「可用」，须先修完再接线 —— ① `enforce=seen` 会放行从未认证过的账号（T2-4）；② `fail_open_on_error: true` 不区分「LDAP 不可达」与「密码错误」（T2-5）；③ `identity_whitelist` 短路位于 LDAP gate **之前**，等于白名单即免认证（T2-6，已在 §15.10 修复）。当时风险最低且收益明确的做法是让状态可观测、文档与现网一致。**后续状态**（2026-09-28）：三处缺口均已修复（§15.8 / §15.9 / §15.10），接线的语义前提已满足；接线本身仍未执行，属独立决策（缺 `identity_routes` 键即保持 dormant，且 dormant 现在只影响反代、不再影响认证）。
- **方案**（`9f453c51e1`）：
  - `owner/feishu/profile_routing.py` 新增 `identity_routing_diagnostics()`：结构化返回 `dormant` / `keys_present` / `identity_route_count` / `identity_whitelist_count` / `config_source`。只读、无副作用、**不抛异常**。
  - `gateway/platforms/api_server.py` 中间件：`route is None` 分支区分**「该 uid 未配置」（已接线）**与**「整条链路未接线」**；后者打印一次显式告警（每中间件实例一次，避免结构性状态按请求刷屏），并点名后果（既不反代、也不做二次认证）与成因（键缺失 / 键存在但为空 / 配置段取不到）。
  - `GET /v1/ldap/identity/{identity}/access` 响应新增 `routing_dormant` 与 `routing_keys_present`，消除 `allowed:false` 的语义歧义（§15.5）。
  - `owner/config/patch_feishu_profile.yaml` 的 LDAP 节顶部标注接线状态与启用前置。
- **成因三分**（`config_source` / `keys_present` 联合判读）：

  | `config_source` | `keys_present` | 含义 |
  |---|---|---|
  | `loaded` | `false` | 配置段正常加载，只是**键从未写入** —— 即当前实况 |
  | `loaded` | `true` | 键存在但条目为空（曾被清空） |
  | `unavailable` | — | 配置段取不到。**`_load_routing_config()` 以 `FEISHU_APP_ID` 为入口**，因此纯 api_server 节点即使把键配好也读不到 —— 这是与「键缺失」不同的另一种 dormant 成因，排障方向也不同 |

- **涉及文件**（官方树 intrude）：`gateway/platforms/api_server.py`（中间件告警分支 + 端点响应两字段）
- **涉及文件**（owner 侧）：`owner/feishu/profile_routing.py`（新增 `identity_routing_diagnostics()`）、`owner/config/patch_feishu_profile.yaml`、`tests/owner/test_identity_routing_dormant.py`（新增 14 例）
- **侵入类型**：薄委托（诊断函数 + 两处响应字段）
- **验证**：14 例覆盖诊断五分档 / 中间件（透传、显式告警、只提示一次、`ldap_gate` 探针不受路由接线影响 —— 该结论已在 §15.10 反向）/ 准入端点（dormant 与已接线对照）。`ldap_gate` 探针配**对照组**——已接线配置下探针必须命中，否则「dormant 时门未被调用」是空断言（探针须同时清 `_owner_lazy` 缓存，否则会静默命中旧函数）。变异验证三条，均失败：关闭 dormant 分支 → 2 例；端点不返回 `routing_dormant` → 3 例；`keys_present` 恒真 → 3 例（含告警的成因归因）。回归：`tests/owner/` + `tests/gateway/test_api_server*` 共 67 文件 / 1056 例全通过（32.2s）。
- **同类普查**（已完成）：
  - `X-Hermes-Identity` 的**全部生产读取点**仅 `gateway/platforms/api_server.py`（中间件 + `_media_owner_matches`）。后者「未验证的身份头被当归属凭据」问题已在 **T2-7 / T2-8** 跟踪，无需另立条目。
  - 其他「配置驱动门」：`owner/approval/skill_manage_gate.py`（`enabled: false`，§3.11 已记录该默认值调整）、`owner/semantic_audit`（默认 `enabled: false`，`config.py` 注释明确）。二者均**有显式开关且文档一致**，关闭是决策而非静默失效。**判定标准**：本条的缺陷形态是「**无开关、靠缺键隐式关闭**」——只有 identity routing 符合，故无同类缺陷。
- **未纳入**：接线本身（语义前提已由 §15.8 / §15.9 / §15.10 补齐，接线与否属独立决策）；`_media_owner_matches` 收紧（T2-7）；归属凭据的服务端盐（T2-8）
- **Commit**：`9f453c51e1`

### 15.8 enforce=seen 改为 fail-closed

- **问题**（T2-4）：`enforce=seen` 的原始语义是「只拦已经认证过的账号」——无密码且缓存失效时，`_has_seen()` 为真才 `DENY_REAUTH_REQUIRED`，**从未认证过的账号一律放行**。原意图是部署期灰度（「前端没上线密码头之前不破坏任何现有流量」），但方向反了：门只拒绝*已经证明过身份*的人，于是攻击者挑一个**从未登录过**的 uid 就能零密码通过，被反代进其专属容器。生产环境下无人携带密码头 ⇒ `_seen_logins` 恒为空 ⇒ **`seen` 与 `off` 行为完全等价**，配置里那个档位名称给出的是虚假的安全感。
- **方案**（fail-closed，`ed0c3dfb21`）：
  - `enforce in ("always", "seen")` 一律 `DENY_REAUTH_REQUIRED`；`seen` 降为 **`always` 的遗留别名**——保留而非删除，因为未识别的取值若落进 `off` 分支即构成**静默降级**。
  - 灰度职责交回 `off`：配置注释已明确它是「纯增强、无防伪造力」，现补充说明其**唯一例外**（该账号刚认证失败且负缓存未过期 → 仍拒绝），与既有用例 `test_negative_cache_blocks_even_enforce_off` 一致。
  - `enforce` 取值校验：无法识别的字符串**按 `always` 处理并告警**。此前 `enforce: "alway"`（笔误）会穿过所有分支落到 `ALLOW`，把门悄悄关掉 —— 与 §15.7 的 dormant 同属「配置驱动的静默失效」。
  - `_seen_logins` / `_has_seen` 不再参与放行判定（保留 state-file v2 结构与诊断用途），相关注释改写以明示，避免后人以为它仍在把门。
  - `patch_feishu_profile.yaml` 的 `enforce` 由 `seen` 改为 `always`（二者现同义，写 `always` 更如实）。
- **决策依据**：该链路当时为 dormant（§15.7），不存在「为保护现有流量而灰度」的对象，收紧无成本。
- **涉及文件**：`owner/gateway/ldap_auth.py`、`owner/config/patch_feishu_profile.yaml`、`tests/owner/test_ldap_identity_auth.py`
- **侵入类型**：纯 owner/ 内部（**零官方侵入**）
- **验证**：新增/改写 3 例 —— `test_unseen_login_enforce_matrix`（`seen` 期望由 `ALLOW` 改 `DENY_REAUTH_REQUIRED`）、`test_unrecognized_enforce_value_fails_closed`、`test_enforce_seen_and_always_share_one_verdict`（三场景下两档必须逐项一致，防名称再次分叉）；两处 SSE / 超时传输用例改为种子化有效缓存（它们断言的是传输行为，不应依赖认证档位）。变异验证两条，均失败：`seen` 退回旧语义 → 5 例失败；未知取值静默降级为 `off` → 1 例失败。回归：`tests/owner/` + `api_server` / profile routing 共 57 文件 / 908 例全通过（20.8s）。
- **同类普查**（清单要求：`_has_seen` / `_prune_expired` / `_positive_cache` 三者交互）：
  - `_cache_get` 是唯一的放行判据入口，且**先 `_prune_expired(_now())` 再取值** ⇒ 不存在「过期条目被放行」的状态泄漏。
  - ⚠️ `_has_seen` 读 `_positive_cache` 时**不剪除过期项**，会把已过期条目算作 `seen=True`。旧语义下方向是安全的（`True` → 更严格 = DENY），且现已不参与判定，故当前无影响。**约束**：若将来把 `_has_seen` 接回判定且语义方向为「`True` → 放行」，即构成漏洞 —— 其 docstring 已标注为 diagnostic-only。
  - `_load_state_file_locked` 按 mtime 短路；同一秒内的外部改写可能漏读。边界极窄（`_cache_put` 会刷新 mtime），不构成实际风险，仅记录。
  - **实质收获**：本次普查另查出「无法识别的 `enforce` 取值静默等价于 `off`」—— 同为「配置驱动静默降级」类，已在 §15.8 内一并修复，**不另立条目**。
- **未纳入**：`fail_open_on_error` 不区分「LDAP 不可达」与「密码错误」（T2-5，见 §15.9）；`identity_whitelist` 短路位于 LDAP gate **之前**（T2-6，见 §15.10）
- **Commit**：`ed0c3dfb21`

### 15.9 带密码但无法验证时默认拒绝（fail-open 收窄为显式 opt-in）

- **问题**（T2-5）：`fail_open_on_error` 全仓**只有一个消费点** —— `ldap_gate` 内「带密码」的 bind 分支（无密码的请求根本不调用 `_bind`，由 `enforce` 档决定，§15.8）。而该分支原本对**所有** `error_class` 一律 fail-open，实测（用真实 `ldap_gate` 路径，带**完全错误的密码**）：

  | bind 侧返回 | 判定 |
  |---|---|
  | 明确判定密码错（`verdict=False`，无 `error_class`） | `deny_bad_credentials` ✅ |
  | 抛 `SocketError`（LDAP 不可达） | **`allow`** |
  | 抛 `LDAPSocketOpenError` | **`allow`** |
  | `host` 为空（`no_config`） | **`allow`** |
  | `ldap3` 未安装（`ldap3_missing`） | **`allow`** |

  后果：请求**声明了凭据**却未被校验，而放行让「没查成」与「查过且正确」不可区分 —— 能干扰 LDAP 连通性的人（或只是等到一次抖动）即可把任意错误密码变合法，即 **DoS → 认证降级**。后两行更糟：它们是**永久性**错误，而非暂时不可达，`fail_open_on_error` 在那里从来不是一个经过权衡的选择。

- **决策**（2026-09-28）：**默认翻转 + 保留开关**。理由：若把「带密码无法验证」一律改为拒绝，该开关就再没有任何作用面（见上），会退化成死配置；翻转默认值并保留语义，它才继续是一个**显式**的「可用性优先于验证」逃生口，同时默认不再降级。
- **方案**（`6613ac2146`）：
  - 新增判定 `DENY_BACKEND_UNAVAILABLE`；`_verdict_on_unverifiable(login, error_class)` 按成因分流：
    - `_CONFIG_ERROR_CLASSES = {"no_config", "ldap3_missing"}` → 永久性配置错误，**无条件拒绝**并 `logger.error` 点名「这是配置错误，不是暂时不可达」。
    - 其余（socket / timeout）→ 读 `fail_open_on_error`，**默认 `False`**；打开时 `logger.warning` 明说「未经验证即放行（显式 opt-in）」。
  - `gateway/platforms/api_server.py`：`deny_backend_unavailable` → **503** `ldap_backend_unavailable`（`type: gateway_unavailable`）。用 503 而非 401，是因为调用方的正确动作是「稍后重试」而不是「去改密码」——把两种失败分开，也是在响应与日志两侧同时保留可归因性。
  - `patch_feishu_profile.yaml`：`fail_open_on_error: false`，并重写说明（含「无密码请求不走此路径」「永久性配置错误不受开关影响」两点）。
- **涉及文件**（官方树 intrude）：`gateway/platforms/api_server.py`（新增一个 verdict 的 503 映射）
- **涉及文件**（owner 侧）：`owner/gateway/ldap_auth.py`、`owner/config/patch_feishu_profile.yaml`、`tests/owner/test_ldap_identity_auth.py`
- **侵入类型**：薄胶水（一个 verdict 分支）
- **验证**：新增/改写 5 例 —— `test_wrong_password_and_unverifiable_differ`（清单要求的验收标准：同一错误密码，`deny_bad_credentials` vs `deny_backend_unavailable`，两者必须不同）、`test_default_is_fail_closed_when_key_is_absent`、`test_configuration_errors_deny_even_with_fail_open_on`、`test_backend_unavailable_returns_503`（中间件层，并断言响应里**不含** `ldap_auth_failed`）、`test_ldap_down_fail_open_vs_closed`（opt-in 仍生效，且 fail-closed 时结果由 `deny_reauth_required` 改为 `deny_backend_unavailable`）。变异验证三条，均失败：暂时性错误恢复为无条件 fail-open → **4 例**；配置错误不再无条件拒绝 → 1 例；把两种失败合并回 `deny_reauth_required` → **5 例**。
- **同类普查**（已完成，见下条发现）：认证链上其余兜底点逐个核对 —— `is_api_identity_whitelisted` 异常时返回 `False`（fail-closed ✅）；`resolve_api_identity_route` 返回 `None` → 透传（**已知且有意**，其状态已由 §15.7 显式化）；中间件 `_owner_import` 取不到模块 → 透传（架构契约，owner/ 整体缺失时的既有约定）。**但查出另一处同类缺陷**：`_load_ldap_config()` 把「配置读不到」与「未启用」压成同一个 `{}`，导致配置故障静默关闭认证门 —— 已单独立项 **T2-23**，其修复涉及共享配置加载器，需独立决策，不在本条内处理。
- **未纳入**：`identity_whitelist` 短路位于 LDAP gate **之前**（T2-6，即白名单 = 免认证）—— 见 §15.10
- **Commit**：`6613ac2146`

### 15.10 认证判定与路由判定解耦（门前移至任何路由决策之前）

- **问题**（T2-6）：`ldap_gate` 的调用点位于「`resolve_api_identity_route` 成功返回」之后，于是**认证是否发生由路由决定**，两条路可绕过二次认证：

  | 流量走向 | 改前 | 后果 |
  |---|---|---|
  | 命中 `identity_whitelist` | 白名单短路早返回，**完全跳过** LDAP 并直达 root 本体 | 「root 本体处理」被读成「免认证」；而 `X-Hermes-Identity` 是任何能触达网关的人都可设置的头 |
  | 已登记但 `profile_endpoints` 配错 | 路由解析返回 `None` → 落到 default 路径，**跳过** LDAP | 一条配置错误变成一条免认证通路：本该受门保护的 uid 失去保护 |
  | 未知 uid | 同上 | 「路由表里查不到」等价于「不必验证身份」 |

  根因是把两件事压成了一件事：**身份声明是否可信**（认证）与**请求该发往哪里**（路由）。前者是后者的前提，而不是后者的产物。

- **决策**（2026-09-28）：**带 `X-Hermes-Identity` 的请求一律先过认证门** —— 白名单 / 已路由 / 未知身份三种走向都在门前排队，认证判定不再与路由判定耦合。
- **行为变更（有意）**：**未知身份不再透传**。一个未登记的 uid 带身份头，改前会落到 default 路径（等价于不带该头）；现在先被门判定，无凭据即 401。之所以接受，是因为身份头是一次**声明** —— 未通过验证的声明不应被当作普通请求处置，否则「带一个随机 uid」就成了探测甚至绕过认证的通用手法。
- **方案**（`571ba8c937`）：
  - `gateway/platforms/api_server.py` 抽出模块级 `_owner_identity_gate_rejection(identity, request)`：把六个 verdict 到 401/503 的映射集中在一处，返回「可直接发出的拒绝响应」或 `None`（放行）；中间件在 `identity` 非空判定之后**立即**调用它，位置在白名单短路与路由解析之前。
  - 做成**独立函数**而非内联分支，是为了让「认证不依赖路由」成为**结构性事实**而非调用顺序的巧合 —— 后续在中间件里新增的任何早返回分支，都不会再顺带绕过认证。
  - `owner/feishu/profile_routing.py`：`is_api_identity_whitelisted()` 与 `identity_routing_diagnostics()` 的 docstring 改写，明示白名单**只管路由、不构成认证绕过**，且 dormant 的后果不再包含「认证门不可达」。
  - `owner/gateway/ldap_auth.py`：模块 docstring 的 gate point 说明改写（原文写的是「位于路由解析成功之后」）。
  - T2-3 的 dormant 告警文案同步改写：原句宣称「no sub-profile reverse-proxy **AND no LDAP second-factor gate**」（§15.7），门前移后该后果不成立 —— 留着就是给排障者一条错误结论。
- **涉及文件**（官方树 intrude）：`gateway/platforms/api_server.py`（抽出 gate 步骤 + 中间件流程重排 + dormant 告警文案）
- **涉及文件**（owner 侧）：`owner/gateway/ldap_auth.py`、`owner/feishu/profile_routing.py`、`tests/owner/test_ldap_identity_auth.py`、`tests/owner/test_identity_routing_dormant.py`
- **侵入类型**：薄胶水（流程重排；认证逻辑仍全在 owner/）
- **验证**：新增 5 例（`TestGateRunsBeforeRouting`）—— 白名单身份无凭据必须 401；白名单身份凭据有效时必须**不被反代**（既有语义完好）；未知 uid 必须过门；endpoint 配错必须过门；门拒绝先于白名单分支（用「白名单命中 + 明确密码错」把两条分支同时置为可达）。T2-3 侧反向改写 1 例并新增 2 例：`test_dormant_config_does_not_disable_the_gate`（dormant 配置下探针必须命中）、`test_dormant_config_still_rejects_when_the_gate_denies`（门真拒绝时 dormant 配置也必须被拦住 —— 否则「门被调用了」只是一次无害观测）。变异验证三条，**均失败**：把门移回路由解析之后 → **6 例**；抽出的 helper 内 503 映射失效 → 1 例（证明 T2-5 的 503 用例在函数搬家后仍然咬得住）；dormant 告警恢复旧措辞 → 1 例。回归：`tests/owner/` + `tests/gateway/test_api_server*` 共 74 文件 / 1165 例全通过（41.5s）。
- **同类普查**（已完成）：
  - `X-Hermes-Identity` 的全部生产读取点：中间件（本条）+ `_media_owner_matches`（**T2-7 / T2-8** 跟踪）。无第三处。
  - 「认证与路由耦合」的同类形态：`_owner_import` 取不到模块时的透传（架构契约 —— owner/ 整体缺失，调用方无法触发）；`resolve_api_identity_route → None` 的透传 —— 本条已把它移到认证之后，故不再构成绕过。
  - **实质收获**：认证门**摆放位置**本身就是安全属性，不能只当作代码组织问题；与之同类的还有 §15.8 的「判据方向」与 §15.9 的「失败归因」—— 三者共同构成「门看起来在、实际不设防」的三种形态。
- **未纳入**：`identity_routes` 的接线本身（§15.7，独立决策）；`identity_whitelist` 消费方（`xy-portal`）对「带头发起请求」的适配 —— 现网该键为空，尚无此类流量
- **Commit**：`571ba8c937`

---

## 十六、API Server：产物媒体与流式事件契约

### 16.1 MEDIA 附件下载 + finish chunk `hermes.files`

- **背景**（`3d9a9ceed4`）：agent 产出图片/文件时输出 `MEDIA:<path>` 标记，但远程 OpenAI 兼容前端（xy-portal 等）读不到网关本机路径。
- **方案**：
  - 图片仍内联为 data URL（保持既有行为）
  - 其余 `MEDIA:<path>` 登记为**不透明 id**，经 `GET /v1/media/{id}` 下载；注册与下载都走 `validate_media_delivery_path` 校验，原始路径不出网关
  - 流式 finish chunk 附带 `hermes.files`，供前端渲染附件卡
  - 新增 `gateway/platforms/api_server_media.py`（`ApiMediaStore`）
- **涉及文件**：`gateway/platforms/api_server.py`（+123）、`gateway/platforms/api_server_media.py`（新增 208）、`tests/gateway/test_api_server_media_files.py`（新增 97）
- **侵入类型**：inline（媒体端点）+ 官方树内新增模块
- **Commit**：`3d9a9ceed4`

### 16.2 媒体存储改为「接管字节 + 目录即索引」

- **背景**（`9df4372591`）：原 `ApiMediaStore` 是纯进程内存字典，且只登记产出方路径。两个独立失效源：
  1. 进程退出即清空索引 —— 网关一重启，磁盘上所有既有产物 id 立刻 404 `media_not_found`
  2. 文件本体留在产出方目录（线上实测为 `/tmp/hermes-inspect`），而 profile 容器并未挂载 `/tmp`，容器重建即丢；生产者的清理同样会让已下发的卡片失效
- **方案**：注册时把字节快照进受管目录，让目录本身充当索引：
  - 受管目录 `<HERMES_HOME>/cache/documents/api-media` —— 现成的无条件受信根，与 `state.db` 同卷同寿命，因此下载侧的 `validate_media_delivery_path` 照旧通过，`api_server.py` 除构造那一行外零改动
  - 条目名 `<media_id>__<原始文件名>`：id、下载文件名、MIME 全部可从目录列表推出 —— **没有内存表、没有 manifest、没有 schema 迁移**，重启后自愈
  - 注册经 `.part` 暂存 + `os.replace` 原子落位；**总是拷贝而非硬链** —— 硬链共享 inode，`os.utime` 会改到产出方文件的 mtime（扰动 `trust_recent_files` 的 recency 判定），且产出方后续原地改写会改掉已下发卡片的字节
  - 保留策略：TTL 24h → **30 天**，新增总量上限 **2GB / 4096 条**，按 mtime 最旧优先淘汰；节流用「每 32 次注册扫一次」的计数而非定时器 —— 注册是唯一的增长来源，容量上限在固定次数内必然收敛，空转时也不会无限堆积
  - 清扫只处理本店铸造的文件（`med_<id>__*` 与 `*.part`），目录内其它内容一律不动
- **配置**（可选）：`gateway.api_server.media_store.{dir,ttl_hours,max_entries,max_file_mb,max_total_mb}`；env `HERMES_API_MEDIA_STORE_DIR` / `HERMES_API_MEDIA_STORE_TTL_HOURS` 优先于 `config.yaml`，沿用 `gateway/media_policy.py` 的既有优先级约定。
- **破坏性变更**：部署后**既有 `med_` id 一律失效**（原映射是进程内存里的随机 id，无法迁移）；此后重启不再影响下载。
- **涉及文件**：`gateway/platforms/api_server_media.py`（+339）、`gateway/platforms/api_server.py`（构造一行）、`tests/gateway/test_api_server_media_files.py`
- **侵入类型**：inline（媒体存储实现）
- **验证**：21 项通过，含重启回归（同一 root 新建 store 仍解析既有 id）、删源文件不影响下载、过期/超容/孤儿暂存清理、目录内外部文件不被误删
- **Commit**：`9df4372591`

### 16.3 `tool.progress` 附带参数与输出摘要

- **背景**（`943b6bf1ac`）：前端 hover 详情卡无法区分连续的多条终端命令。
- **方案**：`chat/completions` 的 `hermes.tool.progress` 在 `running` 时带脱敏参数，`completed` 时带截断输出。
- **涉及文件**：`gateway/platforms/api_server.py`（+98）、`tests/gateway/test_api_server.py`
- **侵入类型**：inline（流式事件字段扩展）
- **Commit**：`943b6bf1ac`

### 16.4 产物下载的归属断言与「未声明即放行」决策

- **背景**（`0925bdf088`，本次补录）：`MEDIA:<path>` 登记为不透明 id 之后（§16.1），持 API key 且知道 `media_id` 者即可取件 —— 而多个用户可能落在同一容器（`default_profile` 共享实例、白名单走 root 本体）。需要一层归属断言，让「取件者就是登记方」在网关侧可判。
- **方案**（`0925bdf088`）：
  - 条目名带上登记方会话的摘要：`<media_id>__o<sha256前16>__<原文件名>`；无归属时退化为 `<media_id>__<原文件名>`，旧条目照旧可下载（§16.2 的「目录即索引」使旧名仍可解析）
  - 下载时重算摘要比对，不符返回 **404 `media_account_mismatch`** —— 不用 403，否则该响应会被当作「他人 id 是否存在」的探测器
  - 归属取**客户端传入的会话 id**（`X-Hermes-Session-Id`），刻意不用会被上下文压缩轮换的 `effective_session_id` —— 用后者会让压缩发生之后的下载断言必然失配
  - 连带整理：去掉不可达的 410 `media_gone` 分支（目录即索引后文件缺失已由 `get()` 走 404），统一为单码 `media_not_found`，仅保留 `is_file()` 作「取记录」与「开读」之间的竞态守卫；`register()` 经 `rejected` 回传超限文件 `{name,size,limit}`，`finalize_api_media` 改三元组返回，`notices` 供流式链路补发一帧正文 —— 流式早已 flush 完 `delta.content`，不补帧用户会以为附件已经送达。新增词条 `gateway.media_too_large`（en/zh 双 catalog，占位符一致）
- **涉及文件**：`gateway/platforms/api_server.py`（+87）、`gateway/platforms/api_server_media.py`、`locales/{en,zh}.yaml`、`tests/gateway/test_api_server{,_media_files,_media_owner}.py`
- **侵入类型**：inline（媒体端点归属断言）+ 官方树内新增模块
- **验证**：用例 131 → 148（+17：归属 8 项、条目命名/超限 7 项、流式端到端 2 项）；另修掉 `test_sweep_evicts_oldest_past_entry_cap` 一处既有偶发断言（用随机 id 排序判断淘汰顺序，约半数翻车）。无回归：与父提交在同一路径下跑同一批用例，失败集合逐条一致（24 项，均为 macOS 环境性失败）
- **Commit**：`0925bdf088`
- **决策 —— 「未声明即放行」为有意接受**（T2-7，2026-09-28 用户确认：**维持现状 + 显式记档**）：

  `_media_owner_matches` 在请求不声明任何身份头时 `return True`；且注册侧「无会话 id → `owner=""`」的条目在下载侧连该函数都不会被调用（`_handle_media_download` 的 `if rec.owner and ...` 整段跳过）。**两条通路都是刻意的**，docstring 与专门用例（`test_unattributable_request_is_allowed`、`test_owner_absent_leaves_legacy_name_shape`）都写明了意图。它接受的边界是：**对未声明的下载，`media_id` 是唯一的归属凭据** —— 握有 API key 且知道 id 即可取件。

  接受依据：

  | 依据 | 内容 |
  |---|---|
  | id 不可枚举 | `media_id = "med_" + secrets.token_urlsafe(12)`（96 bit），且只交给登记方 ⇒ 实际暴露面是「id 泄漏」（前端日志 / 截图 / 转发链接），不是「被猜出」 |
  | 收紧会锁掉设计对象 | 未声明 → 404 会拦住持有 API key 但不回带会话头的调用方，而那正是本项设计要求服务的一方；其真实行为在本仓库内不可核实（前端源码不在本仓） |
  | 单改一处不是完整修复 | 注册侧那条独立通路依然敞着，只改 `_media_owner_matches` 会给出不完整的安全感 —— 收紧必须两条一起改 |
  | 不对称是已知的 | 同文件的 `/v1/artifacts/download/{artifact_id}` 用**服务端推导**的 scope（profile principal + loopback 派生的 transport family）作 `scope_key` 精确相等比对，本身即 fail-closed，没有「不声明就放行」这一档 |

  残余风险（显式记录）：在共享容器（`default_profile` 共享实例 / 白名单走 root）中，持 API key 且拿到他人 `media_id` 者可下载他人产物；与 **T2-9**（跨用户暴露面）叠加时风险上升。归属摘要**本身不掺服务端盐**（§16.5 记录了该取舍），因此这条风险的缓解仍只有 `media_id` 的不可枚举性，叠加项亦只有 T2-9。

  本决策**钉在行为上**：`tests/gateway/test_api_server_media_owner.py::TestAcceptedUnattributedAccess` 断言「未声明即放行」与「注册侧落空 owner」，并断言 docstring 必须点名这是已接受的决策、必须给出本文出处。未来若要收紧，**改测试即是改决策** —— 不会作为某次重构的副作用悄悄发生（变异验证：把 `return True` 改成 `return False` → **4 例失败**；去掉 docstring 中的本文指针 → 1 例失败）。
- **未纳入**：`tool.progress` 的按会话隔离（T2-9）；前端侧「下载时回带会话头」的适配 —— 本仓无法核实。归属凭据本身的处置见 **§16.5**

---

### 16.5 会话 id 派生加服务端盐；归属摘要刻意不加盐

- **背景**（T2-8 / 安全官 S2-2）：`_derive_chat_session_id` 把「system prompt + 首条用户消息」直接截断 sha256 成 `api-<16hex>`，两个入参都**公开且客户端可控**（prompt 是前端自带的，首条消息是用户自己的）⇒ 派生 id 可被**离线算出**。这条 id 不只是连续性键：`/api/sessions/{id}`（GET / PATCH / DELETE / fork，`api_server.py:5279-5347`）只校验 API key 并直接从路径取 id，**无归属校验** ⇒ 可离线推导的 id 等于「可推导地读到、改到、删掉别人的会话」。媒体归属断言只是它被报出来的场景，不是它的实质。
- **原修法为何不成立**（安全官建议「两处摘要都掺盐」）：对归属摘要**零收益**。`_media_owner_matches` 比对的是 `media_owner_token(调用方送来的串)`，而盐在服务端作用于**送到的那串本身**，所以它只能关掉「离线算出一个派生 id」，关不掉「提交一个已知 id」与「什么都不声明」两条主路 —— 付了成本而边界未动。故盐**只加在派生上**。
- **决策**（2026-09-28 用户确认）：只给 `_derive_chat_session_id` 加 HMAC 服务端盐，盐源为**新增独立持久化密钥**；`media_owner_token` 保持不加盐，并在两处 docstring 写明这是决策而非遗漏。
- **方案**：
  - 新增 `owner/gateway/session_salt.py`：`api_session_salt()` 按 `HERMES_API_SESSION_SALT` env > `gateway.api_server.session_salt` config > `<HERMES_HOME>/api_session_salt` 解析；生成档为 32 字节 `secrets.token_urlsafe`，`mkstemp` + `os.replace` 原子写、0600。
  - 盐**跨重启稳定** ⇒ 派生会话连续性活过一次重启（`test_the_secret_survives_a_cache_reset` 断言第二次解析读到的是 `file` 档而非重新生成）。**多节点部署须统一注入 env/config**，否则各节点各自生成会得到不同 id。
  - `_derive_chat_session_id` 改 `HMAC-SHA256(salt, seed)[:16]`；**形状（`api-` + 16 hex）刻意不变** —— 该值会落进磁盘产物名与响应头，改形状是另一件事。
  - 降级：落盘失败 / 无 HERMES_HOME ⇒ 每进程随机盐 + `logger.error` 一次（点名声明的出路）。这只损失重启后的连续性，**不损失「不可离线推导」**；返回空串反而会恢复原缺陷。既有的**过短盐文件既不使用也不覆盖**（别人写的秘密不是我们的文件），同样走降级。`session_salt_source()` 把来源归因成 `env` / `config` / `file` / `generated` / `degraded`。
  - **不接受的近似**：过短的 env/config 值**不当作已配置** —— 占位符（如 `changeme`）最坏的不是弱，而是读起来像已配置。
- **未闭合的边界（显式记录）**：盐**不解决会话碰撞** —— 盐为整个部署共享，同 prompt + 同首句仍得同一 id（同容器两用户即共享会话与沙箱目录）。拆开需要一个本模块没有的「按身份」维度。`test_the_same_salt_still_collides_on_identical_inputs` 把这一条钉住：若哪天真的按身份隔离了，该用例会红 —— 那正是提醒更新本节的信号。
- **涉及文件**：`owner/gateway/session_salt.py`（新增）、`gateway/platforms/api_server.py`（`_owner_session_salt` 薄委托 + `_derive_chat_session_id` 改 HMAC + 两处 docstring）、`tests/owner/test_session_salt.py`（新增 23 例）、`tests/gateway/test_api_server_media_owner.py`（+2 例钉住「摘要不加盐」）
- **侵入类型**：官方文件薄胶水（一个模块级 helper + `_derive_chat_session_id` 内 8 行）
- **验证**：新增 23 例覆盖优先级三档 / 生成落盘 0600 与暂存清理 / 跨重启稳定 / 三条降级路径 / 换盐换 id / 碰撞仍存在 / 形状不变 / 来源可归因。**变异验证 6 条全部失败**：撤销加盐 → 3 例；接受过短盐 → 1 例；删缓存提前返回 → 1 例；覆盖操作者的短文件 → 1 例；落盘权限放宽到 0644 → 1 例；空盐当有效 → 1 例。
- **连带修复**（建立基线时发现的两处既有缺陷。与本题无关，但会让「回归全绿」这句话失真，故一并修）：
  - `tests/gateway/test_api_server_media_files.py::test_sweep_evicts_oldest_past_entry_cap` 用 `name.split("__", 1)[0]` 解析条目名。id 是 `med_` + token，token 首字符恰为 `_` 时条目名成为 `med__…`，解析结果退化成 `"med"` ⇒ 实测约 **3.1%** 翻车（`1-(63/64)^2`）。改为按 id 锚定的 `glob(f"{id}__*")`（与同文件 `_blob` 同法）。**不可改用 `store.get()`**：它还套用 TTL，而本用例故意把 mtime 钉在 epoch 1000，会被判过期并真的删掉条目。
  - `tests/owner/test_identity_routing_dormant.py` 的 `_LdapGateProbe.patch()` 只在**进入时**清 `_owner_lazy`，退出时仅还原模块属性 ⇒ 探针自己那次调用把 `fake_gate` 记忆化，同一 pytest 会话里后面的 `test_ldap_identity_auth.py` 拿到**假门**，放行本应被拒的请求；配置里的 `profile_endpoints` 指向本机真实监听中的网关，于是表现为该网关回的 401 `gateway_auth_failed`（**7 例失败**）。改为退出时一并清缓存。
  - 净收益：`tests/owner/` + `tests/gateway/test_api_server*.py` 由 **7 例失败 / 956 通过** 变为 **963 例全通过**。
- **未纳入**：`/api/sessions/{id}` 端点自身的归属模型（上游既有设计：只认 API key + 路径里的 id）—— 本条只让派生 id 不再可离线推导；`tool.progress` 的按会话隔离（T2-9）
- **Commit**：`a622691915`

---

### 16.6 `tool.progress` 出口强制脱敏 + 帧绑定断言；飞书转发补子容器归属校验

- **背景**（T2-9 / 安全官 S2-3 + S2-4）：S2-3 指 `hermes.tool.progress` 把工具 args（≤6000 字符）与输出摘要（≤1500）推入 SSE，「隔离完全依赖『SSE 只回发起者』这一隐式前提」；S2-4 指群聊 reaction 按**反应者**而非**消息归属**路由。
- **S2-3 取证（比原记录多三条通路）**：① args 只过 `redact_tool_args_for_display`，而该函数实测**只处理 `browser_type.text`**（`agent/display.py:401-415`），其余工具原样出口；② `_clip_tool_output_for_sse` **完全没有任何脱敏**（只挑字段 + 截断）；③ **`label` 字段**由 `build_tool_preview(function_name, function_args)` 从**原始** args 派生 —— 只脱敏 `args` 仍会从 label 漏出密钥，是最容易连带漏掉的一条通路；④ native run 事件流（`/v1/runs` 的 `_tool_progress`）把 `args` 原样且**不限长**入队；⑤ Responses 通道（`/v1/responses`）的 `function_call.arguments` / `function_call_output.output` 原样出网（该通道按 spec 就是要回显参数）。
- **「隔离依赖隐式前提」这一判断在仓内成立**：`_stream_q` 在 handler 内按请求新建、`_run_agent` 每请求新建 agent、回调闭包绑死该队列 —— 仓内**不存在**按会话扇出的逻辑，所以 P2 评级合理。问题不在隔离被破坏，而在**出口本身把工具参数与命令输出原样放出去**：一旦消费方（portal / 前端）按会话或按 chat 扇出，被放出去的就是真东西。
- **S2-4 原修法为何不成立**（审查建议「维护 `message_id → origin profile`（出站时落库，`d74762a04e` 已做）并只在归属匹配时转发」）：
  - 落库落错了地方。`d74762a04e` 写的是**发送方容器自己** `state.db` 的 `delivery_obligations.platform_message_id`，**没有 profile 列**；而主网关与子容器是**不同 HERMES_HOME / 不同 state.db**（容器身份取自 `HERMES_PROFILE`，见 `owner/approval/skill_manage_gate.py:181-198`）⇒ 处理 reaction 的主网关**根本看不到那张表**。
  - 即便在容器内部可用，`gateway/delivery_ledger.py` 的 `_RETENTION_SECONDS = 7 天` + `_MAX_ROWS` 上限 + 受 `gateway.delivery_ledger` 开关控制 + 写入 best-effort（docstring 明写「ledger failures must never block an actual send」）⇒ 拿它当归属判据会**误丢超过 7 天的消息上的表情**。
- **现网拓扑实测（决定 S2-4 的真实可达面）**：`user_routing` 为 `default_profile: hermesxiyun` + `whitelist: {杨天宝}`；`resolve_profile_route` **在群聊里跳过 whitelist**（`profile_routing.py:102-119`）⇒ 群聊里**所有人**的消息（含白名单用户的）都进同一容器，白名单用户的群表情也进同一容器 —— **去向一致**。容器内 `group_sessions_per_user` 默认 **True**（`adapter.py:4522`）⇒ 每个参与者独立会话 ⇒ 表情落在**反应者自己**的会话。因此当前拓扑下**不存在跨边界误投**，可达影响限于「同一容器内把表情投给了与消息不同属的会话」（只有表情文本跨过去，无跨用户读取）。S2-4 维持审查给的 **P2**；工作台把 T2-9 升到 P1 的叠加理由在 reaction 这一半**不成立**（tool.progress 那一半成立）。
- **决策**（2026-09-28 用户确认）：
  - S2-3：**强制脱敏 + 帧绑定断言**。args/output 出 SSE 前一律过 `redact_sensitive_text(force=True)`；每请求的进度帧打上 run 绑定标识，写出侧断言「帧只投本请求」，跨请求即降级为只发工具名 + 状态。
  - S2-4：**补子容器身份校验 + 钉语义**，**不改路由**。转发载荷带 `target_profile`，子容器按自身身份校验、不匹配即显式拒绝；把「群聊表情投给反应者自己的会话」写成显式决策并用用例钉住。
- **方案**：
  - 脱敏统一走 `agent.redact.redact_sensitive_text(force=True)` —— 复用日志那套模式表，而不是另造一套；`force=True` 是 `agent/redact.py` docstring 明写的「must never return raw secrets regardless of the user's global logging redaction preference」边界档，因此**不受** `security.redact_secrets: false` 影响。新增 `_redact_for_sse()` / `_redact_args_for_sse()`（递归到 dict/list/tuple 内的字符串）/ `_redact_result_for_sse()`。
  - **顺序是逻辑的一部分**：先在**值的层面**脱敏再截断。反过来会留下 `…ghp_abc` 这样的密钥碎片，而碎片一旦被截断就短到模式表认不出、dict 级兜底也救不回来（完整密钥两种顺序都留不下，差别只在这段碎片 —— 用例只钉这一段，不夸大）。
  - **脱敏不可用即拒绝出网**：`_redact_for_sse()` 取不到脱敏器时返回占位符而非原文，并 `logger.error` 一次。这是出口边界，「无法确认」不能静默降级成「原样发出」。
  - 帧绑定用**三元素元组** `("__tool_progress__", token, payload)`：token 走队列元组、**不进 payload** —— payload 会被原样序列化上网，而这条断言是内部契约，消费方既不需要也不该解析它。`_tool_frame_is_ours()` 对**无 token 的旧二元组**与**token 不匹配**一律返回假（fail-closed），写出侧把这类帧降级成 `{tool, toolCallId, status}`（`_stripped_tool_frame`）而不是丢弃 —— 表情/工具生命周期 UI 不能因为一次越界就消失。chat-completions 与 Responses 两条 SSE 通道共用同一套。
  - S2-4 的校验放在**子容器入口**、与业务解耦：`owner/feishu/profile_routing.py` 新增 `container_profile_identity()` 与 `verify_inbound_target_profile(body)`；发送侧 `_forward_to_profile_container` / `_forward_card_action_sync` 带 `TARGET_PROFILE_KEY`；两个 doorway（`/v1/feishu/inbound`、`/v1/feishu/card-actions`）在鉴权后立即校验，不匹配返回 **409 `profile_mismatch`** 并点名两侧 profile。
  - **校验对失败刻意不对称**：两侧都识别出来且不等 ⇒ **拒绝**；`target_profile` 缺失（旧发送方）或自身身份不可判定 ⇒ **接受 + 告警一次**。后两种若一律拒绝，会把一次版本错配或一个没打标的容器变成**整个多租户路由全部不可用** —— 那比它要防的误投更糟。API key 仍是鉴权边界，这条是纵深。
  - **自身身份不猜**：`container_profile_identity()` 只读 `HERMES_PROFILE` env 与 `user_routing.container_profile` 配置，**不**回落到「当前 profile 名 / `default`」。这个值决定**是否拒绝**流量，猜「default」会在真实 profile 是别的名字时把所有正确寻址的事件全拒掉。
- **未闭合的边界（显式记录）**：
  - 帧绑定断言保护的是**本进程内**的投递对象。会话 id 可被调用方用 `X-Hermes-Session-Id` 指定并加入他人会话（只认 API key），这是上游既有模型，本条未动（同 §16.4 / §16.5 的取舍）。
  - S2-4 的校验挡的是「主网关**寻址错了**」这一类配置漂移；容器自身身份没配出来时该检查自动让行（上面那条不对称规则），残余风险 = 一个没打标容器仍会接受任何寻址。
  - 群聊 per-user 路由的语义张力本身没解：群是共享状态，而 `user_profile_routes` 是按人分的。本条只把「表情按反应者解析」记档为决策，没有改这个模型。
- **涉及文件**：`gateway/platforms/api_server.py`（`_redact_for_sse` / `_redact_args_for_sse` / `_redact_nested_for_sse` / `_redact_result_for_sse` / `_bind_tool_frame` / `_tool_frame_is_ours` / `_stripped_tool_frame` / `_owner_inbound_profile_rejection` / `_profile_mismatch_response` + 两处 clip 助手 + 两条 SSE 通道的产出与写出点 + `/v1/runs` 的 `_tool_progress` + 两个 feishu doorway）、`owner/feishu/profile_routing.py`（`TARGET_PROFILE_KEY` / `container_profile_identity` / `verify_inbound_target_profile` / `reset_ownership_notices` + 两处转发载荷）、`plugins/platforms/feishu/adapter.py`（reaction 的决策记录）、`tests/gateway/test_api_server_tool_progress_egress.py`（新增 18 例）、`tests/owner/test_feishu_profile_transport.py`（+14 例）
- **侵入类型**：官方文件薄胶水（api_server 的出口加固函数与 8 处调用点；adapter 仅注释）
- **验证**：新增 32 例 + **变异验证 11 条全部失败** —— A1 参数值先截断后脱敏 → 1 例 / A2 output 不脱敏 → 3 例 / A3 label 不脱敏 → 1 例 / A4 帧不校验 token → 2 例 / A5 脱敏器失败时放行原文 → 1 例 / A6 Responses 的 arguments 不脱敏 → 1 例 / B1 归属校验恒不拒绝 → 2 例 / B2 身份不可判定时猜 `default` → 2 例 / B3 发送侧不带 `target_profile` → 1 例 / B4 入口不校验 → 1 例 / B5 决策记录被抹掉 → 1 例。其中 A1 与 A6 的守卫**一度测不出来**：A1 被 dict 级兜底遮蔽（断言完整密钥时两种顺序等价），A6 的变异模式同时命中相邻字典。A1 的解法是把断言下沉到**密钥碎片**（`test_redaction_precedes_the_per_value_cut` 断言 `"ghp_abc"` 不出现），A6 的解法是给变异脚本加**命中数期望**并收窄范围。两条已沉淀为 skill 第 23–24 条。
- **未纳入**：`/api/sessions/{id}` 的归属模型（上游既有设计）；SSE 扇出逻辑本身（**不在本仓**，无法核实）；群聊 per-user 路由模型的改造；`tool.progress` 对「能力型工具只发摘要」的收紧（用户选定只做强制脱敏，避免改变前端可见的工具参数）
- **Commit**：`6b80b565f4`

---

### 16.7 `output_guard` 的复读判据由 O(n²) 正则改为线性扫描（语义不变）

- **背景**（T2-10 / 代码审查 L1）：v2 生成退化扫描里的复读判据写作 `_WORD_REPEAT = re.compile(r"(\S+)( \1){5,}")`，调用点 `_degenerate_scan()`。
- **实测比原记录更重**：审查记录「4000→175ms / 8000→692ms / 16000→2745ms，`_MAX_CHARS` 按 O(n²) 外推约 20s」—— 其中 2745ms 实为 **16000 字符**的实测值，被当成了 40000。本机实测（各取 3 次最小值）：4000→185ms、8000→735ms、16000→**2 962ms**、40000→**18 735ms**、50000（= `_MAX_CHARS`）→**30 360ms**，翻倍即 ×4。
- **为什么它是真问题**：该判定位于每轮生成收尾的**同步阻塞链**上（`agent/turn_finalizer.py` 的 `transform_llm_output` → `analyze`，且已被前移到 `_persist_session` 之前），而触发输入是**完全合法的正常中文长回复**（判定结果为 `verdict=ok`）⇒ 最坏会把落库、微压缩与最终投递一起拖住半分钟。这与模块 docstring 自己写的契约「纯 stdlib、**O(n)**、微秒~毫秒级，不影响回复延迟」直接矛盾。
- **为什么不用「量词加上界」**：审查给的二选一里 `(\S{1,64})` 一行即可、393× 提速，但它**不是语义等价** —— 重复单元长于 64 字符时不再命中（实测 64 字符命中、65 与 200 字符双双漏判），且该形态下 `dirty_run` 与 `comp_belt` 都不会补位（`comp_belt` 要求 `sentence_count ≥ 10`，而这种重复的句子数只有 1）。故采用**线性扫描 + 完整复刻原语义**（2026-09-28 用户决策）。
- **等价性怎么证**：把**被替换掉的原正则**原样留在测试里作 oracle，逐例比对「命中与否 + **最左匹配起点**」，而不只是命中与否。开发期扫到 **140 536 例零不一致**（穷举 `{a,b,空格,Tab,换行}` 长度 ≤ 7 的全部串 97 656 例 + 随机语料 40 000 例（含 NBSP 与全角空格）+ 结构化 2 880 例）；**提交进仓的用例**保留约 22 400 例（穷举长度 ≤ 6 的 19 531 例 + 随机 2 000 例 + 结构化 882 例），run 时间 0.7s。
- **原语义里两处未写档的既成行为**（照旧保留，均已写进函数 docstring 并钉了用例）：
  - 重复单元只能是「某个非空白 run 的、从起点到 run 末的**尾串**」⇒ 正则**可以从 token 中间起步**（`Zabcde` + 5×`abcde` 在偏移 1 处命中，`first_offense=1`）。
  - run 的边界是**任意**空白（Tab / 换行 / NBSP 都算），而重复段之间的分隔符必须是**字面单空格** —— 两者必须分开建模，否则 `a\tb a\tb …` 会被线性版误判命中（正则不命中：`\S+` 只能匹配到 `a`，其后不是空格）。
- **方案**：`_find_word_repeat()` 只穷举两种起点形态（run 起点 / run 内部，后者由「第 2 次出现后必须跟空格 ⇒ 它本身是完整 token ⇒ 单元长度唯一确定」推出），每种只需一次常数比较 ⇒ 整体 O(n)。助手 `_repeat_after` 只校验「单空格 + unit」而**不**要求 unit 之后也是空白（反向引用是字面串，可以落在更长 token 的前缀上）；`_token_at` 按 `_WS_RE` 取 run。判定语义、次数阈值（6 次）、信号名 `word_repeat` **全部不变**。
- **效果**：50000 字符 **30 360ms → 0.26ms**；端到端 `analyze()` 于 50000 字符为 4.8ms（余量来自 `dirty_run` 与 zlib）。
- **同类普查**：`owner/` 树内 8 处 `re.compile` 逐个核对 —— **仅此一处使用反向引用**，故「无上界量词 + 反向引用」这一二次回溯组合在本仓仅存在于此、已随本条修掉；`stream_guard._MARKER_RE` 是固定短语的择一，无反向引用、无嵌套量词，不构成 ReDoS。无需其他改动。
- **涉及文件**：`owner/owner-extensions/output_guard/__init__.py`（新增 `_find_word_repeat` / `_repeat_after` / `_token_at` / `_WS_RE` 与 `_WORD_REPEAT_MIN_RUNS` / `_WORD_REPEAT_SEP`，删去 `_WORD_REPEAT` 正则；`_degenerate_scan` 改调用点；模块 docstring 与常量注释记录成因）、`tests/owner/test_output_guard.py`（+8 例）
- **侵入类型**：owner-extensions 插件（**零官方侵入**）
- **验证**：新增 8 例；**变异验证 9 条全部咬住** —— M1 退回原正则 → 2 例（时间上界 30.43s + 端到端 30.40s）/ M2 收窄为 `(\S{1,64})` → 2 例（差分 + >64 字符 token）/ M3 去掉尾串形态 → 1 例 / M4 给反向引用补尾随边界要求 → 差分 1 例 / M5 run 边界只认空格 → 差分 1 例 / M6 次数下限 6→5 → 1 例 / M7 重新引入无上界正则常量 → 1 例 / M8 抹掉 docstring 里的成因 → 1 例 / M9 段长上界判断由 `>` 收紧为 `>=` → 差分 1 例。定向回归（`tests/owner` + 3 个 `tests/gateway/test_api_server*.py`）**977 通过 / 0 失败**，父提交基线 **969 通过 / 0 失败**，`comm -23` 为空（差集恰为本轮新增的 8 例）；健康检查 **6 passed / 1 warning**（该 warning 是 merge `315551234` 的 4 条旧标记丢失，属既有，归 T2-11）。
- **未纳入**：`_degenerate_scan` 的分块扫描（本就是 O(n)）；`stream_guard` 的正则（已核查，无反向引用）。
- **Commit**：`958594ce6f`

### 16.8 官方改动文件 `[owner]` 标记全量补齐 + 覆盖率守卫（T2-11）

- **背景**（T2-11 / 代码审查 M1）：sync fork 解冲时，判断某个 hunk 属于我们还是上游，靠的就是改动处的 `[owner]` 标记。而当时**有 58 个已被修改的官方文件全文没有任何标记** —— 解冲者只能按「上游代码」处理，整份定制被静默搬走。merge `315551234` 就是这样丢掉了 4 处标记（见 Check 5 的 4 条 warning）。
- **口径先校正**：审查原文写「67 个官方文件」。实测口径差异在于**「无 `[owner]`」与「无任何标记」是两个集合** —— 前者 68 个（含 10 个只用 `[owner-patch]`），后者 **58 个**。本条的落地对象是后者（另 10 个由 `[owner-patch]` 归一覆盖）。
- **范围边界**：官方目录下**新增**的文件不在本条内 —— 按 §2.2，新增文件靠 commit message 的 `[owner]` 前缀标识，不需要文件内标记。故统计一律用 `--diff-filter=M`。本仓该窗口内新增官方文件 11 个（`translucency.cjs`/`.test.cjs`、`api_server_media.py`、`feishu_client_utils.py`、`mimo_thinking.py`、`plugins/model-providers/damodel/*`、`REVIEW.md`、`ui-tui/src/owner/*`）。
- **改前基线**：官方（非 `owner/`、非 `tests/`）改动文件 **117** 个，其中**零标记 58 个**；`--diff-filter=M` 窗口内共 **363 个带新增行的 hunk** 待落标记（另有 6 个纯删除 hunk），分布 **43 个 `.py` + 13 个 `.ts/.tsx` + `.gitignore`**。
- **做法（逐 hunk 全标）**：每个 hunk 的**首个新增行上方**插一行标记。三类边界情形各有专门处置，且都不是"跳过"：
  1. **改动落在多行字符串内部**（12 处：`agent/display.py`×3、`hermes_cli/commands.py`×3、`gateway/delivery_ledger.py`×2（`CREATE TABLE` 与 `SELECT` 字面量）、`kimi-coding/__init__.py`、`tools/feishu_drive_tool.py`、`ui-tui/src/gatewayTypes.ts`、`hermes_cli/gateway.py`）—— 往字符串里插 `#` 会改坏内容，故**上移到该字符串 token 起始行的上一行**，并在文案里注明「改动在下方的多行字符串内」。典型是 `hermes_cli/gateway.py`：唯一 hunk 落在 **112 行**的 respawn 脚本模板里，若无上移规则该文件会保持零标记。
  2. **JSX children 位置**（`ui-tui/src/components/branding.tsx` 1 处）—— 裸 `//` 在 JSX children 里**不是注释而是文本子节点**，banner 会多渲染一行字面量；改用 JSX 惯用的 `{/* ... */}`。
  3. **纯删除 hunk**（6 处，涉 4 文件：`.gitignore`、`agent/display.py`、`tools/feishu_drive_tool.py`、`ui-tui/src/app/useMainApp.ts`）—— 没有可挂的新增行，改为在**文件顶部**登记一小块「本文件另有 N 处仅删除上游代码的改动：新文件第 X 行附近」并含清单指针。
- **标记格式的另一处取舍**：规范 §2.2 要求「短描述 + 指向 owner/ 位置」，但给 361 个插入点各带一句指针会给官方文件灌进约 19KB 纯注释，直接与 §2.1「极致最小化」相抵，反而放大每次 sync 的冲突面。故**标记只留短描述**（如 `# [owner] i18n 中文文案 t() 替换`），指针改由**改动清单的每文件条目**承担 —— 为此本轮同时补齐了附录 B 中缺失的 39 个文件条目，使「指针可查」成立。§2.2 已同步写入这条细则。（本仓 116 个官方改动文件在附录 B 中全部有全路径条目 —— 收口过程见 §16.9 的「顺带收口」。）
- **生成物豁免**：`uv.lock` 的 4 个 hunk 曾插入标记，实测后**撤回** —— `uv lock` 会整文件重写、标记必被抹掉，且解冲时标记会诱导人保留本应重新生成的产物。依赖 pin 的标记挂在人工维护的 `pyproject.toml`（已有 `# [owner] LDAP bind auth ...`）。生成物清单固定在 `_GENERATED_ARTIFACTS`。
- **`[owner-patch]` 归一**：全仓 95 处，**33 个文件共 90 处**归一为 `[owner]`（含 23 处清单散文、6 处 `inventory.yaml` 断言载荷、2 处补丁源码注释、1 处 `hermes_state.py` 的 SQL 字面量内注释）。刻意保留 5 处：**3 处**在 `owner/code-review/00-REVIEW.md`（2026-09-28 那轮评审的**冻结报告**，正文是当时的发现记录，改写会抹掉证据价值）、**2 处**在 `merge_health_check.py`（`_OWNER_MARKER_RE` 的 `(?:-patch)?` 容错分支 + `_normalize_owner_marker_line` 的 `.replace("[owner-patch]", " ")`）。后者是承重的：Check 5 要比对 merge `315551234` 的**历史删除行**，那些行里就是旧拼写（本次健康检查输出中可见），丢掉容错会让历史标记从"可见的遗留"退化为"不可见的 hunk"。
- **归一的安全网**：`inventory.yaml` 的 6 条 `file_contains` 断言直接匹配 `# [owner-patch] <描述>` 文本，只改源码不改断言会让 Check 7 立刻变红 —— 这条断言恰好成了改名完整性的哨兵，改完两侧一致后 Check 7 为 0 issue。
- **配套守卫（新增 Check 8）**：`merge_health_check.py` 增至 8 项检查。Check 8「Changed-file [owner] marker coverage」以 `git merge-base HEAD {upstream/main,origin/main,main}` 为基准（三者在本次均为 `00b2e03c80`），取 `--diff-filter=M` 的官方文件，逐个断言含至少一个 `[owner]` 标记；命中即 FAIL（不是 WARN）。这条守卫把"零标记官方文件"从**一次性人工普查**变成**每次跑健康检查都会验的不变量**。
- **效果**：官方改动文件覆盖率 **0 标记 58 个 → 116/116 全覆盖**（117 减 1 个生成物）；健康检查 **6 passed / 1 warning → 7 passed / 1 warning**，Check 5 的 4 条既有 warning 不变（属 merge `315551234`，非本轮引入）；Check 4 识别 **670 个标记 / 99 个文件**。
- **涉及文件**：58 个官方文件的标记插入（+365 行注释，纯插入、**零删除行**）；33 个文件共 90 处 `[owner-patch]` → `[owner]`；`owner/validation/merge_health_check.py`（新增 `check_changed_file_markers` / `_resolve_upstream_base` / `_is_generated_artifact` / `_GENERATED_ARTIFACTS` / `_UPSTREAM_BASE_REFS`，注册为 Check 8，模块 docstring 与 `_OWNER_MARKER_RE` 注释同步）、`tests/owner/test_merge_health_check.py`（+3 例）、`owner/docs/二次开发规范.md`（§2.2 新增「标记细则」+ §5 补注）、`owner/docs/owner改动清单.md`（本条 + 附录 B 补 39 个文件条目 + 附录 E）
- **侵入类型**：仅注释（**零逻辑改动**）
- **验证**：全部 43 个改动 `.py` 过 `py_compile`；**改名纯度逐行校验** —— 33 个改名文件的删除行与新增行**完全配对**，84 对逐对比较**每对只差 `[owner-patch]` → `[owner]`**，无附带改动；58 个插入文件为纯新增行（`git diff --numstat` 第二列全为 0）；`tests/owner/` **837 通过 / 0 失败**；**Check 8 变异验证 4/4 咬住** —— A 反向验证：从 47 个标记的 `browser_tool.py` 删 1 个 → 不报错（证明是文件级覆盖而非逐 hunk 计数）/ B：删掉只有 1 个标记的 `background_review.py` 的标记 → 用例 1 failed + Check 8 报 1 条（115/116）/ C：撤掉生成物豁免 → 点名 `uv.lock`（117/116，证明豁免承重）/ D：清空基准 ref 候选 → 优雅降级为 `skipped` 而非崩溃。
- **未纳入（已登记为独立待办 T2-11b）**：逐 hunk 铺开本轮只覆盖了**零标记的 58 个文件**。用工作区重算，官方文件共有 **1528 个带新增行的 hunk**，其中 **626 个带标记**、**902 个未标记**，分布在 **55 个「已有标记但不完整」的文件**里（前 15 名占 692 处 = 76%：`gateway/run.py` 190/233、`tools/approval.py` 90/95、`agent/conversation_loop.py` 62/71、`hermes_cli/model_switch.py` 58/65、`plugins/platforms/feishu/adapter.py` 41/81、`gateway/platforms/api_server.py` 38/54、`cli.py` 36/40 …）。这 55 个文件在清单里都已有条目可查，且 Check 8 会持续守住文件级覆盖，故本轮**按文件级收口**（2026-09-28 用户决策），hunk 级铺开另立条目按冲突权重分批推进。
- **Commit**：`a77e345342`（代码 + 测试；本条留档见附录 E）

---

### 16.9 写入护栏文案的英文原文回归代码 + `_localized()` 渲染与漂移守卫（T2-12）

- **背景**（T2-12 / 逻辑审查）：`tools/file_tools.py` 的两处写入护栏（`_request_protected_instruction_approval`、`_check_approval_required_write`）上游把文案写成**函数内的模板常量**，模板内含 `{why}` 占位符、由 `.format(why=...)` 在 7 + 8 个分支分别填充。一次 i18n 改造把模板与 8 个 `why` 片段整体搬进 `locales/{en,zh}.yaml`（12 个目录键），代码里只剩 `t("<key>")`。
- **为什么这是真问题（不是风格）**：改造后运行期输出的**唯一来源是目录**。上游日后改词会在代码里形成冲突并被人工解决，但解决了也换不来新文案 —— 输出仍取自目录。更关键的是模板里那句安全指令（`Do NOT retry it or attempt the same edit via another path (terminal, execute_code, etc.)`）**只存在于目录**，上游删改它不会在代码里留下任何痕迹。属「上游护栏改进永不传导」这一类。
- **口径先校正**：实测这 **12 条字符串当前与上游逐字一致**（AST 抽取两版逐条比对，唯一差异是 SSH 那对模板里占位符名 `{display_targets}` → `{targets}`）。因此本条修的是**潜在分叉**而非已发生的分叉，改动是**无损**的 —— 中/英输出零变化（见验证）。
- **为什么不能按审查原建议「只把最终文案交给 `t()`」**：`agent/i18n.py::t()` 是**目录键查找**，没有接收英文原文的参数（回落链是 目标目录 → en 目录 → 裸键）。要让英文原文成为真源，必须在 `t()` 之外另加一层渲染。
- **方案（2026-09-28 用户决策：原文回归代码）**：
  - 4 个模板 + 8 个 `why` 片段以**具名模块常量**写回 `tools/file_tools.py`（措辞与上游逐字一致），并由 `_GUARD_EN_TEXTS` 把「目录键 → 英文原文」显式登记成表；调用点引用同名常量，因此表与调用点用的是同一个字符串对象。
  - 新增 `_localized(key, en_text, **kw)`：活跃语言为 `en` ⇒ 直接格式化并返回代码原文、**不查目录**（上游改词因此自动传导到输出）；非 `en` ⇒ 取 `key` 的目录条目，**目录全缺时回落代码原文**（不抛异常、不把裸键显示给用户）。
  - `_blocked()` 由 `(why)` 改为 `(why_key, why_en)`：外层渲染模板、内层 `_localized(why_key, why_en)` 渲染 `why` 片段。这一层不能省 —— 省掉后英文片段会漏进中文输出（见验证中的变异 G7b）。
- **渲染助手放在 `tools/file_tools.py` 内而非 `owner/i18n/`**：`owner/i18n/` 是**输出侧展示层**翻译（设计文档 `owner/docs/design/i18n-display-layer/display-layer.md` §3.2 记录：回退 643 处 `t()` 调用点后与上游的冲突块 450 → 451，**净零**，T1-4 因此暂停）。为 12 条护栏文案复活那个机制属无实测收益的范围外扩张；放在文件内还使漂移守卫退化成一个**纯本地**比较。
- **漂移守卫是纯本地的**：`tests/owner/test_file_tools_guard_text_i18n.py` 只比对「代码常量 vs `locales/en.yaml`」，**不需要上游 ref** —— CI 只克隆单分支时也能跑（对比 Check 8 需要 `merge-base`，缺 ref 时只能降级为 skipped）。
- **守卫清单（7 类，全部经变异验证）**：① 代码常量 ↔ en 目录逐字一致；② zh 目录对 12 个键全覆盖；③ 代码里出现的每个 `_localized`/`_blocked` 键都在表里、且表里没有无人引用的键；④ 受守卫的键不得再以 `t("<key>")` 直取（会绕过代码真源）；⑤ 每个调用点必须把键与**表中那个**常量配对（按对象身份把常量表反查成「键 → 常量名」，再从 AST 逐调用点核对，纯机械、不依赖目录）；⑥ en 输出不查目录、非 en 必须查目录（双向哨兵法）；⑦ 目录全缺时回落原文且不抛异常，外加两个护栏的端到端文案在 en/zh 下的语言一致性与键↔常量配对。
- **技巧（值得复用）**：「en 输出不查目录」用**哨兵法**证 —— 把目录值全换成哨兵串，断言 en 输出不变；非 en 再做一次**反向**哨兵（断言哨兵**出现**）。这比比对常量更硬：它直接证明「查没查目录」这条控制流事实，而不是间接推断。
- **一个被变异测试抓出的自证陷阱**：端到端 zh 断言最初写成「与 `t(template, why=t(why_key))` 逐字相等」，而改造前后 zh 路径**都**走目录 ⇒ 该断言对目录改动完全不敏感（变异「改 zh 模板」实测**不失败**）。改为断言与目录无关的性质：三段文案必须互不相同（证明 why 键配对正确且各自被本地化）+ 英文原文一个字都不许出现在中文输出里。
- **涉及文件**：`tools/file_tools.py`（新增 12 个英文原文常量 + `_GUARD_EN_TEXTS` + `_localized`；`_blocked` 签名与 15 个调用点改写；import 面加 `DEFAULT_LANGUAGE` / `get_language`）、`tests/owner/test_file_tools_guard_text_i18n.py`（新增 11 例）、`owner/docs/owner改动清单.md`（本条 + 附录 B 收口 + 附录 E）
- **侵入类型**：inline（字符串）+ 局部渲染助手（**零行为改动**）
- **验证**：
  - **输出零变化**：12 个键 × en/zh/ja 与「改造前行为（全走目录）」逐字比对，**0 处不一致**；两个护栏端到端（无人工通道的 fail-closed 分支）在 en/zh 下逐字一致。
  - **变异验证 14/14 全部咬住**：G1 改代码常量 / 改 en 目录 → 漂移守卫失败；G1 zh 目录删键 → 覆盖守卫失败；G2 表里删条目 / 调用点引用未声明键 → 结构守卫失败；G3 改回 `t("<key>")` 直取 → 失败；G4 en 分支改成也查目录 → 哨兵泄漏；G5 非 en 改成永远返回原文 → 反向哨兵缺失；G6 目录全缺时抛异常 → 失败；G7 ssh 分支配错 why 常量 → 失败；G7b `_blocked` 不再本地化 why → 中文断言失败、英文**如期通过**（说明该条守卫不可省）；G8 gate 1 配对错 why 常量 → 失败；G8b 常量对但键配错（en 输出**看不出**）→ 机械配对守卫失败；G9 退化为硬编码字符串 → 失败。
  - **定向回归 1325 通过 / 7 失败**，与改造前基线**失败集合完全相同**（新增集合为空；7 例为既有失败：2 例 macOS `/tmp` → `/private/tmp` 符号链接、5 例 `tests/tools/test_approval.py` 的 webhook / timeout 用例）；通过数 +11 恰为本轮新增用例。
  - 健康检查 **7 passed / 1 warning**（Check 5 的 4 条既有 warning 不变）；Check 8 **116/116**。
- **同类普查**：官方 `.py` 文件共 **827 个 `t()` 键**，其中 **229 个**（分布在 **28 个官方文件**）与 T2-12 同属一类 —— 上游代码里**有**该文案、被 `t()` 替换后文案只存在目录里（判定法：取 en 值里最长一段不含占位符的 ≥20 字符片段，看它是否「当前文件没有、BASE 版本有」）。集中度：`gateway/run.py` 73、`agent/conversation_loop.py` 33、`cli.py` 25、`hermes_cli/models.py` 18、`tools/memory_tool.py` 15、`tools/computer_use/doctor.py` 13、`gateway/platforms/base.py` 8 …。本条只改造写入护栏这 12 条（含安全指令、价值最高）；其余未逐条回归代码 —— 逐一搬回会把这些文件的 i18n 侵入面显著放大、与 §2.1「极致最小化」相抵，应先按「是否含安全指令 / 是否易被上游改动」排序再分批。
- **顺带收口**：附录 B 补齐本仓 **28 个官方改动文件**的速查条目（**25 行**，部分行按主题合并），使 **116 个官方改动文件在附录 B 中全部有全路径条目**；其中 `hermes_cli/tips.py` 此前在清单全文任何位置都没有路径提及，一并补上。
- **未纳入**：`t()` 公共签名是否该扩展为「可传英文原文」（本条用局部助手规避，未动公共 API）；上面普查出的其余 217 个同类键未逐条改造。
- **Commit**：`dfedb2ec74`（代码 + 测试；本条留档见附录 E）

---

### 16.10 `discover_and_load` 消除 40 行纯缩进重排 + 取锁失败可观测（T2-13）

- **背景**（T2-13 / 合并冲突审查 §4.4）：owner 侧为消除「hermes 开局白屏挂死」（§7.20）给 `PluginManager.discover_and_load()` 加了带超时的取锁。当时把上游的 `with self._discovery_lock, _plugin_home_scope(self.home_path):` 拆成 `acquire(timeout=15.0)` + `try/finally`，为套 `try` 把 `with` 块内 **40 行函数体整体缩进 +4**。纯重排是冲突放大器：git 把整段判为改写，上游动这一段的任何位置，人工都要面对一整块「被谁改写了」。
- **实测口径（审查的「约 40 行」成立，且更精确）**：`git diff 00b2e03c80 -- hermes_cli/plugins.py` 为 **+111/−40**；加 `-w` 为 **+72/−1** ⇒ 40 个删除里 **39 行是纯缩进**，真删除只有 1 处（那一行 `with`）。函数体实测 **40 行**，其中 `if force:` 有两处（外层 16 空格 / 内层 `try` 内 16 空格），git 的 Myers 算法把这两行**交叉匹配**成上下文，所以 41 行候选里只报了 39 行纯缩进 + 1 行真删除 —— 这也是同一段代码在 plain diff 里 6 hunk、在 `-w` 里 7 hunk 的原因。
- **口径先校正（审查给的三处前提都不成立）**：
  1. **审查建议的修法按字面不可实现**。原文是「保留上游 `with` 原样不动 + 函数最前面加一个 `if not _discovery_lock_or_bail(self): return`」。但 `self._discovery_lock = threading.RLock()`（:3749）——**是 RLock**。helper 取锁后**不释放** ⇒ 内层 `with` 同线程重入成功，却**没有任何代码释放外层那一层** ⇒ 锁被永久多持一层，此后本进程所有 discovery 全死锁；取完**就释放** ⇒ 内层 `with` 退回原来的无限阻塞，**护栏被静默删除**。要让它正确，调用方必须补 `finally: release()`，而 `try` 一旦包住函数体，那 40 行**必然回到 +4 缩进** —— 绕回原点。
  2. **审查指定的落点不存在**：`owner/plugins/discovery_guard.py` 所指的 `owner/plugins/` 目录本仓**不存在**。
  3. **审查 §5.5 提议的 CI 门禁脚本不存在**：`owner/scripts/check-reindent.sh` 本仓**不存在**（`owner/scripts/` 下 38 个脚本里最接近的 `check-merge-residue.sh` 做的是另一件事）。§5.5 想用它把「纯缩进重排」变成 CI 阻断项，目前没有任何实现。
  另有一条方向性判断：把函数体搬到 `owner/` 在冲突维度上是**反向**的 —— 留在原文件，上游将来改那 40 行是**干净合并**；搬出去之后，同样的上游改动会撞在「我们删掉的行」上，变成冲突。
- **方案（2026-09-29 用户决策：同文件抽 `_scoped` 方法）**：把函数体抽成 `_discover_and_load_scoped(force)`，**`with self._discovery_lock, _plugin_home_scope(self.home_path):` 逐字保留、缩进不变**，40 行正文回到上游缩进。这不是新花样：本文件上游自己就是「持锁薄壳 + `_xxx_scoped` 正文」——`unload()` → `_unload_scoped()`（:4043）、`_load_plugin()` → `_load_plugin_scoped()`（:5232）；`discover_and_load` 是全文件**唯一**持锁却不抽方法的异类。
- **保留内层 `with self._discovery_lock,` 不引入新依赖**：RLock 重入在本文件**已是上游自己的依赖** —— `discover_and_load` 体内调 `self.unload()`（:4251），扫描过程中调 `_load_plugin`（:4456 / :4503 / :5026），三者都 `with self._discovery_lock`。重入是被上游既有代码要求的，不是本条引入的。
- **顺带修掉两处护栏缺陷**（2026-09-29 用户决策：一并修）：
  1. **`force=True` 被静默丢弃**：护栏原来不分 force，`discover_and_load(force=True)` 拿不到锁时同样 15s 后静默 `return`，显式重扫请求消失。现在改为上抛新增的 `PluginDiscoveryLockBusy(RuntimeError)`。这是安全的：全部 5 处 `_ensure_plugins_discovered(force=True)` 调用点（`tools/image_generation_tool.py`、`tools/transcription_tools.py`、`tools/tts_tool.py`、`tools/video_generation_tool.py`、`tools/voice_mode.py`）**本来就**把发现包在 `try/except Exception` 里、按非致命处理并回落到各自的 missing-provider 报错；`hermes_cli/main.py:12019` 那处更会把原因直接打印给操作者。默认（非 force）路径刻意**不**改成上抛 —— `_ensure_plugins_discovered()` 背后有几十个 getter，抛出去会波及全部读取点。
  2. **取锁失败的后果不可观测**：`discover_and_load` 返回 `None`，调用方无从分辨「扫过了」与「没扫成」。新增 `PluginManager._discovery_deferred`（拿不到锁置 True、任何一次成功扫描后复位），`discover_plugins()` 由 `-> None` 改为 `-> bool` 如实回报；`start_background_plugin_discovery()` 文档里那句「so no caller can observe a half-loaded registry」补上这一例外 —— 该承诺在 join 超时窗口内**确实**被打破，写清楚比留着假话好。
- **一处我自己的判断错误，被本轮守卫测试当场抓出**：最初把 `discover_plugins()` 里 `if (not force and _background_discovery_join_timed_out ...)` 的 `not force` 当成缺陷删掉了。实际它是**承重的** —— 没有它，`force=True` 会被同一个 join-timeout 早返回吞掉，「强制重扫」反而更静默。正确结论：静默丢弃发生在 `discover_and_load` 的护栏里，不在 `discover_plugins()` 的早返回里。`not force` 原样保留，并新增守卫 `test_discover_plugins_never_short_circuits_a_forced_rescan` 钉住它。
- **涉及文件**：`hermes_cli/plugins.py`（新增 `PluginDiscoveryLockBusy`；`__init__` 增 `_discovery_deferred`；`discover_and_load` 抽成薄壳 + 新增 `_discover_and_load_scoped`；`discover_plugins` 返回 `bool` 并补 docstring；`start_background_plugin_discovery` docstring 补例外；`[owner]` 标记 2 → 6 处）、`tests/owner/test_plugins_discovery_guard.py`（新增 19 例）、`owner/docs/owner改动清单.md`（本条 + §7.20 指针 + 附录 B 行 + 附录 E）
- **侵入类型**：结构调整（方法抽取，**零缩进重排**）+ 两处行为修正
- **验证**：
  - **缩进噪音归零**：`git diff 00b2e03c80 -- hermes_cli/plugins.py` plain **+123/−2**、`-w` **+123/−2** —— **两串数字完全相同 ⇒ 全文件零「仅空白」改动**（改造前是 +111/−40 与 +72/−1，差值就是那 39 行）。`discover_and_load` 区域的删除数 **40 → 0**：`with` 行与 40 行正文全部成为上下文，该 hunk 是纯插入 `+29/−0`。仅剩的 2 处删除都在 `discover_plugins()`，且都是本轮行为修正不可回避的（返回类型注解 + 末尾调用行）。hunk 数 6 → 10，多出的 4 处**全为纯插入**。
  - **变异验证 17/17 全部咬住**：G1a 正文退回旧形态 / G1b 正文被套进一层 `try`（`with` 落到 12 空格）/ G1c 上游那行被改写成不再自己取锁（MOD 回归）/ G1d 正文重新内联 / G1e 薄壳不调 scoped 方法；G2a 不释放锁 / G2b 超时值改小 / G2c 拿不到锁后忘了 `return` / G2d 不复位 deferred；G3a 不记 deferred / G3b force 不再上抛 / G3c 取锁条件取反；G4a 永远回报 True / G4b 谎报 / G4c 把 force 也短路掉；G5a already-discovered 捷径吞掉 force / G5b SAFE_MODE 不置位。
  - **变异体的有效性也做了把关**：两个最初设计的「只给一行改缩进」变异实测是 **IndentationError**（不可导入），pytest 报的是 collection error 而不是用例失败 —— 那证明不了断言在起作用。改用「套一层 `try`」「去掉内层的那把锁」两个合法变异体，并在装置里加了 `compile()` 前置校验：不可导入的变异直接判不合格，不记成「没咬住」。
  - **定向回归**（爆炸半径 27 个路径：所有引用 `discover_plugins` / `discover_and_load` / `_discovery_lock` 的用例 + force 重试路径 + `tests/owner/`）**1381 通过 / 15 跳过 / 0 失败**，两腿失败集合完全相同（NEW: 0 / GONE: 0）
  - 健康检查 **7 passed / 1 warning（Check 5 的 4 条既有 warning 不变，属 merge `315551234`）**；Check 8 **116/116**。
- **守卫清单（8 类）**：① 上游 `with` 行在 `_discover_and_load_scoped` 内逐字保留且缩进 8；② 正文抽查三处代表性行的缩进与上游一致；③ 全文件不出现 12 空格的该 `with` 行；④ `discover_and_load` 是薄壳（不含任何正文标记 + 行数上限）；⑤ 取锁/释放成对且重入深度归零（`acquire(15.0)` → `enter` → `exit` → `release`）；⑥ 护栏拦下时确实不扫描、`_discovered` 仍 False、`_discovery_deferred` 置 True；⑦ `force=True` 上抛且一路可观测到 `_ensure_plugins_discovered`；⑧ `discover_plugins()` 的返回值语义 + 三条既有捷径（already-discovered / SAFE_MODE / force）不被吞掉 + 真 RLock 在正常与异常路径后都不泄漏（另一线程可非阻塞拿到）。
- **技巧（值得复用）**：真实 `RLock` 不暴露重入计数，同线程再取一次**永远成功**，所以「锁泄漏」在本线程里查不出来 —— 必须**换一个线程**用 `acquire(blocking=False)` 才测得准。用**记录型锁替身**（记录 `acquire`/`release`/`__enter__`/`__exit__` 顺序并跟踪 depth）把「取了几层、放了几层」变成可断言的完整日志；替身的 `__enter__` 在未授权时**直接抛错**，让「拿不到锁后忘了 `return`」变成测试失败而不是挂起。
- **未纳入**：`owner/scripts/check-reindent.sh`（审查 §5.5 提议的 CI 门禁）本轮**未实现** —— 它需要 `git diff <base> -w --stat` 与上游 ref，只在多分支克隆里可用；本条的守卫改成**纯本地**的结构不变量，不依赖 ref。`_delivery_manager()`（:6480）走 `manager.discover_and_load()` 且不看 `_discovery_deferred`，在延迟窗口内 hook 投递仍会静默落空 —— 一并记录，未改（改动会波及 hook 投递语义）。
- **Commit**：`bae086a304`（代码 + 测试；本条留档见附录 E）

### 16.11 feishu adapter 自有卡片胶水迁入 `owner/feishu/`（T2-14）

- **背景**（T2-14 / 合并冲突审查 §5.4）：`plugins/platforms/feishu/adapter.py` 是全库第二冲突文件（33 个冲突块），上游活跃度 76 次/3 月。审查给出的修法是「按规范 §3 的『审批卡片经验』继续收薄 —— 标签注入收口到**新建**的 `owner/feishu/profile_tag.py`，路由继续收拢到已有的 `owner/feishu/profile_routing.py`，adapter 侧每处 1 行调用」，并预期冲突块 33 → 8–10。
- **口径先校正（审查 §5.4 表格四条前提，三条不成立）**：
  1. **标签注入已经收口了**。`owner/feishu/card_sender.py::_maybe_tag_interactive_payload`（配 `_maybe_tag_card_profile` / `_inject_profile_tag`）是**唯一**的序列化期注入点；adapter 侧只有 `_send_raw_message` 里**一处 5 行调用**，且 2026-09-15 那次「root fix」的说明已经写在代码注释里。新建 `profile_tag.py` 只是在自家两个文件之间搬约 100 行，**冲突面一字不减**。
  2. **profile 路由已经收拢了**。`owner/feishu/profile_routing.py` 已有 982 行 / 25 个公开符号（`try_route_inbound_message`、`try_route_card_action`、`handle_card_action_request`、`try_route_bot_menu_command`、`resolve_profile_route`、`verify_inbound_target_profile`、`_forward_to_profile_container` …），adapter 侧是 1 行 `_owner_import` + 调用。
  3. **i18n 那一行不成立**。adapter 内 **0** 个 `t()`；全文件 i18n 引用只有 3 行，是 `send_exec_approval` 里一处 `get_language()`。
  4. notice 卡 / queue 卡那行本来就写着「保持」。
- **实测口径（审查的数字有出入，以实测为准）**：文件 7092 行；`[owner]` 标记 **71**（审查说 67）；默认 `-U3` 下 **52 个 hunk、其中 28 个含删除**（审查说 27；配「24 个纯插入 hunk」，52 = 28 + 24 自洽）；plain diff `+1447/−270`（审查说 +1425）。另外审查 §5.5「用 `git diff -w` 判纯重排」这条仪器在本文件上**方向是反的**：`-w` 给出 `+1476/−299`，**比 plain 更大** —— 因为空白不敏感后 git 的配对变了，它在这里什么也证明不了。
- **33 块真正的构成**：把 `git merge-tree --write-tree upstream/main HEAD` 的冲突块逐块解析后，我方这一侧共 **1193 行**，其中**可执行代码 824 行**、注释 274、空行 95。也就是说审查说的「深度耦合」并不是标签/路由，而是**只有我们才有的卡片胶水被内联塞在上游类体里**：最大块 357 行（`_handle_update_prompt_card_action` 尾 + 卡片发送/澄清/选择器/引导/队列一族）、次大 135 行（`_on_card_action_trigger` + `_dispatch_card_action`）、再次 85 / 71 / 54 / 52。**上游的结构性重构也正砸在同一片区域**：上游新增了 `_pop_validated_prompt_state`（我方没有，块内上游侧 55 行）、把 `send_exec_approval` 改名 `_send_exec_approval_prompt` 并把卡片核心抽到共享模板 `gateway/platforms/base_exec_approval.py`、把 sender_name 一族的方法签名改成多行（后两块属**纯排版，无解**）。
- **方案**（2026-09-29 用户决策：**只搬纯自有代码**）：把**纯属本项目、与上游零耦合**的方法正文整块迁入既有 owner 模块，adapter 侧只留签名 + 1 行委托。**方向刻意如此** —— 对我们自己的代码，搬走不删上游任何一行，因此**零合并债**；反过来「把上游正文搬到 `owner/`」是**反向**的（§16.10 同一结论：搬走后上游以后每次改那段正文都会撞在「我们删掉的行」上）。
- **迁移清单（11 个方法，合计 404 → 212 行）**：

  | 方法 | 行数 | 迁往 |
  |---|---:|---|
  | `_dispatch_card_action` | 111 → 49 | **新建** `owner/feishu/card_action.py` |
  | `_normalise_card_action_value` | 20 → 12 | 同上 |
  | `send_card` | 63 → 19 | `owner/feishu/card_sender.py` |
  | `_get_card_send_lock` | 23 → 12 | 同上 |
  | `send_model_picker_card` | 29 → 21 | `owner/feishu/model_picker.py` |
  | `_handle_model_picker_action` | 21 → 13 | 同上 |
  | `send_guide_card` | 25 → 16 | `owner/feishu/steer_card.py` |
  | `_handle_guide_card_action` | 27 → 13 | 同上 |
  | `send_queue_status_card` | 34 → 28 | `owner/feishu/queue_card.py` |
  | `_handle_queue_card_action` | 22 → 13 | 同上 |
  | `_send_media_guard_hint` | 29 → 16 | `owner/feishu/media_guard.py` |

  `adapter.py` 7092 → 6900 行。**不新建平行目录**：正文一律进「本来就属于它」的模块。命名冲突处理：`steer_card.py` / `queue_card.py` 里本来就有同名的 `handle_*` 处理器，新增的薄封装改名 `dispatch_*`，避免遮蔽处理器自身。
- **刻意保留的三处设计决定**：
  1. **兜底尾巴留在 adapter**。`_dispatch_card_action` 末尾的 `self._submit_on_loop(loop, self._handle_card_action_event(data))` + 空响应构造**没有搬走** —— 它构造的是**适配器模块全局** `P2CardActionTriggerResponse`，而 `tests/gateway/test_feishu_approval_buttons.py` 的 `_patch_callback_card_types` fixture 正是给那个全局打补丁（`monkeypatch.setattr(feishu_module, "P2CardActionTriggerResponse", _FakeP2Response)`）。搬进 owner/ 后它会读自己模块的绑定，那些补丁点**静默失效**，测试会拿到真实 lark 类。
  2. **哨兵必须是哨兵**。既然尾巴留在 adapter，owner 侧就需要一个「没有命中任何分支、请走兜底」的信号。**不能用 `None`**：处理器**可以合法返回 `None`**（事件没有对应状态时就是解完的结局），`None` 当哨兵会把「处理器返回 None」误判成「没命中分支」，凭空多 submit 一次合成命令。故定义 `UNHANDLED = _Unhandled()` 单例并做**身份比较**。owner 模块内的 lark 类型走自己 `_lark_card_types()` 式 import，与 `clarify_card.py` / `queue_card.py` 既有写法一致。
  3. **名字一个都不能少**。`owner/feishu/auto_card.py:663` 用 `getattr(adapter, "_get_card_send_lock", None)` 解析锁，拿到 `None` 就 `contextlib.nullcontext()`（**无锁**）。名字丢了**不报错**，而是静默重新打开「多块卡片交错发送」的 bug —— 所以 11 个方法一律保留为真方法，守卫也把这条耦合显式钉住。
- **涉及文件**：`plugins/platforms/feishu/adapter.py`（11 个方法改薄壳）、`owner/feishu/card_action.py`（新建 214 行）、`owner/feishu/card_sender.py`（+107）、`owner/feishu/model_picker.py`（+65）、`owner/feishu/queue_card.py`（+68）、`owner/feishu/steer_card.py`（+64）、`owner/feishu/media_guard.py`（+37/−1，多一个 `Dict` 导入）、`tests/owner/test_feishu_adapter_thinning.py`（新建，40 例）
- **侵入类型**：结构调整（正文外移 + 薄壳委托），**零行为变更**
- **验证**：
  - **冲突面（同一把尺：`git merge-tree --write-tree upstream/main HEAD`）**：冲突块 **33 → 33**；我方冲突侧 **1193 → 1033 行**（code 824 → 691、注释 274 → 255、空行 95 → 87）；最大块 **357 → 259**，次大 **135 → 73**。逐块核对：块 #19 与 #17 的缩减量正好等于对应方法迁出的行数（`_dispatch_card_action` −62 ⇒ #17 135→73），说明仪器读数可靠。
  - **「33 → 8–10」判定不可达（口径说明）**：冲突块是按「两处都改过」**计块**，不是计行 —— 把 357 行的块缩成 5 行委托，**仍然是 1 块**。要到 8–10 必须把我们在约 15 个上游函数里的存在**彻底移走**，而其中若干（审批按钮必须由 card-action 处理器派发、reaction 必须由 `_handle_reaction_event` 转发）**结构上离不开**。本条只动自有代码，剩下 27 处「注入上游函数内」的落点原样未动（见「未纳入」）。
  - **变异验证 17/17 全部咬住**：删除/改名 `_get_card_send_lock`；把 `send_model_picker_card` 重新内联撑大；把一段已迁走的正文串复制回 adapter；把 `None` 当哨兵；末尾不再返回 `UNHANDLED`；去掉兜底的 `_submit_on_loop`；HTTP 重放路径也走路由；normalise 返回非 dict 的 JSON；`send_card` 异常吞成 success；`send_card` 忽略发送失败；卡片锁不做 LRU；锁从不复用；选择器状态改到发送之后写（两条）；引导卡不记 source；队列卡丢掉 `SendResult`；media guard 空文本也发。
  - **变异验证当场补上一处守卫缺口**：`normalise_card_action_value` 的参数集原先只喂 Python `list`，没有喂「**编码成 JSON 字符串**的非 dict」（`"[1,2]"` / `"\"plain\""` / `"42"`）。于是「去掉 `isinstance(parsed, dict)` 判断」这个变异体**没被咬住** —— 若不跑变异，这一处会以「17/17 全绿」的假象留下。补齐三个参数后咬住（3 例失败）。
  - **爆炸半径回归**（同一语料 134 个路径：全部 feishu 相关用例 + `tests/owner/` 全量）：**NEW 0 / GONE 0**。leg A（当前树）30 failed / **2589 passed**；leg B（`be5a509bc7`，把两条新文件移走、其余按基准还原）30 failed / **2546 passed**；通过数差 **43 = 40**（薄壳守卫整文件在对照腿中被移走）+ **3**（本收尾新增的健康检查门），两侧 30 个失败**同一集合**，均为存量。
  - **收尾复跑**（补上健康检查门之后）读数一致：leg A **2589** passed、leg B **2546** passed，**NEW 0 / GONE 0** 不变。
- **守卫清单（`tests/owner/test_feishu_adapter_thinning.py`，40 例 / 18 个用例函数，其中 3 个参数化：11 + 9 + 5）**：① 11 个方法名字仍在（`hasattr`，含「多个调用点用 `getattr(..., None)` 解析」的说明）；② 每个方法体不超界（约 1.3× 迁移后大小）；③ 11 个方法总量 ≤ 260 行（迁移后 212、迁移前 404）——②③ 合起来把「回流内联」变成测试失败；④ 被迁走的正文特征串不再出现在 adapter（防「复制而非搬走」）；⑤ `auto_card.py` 仍以 `getattr` 解析 `_get_card_send_lock`（把这条静默降级耦合显式化）；⑥ 兜底尾巴仍读 **adapter 模块全局** 的响应类（打补丁后拿到假类）；⑦「处理器返回 `None`」**不**被当成 fallthrough（不额外 submit）；⑧ profile 路由短路优先于任何本地分支；⑨ `allow_profile_routing=False` 时**绝不**路由；⑩ `normalise` 对「能解析但非 dict」的 JSON 仍收敛为 `{}`；⑪ `send_card` 失败上报与异常 fail-open；⑫ 卡片锁按 chat 复用且 LRU 有界；⑬ 选择器 / 引导卡状态**在发送之前**写入；⑭ 队列卡把 `SendResult` 透传；⑮ media guard 提示 best-effort（发送异常不外抛、空文本不发）。
- **技巧（值得复用）**：① **搬自家代码与搬上游代码是两件方向相反的事** —— 前者不删上游行、零合并债；后者让上游以后的每次改动都撞在「我们删掉的行」上。判断依据很简单：这段正文在上游 `main` 里**存不存在**。存在就留在原地，不存在才搬走。② **「块数」与「行数」是两把不同的尺**：缩小一个块不会让块数下降，只有把某个落点的改动**整个撤走**才会。做收益预估时先用块数核预期，别拿行数降幅去承诺块数降幅。③ **把「块缩了多少」与「方法缩了多少」对账**：`_dispatch_card_action` 从 111 缩到 49（−62），冲突块 #17 正好从 135 掉到 73（−62）—— 对得上才说明测量仪器没问题。④ **跨模块「薄壳」若被 `getattr(obj, name, None)` 解析，名字就是契约**：这类调用点丢名字不会抛异常，而是走一条「功能静默降级」的分支；写守卫时要断言的是**那条降级分支的调用方仍然找得到名字**，而不只是「方法存在」。⑤ **哨兵不能用 `None`**，只要被包装的处理器有「合法返回 `None`」的可能 —— 用专门单例 + 身份比较。
- **收尾：两处校验锚点必须跟着搬家，并把它们收进 pytest**。`owner/validation/merge_health_check.py` 的 Check 6（`anchors.yaml` 关键锚点）与 Check 7（`inventory.yaml` 静态断言）都是**直接匹配文本**的，源码搬走后断言不改就会红。实测迁移后：**Check 6 报 5 条**（`handle_feishu_diff_action` / `owner.diff_card.feishu` / `handle_card_click` / `owner.feishu.memory_approval` 四条随正文一起搬走；`handle_picker_action` 是本轮把它改名成 `dispatch_model_picker_action` 所致）、**Check 7 报 2 条**（`feishu-diff-card-dispatch` 的 `file_contains` 仍指向 adapter）。处置：`anchors.yaml` 的 `feishu-adapter-card-routes` 改为只断言**仍留在适配器里的接线**（`owner.feishu.card_action` / `dispatch_card_action` / profile 路由 / clarify / picker / guide），新增 `feishu-card-action-branch-table` 条目指向 `owner/feishu/card_action.py`；`inventory.yaml` 的 `feishu-diff-card-dispatch` 拆成两条（新落点 + 「适配器仍路由进这张表」）。复跑 **Check 6 28/28、Check 7 140/140，0 issue**。
  **顺带暴露的真正问题**：这两个检查**只存在于健康检查脚本里，pytest 里没有** —— 所以那 134 个路径的回归语料虽然**包含** `tests/owner/test_merge_health_check.py`，却**不会**因它们变红，「全绿」的结论里根本不包含这两项。已在同一文件补 3 例（Check 6、Check 7，以及**按 id 钉住**分支表锚点必须指向新落点的第 3 例），变异 **7/7 咬住**。第 3 例是必需的：前两例断言 `issues == []` 与 `checked == total`，两者都**从被测文件自身推导** ⇒ 把过期条目**整条删掉**反而更绿（27 specs / 27 readable / 0 issue），而那恰恰是最省事的假修法。
- **标记数变化（附录 B 是当前状态索引，故按 70 计）**：`[owner]` 标记 **71 → 70**，净 −1 —— `send_card` 原有两处标记随正文迁出、薄壳只留一处；分派表的 9 处随表迁入 `card_action.py`；其余 8 个新薄壳各补 1 处。本条与附录 E 里出现的 **71** 是**改造前**实测口径（用于纠正审查的 67），量的不是同一版文件。
- **未纳入**：
  1. **注入上游函数内的我方代码**（约 436 行，占我方新增 30%）：`_handle_reaction_event`(64)、`_process_inbound_message`(51)、`_on_card_action_trigger`(55)、`send_exec_approval`(66)、`_send_uploaded_file_message`(19)、`send_image_file`(16)、`_send_raw_message`(16)、`__init__`(42)、`_finalize_send_result`(31) 等。把它们也收成 1 行委托能**进一步降行数**，但这几处搬出会**新增合并债**，且块本身仍在（只是更小），需要另行决策（属审查 §5.4 未言明的另一半）。
  2. **上游已重构、非我方可控**：`_pop_validated_prompt_state` 是上游新加的助手（我方没有该名字）；`send_exec_approval` 被上游改名并模板化；sender_name 一族的上游签名排版变化。这三类冲突**任何收薄动作都消不掉**。
  3. **`_render_merge_forward_entries` 及其调用方 `_expand_merge_forward_text`**：`tools/feishu_client_utils.py:1593` **从 adapter import 这个渲染器**，搬走必须改上游文件，等于亲手新增合并债 —— 故整体不动。
  4. **审查 §5.4 提议新建的 `owner/feishu/profile_tag.py`**：不建（前提 1 已不成立）。
  5. **审查 §5.5 提议的 `owner/scripts/check-reindent.sh`**：仍未实现（§16.10 已记录，本文件上 `-w` 方向还是反的）。
- **Commit**：`881092cbe0`（代码 + 测试）/ `f244475b09`（校验锚点同步 + Check 6/7 收进 pytest）；本条留档见附录 E

---

### 16.12 `locales/{zh,en}.yaml`：删掉被 YAML 静默丢弃的重复键 `approval.hardline_blocked`（T2-15）

- **背景**（T2-15 / 合并冲突审查）：审查说 `locales/{zh,en}.yaml` 的 owner 新增键「分散成两簇，插在上游活跃区间内」（引 `zh.yaml:36-69` 与 `:560-606`；上游 **28** 次/3 月），修法是「新增键统一追加到 `approval:` 块末尾 + 界标注释（**~120 行移动**）」。
- **口径先校正（审查给的位置、量、修法、活跃度四条，逐条不成立）**：
  1. **`approval` 本来就是一个连续的尾部块，修法即现状**。同一把尺（`yaml.compose()` node 树；行号一律取**我方文件**行号，上游树只用来判**成员资格**，不提供位置 —— 混用两套行号会静默把答案反转）：`approval` 段与上游共有的键 17 个占我方 **4–20 行**，owner-only 键 **516** 个，**落在共有键区间内 0 个**、**首个 owner 键之后再无共有键 0 个**。en 同形（共有 17 个占 13–30 行，结论相同）。审查给的两个区间对不上任何一簇 owner 键：`36-69` 在 `approval` 段内部，`560-606` 在 `gateway` 段里。
  2. **真正交错的是 `gateway`，不是 `approval`**：`gateway` 共有键 395 个占我方 **609–1519 行**，owner-only 条目 **398** 个，其中 **388 个**落在共有键区间内（另 10 个在末个共有键之后）。这是全文件**唯一**一处真交错；其余 8 个顶层块（`browser` 36 / `cron` 11 / `display` 329 / `memory` 27 / `memory_proposal` 43 / `terminal_tool` 7 / `toolguard` 3 / `tools` 57 个 owner-only 键）**一个共有键都没有**，结构上不可能交错。
  3. **「~120 行」量错了对象**：实测 owner-only 键路径 **1427 个**（zh / en 相同，且这 1427 个在基点 `00b2e03c80` 也全都不存在），共有键路径 412 个。1427 是**键路径数**、120 是**行数**，两者不可直接比较；即便折成行，`gateway` 那 398 个条目落在 609–1519 区间内，量级也完全不同。
  4. **上游活跃度**：审查说 28 次/3 月，实测 **33 次/3 月**（`git log --since='3 months ago' upstream/main -- locales/`）。上游维护的是**同一套 17 本 catalog**（`git ls-tree upstream/main locales/` 与本地逐名一致），其中 2026-09-14 一次「plain-language, actionable user-facing messages (core)」直接覆盖本次涉及的文案。
- **「把新增键收拢到块尾」买不到任何收益（实测）**：把 `gateway` 下全部 **398** 个 owner-only 条目整块搬到 `gateway` 映射末尾（共有键原位不动、搬动后 `yaml.safe_load` 语义等价的断言通过），用同一把尺量冲突块：

  | 文件 | 收拢前 → 后 |
  |---|---|
  | `locales/zh.yaml` | **1 → 1** |
  | `locales/en.yaml` | **0 → 0** |

  仪器：`git merge-file -p ours base theirs` —— 它是 `merge-tree` 的逐文件形态但**无 ref 依赖**，因此可以量一个只存在于内存里的候选；先用未改动字节自校验，读数与 `git merge-tree --write-tree upstream/main HEAD` 一致（zh 1 / en 0）。**结论**：`zh.yaml` 那唯一一个冲突块由**共有键的取值分叉**造成（`gateway.status` 我方 6 行本地化中文 vs 上游 7 行英文、且上游多一个 `free_tier`），只要不放弃本地化取值它就消不掉，而**重排 owner-only 键碰不到它**。故本项按「不纳入」处置（见下）。
- **复核过程中发现的真缺陷**：`approval.hardline_blocked` 在两本维护语种里**各被定义了两次**。

  | 文件 | 修复前 | 修复后 |
  |---|---|---|
  | `locales/zh.yaml` | 34 / 55（两处值逐字相同） | 仅 55（块结果段） |
  | `locales/en.yaml` | 44 / 65（两处值逐字相同） | 仅 67（块结果段） |

  - YAML 对同层重复键**不报错**：后定义者胜出、先定义的静默丢弃。于是**编辑第一处是静默无操作**，而运行期 `t("approval.hardline_blocked")` 读到的文案一直是对的 —— 这正是它能存活两个月没被发现的原因。
  - **来源**（`git log -S` 逆序 + 逐次取值定位所在小节）：`e93f3148e7`（2026-07-01，owner 17.10/17.14/17.22 i18n 补全）先把它加在**块消息**段；`92e0787ea6`（2026-08-27，「i18n: 本地化 approval/gateway/tools 硬编码用户可见字符串」）**新建块结果段**时又加了一次（同一提交里那段标题 `# 拦截结果消息 — …` 本身也是新增行）。即第二次批量 i18n 重新本地化了同一条文案，没有回看它在上一个小节已经存在。两次提交各只新增 1 次出现（`git show <c> -- locales/zh.yaml | grep -c '^+  hardline_blocked:'` 均为 1）。
  - **保留哪一处**：消费者是 `tools/approval.py:936 _hardline_block_result()`（返回**工具结果** dict，`:951` 调 `t("approval.hardline_blocked", description=display_description)`），所以它属于「拦截结果消息 / Block-result messages」段，与同段的 `hardline_recovery_saved` / `hardline_recovery_manual` 同组。删除的是块消息段那一处，原位留说明注释（zh 2 行 / en 3 行）。
  - 全库扫描：**17 本 catalog 修复后全部无重复键**。
  - **不给这处说明注释补 `[owner]` 标记**：本文件已有的标记（各 2 处）标注的是 `approval_explainer` **键组**（真实特性插入），本处是「删除重复 + 说明注释」而非键组；同文件另 1427 个 owner-only 键按「目录（数据）」惯例一律不标记，单独给一条注释加标记反而破坏一致性。
- **既有守卫的盲点（这才是本缺陷能存活的另一半原因）**：`tests/agent/test_i18n.py::test_catalog_keys_match_english` 走 `yaml.safe_load` + `_flatten` —— `safe_load` 对重复键不报错并用后定义者覆盖，`_flatten` 再把它折进一个 `dict`，**重复在建字典之前就已经被合并掉了**。两本 catalog 被**同等地**抹平，`en_keys - lang_keys` 与反向差集都看不出异常。所以「同一本册子里有没有重复」与「两本册子键集是否一致」是**两条独立**的不变量，前者永远无法由后者发现。
- **方案**：删掉块消息段那一处重复定义，原位留说明注释；新增 `tests/owner/test_locale_catalog_integrity.py` 补齐这条独立不变量。
- **涉及文件**：`locales/zh.yaml`（−1/+2）、`locales/en.yaml`（−1/+3）、`tests/owner/test_locale_catalog_integrity.py`（新建 158 行 / 20 例）
- **侵入类型**：缺陷修复（删除被静默丢弃的重复定义）+ 数据文件注释；**零行为变更**（改动前后 `yaml.safe_load` 取到的 `approval.hardline_blocked` 逐字相同）
- **守卫清单（`tests/owner/test_locale_catalog_integrity.py`，20 例 = 17 本 catalog 参数化 ×1 + 维护语种钉住 ×2 + 仪器钉住 ×1）**：
  1. `test_no_locale_defines_the_same_key_twice[<17 本>]`：走 `yaml.compose()` 的 node 树 —— 只有 node 还留着被丢弃的那一次出现，`KeyNode.start_mark.line` 给出它的行号；断言 `duplicates == {}`，**而不是**「文件还能加载」（后者正是问题被遮住的方式）。
  2. `test_the_maintained_locales_still_define_hardline_blocked_once[zh|en]`：钉**修复对象本身**，两条断言 —— ① `"hardline_blocked:"` 在本册内**恰好出现 1 次**；② `_key_line(text, "approval", "hardline_blocked")` 的行号 **大于**该段标题行号。第 ② 条是必需的：只钉「恰好 1 次」的话，**把定义搬回上一个小节**同样通过（变异体 5 只被这半条抓到）。
  3. `test_safe_load_would_not_notice_a_duplicate`：钉**仪器选择是承重的** —— 同一段含重复键的样本，`safe_load` 只看到 1 个值、`compose` 看到两个定义。没有这一例，「把检查重写在 `safe_load` 上」会得到一个**空洞全绿**的守卫。
  - 三处实现坑（已修，说明留在代码注释里）：① **标题匹配不能裸子串** —— 我们留的说明注释**点名了**「拦截结果消息」段，裸子串搜索命中 2 次，改用 `re.compile(r"^#\s*" + re.escape(heading))` 锚定到注释行；② **`_mappings()` 会遍历所有 mapping，顶层名字可能撞上嵌套 mapping 的整个键集** —— `_key_line` 初版按「键集包含」找节点，命中的是嵌套的 `tirith` 块，改为只走顶层 mapping 的条目（`for key_node, value_node in root.value` + `isinstance(value_node, yaml.MappingNode)`）；③ **样本行号要数对** —— `'root:\n  k: "first"\n  k: "second"\n'` 里 `root` 在第 1 行、`k` 在 **2、3** 行（是 `root` 的兄弟而非嵌套子节点的兄弟），初版写成 `[3, 4]`。
- **验证**：
  - **守卫**：`tests/owner/test_locale_catalog_integrity.py` **20 passed**；与上游 parity 同跑（`+ tests/agent/test_i18n.py`）**27 passed / 30 skipped**（skipped 是需要 ref 的非维护语种对照）。
  - **变异验证 7/7 全部咬住**（`/tmp/t215/mutate_t215.py`：每个变异体先 `yaml.safe_load` 预校验仍可加载、`.py` 变异体先 `compile()`；锚点必须**恰好命中 1 次**否则判 `BAD ANCHOR`；还原走内存快照 + md5）：① 把删掉的那处写回块消息段 ⇒ 咬住 `[zh.yaml]` + `[zh]`；② 在**非维护语种** `ja.yaml` 造重复 ⇒ 咬住 `[ja.yaml]`（证明不变量与语言无关、参数化确实覆盖 17 本）；③ 在 `en.yaml` 复制一个**嵌套**兄弟键 ⇒ 咬住 `[en.yaml]`（证明 compose 行走会下探子映射）；④ 把两处都删掉 ⇒ 咬住 `[zh]`；⑤ 保留 1 处但搬回上一个小节 ⇒ 咬住 `[zh]`（**只有守卫 2 的「行号 > 标题行」那半条抓到它**）；⑥ 在 `en.yaml` 删掉唯一那处 ⇒ 咬住 `[en]`；⑦ 把 `_duplicate_keys` 的仪器换成 `yaml.safe_load`（后人最可能的「简化」）⇒ 咬住仪器钉住那一例。
  - **变异装置首轮不合格，已修（记录在案）**：首轮 **2/6**，三个 `BAD ANCHOR`（锚点用的是 `S2_HEAD + HB + "，请在…"` 这种**拼接后根本不存在**的串 ⇒ 命中 0 次；另一个 `    shortened_url:` 作为裸行命中 2 次）+ 一个 `MISS`（`rewrite_the_check_on_top_of_safe_load` 注入的是 `if isinstance(node, dict): break`，而 `_mappings` yield 的是 `yaml.MappingNode`、从来不是 `dict` ⇒ 那个 `break` 永远不执行）。**后者是变异体本身坏了，不是「代码多了一层」**。修法：锚点一律改用**整行原文**并在应用前先数命中数，仪器变异体改成真正把仪器换掉。
  - **爆炸半径回归**（语料 **136 个路径** = T2-14 的 134 个 + **补入 `tests/agent/test_i18n.py`** + 本守卫）：T2-14 的语料竟然漏了上游 parity 用例，对一个 locale 条目而言这是真实缺口，本轮补上。

    | 腿 | 内容 | 读数 |
    |---|---|---|
    | A | 当前树 | 30 failed / **2616 passed** / 43 skipped |
    | B | `locales/{zh,en}.yaml` 还原到 HEAD（即把重复放回去）、本守卫移走并从语料里剔除 | 30 failed / **2596 passed** / 43 skipped |

    **NEW 0 / GONE 0**；两腿 30 个失败**同一集合**，均为存量；通过数差 **20 = 本守卫整文件 20 例**在对照腿中被移走。相对 T2-14 的 2589 多出的 **27** = 20（本守卫）+ 7（`tests/agent/test_i18n.py` 的 7 例）。还原后三处 md5 校验全部 OK。
  - **冲突面**（同一把尺 `git merge-tree --write-tree upstream/main <ref>`，`567fc4dbec` → `cc8e245a1a`）：`locales/zh.yaml` **1 → 1** 块（我方 6 行 / 上游 7 行，差异只有「上游多 `free_tier`」+「我方取值本地化」）、`locales/en.yaml` **0 → 0**。**修复本身不动冲突面** —— 被删的那处取值与保留处逐字相同，从来没参与过冲突。
  - **健康检查**：`python -m owner.validation.merge_health_check` → **7 passed / 1 warning**，与 T2-14 后完全一致（Check 5 的 4 条 warning 属 merge 315551234 的既有项；Check 6 28/28、Check 7 140/140、Check 8 116/116 仍全绿）。
- **技巧（值得复用）**：① **重复键被 YAML 静默丢弃**，`safe_load` + flatten 形态的守卫**在结构上永远看不到它**，必须走 `compose()` 的 node 行号。② **「单册内无重复」与「两册键集一致」是两条独立不变量**，别指望后者发现前者。③ 发现重复键时要问「**哪一处才是对的**」并把答案钉在测试里，否则「两处一起删掉」同样通过，而那会让 `t(key)` 静默退回裸键。④ **审计给「位置 + 行号范围」时，位置本身也要复核**：「已按现状收尾」与「未做」在报告里长得一样 —— 量两个数即可判：区间内我方键数、首个我方键之后的对方键数，两个都是 0 就是现状。⑤ **修法的收益要用同一把尺在同一个对象上量**：审计修法（收拢）是针对 `approval` 提的，而 `approval` 早已收拢；把它移到真有交错的 `gateway` 上量，收益仍是 **0** ⇒ 结论是**修法本身不成立**，不是落点选错。
- **未纳入**：
  1. **`gateway` 段 398 个 owner-only 条目的纯搬动**：实测冲突块 **1 → 1 / 0 → 0**，零收益；约 900 行纯 churn 本身就是一次大 diff（还要重跑一次 136 路径回归）。**这是该修法唯一的落点，因此整条修法按「不纳入」处置。**
  2. **`gateway.status` 那 6 行取值分叉**（我方本地化中文 vs 上游英文 + `free_tier`）：属 **T2-12 家族**（本地化取值与上游文案的漂移，已登记 **T2-12b**：229 键 / 28 文件的上游文案现只存在目录里），不在本项范围。
  3. **共有键的取值分叉**：412 个共有键路径中，zh 有 **45** 个取值与上游不同、en 有 **19** 个。这些是「已接受的本地化差异」，同属 T2-12 家族。
  4. **给本处说明注释补 `[owner]` 标记**：不加（理由见上）。hunk 级标记铺开本身是已登记的 **T2-11b**（55 个已标记但不完整的文件、902 个未标记 hunk），本项不裁决 `locales/*.yaml` 是否该进那个范围。
- **Commit**：`cc8e245a1a`（代码 + 测试）；本条留档见附录 E

---

### 16.13 官方**私有符号**依赖：调用点可降级 + 可观测，并按名字钉住（T2-16 + 同类普查）

- **背景**（T2-16 / 合并冲突 + 安全审查）：审查说 `gateway/platforms/api_server_media.py:517` 在函数体内裸导入官方**私有**符号 `_resolve_media_to_data_urls`，该符号上游已搬过一次，失败点在每次媒体投递、启动自检抓不到；修法是「**把实现复制进 `owner/gateway/media_resolve.py`（~25 行）**消除私有符号依赖 + 整体迁 `owner/gateway/`，官方文件留 1–3 行委托」；验收口径是 `grep -rn "from gateway.platforms.api_server import _" gateway/platforms/api_server_media.py` **应为空**。审查另给两条同族风险：官方文件 `api_server.py` **反向 import** 我方文件（双向耦合，`owner/` 不可移除）；add/add 同路径碰撞。
- **口径先校正（审查给的位置、量、修法三条）**：
  1. **符号的行号三处都不对**。审查说「`api_server.py:1165`→`:873`，现 HEAD 在 `:1272`」。实测：**我方 HEAD `:1547`**（`1547:def _resolve_media_to_data_urls(text: str) -> str:`）、上游 `upstream/main:873:def …` ✓、基点 `00b2e03c80:1165:def …` ✓。`1272` 不存在于任何一版；`1165→873` 是**基点 → 上游**的位移，不是两个本地位置。
  2. **复制量的对象与量级都错**。审查说「~25 行」。实测函数本体 **51 行**（基点口径，我方与基点**逐字相同** —— 我们从来没碰过它），上游同函数已缩到 **37 行**；复制还要带上 1 行模块常量 `_MEDIA_IMG_EXT`（`api_server.py:1535`）与两条已从 `gateway/platforms/base.py` 来的依赖（`MEDIA_TAG_CLEANUP_RE` / `validate_media_delivery_path`），合计约 **52 行**，是审查估计的两倍。**这个被量错的行数正是「复制很便宜」这个判断成立的前提**。
  3. **计量口径提示**：`api_server.py` 我方在 `:1535`–`:1560` 一带（`_MEDIA_IMG_EXT` / `_MEDIA_MIME` / 函数）与上游**行号不可互相牵引** —— 上游同段在 `:860`–`:910` 一带，中间隔着 `_redact_api_error_text` / `_openai_error` 等上游新函数。**行号只能在同一棵树内比较**。
- **审查修法①（复制实现）经实测判定为有害**：被复制的那个函数在**上游已经改过两次，而我们的树停在基点**。

  | 提交 | 日期 | 改了什么 |
  |---|---|---|
  | `581d97e545` | 2026-09-02 | docstring 35 行 → 7 行；`_to_data_url` 重构（`validate_media_delivery_path` 结果为空时提前返回改为 `p = Path(safe_path) if safe_path else None`） |
  | `13f908f10d` | 2026-09-14 | **`#111046`：尾部 `<|eos|>` 哨兵粘在最后一个 media 标签上时不再内联** —— 新增 `_terminal_sentinel_start()`，正文改为「按 `scan` 扫描、只在有标签被解析时才丢弃哨兵」 |

  第二条是**行为变更**，不是排版。复制 = 把这套**旧于 `#111046` 的语义**永久写进我们自己的树：以后上游再修这个函数，我们的副本既不会收到修复，也不会报冲突 —— 它会安静地用过时语义服务。**修法的方向错了**：移走「我们自己的代码」才是零合并债（§16.11），**复制上游正文**恰好相反。
- **审查没看到的四点**：
  1. **失败模型不是静默的**。原形态在模块级首条语句上无条件导入，`tests/gateway/test_api_server_media_files.py`（owner 新增，本项语料内）会在上游改名时直接 **ERROR**。隐患是真的（启动自检确实不看这条路径），但「静默断裂」的定性不成立 —— 它是一条**响的**断裂，只是响在测试里而不是模型层。
  2. **降级路径本来就存在且可用**。`finalize_api_media` 不内联时，剩余 `MEDIA:` 标签照旧走 `BasePlatformAdapter.extract_media` → `store.register()` → 可下载附件。**内联是装饰性的，不是功能性的**，所以「import 失败就整个功能不可用」的前提不成立。这正是本项敢降级的根据。
  3. **同族依赖比 grep 看到的多**。审查的 `grep -rn "from gateway\|from agent\|from tools" owner/ | grep " import _"` 找到 5 处。改用 **AST 普查**（`ast.ImportFrom` + `Try` 体判定）得：普查目标 **154 个文件**，含官方私有导入的 **9 个文件 / 14 条符号引用**，其中裸导入 **2 条**（`owner/cron/session_context.py`，见下）。grep 少算的两个原因：**多行 `from x import (\n    _a,\n    _b,\n)` 不匹配**；模块前缀白名单**漏了 `hermes_cli` 与 `plugins`**（`hermes_cli.runtime_provider._get_model_config`、`plugins.platforms.feishu.adapter._render_merge_forward_entries` 都在 grep 的覆盖之外）。
  4. **反向 import 是唯一生产调用点，但同族还有更重的**。`api_server.py:155-161` 从 `api_server_media` 导入 5 个名字（`ApiMediaStore` / `attach_hermes_files` / `content_disposition` / `finalize_api_media` / `media_owner_token`），生产代码里**只此一处**（其余 4 处都在测试里）。这条是**真的**，但它是 §2.3 可移除性的问题，不是本项（私有符号）的问题 —— 见「未纳入」。
- **方案**（2026-09-29 用户决策：**可观测降级 + 命名守卫**，**不复制实现**）：调用点**按名字在运行时解析**、允许失败、**降级为「不内联」**（图片转成可下载附件而非内联 data URL）并 **warn 一次**（点名 `§16.13` 的处置指引）；再用测试**按名字把它钉住**，让下一次 sync 的改名变成一条点名的红用例而不是运行期的 `ImportError`。
  - **明确不满足审查的字面验收**：`grep -rn "from gateway.platforms.api_server import _" gateway/platforms/api_server_media.py` **仍然非空** —— 那行还在，只是搬进了 `try:` 块。这是**刻意**的：审查那条口径要求的是「消除私有符号依赖」，而消除它的唯一办法就是复制实现，复制已被实测判定有害（上表）。**本项按「依赖仍在、但可降级且可观测」交付。**
  - **同类普查发现的另外 5 处一并处置**（用户决策：「一并改成可降级调用」）：本该「登记一下就完」的静默降级站点也全部改成**可观测**（`except Exception: pass` → `except Exception as exc:` + `_warn_once(...)`）。
- **逐站点表（9 文件 / 14 条符号引用，行号为改动后当前位置）**：

  | # | 文件 | 行 | 官方私有符号 | 处置 |
  |---|---|---|---|---|
  | 1 | `gateway/platforms/api_server_media.py` | 522 | `gateway.platforms.api_server._resolve_media_to_data_urls` | **本项本体**：裸导入（HEAD `:517`）→ 可降级 `_inline_image_data_urls()`（`:504`），降级 = 不内联、图片转附件，warn 一次 |
  | 2 | `owner/patches/pool_base_url_override.py` | 46 | `hermes_cli.runtime_provider._get_model_config` | 原本 `except ImportError: pass`（**静默**）→ `except Exception as exc` + warn 一次（函数返回值语义不变：拿不到就 `return None` 交回上游默认） |
  | 3 | `owner/i18n/display_filter.py` | 122 / 156 | `agent.i18n._locales_dir` / `._load_catalog` | 原本两处 `except Exception: pass` → 各自 warn 一次；降级后仍落到本地解析 |
  | 4 | `owner/approval/approval_history_policy.py` | 220 | `agent.i18n._locales_dir` | 同上（同族第 3 处） |
  | 5 | `owner/feishu/compression_summary.py` | 39 | `agent.context_compressor._SUMMARY_END_MARKER` / `._HISTORICAL_SUMMARY_PREFIXES` | 原本**模块级裸导入**（HEAD `:16`）→ 移入 `try:`；拿不到则 **`_SUMMARY_ANCHORS_AVAILABLE = False` 整个能力关闭** + warn 一次 |
  | 6 | `owner/semantic_audit/policy.py` | 134 | `tools.approval._YOLO_MODE_FROZEN` | 原本 `except Exception: return False`（静默）→ warn 一次后 `return False`（降级方向安全：不跳过审计 = 更严格） |
  | 7 | `owner/approval/skill_manage_gate.py` | 634 | `tools.approval._lock` / `._gateway_notify_cbs` / `._await_gateway_decision` | **无需改动**：已有 `except Exception as exc:` → `hard_stop_turn(f"BLOCKED: skill approval infrastructure unavailable ({exc})")` + `{"action": "block"}`。**已可观测且 fail-closed**，本项只把它登记进清单 |
  | 8 | `tools/feishu_client_utils.py` | 1606 | `plugins.platforms.feishu.adapter._render_merge_forward_entries` | 原本裸导入（HEAD `:1593`）→ 可降级，走本函数**既有**的 `(None, msg)` 失败形态（不抛异常、也不假装成功返回 `(text, None)`） |
  | 9 | `owner/cron/session_context.py` | 35 | `gateway.session_context._UNSET` / `._VAR_MAP` | **刻意不降级**，登记进 `FAIL_LOUD_ALLOWLIST`（理由见下）；本次只加 docstring |

  - 站点 1 与 2–6 的**降级方式不同，这是有意的**：站点 1 降级后功能照旧可用（换交付形式），5 必须**整体关闭能力**（锚点是格式常量，猜错会让解析器静默跑偏 —— 把「摘要 + 真正的一轮对话」当摘要整段播出去，比不播更糟），2/3/4/6 降级后仍是本来的次优路径。
- **为什么 `owner/cron/session_context.py` 刻意保持硬导入**（写进模块 docstring + 由守卫强制）：① **没有可退回的语义** —— 该模块的全部职责就是往官方 `_VAR_MAP` 注入，表没了就注册不了，静默跳过只会让 cron 悄悄丢掉会话上下文，比启动即报错更糟；② **`_UNSET` 就是那个哨兵本身** —— 它被当作 ContextVar 的 `default` 并在上游按**身份**比较，换成本地占位符会改变比较结果。allowlist 按**双向**守卫：文件不再是裸导入时，那条 allowlist 也必须被删掉（否则它就从「记录一个刻意的决定」退化成「掩盖新裸导入的免检通道」）。
- **涉及文件**：`gateway/platforms/api_server_media.py`（+48/−2）、`owner/feishu/compression_summary.py`（+52/−7）、`owner/i18n/display_filter.py`（+36/−3）、`owner/patches/pool_base_url_override.py`（+29/−2）、`owner/semantic_audit/policy.py`（+27/−1）、`tools/feishu_client_utils.py`（+27/−1）、`owner/approval/approval_history_policy.py`（+25/−2）、`owner/cron/session_context.py`（+21/−0）；合计 **8 文件 +246/−19**。新建 `tests/owner/test_upstream_private_symbol_deps.py`（**588 行 / 29 例**）。
- **侵入类型**：缺陷修复（私有符号依赖可降级 + 静默降级改可观测）+ 官方文件 1 处 `[owner]` 标记（新增耦合点说明）；**行为在正常情况下零变更**（import 成功时走的还是原路径、原返回值）
- **守卫清单（`tests/owner/test_upstream_private_symbol_deps.py`，29 例，四类）**：
  1. **符号存在性**（14 例）：`PRIVATE_SYMBOLS` 13 行登记表 → `test_official_private_symbols_we_reach_for_still_exist[<13>]` 参数化断言 `hasattr`，并**连带断言 `why` 非空**（否则这份普查会退化成一份没人敢删也看不懂的清单）；另有 `test_the_api_server_resolver_keeps_the_signature_we_call_it_with` —— **签名**变了同样会坏（我们按 `(text)` 单参调它），把参数名 / 无默认值 / 返回注解一起钉住。
  2. **降级可用且可观测**（11 例）：`test_finalize_api_media_degrades_when_the_resolver_is_gone`（**不抛异常 + 标签外的正文本必须活下来**）、`test_the_degrade_keeps_an_image_deliverable_as_a_file`（**两条腿各自的交付契约**：可用腿内联成 data URL 且**不**登记附件、降级腿不内联但**必须**登记附件；两腿共同底线是 `MEDIA:` 不得泄漏原始路径）、`test_the_degrade_warns_exactly_once_and_names_the_fix`（**恰好 1 次** + 文案里必须有 `§16.13`）、`test_owner_side_degrade_paths_are_observable[<4>]`（站点 2/3/4 参数化）、`test_compression_summary_disables_itself_when_the_anchors_are_gone`（**关闭能力**而不是照原样交出）、`test_merge_forward_renderer_degrades_to_the_functions_own_failure_shape`、`test_semantic_audit_policy_warns_when_the_yolo_probe_is_unreachable`、`test_the_cron_session_var_is_registered_into_the_upstream_var_map`（注册类依赖的**正面**断言：既要求注册真的发生，也要求 `_CRON_SESSION.get() is session_context._UNSET` **身份相等**）。
  3. **全仓普查（AST）**（2 例）：`test_no_official_private_import_is_left_unguarded`（裸导入 = 下一次 sync 的静默断裂点）、`test_the_census_covers_every_guarded_private_import`（**反向**：凡已包进 `try` 的导入都必须在 `PRIVATE_SYMBOLS` 里登记 —— 只查「有没有裸导入」是不够的，那样在 `try` 里偷偷加一条没人知道的依赖是**无声通过**的）。
  4. **守卫自证 + allowlist 双向**（2 例）：`test_the_census_actually_reaches_the_files_it_claims_to_guard`（枚举出的目标集合必须**真的**覆盖已知站点、且**至少解析出 5 个含私有导入的文件** —— 防「路径写错 ⇒ 枚举为空 ⇒ 全绿」）、`test_the_fail_loud_allowlist_is_still_justified`（allowlist 里每一行都必须**确实**是裸导入，否则它就是一条免检通道）。
  - 两处实现坑（已修）：① **`py_compile` 只查语法** —— 它放过了 `tools/feishu_client_utils.py` 里缺失的 `from typing import Any`（该文件没有 `Any` 导入，会在首次调用时 `NameError`），验证因此改成对 8 个改动模块跑真正的 `importlib.import_module()` 循环；② **warn-once 状态要按参数化用例清掉** —— 模块级 `set` 不清的话，同 key 的第二个参数化用例会看到 **0** 条告警并误判为「静默降级」。
- **验证**：
  - **守卫**：`tests/owner/test_upstream_private_symbol_deps.py` **29 passed**；相关定向套件（`test_merge_forward_expansion` / `test_feishu_client_utils` / `test_runtime_provider_resolution` / `test_compression_summary` / `test_skill_manage_gate` / `semantic_audit*` / `test_compression_logging_session_context` / `test_approval_suggest_i18n_blocks`）**286 passed**；媒体三件套（`test_api_server_media_data_urls` / `_files` / `_owner`）**45 passed**；8 个改动模块 `importlib` 全通过。
  - **变异验证 12/12 全部咬住**（`/tmp/t216/mutate_t216.py`：每个 `.py` 变异体先 `compile()` 预校验、锚点必须**恰好命中 1 次**否则判 `BAD ANCHOR`、还原走内存快照 + md5）：① 裸导入回来 ⇒ 咬住普查；② 降级改成 `raise` ⇒ 咬住「不抛异常」+「附件仍交付」；③ 降级 `return ""`（不内联变成丢件）⇒ 咬住「标签外正文本存活」；④ 删掉告警（回到静默降级）⇒ 咬住；⑤ warn-once 改成 warn-every-call ⇒ 咬住；⑥ 告警丢掉 `§16.13` 指引 ⇒ 咬住；⑦ 有人把硬导入改成软回退 ⇒ 咬住 **allowlist 双向守卫**（运行时抓不到，因为本环境 import 成功、回退分支不可达 —— 这是正确的分工，不是测试缺口）；⑧ 删掉注册那一行 ⇒ 咬住注册断言；⑨ 哨兵换成本地 `object()` ⇒ 咬住**身份**断言；⑩ 摘要能力不再关闭 ⇒ 咬住；⑪ `PRIVATE_SYMBOLS` 少一行 ⇒ 咬住反向普查；⑫ 扫描器不再下探函数体 ⇒ 咬住**自证**用例（9 个含私有导入的文件会只剩 2 个可见）。
  - **变异装置两处首轮不合格，已修（记录在案）**：① `resolver_import_goes_bare` 与 `degrade_goes_silent` 的锚点只切了 `try:` / `logger.warning(` 一行，**留下悬空的 handler 体 / 字符串参数 ⇒ `SyntaxError` ⇒ 判 `INVALID`**；修法是把锚点扩成**整块正文**（这也说明「变异体必须仍是合法程序」这条预校验是承重的）。② **`test_finalize_api_media_degrades_when_the_resolver_is_gone` 的输入不含 `MEDIA:`** —— `finalize_api_media` 在无标签时**提前返回**，那条路径压根走不到解析器，用例**绿得毫无意义**；变异体②③因此双双逃逸。这是**测试的缺口**（不是代码多余），改成含标签的真实输入后才咬住。
  - **爆炸半径回归**（语料 **137 个路径** = T2-14 的 134 个 + `tests/agent/test_i18n.py` + `tests/owner/test_locale_catalog_integrity.py` + 本守卫）：

    | 腿 | 内容 | 读数 |
    |---|---|---|
    | A | 当前树 | 30 failed / **2645 passed** / 43 skipped |
    | B | 8 个被改文件还原到 HEAD（裸导入 / 静默 `except: pass`）、本守卫移走并从语料里剔除（136 路径） | 30 failed / **2616 passed** / 43 skipped |

    **NEW 0 / GONE 0**；两腿 30 个失败**同一集合**，均为存量。通过数差 **29 = 本守卫整文件 29 例**在对照腿中被移走。还原后 9 处 md5 校验全部 OK。
  - **健康检查**：`python -m owner.validation.merge_health_check` → **7 passed / 1 warning**，与 T2-15 后完全一致（Check 5 的 4 条 warning 属 merge 315551234 的既有项；Check 4 674 个标记 / 100 文件、Check 6 28/28、Check 7 140/140、Check 8 116/116 全绿）。
- **技巧（值得复用）**：① **对官方私有符号的依赖必须「可降级 + 可观测」**：可降级是因为私有符号的位置不由我们控制；可观测是因为**静默降级等于把上游改名变成一次无人察觉的降级**。② **审计给「复制实现」这类修法时，先问一句**：这个函数在上游**自我们的基点以来改过没有**？改过 ⇒ 复制 = **冻结旧语义**，比不改更糟（判据是 `git log -S<新符号> upstream/main -- <file>`，本项一次就捞出 `13f908f10d`）。③ **「复制很便宜」通常建立在错的行数上** —— 先量函数本体（本项 51 行 vs 审查的 ~25 行），量错量级会让判断反向。④ **AST 扫描普查强于 grep**：多行 `import (` 与模块前缀白名单是 grep 的两个结构性盲区（本项 5 → 9 文件 / 14 条）。⑤ **普查要双向 + 自证**：只查「有没有裸导入」会漏掉「在 `try` 里偷偷加依赖」；只枚举路径会漏掉「路径写错 ⇒ 枚举为空 ⇒ 全绿」。⑥ **allowlist 条目不成立时守卫必须强制删除它**，否则它变成免检通道。⑦ **变异体的注入点必须真的可达**：`except` 分支在本环境不可达的变异体在运行时永远等价（本项变异体⑦），此时**正确的期望是只有静态守卫咬住它** —— 别为了让数字好看去改测试。⑧ 「降级」有不同形态，**要按语义选**：装饰性功能可以「换交付形式」，格式锚点类必须「整体关闭能力」，注册类只能「硬失败」。
- **未纳入**：
  1. **审查修法①「复制 `_resolve_media_to_data_urls` 进 `owner/gateway/media_resolve.py`」**：实测有害（冻结 `#111046` 之前的语义），**整条按「不纳入」处置**。由此**审查的字面验收（`grep … import _` 为空）也不满足**，这是决策的已知代价。
  2. **审查修法②「整体迁 `owner/gateway/`，官方文件留 1–3 行委托」**：官方文件反向 import 我方文件（`api_server.py:155-161`，5 个名字，生产代码唯一调用点）是 **§2.3 可移除性**问题，不是私有符号问题；迁移还会把「官方文件里的官方代码」搬到 `owner/`，方向与 §16.11 的结论相反。**另立条目，不在本项范围。**
  3. **add/add 同路径碰撞**：风险为真但弱 —— 上游 `gateway/platforms/` 下**没有** `api_server_media.py`（它有 `api_server_openai_routes.py` / `api_server_turn_boundary.py` 等 6 个 `api_server_*`），故不会与我们对同一路径各写一份；但 `api_server.py` 本身 **195 次提交 / 3 月**，属于「上游正在系统拆 `api_server_*.py`」的高活跃区，将来若上游造出同名文件即为 add/add。**已登记，不展开。**
  4. **owner 在官方树内「新增」的文件不受 Check 8 覆盖**：Check 8 的口径是「**被修改的**官方文件必须带 `[owner]` 标记」（116/116 全绿），而 `gateway/platforms/api_server_media.py` 在上游不存在 ⇒ 被算作新增 ⇒ 不进那个集合。该文件在本次之前**零 `[owner]` 标记**（本次新增 1 处耦合点说明，`:498`）；`tools/feishu_client_utils.py` 已有 5 处（均属别的特性）。这是 Check 8 的**结构性盲区**，**已登记，不展开**。
  5. **`owner/approval/skill_manage_gate.py` 的告警化**：它已经是 `hard_stop_turn` + 点名 `exc` 的 fail-closed 形态，**比 warn-once 更强**，本项只登记不改。
- **Commit**：见附录 E（代码 + 测试一次提交；本条文档单独提交）

---

### 16.14 `delivery_ledger` 的合并面收敛：审计两条修法逐条量掉，改从「我方噪声」入手（T2-17）

- **背景**（T2-17 / 代码审查 M8）：审查说 `gateway/delivery_ledger.py:138/320/365` 改了上游 SQLite schema/事务层，而上游有一条 `refactor(sqlite): one open_db/transaction layer for every small store`（`576accd92b`，2026-09-12）**直冲该区域**；该文件**零 `[owner]` 标记**（违反规范 §2.2）。修法两条：① schema 迁移抽到 `owner/gateway/ledger_schema.py`；② `mark_delivered` 的新参数用 `**kwargs` 兼容而非改签名。行动清单 #8 复述了修法①。merge 侧独立给了同一结论：该文件净改动 `+109/−20`、**MOD 4**、`up3m` **21**（近 3 个月上游触碰次数）、命中冲突热点，定级 **P1**。
- **口径先校正（审查给的位置、标记数、修法三条）**：
  1. **行号位移**：审查说 `138/320/365`；实测我方 HEAD 三处函数定义在 **`:140` `_initialize_schema` / `:326` `mark_delivered` / `:372` `_update_state`**（`debug_rows` 在 `:639`）。三处都在，只是各错 2/6/7 行。另：报告的净改动写 `+109/−20`，实测我方 **HEAD vs 基点**是 `+119/−20`（12 hunk）。
  2. **「零标记」是审查当时的旧数，且新补的标记本身有形式缺陷**。现为 **10 处**（2026-09-28 `a77e345342` 随 T2-11 补上）。这 10 处的**文本逐字相同** —— T2-11 是**逐 hunk** 机械打标，同一个 §7.21 标题行被复制了 10 次；其中 **6 处「缩进逃逸」**（写在缩进块内却顶格到第 0 列，`:144/:164/:173/:387/:642/:655`），另有 4 处本就该顶格（`:70/:93/:325/:371`）。缩进逃逸是**独立于合并风险的正式缺陷**：正确形态是 `#` 与所在块同缩进、被注的语句在下一行。
  3. **修法①要我们自建一个基点就已存在的原语**。`hermes_cli/sqlite_util.py` **在基点 `00b2e03c80` 就存在**，已含 `add_column_if_missing(conn, table, column, ddl)` 与 `write_txn(conn)`；其模块 docstring 原文就写着「The projects and kanban stores open WAL SQLite files with the same two primitives — an idempotent column-add migration and an IMMEDIATE write transaction. One definition here keeps the two stores from drifting.」，`hermes_cli/kanban_db.py:92` 一直在用（`from hermes_cli.sqlite_util import add_column_if_missing as _add_column_if_missing`，约 20 个调用点）。**更关键的是：上游 `576accd92b` 对该文件采用的正是这个形态** —— `upstream/main` 的 `delivery_ledger.py:25` 就是 `from hermes_cli.sqlite_util import add_column_if_missing`，`_connect()` 与 `_transaction()` 也改成了 `sqlite_util.open_db` / `sqlite_util.transaction`（该提交把引用该模块的文件数从基点的 **12 个**扩到 **27 个**），我们只是成为**同向的第三个消费者**。与 T2-16 修法①同型（要我们造一个已有的东西）。
- **审计两条修法逐条量掉（零收益）**。口径 = `git merge-file -p --diff3 ours base theirs` 的**冲突块数**（ref-free 的文件级三方合并，故**内存中的候选也能量**；先用 `git merge-tree --write-tree upstream/main HEAD` 自校验 —— 该路径确被独立判为内容冲突）：

  | 候选 | 冲突块 | 我方侧行 |
  |---|---:|---:|
  | 对照（HEAD 现状） | **4** | 123 |
  | 审计修法①（schema 迁移抽 `owner/gateway/ledger_schema.py`） | **4** | 89 |
  | 审计修法②（`mark_delivered` 改 `**kwargs` 签名） | **4** | — |

  两条都只买到「我方侧行数」这一个指标，**块数一动不动** —— 与 **§16.11**、**§16.12** 同构，这是**第三例**：**块由「两处都改过」定义，缩我方侧只减行不减块；消块的唯一办法是让某一侧在该区域回到基点**。
- **撑起冲突面的其实是四件别的事（逐条实测，base/ours/theirs 行数取自块内读数）**：

  | # | 块内读数 | 成因 | 处置与结果 |
  |---|---|---|---|
  | 块 1 | `19/22/19` | `RECOVERED_MARKER` 上方：我们在**上游同一段注释**里插了 3 行（1 行 `[owner]` 标记 + 2 行指向待删死函数的引语），而上游也润色了同一段（`Visible prefixes … — honest at-least-once.`） | 3 行全删、该区域恢复基点原文 ⇒ **块消失** |
  | 块 2 | `1/2/1` | `apply_wal_with_fallback(...)` 之后那处**顶格标记**把 1 行基线区域一分为二。上游已把 `_initialize_schema` 的头两行（`from hermes_state import apply_wal_with_fallback` + 该调用）**删掉**（WAL 交给 `open_db`），函数的 `def` 行直接接 `conn.execute(` —— 那处标记正好落在上游改过的位置上 | 随标记去重删掉 ⇒ **块消失** |
  | 块 3 | `27/53/11` | 上游在**该函数上整体重写**（改成 `add_column_if_missing` 形态），而我们**必须**在这个函数里加一列 | **消不掉**（见下） |
  | 块 4 | `36/46/43` | 我们在 `_update_state` 里改了正文，而上游也改了同一个函数（把 `)` 收进参数行）；我们的 `mark_delivered` 改动紧邻其后，于是两侧的改动**并成一个 36 行基线区域** | `_update_state` **逐字节还原基点** + 戳记内联进上游从未触碰的 `mark_delivered` ⇒ **块消失** |

- **块 3 消不掉的证明（写下来，省掉反复试修法）**：① 消块要求某一侧在该区域回到基点；上游是**整体重写**（base 27 行 → theirs 11 行），我们不可能要求上游回退。② 我们也不可能回到基点：`platform_message_id` 列**必须**在这个函数里建，而**不能**推迟到首次写入 —— `debug_rows()` 会**无条件** `SELECT platform_message_id`，先开库后建列会在读路径上报 `no such column`（下方「被刻意否掉的一条」实测把钩子挪到 `record_obligation` 能到 0 块，代价正是这个）。③ 于是只剩「缩小我方侧」（53 → 49 行），而缩放不消块。
- **方案**（2026-09-29 用户决策：**C1′ 最小冲突面** + **删死函数**），四步，每步各自实测：
  1. **清掉注释噪声**：删 `RECOVERED_MARKER` 上方我方那 3 行，该区域**恢复基点原文**（现在与基点逐字节相同）。
  2. **标记去重 10 → 3，且全部按所在块自身缩进写**（4 / 0 / 8 空格）：`_initialize_schema` 区域 1 处、`mark_delivered` 上方 1 处、`debug_rows` 内 1 处。**缩进逃逸 6 → 0**。
  3. **建列腿改用既有共享原语** `hermes_cli.sqlite_util.add_column_if_missing`（顺带把既有的 `adapter_profile` 一并纳入同一个循环），保留部分索引 `idx_delivery_platform_message_id`。
  4. **`_update_state` 逐字节还原基点**；**戳记内联进 `mark_delivered`**（上游未触碰的安静区）—— 两条语句，先改状态、后补 id。
- **结果**：冲突块 **4 → 1**、我方侧行 **123 → 49**、文件 **661 → 613** 行；相对**基点**的我方足迹 **12 hunk / +119−20 → 9 hunk / +64−13**（我方自有的改动面收缩约 45%）。**零新耦合** —— 未新建 `owner/` 模块、未新增私有符号依赖、未新增跨文件 import。
- **落点阶梯（哪个动作买到哪个读数）**：

  | 阶梯 | 动作 | 冲突块 | 我方侧行 |
  |---|---|---:|---:|
  | 对照 | HEAD 现状 | **4** | 123 |
  | S1 | 清注释噪声（删残留引语 + 删死函数 + 标记去重） | **2** | 96 |
  | S2 | \+ `_update_state` 还原、戳记移出该函数 | **1** | 51 |
  | S3 | \+ 建列腿改用共享原语 | **1** | 42 |

  S1 消掉块 1/2，S2 消掉块 4，**S3 不减块** —— 它买的是「我方侧行数 + 与上游同向」。落盘成品的我方侧为 **49 行**（探测阶梯里的 42 行用的是简写注释；落盘版保留完整英文注释与不变式说明。**判据是块数，不是这一列**）。
- **代价（明写，属有意取舍）**：戳记由**一条 UPDATE 拆成两条语句**。两步之间崩溃只丢**可追溯 id** —— 行已是 `delivered`，`sweep_recoverable` 不会再捡起它重投；**次序反过来**才会让「已投递」的行停在 `attempting`，那是**会重复发送**的窗口。§7.21 的「**非覆盖语义**」仍在：`if message_id:` 守卫保证默认路径**不**把已学到的 id 抹成 NULL（§7.21 原文「两条 UPDATE，非 COALESCE」的语义不变，变的是**原子性**）。
- **被否证 / 被刻意否掉的两条思路（记录在案，避免下次重走）**：
  1. **被实测否证**：「把 schema 钩子挪到上游没在改的地方」—— 上游**连 `_connect()` 都重写了**（改成 `sqlite_util.open_db`）。在噪声已清净的树上实测把钩子挪进 `_connect()`：块数 **3 → 3**，但**新造了一块**（不是消块）——挪落点只是**换一个块**。
  2. **被刻意否掉（能到 0 块但会坏功能）**：把建列钩子挪到 `record_obligation`（首次写入路径）可降到 **0 块**，但 `debug_rows()` 无条件 `SELECT platform_message_id` ⇒ **先开库、后建列**会在读路径上报 `no such column`。**列必须建库时就存在，不能拿到才建。**
- **顺带发现的缺陷：`recovered_reply_marker()` 零生产调用者**。29 行、按 profile 给「重投前缀」打标；`git grep -n recovered_reply_marker HEAD` 全仓只有 **自身定义 + 上方注释里的 `:func:` 引用 + 3 个测试**，生产路径走的是 `gateway/run.py:13225` 的 `row.get("marker", RECOVERED_MARKER)`。上游 `_claimed_row` 的 docstring 自己写明 boot 恢复的行**不带 marker**、由 runner 定默认值（`marker = FLOOD_MARKER if flood else (RECONNECTED_MARKER if runtime else None)` ⇒ `None` ⇒ 落到 runner 默认）—— **上游独立选了我们同一个方向**。一个**拿不到任何输入**的函数活在官方文件里是「既不收上游修复、也不报冲突」的最坏形态；本次它恰好还生产了一个冲突块（块 1 里我方那 2 行引语就是指向它的）。用户决策：**删掉**。3 个用例分流：`test_recovered_reply_marker_named_profile` / `test_recovered_reply_marker_default_matches_baseline` 是**纯单测**（随函数删）；`test_attempting_redelivers_with_marker` 是**真的覆盖重投路径**（**不删**，只把期望值由 `dl.recovered_reply_marker()` 改为 `dl.RECOVERED_MARKER`，并把「上游 boot 恢复不给 marker」这句写进注释）。
- **涉及文件**：`gateway/delivery_ledger.py`（661 → 613 行；相对 HEAD `+37/−85`、13 hunk；相对基点 `+64/−13`、9 hunk）、`tests/gateway/test_delivery_ledger.py`（`+78`：新增 3 例 + 1 个 `_updated_at` 辅助）、`tests/gateway/test_restart_notification.py`（`−22`：删 2 例）。
- **侵入类型**：合并面收敛（删我方噪声 + 换用**上游同向**的共享原语 + 把钩子移到上游未触碰的安静区）+ 缺陷修复（标记缩进逃逸 6 → 0、删零调用者死函数）；**正常路径行为零变更**（唯一差异是戳记走两条语句，语义等价论证见「代价」）。
- **验证**：
  - **定向**：`tests/gateway/test_delivery_ledger.py` + `tests/gateway/test_restart_notification.py` **75 passed**。
  - **变异 7/8 咬住**（`/tmp/t217/mutate_t217.py`：锚点必须**恰好命中 1 次**、变异体必须仍能 `compile()`、还原走内存快照 + md5）：① 删掉补 id 语句 ⇒ **7F**；② `if message_id:` 改成无条件写（`None` 也覆盖）⇒ **1F**；③ 两条语句次序颠倒 ⇒ **1F**；④ 只补 id 不做状态迁移 ⇒ **9F**；⑤ 建列腿整条不生效（只剩 DDL）⇒ **2F**；⑥ 去掉幂等守卫 + 裸 ALTER ⇒ **39F**；⑦ `debug_rows` 不再带该列 ⇒ **1F**。**未咬住的那 1 个是正确预期**（见下）。
  - **唯一 MISS 是正确预期，不是测试缺口**：从建表 DDL 里拿掉 `platform_message_id TEXT`（同时把上一行的尾逗号收好、保证仍是合法 SQL）后，ALTER 腿在**新建库**上同样把它补上 ⇒ **运行时等价**。首轮这个变异体写成「只删一行、留下悬空逗号」⇒ **DDL 不合法** ⇒ 39 个失败被误读成「咬住」；**非 Python 载荷 `compile()` 校不出来**，改成合法删法后读数才可用。
  - **爆炸半径**（语料 **138 路径** = T2-14 的 134 + 4 追加）：

    | 腿 | 内容 | 读数 |
    |---|---|---|
    | A | 当前工作树 | 30 failed / **2677 passed** / 43 skipped |
    | B | 3 个被改文件还原到 HEAD | 30 failed / **2676 passed** / 43 skipped |

    **NEW 0 / GONE 0**；两腿 30 个失败**同一集合**，均为存量。通过数差 **+1 = 3 个新用例 − 2 个被删用例**；3 个文件还原后 md5 全部 OK。
    - **本轮修掉的一处语料缺口（记录在案）**：首轮 B 腿的通过数差是 **+3**，与「+1」对不上 —— 因为语料里**根本没有** `tests/gateway/test_restart_notification.py`，B 腿对它的「还原」是**空操作**，被删的 2 例（以及被删的死函数）从未进入回归。补进语料后加了**自证断言**（本次改过的 `tests/` 文件必须都在语料里，否则直接 fail），再跑才对上 +1。
  - **健康检查**：`python -m owner.validation.merge_health_check` → **7 passed / 1 warning**（Check 5 的 4 条 warning 属 merge `315551234` 的既有项，与本次无关）；Check 8 **116/116**、Check 6 **28/28**、Check 7 **140/140** 全绿。Check 4 标记数 **674 → 667**（−7 = 删 10 + 留 3），全仓口径 **1019 → 1012**，两侧一致。
- **技巧（值得复用）**：① **「缩小我方侧」与「消掉冲突块」是两个指标**：块由「两处都改过」定义，缩我方侧只减行不减块；消块的唯一办法是**让某一侧回到基点**（本项是 §16.11、§16.12 之后的第三例）。② **块消不掉时，把「为什么消不掉」写下来**：块 3 的不可消性有两个独立理由（上游整体重写 + 列必须在建库时存在），写进清单比反复试修法省时间。③ **审计要求我们「造一个东西」时，先查它在基点是否存在**：`sqlite_util.add_column_if_missing` 在基点就有，而且**上游自己刚把这个文件改成用它** —— 审计的直觉（用共享原语）是对的，只是被包装成「另建一个模块」。④ **挪落点前先查上游有没有动过那个落点**：`_connect()` 已被上游重写，挪进去只是换个块。⑤ **逐 hunk 机械打标会把同一行复制 N 次，还容易顶格写进缩进块**：本项 10 处文本逐字相同、6 处缩进逃逸。正确形态是「按区域留 1 处 + 落在该块自身缩进上」，并接受**区域级覆盖优先于 hunk 级覆盖**。⑥ **变异体载荷不是 Python 时，`compile()` 校验不了它**：SQL 变异体首轮留下悬空逗号（非法 DDL）⇒ 39 个失败被误读成咬住；非 Python 载荷要**单独想一遍合法性**。⑦ **`pytest --collect-only` 比跑测试快一个数量级，适合做语料自证**：「语料声明 N 个路径」不等于「N 个路径被真的收进回归」，本项就是靠它 + 自证断言抓出漏掉的那个测试文件。
- **未纳入**：
  1. **审计修法①「schema 迁移抽到 `owner/gateway/ledger_schema.py`」**：零收益（4 块 → 4 块），且要自建一个**基点已有**的原语；改用既有共享原语后**方向与上游一致**（上游 `576accd92b` 自己就是这么改的）。**整条按「不纳入」处置。**
  2. **审计修法②「`mark_delivered` 用 `**kwargs` 兼容」**：零收益（4 块 → 4 块），且会把 3 个显式参数换成无名字典，丢掉签名可读性与类型检查。**不纳入。**
  3. **hunk 级标记覆盖的缺口**：本项把 `_initialize_schema` 的标记由「逐 hunk 3 处」收敛为「区域 1 处」，于是 **`CREATE TABLE` 的 DDL hunk（`platform_message_id TEXT`）不再有紧邻标记**。要覆盖它只能把标记写回 `conn.execute(` 上方 —— 而**上游把 `_initialize_schema` 的头两行删掉了**，这一落点正是**块 2 的成因**：实测**加回去 1 块 → 2 块**。故按「**区域级覆盖 + hunk 级留缺口**」交付，缺口归 **T2-11b**（已登记的 902 处 hunk 级缺口）一并处置。Check 8 是**文件级**口径，仍 116/116 全绿。（旁证：`merge-file` 的冲突标记是**带路径的** `<<<<<< <path>`，用 `grep -c "^<<<<<< $"` 数块会得 0 —— 数块必须解析标记行前缀。）
  4. **`mark_delivered` 的语义分叉风险**：本项把戳记留在官方文件的 `mark_delivered` 内，**没有**把它搬进 `owner/`。若日后按 §16.11 的方向把这段自有代码搬出去，搬走的是「两条语句的次序」这一个决策 —— 已由 `test_the_id_stamp_does_not_disturb_the_state_columns` 与 `test_a_stamp_failure_does_not_lose_the_delivery` 两例钉住，故本次不动。**已登记，不展开。**
- **Commit**：见附录 E（代码 + 测试一次提交；本条文档单独提交）

---

### 16.15 飞书三件套的请求管线并入上游 `feishu_lark`：审计的「换目录」修法零块收益，真正相撞的是两个官方兄弟（T2-18）

- **背景**（T2-18 / 代码审查 M7-附带）：审查条目针对 `tools/feishu_client_utils.py` —— 「1,596 行、创建于 `tools/` 官方树内（违反规范 §2.2 落点约定）；本次 merge 未冲突（MOD=0、上游无同名、无私有符号依赖）→ 风险低于 T2-16」，修法是「评估迁入 `owner/tools/`」。用户决策：**不做换目录，改为对齐上游 `feishu_lark`**。
- **口径先校正（审查给的行数与风险判断两条）**：
  1. **行数**：报告写 1,596 行，实测 **1,621 行**。
  2. **「上游无同名」属实，但结论下错了方向**。该路径确实 MOD=0（`git merge-tree --write-tree upstream/main HEAD` 未把它列为冲突）；问题在于**上游另建了 `tools/feishu_lark.py`**（`6723628de9`，2026-09-02，晚于我方基点 2026-09-01），把 `set_client` / `get_client` / `_check_feishu` / `build_request` / `lark_call` / `raw_body` / `response_data` 这 7 个符号从官方文件里抽了出来 —— 而**我方自建模块重实现的正是同一套管线**。于是风险不在被审文件自身，而在**两个官方兄弟**：

    | 文件 | 冲突块 | 我方侧行 | 行数（基点 / 我方 / 上游） |
    |---|---:|---:|---|
    | `tools/feishu_doc_tool.py` | **6** | 143 | 138 / 281 / 95 |
    | `tools/feishu_drive_tool.py` | **7** | 249 | 431 / 413 / 203 |
    | 合计 | **13** | **392** | |

    被审的那个文件自身 **0 块** —— 审查说「风险低于 T2-16」就**该文件自身**成立，就**它引发的**冲突面不成立。
- **审计修法（迁入 `owner/tools/`）零块收益**。在 HEAD 上只把模块级 import 路径改成 `from owner.tools.feishu_client_utils import ...`（文件搬走后官方文件的引用行必然变）后实测：

  | 候选 | 冲突块 | 我方侧行 |
  |---|---:|---:|
  | 对照（HEAD 现状） | **13** | 392 |
  | 审计修法（迁入 `owner/tools/`） | **13** | 392 |

  **块数与路径无关** —— 块由「同一基点区域两处都改过」定义，换一个 import 路径不改区域归属（**§16.11、§16.12、§16.14 之后的第四例**）。故本项按「对齐上游」处理，换目录另见「未纳入」①。
- **相撞的真实成因（逐块实测，分两类）**：
  1. **管线重复类**（可消，本项目标）：文件头的 `import` / `logger` / `_local` / `set_client` / `get_client` / `_check_feishu` 区域 —— 上游**删掉这些定义**改为 `from tools.feishu_lark import (...)`，我方**删掉同一批**却换成**自建模块的 import**，两侧在同一区域做了**不同的替换**。
  2. **能力类**（消不掉，本项不承诺）：我方 handler 有**上游没有的能力** —— env-fallback client、wiki 节点解析、bitable / sheet 读取、docx 图片物化 + vision OCR、`om_` 合并转发分页。上游把 4 个 drive handler 收成了 `_comment_op` 工厂函数，我方的 4 个显式 handler 与它**正面相撞**。
- **方案（对齐上游 `feishu_lark`）三步**：
  1. **预置上游 `tools/feishu_lark.py`，与上游逐字相同**（86 行）。该文件在基点与我方都不存在、上游存在 ⇒ merge 侧是「上游新增」，我方预置成同文 ⇒ **零合并债**（`git merge-tree` 不把它列为冲突）。
  2. **两个官方文件的头部换成上游形态**：docstring 取上游 5 行、`import` 块逐字照抄上游（含我方不用的 `build_request` / `raw_body`，由上游那句 `# noqa: F401` 覆盖）、`_RAW_CONTENT_URI` 就位、`logger = logging.getLogger(__name__)`；**删掉我方 5 处重复实现**（2× `set_client`/`get_client`、2× `_check_feishu`，以及 drive_tool 里早已搬进共享模块的 `_do_request` 残影）。
  3. **我方扩展代码（`feishu_client_utils` 的 import + `logger`）落到上游改过的区域之外** —— 本项最关键、也最容易做错的一步（见「技巧」③）。
- **我方 `do_request` 与上游 `lark_call` 的等价性实测（不能直接替换）**：`lark_call` 的 `raw_body` 只兜 `JSONDecodeError` / `AttributeError`，而**媒体下载端点返回的是原始图片字节**，`json.loads(b'\x89PNG...')` 抛的 `UnicodeDecodeError` 会**穿出去**。按「删掉 60 行内联解析、直接调 `lark_call`」执行后，`read_docx_with_images` 的 **2 个用例当场变红**。落盘改法：**共享 `build_request` + `response_data`，只在「不是文本」这一种响应体上兜一层**，并保留 `GET` / `POST` 以外的 `ValueError` 严格拒绝。
- **落点阶梯（doc_tool：哪个落点买到哪个读数）**：

  | 落点 | 冲突块 | 我方侧行 |
  |---|---:|---:|
  | 对照（HEAD 现状） | **6** | 143 |
  | 扩展块紧跟 `_RAW_CONTENT_URI` | 5 | 129 |
  | 扩展块紧跟 `logger` | 5 | 128 |
  | **扩展块挪进 handler 体内（落盘）** | **4** | **111** |

  drive_tool 把 7 种落点全扫过一遍（紧跟 docstring / `import logging` / `feishu_lark` import / registry import / `logger` / EOF / handler 内导入），**最低就是 5 块** —— 因为它的 4 个块是 `_comment_op` 正面相撞，落点怎么挪都消不掉。
- **结果**：

  | 文件 | 冲突块 | 我方侧行 | 行数 |
  |---|---|---:|---:|
  | `tools/feishu_doc_tool.py` | 6 → **4** | 143 → **111** | 281 → 246 |
  | `tools/feishu_drive_tool.py` | 7 → **5** | 249 → **219** | 413 → 375 |
  | 合计 | 13 → **9** | 392 → **330** | 694 → 621 |
  | `tools/feishu_lark.py` | — | — | 新增 86（与上游逐字相同） |

- **留下的 9 块是什么**：doc_tool 的 4 块 = `resolve_client(get_client())`（env-fallback client）、错误文案 + `om_` 合并转发 + wiki 解析、docx/bitable/sheet 分派、我方不再做 raw_content GET；drive_tool 的 5 块 = 1 块「我方 4 行扩展 vs 上游 `_comment_op`」+ 4 块 handler 本体。**9 块全是「能力类」，管线重复类已清零。**
- **顺带修掉的形式缺陷（drive_tool 标记）**：`[owner]` 标记 **15 → 9**；**缩进逃逸 9 → 0**（原 9 处写在缩进块内却顶格到第 0 列）；删掉第 2 行那条**位置错挂且实际无对应改动**的「改动在下方的多行字符串内」标记（它指向的 docstring 新增行是普通新增行、不在任何字符串内）；删掉 4 处装饰性 `# ---- feishu_drive_* ----` 分隔线（基点有、上游已删）。
- **我方新增一个官方树文件（对规范 §2.2 的显式例外）**：`tools/feishu_lark.py` 落在官方目录，**内容与上游逐字相同** ⇒ 它不是「我方自定义文件」，而是**提前抵达的上游文件**；放进 `owner/` 反而会造出永久分叉。故按例外处理并在此登记。
- **涉及文件**：`tools/feishu_lark.py`（新增 86 行，与上游逐字相同）、`tools/feishu_doc_tool.py`、`tools/feishu_drive_tool.py`、`tools/feishu_client_utils.py`（`do_request` 60 → 37 行，改走共享管线 + 非文本兜底）、`tests/tools/test_feishu_tools.py`（新增 3 例）。
- **侵入类型**：合并面收敛（沿用上游同向的共享管线 + 把扩展块移到上游改区之外 + 删重复实现）+ 缺陷修复（标记缩进逃逸、无对应改动的标记、装饰性分隔线）；**正常路径行为零变更**（唯一差异是 `do_request` 的非文本响应体兜底由「内联解析的副作用」变为显式分支，语义等价论证见上）。
- **验证**：
  - **定向**：`tests/tools/test_feishu_client_utils.py` + `tests/tools/test_feishu_tools.py` + `tests/owner/test_merge_forward_expansion.py` + `tests/owner/test_upstream_private_symbol_deps.py` + `tests/gateway/test_feishu.py` —— 基线（`8645d5c236`）**199 passed / 6 failed**，本次 **202 passed / 6 failed**（**Δ+3 = 本次新增的 3 个用例**）；6 个失败**与基线逐节点相同**（全部在 `tests/gateway/test_feishu.py`，落在 adapter 的 `_sender_name_cache` 上，为本仓既有存量、与 `tools/feishu_*` 无关）⇒ **本次引入 0 个新失败**。
  - **变异 8 例 / 6 咬住 + 2 如实记缺**（`/tmp/t218/mutate_t218.py`：锚点必须**恰好命中 1 次**、变异体必须仍能 `compile()`、还原走内存快照 + md5）：① 去掉 `GET`/`POST` 方法守卫 ⇒ **1F**；② 去掉非文本响应体容忍 ⇒ **2F**（正是等价性缺口那 2 例）；③ `build_request` 的 `paths`/`queries` 互换 ⇒ **1F**；④ doc_tool 不再再导出 `set_client` ⇒ **2F**；⑤ drive_tool 不再导入 `_check_feishu` ⇒ **1F**；⑥ `_typed_data` 恒返回 `{}` ⇒ **MISS**；⑦ `_check_feishu` 恒为 `True` ⇒ **MISS**；⑧ 去掉 doc_tool 的异常日志行 ⇒ **1F**。两个 MISS 是**如实记录的覆盖缺口**（⑥ 只断言「不抛异常」、未断言回落内容；⑦ 无用例验证 `lark_oapi` 缺失时探测为 False）。
  - **仪器口径的一处修正（记录在案）**：首轮变异只解析 `(\d+) failed`，而**模块级 `NameError` 让 pytest 报的是 `1 error`、退出码非 0**，于是正确咬住的 ⑤ 被读成 MISS。改为 `failed + error` 并加「退出码非 0 却说零失败/零错误记 1」的兜底后读数才可用。**仪器口径错了会静默改变结论。**
  - **爆炸半径**（语料 **135 路径** = T2-14 的 134 + 1 追加）：

    | 腿 | 内容 | 读数 |
    |---|---|---|
    | A | 当前工作树 | 30 failed / **2624 passed** / 13 skipped |
    | B | 4 个被改文件还原到 HEAD + `feishu_lark.py` 移开 | 30 failed / **2621 passed** / 13 skipped |

    **NEW 0 / GONE 0**；通过数差 **+3 = 3 个新用例**；语料自证「收集到 518 个 feishu 节点」，4 个被改文件还原后 md5 全部 OK、新增文件归位。
  - **健康检查**：`python -m owner.validation.merge_health_check` → **7 passed / 1 warning**（Check 5 的 4 条属既有项，与本次无关）；Check 8 **116/116**、Check 6 **28/28**、Check 7 **140/140** 全绿。Check 4 标记数 **667 → 662**（−5 = doc_tool +1、drive_tool −6），与逐文件计数一致。
- **技巧（值得复用）**：① **审计说「某文件违规」时，先量它引发的冲突面落在哪**：被审文件 0 块、两个官方兄弟 13 块；只盯着被审文件会把风险读到反方向。② **换目录修不动块数**：块由「同一区域两处都改过」定义，与路径无关（第四例）。③ **我方新增块的落点决定块数**：落点必须选在**两侧都没改**的基点区域；把新增块放在上游改写区的**紧邻**处会被并进同一个 hunk（doc_tool 的扩展块紧跟 `_RAW_CONTENT_URI` 或 `logger` 都是 5 块，**挪进 handler 体内才到 4 块**）。④ **「头部逐字等于上游」本身有收益**：docstring 与 import 块逐字照抄（含我方不用的符号，由 `# noqa: F401` 覆盖）后，文件头永久零合并债；代价是 `_RAW_CONTENT_URI` 在我方成了无使用者的常量 —— **这笔账要明写**。⑤ **复用上游实现前必须实测等价性**：`raw_body` 只兜 JSON 解析错，二进制响应体（媒体下载）会穿出去；照「删掉自己的、直接调上游的」执行会当场坏功能。⑥ **薄壳的再导出是契约**：`feishu_comment.py` 用 `mod.set_client(client)` 注入，官方文件 `from tools.feishu_lark import (...)` 上那句 `# noqa: F401` 就是这条契约；删重复实现时必须**保名**（§16.13 同型）。⑦ **变异仪器要计 error 不只计 failed**（见上）。
- **未纳入**：
  1. **审计修法「把 `tools/feishu_client_utils.py` 迁入 `owner/tools/`」**：零块收益（13 → 13），且会让官方文件的 import 指向 `owner/`、在同一块区域内换掉一行 —— **合并面不变、规范面另有争议**。本项按「不纳入」处置并**登记为待决**：这是**同一批「官方目录新增文件」的第 2 例**（T2-16 的 `gateway/platforms/api_server_media.py` 是第 1 例），两例的落点问题应一并决策。
  2. **`do_request` 直接替换为 `lark_call`（省掉 60 行内联）**：**不可行** —— 媒体下载路径 2 例变红（等价性缺口见上）。保留薄壳 + 非文本兜底。
  3. **drive_tool 剩余 5 块（我方侧 219 行）**：4 块是「上游改成 `_comment_op` / 我方 4 个显式 handler」的正面相撞，属 **T2-20（采纳上游拆包）** 的邻接工作 —— 本项**不承诺**消掉它们，做完后如实记录为 5 块。
  4. **`_RAW_CONTENT_URI` 在 doc_tool 成为无使用者常量**：为「头部与上游逐字节相同」保留。若日后清理，需接受 **+1 块**。
  5. **Check 8 对「官方目录新增文件」的盲区**：`tools/feishu_lark.py` 是我方新增的官方树文件、**无 `[owner]` 标记**，而 Check 8 只数 **modified** 文件（仍 116/116）⇒ 这是该盲区的**第 5 例**，扩展项已登记。
  6. **`tests/gateway/test_feishu.py` 的 6 个存量失败**：与本次无关（基线同集合），**未在本项范围内修**。
- **Commit**：见附录 E（代码 + 测试一次提交；本条文档单独提交）

---

### 16.16 采纳上游 `run.py` 拆包：23 个模块落地 + 56 处定制重落；换码就绪性复核不成立（T2-20）

- **复核结论（2026-09-30，本节后续"进度尺归零"的适用边界）**：本节的机检（`verify` PASS、`ruler` **0 缺口**）只回答「**标记文本计数是否下降**」。对**换码**这一步，该口径**不充分**，原因是它有两条按构造原理的失明面：
  1. **无标记的定制**：我方 `gateway/run.py` 相对 merge-base 的真实改动是 **+906 / −475 行 / 240 个 hunk**，而 `[owner]` 标记只覆盖其中 **56 行**。其中 **i18n `t(` 调用 163 行**（三方交叉验证：BASE 10 处 → 本地 172 处 / 159 键；上游 24 文件族 8 处）**完全无标记**，是最大的一块。
  2. **惰性导入**：`ruler` 只数标记文本；当"重落"落成的是一句 `from gateway.run import <我方自有助手>` 时，标记文本出现了、符号却仍只在单体里 —— 仪器判「已落位」。
- **实测结果（独立交付物 `deliverables/gstack/T2-20-换码暴露面与就绪性实测.md` + `T2-20-换码暴露面清单.tsv`）**：
  - **尺度**：`GatewayRunner` 我方 **24,978 行** vs 上游 `run.py` **1,111 行**（上游把方法拆进 14 个 `Gateway*Mixin`）；本地 `run.py` **不 `import` 任何 `gateway.run_*`（计数 0）** ⇒ 23 个模块目前是**惰性死重**，运行时仍是单体。
  - **行级核对**（未来树 = 全仓 .py 去 `run.py` ∪ 上游 `run.py`）：906 行中逐字命中 331、令牌命中 84、**未覆盖 385**（标记 6 = 4 原地 + 2 已登记塌缩 / i18n 133 / 代码 200 / 注释 46）。叠加「符号存续」判据后，**换码后消失的符号所含未覆盖行 = 140**（代码 100 / i18n 20 / 标记 4 / 注释 16）：`_gateway_profile_tag`(24)、`_classify_edit_failure`(16)、`_is_executor_shutdown_error`(12)、`_format_exec_approval_fallback`(11)、`_append_dedup_counter`(11)、`_escape_code_fences_for_inline_block`(8) 等。
  - **就绪性机检：9 处生产引用会在换码时 `ImportError`**。5 个符号（`_gateway_lifecycle_msg`、`_classify_edit_failure`、`_is_executor_shutdown_error`、`_append_dedup_counter`、`_load_gateway_runtime_config`）**上游 `run.py` 没有**（上游可用名 = 顶层 371 + 惰性再导出表 41 = 412），而调用点已写进 `gateway/run_turn.py:2014`、`gateway/run_turn_runner.py:616/656/708`、`gateway/slash_commands.py:91/1640/1728/4370`；测试侧另有 7 处。
  - **判定：本节的"重落"是「调用点搬迁」而非「定义搬迁」** —— 与本条已记的 `resolve_tool_progress` 一例同因（惰性闭包 + 只补调用点），是同一盲区的第二次复现。**换码范围与验收须按上述三点重建**；映射表 §3 的 52 条**不构成**换码的验收面。
- **A1 自足性落地（用户 2026-09-30 决策「全量保真换码」，A1 为其先决阶段）**：4 个我方助手移入 `owner/`，官方文件只留薄委托。
  - 新建 **`owner/gateway/lifecycle_copy.py`**（`profile_tag()` / `lifecycle_msg()`，即 §7.14 的 `{profile_tag}` 注入）与 **`owner/gateway/turn_helpers.py`**（`append_dedup_counter()` / `classify_edit_failure()` / `is_executor_shutdown_error()` / `escape_code_fences_for_inline_block()`）。
  - `gateway/run.py` 6 处改为薄委托，**各带 `[owner]` 标记** ⇒ `run.py` 标记数 **56 → 62**（此前这几处正是「无标记的定制」的一部分）。
  - 调用点改指 `owner/`：`gateway/run_turn.py:2015`（`lifecycle_msg` + `is_executor_shutdown_error`）、`gateway/run_turn_runner.py:616`/`:708`（`classify_edit_failure`）、`:656`（`append_dedup_counter`）、`gateway/slash_commands.py:91`/`:1640`/`:1728`（`lifecycle_msg`）。
  - 测试改指 `owner/`：`test_progress_dedup_codeblock.py`、`test_feishu_edit_rotate.py`、`test_reasoning_fence_escape.py`、`test_restart_notification.py`。这 4 个助手经**三方核对**确属我方独有（上游 0 文件、BASE `run.py` 0 行）。
  - **一处非机械的归属判定**：`_load_gateway_runtime_config`（BASE 17 处、上游 0 处）**不是**我方新增，而是**上游删掉的** —— 上游把 `${VAR}` 展开移进了 `hermes_cli.config_effective.load_user_config_effective`（上游 `_load_gateway_config` 的 docstring 明写 "managed overlay, `${VAR}` expansion"）⇒ 其调用点在换码时**取上游的 `_load_gateway_config()`** 即行为等价。故**不搬 `owner/`**，只登记为 A4 的合并动作。
  - **就绪性机检**：生产侧 **9 处 / 5 符号 → 1 处 / 1 符号**（仅剩上述 `_load_gateway_runtime_config` 于 `slash_commands.py:4370`）；测试侧 7 处 / 5 符号 → 3 处 / 3 符号。余项归属：`_clarify_send_disposition` / `_clarify_send_then_wait`（上游已移入 `gateway/run_turn_runner_clarify_delivery.py` ⇒ 取上游落点）、`SecondaryPortBindingConfigError`（我方独有异常，其 2 处 raise 站点在单体 multiplex reconcile 代码内 ⇒ 随 `run_profile_reconcile.py` 在 A3 重落）。
  - **验证**：导入烟测 **27 模块 / 0 失败**；定向 7 个测试文件 **118 passed**；`verify` **PASS**（全仓 885）、`ruler` **0 缺口**（4 处原地登记）；健康检查 **7 passed / 1 warning**（Check 8 **122/122**；该 warning 为存量 Check 5 项，与本轮无关）。
- **背景**（T2-20）：上游在 19 天窗口内把 `gateway/run.py` 从 5,676 行拆成 23 个 `run_*.py`（合计 21,542 行），我方仍是 34,113 行的单体。三方合并实测 `run.py` 有 **32 冲突块 / ours 侧 25,005 行**（`git merge-file` 口径；`merge-tree` 结果树口径为 25 块 / 25,294 行），其中 **1 块独占 19,945 行**——那不是「某几处定制」，而是**整段拆包搬走**。**用「逐处迁定制」的手法消不掉它**，只能采纳上游结构。
- **成本 / 收益被实测改写（本项的决策依据）**：
  - 真实 `git merge upstream/main`（`merge-tree --write-tree`）冲突 **117 文件 / 544 块 / ours 侧 124,755 行**；`run.py` 是第 1 名但**只占 20.0% 行、5.9% 块**（次席 `cli.py` 10.7%、`tui_gateway/server.py` 9.7%、`hermes_state.py` 8.6%）。上游做的是**全仓规模**的模块化，`run.py` 只是最大一例 ⇒ **单项治理的收益上限是五分之一**。
  - 换码前置依赖：23 个上游模块**不自足**。静态闭包四代收敛，最终判定 **import-time 只要 5 个模块 + 0 个符号**；惰性闭包是 **230 模块 / 142 符号**（属运行期，不阻塞 import）。
- **用户决策：收窄为「按符号补齐」**——23 个上游模块整取；55 个依赖文件**一律不替换**，只把缺的符号移植进来。
- **落地分两步**：
  1. **结构 + import-time 闭包**（`fcae2029a0`、`21f32d86d6`）：23 个 `run_*.py` 落地（19 个与上游**逐字一致**、4 个已承载定制）；补 **7 处 import-time 符号** + **5 个 import-time 模块**（均逐字取上游、字节一致已验）+ `FailoverReason` 上游新增的 5 个成员。
  2. **定制重落**（`ab969baa80`、`58be2cbe98`）：monolith 里剩余 **24 种标记文本 / 30 处缺口**全部重落到 `gateway/run_turn.py`。
- **移植约定（本条确立）**：**前向移植的上游代码逐字复制、不加 `[owner]` 标记**。判据一句话：「merge 那一刻，该以谁的一侧为准」——上游代码提前取用后，未来真 merge 时与上游一致可**自动合掉**；加标记反而把自动合入变成手动冲突。我方自己的定制（上游没有的）**必须**标记。
- **口径决策：逐点传 `source=`，不用「单点绑定 partial」**。曾评估把 per-chat 解析收敛成 `functools.partial` 单点注入（标记更少、合并面更小），但会让 **8 处站点共用 1 条标记**，机检仪器从此对这 8 处失明，还须新增 `allow_drop` 假造一次「塌缩」。取舍是**仪器灵敏度优先**——仪器的存在理由正是「漏搬 = 定制静默消失」（T0-1 的动机），不能为省几行标记削掉它的分辨力。最终**未新增任何 `allow_drop`**。
- **惰性闭包提前咬到一次（改写「可完全推迟」的判断）**：上游 `run_turn.py` 运行期 `from gateway.display_config import resolve_tool_progress`，而 `display_config.py`（55 个依赖文件之一，**不整体替换**）**没有这个符号**。它属惰性闭包、非 import-time 依赖 ⇒ 「23/23 可 import」的检查**看不见它**，一旦走到这条路径就是 `ImportError`。按既定路线**只补符号**：`resolve_tool_progress`（含 per-chat 层）、`_configured_display_value`（含 per-chat 层），并把原先内联在 `resolve_display_setting` 里的 owner 钩子惰性 import 收敛成单点 `_owner_display_hooks()`（避免优雅降级 fallback 在两个调用点之间漂移）。
  - 上游 `resolve_tool_progress` 回答的是**第二问**：「这个模式是运维写下的，还是继承来的 tier 默认值」——Slack 原生 task cards 依赖该区分（tier 的 `off` 不该杀卡片，写下的 `tool_progress: off` 必须杀）。移植版额外携带 per-chat 层，否则 `display.per_chat.<platform>.<chat_id>.tool_progress` 对溯源问题不可见，per-chat 的 `off` 会留下卡片通道继续跑。
  - **等价性实测（非抽样）**：`resolve_display_setting` 8 组配置 × 5 平台 × 9 设置 × 2 chat_id = **720 组比较，0 处差异**。
- **四处「不能机械套模板」的判定**：
  1. `_clear_planned_restart_notification` **上游全仓无**（被删）。但其内的 `[owner]` 标记经 **AST 复核实为模块级代码**——紧跟 `os.environ["_HERMES_GATEWAY"] = "1"` 之后的环境清洗，与该被删函数无关 ⇒ 判为 **run.py 原地**。
  2. `track_agent` 上游**改名** `_run_agent_track_agent`（`run_turn.py`）⇒ 按新名落笔。
  3. `_interim_assistant_cb` 实测**不是定制**（我方与基点逐字一致；上游版本是上游自身加的 streaming-TTS flush + `_send_status_text`）⇒ 采纳上游、无丢失。
  4. **两处「正当塌缩」**（上游把我方重复的定制**收敛成单一 choke point** ⇒ 标记数合法下降，登记进 `allow_drop`）：
     - `# [owner] cron-env-leak: scrub session/cron env (see owner/cron/restart_scrub.py)` → `GatewayShutdownMixin._restart_watcher_env()`（`gateway/run_shutdown.py:1348`）。
     - `# [owner] fence-safe` → `_progress_absorb`（`gateway/run_turn_runner.py`，主循环与 drain 循环两处调用同一助手）。
- **四处「run.py 原地」不迁移**（逐条复核确认）：CR-004 白名单（模块级）、BOS/EOS 清洗（`_sanitize_gateway_final_response` 内）、`_resolve_gateway_display_bool` 的 `chat_id` 文档行、cron-env-leak 的模块级环境清洗。上游 `run.py` 至今保有这 4 个宿主/位置 ⇒ **换码收尾时补回新 run.py** 即可。
- **机检（零定制丢失仪器，口径 v2）**：
  - `verify` **PASS**：43 种标记文本全部未下降；全仓总数 **869** ≥ 下限 54。
  - `ruler` 收敛到 **0 缺口**：**39 种已落位 + 4 种登记为「run.py 原地」= 43**。
  - **仪器本轮两次加固 / 一次扩展**：① 记录口径由「整行」改为「**从 `# [owner]` 起的部分**」——`run.py` 里大量标记是**代码行上的行内注释**（`progress_lines[-1] = ... # [owner] fence-safe`），重落时上游把接收者改名是**正当改写**，用整行做身份会把这 16 处报成漏搬；裸标记（标记后无评注）**回退整行**，否则不同裸标记合成一条计数、丢一个加一个互相抵消，产生**假阴性**。② 新增 `run_py_inplace.json` 的**分类报告**：原地项若不加登记会**永远**留在待落清单里，使计数器收敛不到 0，真实缺口被已知项淹没。
- **Check 8 与「前向移植不加标记」约定的冲突（本轮修的是守卫，不是约定）**：手工跑健康检查发现 Check 8 由 **116/116 掉到 116/122**，报 6 个文件「modified official file with no `[owner]` marker anywhere」（`agent/replay_cleanup.py`、`agent/session_activity.py`、`gateway/response_filters.py`、`gateway/restart.py`、`hermes_cli/timefmt.py`、`utils.py`）。
  - **冲突本质**：这 6 个文件**在我方基点零足迹**，本次改动**全部**是逐字上游移植。Check 8 的规则是「改过的官方文件必须带标记」，而本条的约定是「前向移植不带标记」——**两者在这类文件上正面相撞**。
  - **判定：约定对、守卫粗**。`[owner]` 标记在本仓的语义是「**这是我方定制，冲突时保我方**」；而对逐字移植，正确的解冲突方向恰恰是**取上游版本**。给它们加标记会**误导后续 merge 去保留一份上游自己代码的旧拷贝** —— 比不加标记更糟。所以修的是守卫。
  - **改法（保留 Check 8 的严格性，而不是放水）**：新增 `owner/validation/upstream_port_files.txt` 逐文件**带理由**的豁免清单，并在 Check 8 里加**两个反向断言**防止它变成静默开关 —— ① 豁免文件**长出** `[owner]` 标记 ⇒ 报「条目过期（该文件已是真定制，须正常标记）」；② 豁免文件**已不再是改过的官方文件** ⇒ 报「条目过期（应退休）」。**「把有定制的文件塞进清单来消音」这条路被 ① 直接堵死。**
  - **自证三探针全部咬住**（`/tmp/t220/selfproof_check8.py`，内存快照 + 字节比对还原）：A 给 `utils.py` 加 `[owner]` ⇒ 报条目过期 ✓；B 移除 `gateway/restart.py` 条目 ⇒ 报缺标记 ✓；C 塞入无效路径 ⇒ 报条目过期 ✓。还原后回到 **122/122 / 0 issue**。
  - 该清单是**过渡性**的：换码收尾后这些文件由上游版本取代，条目随之退休（第 ② 个断言会主动提示）。
- **涉及文件**：新增 `gateway/run_*.py` × 23；`gateway/display_config.py`（补 `resolve_tool_progress` / `_configured_display_value` / `_owner_display_hooks`）、`gateway/run_turn.py`（25 处标记重落）、`owner/validation/merge_health_check.py`（Check 8 增豁免清单 + 两个反向断言）、新增 `owner/validation/upstream_port_files.txt`、`gateway/config.py` / `gateway/restart.py` / `gateway/response_filters.py` / `agent/session_activity.py` / `agent/replay_cleanup.py` / `agent/error_classifier.py` / `hermes_cli/timefmt.py` / `utils.py`（逐符号补齐）、新增 `agent/turn_failure_copy.py` / `gateway/platforms/base_exec_approval.py` / `gateway/platforms/event.py` / `gateway/session_transcript.py` / `gateway/warning_notifications.py`（与上游逐字相同）。
- **侵入类型**：结构性采纳上游拆包 + 薄胶水重落（25 处标记）。**正常路径行为零变更**（per-chat 解析逐点仍传 `source`，与 monolith 一致）。
- **验证**：
  - **机检**：`verify` PASS、`ruler` 0 缺口（见上）。
  - **定向回归（非全量）**：9 个测试文件 **9 failed / 221 passed** —— 9 项与基线**同一批**（`test_error_classifier` 的 `429`/`rate_limit` 归类，属 T2-21），**零新增失败**；`tests/gateway/test_display_config.py` 单跑 **23 passed**。
  - **可导入性**：**23/23** 个 `run_*.py` 可 `import`；`import gateway.run` 正常。
- **顺带发现（P2，留待清理类条目）**：`_resolve_gateway_display_bool(..., chat_id=)` 的 `chat_id` 形参**没有任何生产调用方**（唯一调用点与两处测试都不传）——该 per-chat 支持目前是**死能力**。本次按「不静默丢弃定制」**保守移植**（保留形参 + 文档行），但应纳入「无使用者 owner 面」的清理判定：**要么**在 `show_reasoning` 调用点补 `chat_id=source.chat_id` 激活它，**要么**删除。
- **未纳入**：
  1. **惰性闭包全量补齐（230 模块 / 142 符号）**：留到换码后按**实际暴露的运行时路径**驱动，避免为不存在的路径付合并面。`resolve_tool_progress` 一例说明「可完全推迟」不成立，届时须逐条实测。
  2. **同批 116 个冲突文件的其余部分**：`run.py` 只占 117 文件 / 544 块的 20.0% 行。本项**只治理 `run.py`**，其余属别的条目。
  3. **`owner/docs/run-py-owner-mapping.md` 的逐模块计数差**：该文档（2026-09-28，HEAD `efec7a3696`）记 `run.py` 5 / `run_turn.py` 33、合计 57，与本轮实测 `run.py` 3 / `run_turn.py` 32、合计 56 不一致；其第 208/210 行建议把 per-chat 显示簇（18 标记 / 11 调用点）**收敛进 `owner/`**，本次按「逐调用点重落」**未采纳**。该文档需按本轮实测**重写对齐**。
- **本条改动**：本清单 §16.16 正文 + §0.2 导航行 + 附录 B（新增 `gateway/run_*.py` 行、修订 `gateway/run.py` 与 `gateway/display_config.py` 两行）+ 附录 E。
- **Commit**：`fcae2029a0`（结构）→ `21f32d86d6`（import-time 闭包）→ `ab969baa80`（`display_config` 符号）→ `58be2cbe98`（`run_turn.py` 重落）。见附录 E。

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
| `owner/approval/skill_manage_gate.py` | skill_manage 写操作飞书审批门（profile 白名单） | plugin hook + feishu adapter 点击路由 |
| `owner/approval/approval_history_policy.py` | 审批历史拦截判定的结构标记策略（status / catalog key / 兜底三层 + SQL 锚点同源，§3.13） | hermes_cli/approvals_suggest.py 薄委托 |
| `owner/feishu/skill_approval_card.py` | skill 审批自建卡 + card action 处理 | feishu/adapter.py（skill_approval_gate） |
| `owner/owner-extensions/skill_manage_bridge/` | pre_tool_call / gateway 缓存接线 skill 审批门 | owner-extensions plugin |
| `owner/owner-extensions/output_guard/` | transform_llm_output 复读/乱码/超长检测与折叠；复读判据 `word_repeat` 已改为**线性扫描**（§16.7：原 `(\S+)( \1){5,}` 正则对无空白长文本是 O(n²)，50 000 字符 30.4s，且位于生成收尾的同步阻塞链上） | owner-extensions plugin（零官方侵入） |
| `owner/english_explainer/` | 英文终局回复中文解说旁白（§7.26，同 progress_explainer 形态） | owner-extensions plugin（零官方侵入） |
| `owner/outbound_special_token_scrub.py` | 出站剥 DeepSeek BOS/EOS 泄漏（§7.27） | gateway/run.py + run_agent.py 薄胶水 |
| `owner/progress_explainer/` | 沉默期进度旁白（§7.24） | gateway/run.py 薄胶水 |
| `owner/approval_explainer/` | 审批卡命令解说（§7.25，飞书+QQ） | feishu/qqbot adapter 薄胶水 |
| `owner/checkpoint_predictor/` | terminal 预测式 checkpoint（静态+LLM） | agent/tool_executor.py |
| `owner/clarify/` | clarify choice 归一化 + gateway helpers | tools/clarify_tool.py / clarify_gateway.py |
| `owner/cli/yolo.py` | YOLO on/off/status 命令 | — |
| `owner/commands/providers.py` | /providers plugin 斜杠命令实现 | owner-extensions plugin |
| `owner/cron/` | cron session 隔离 + restart scrub + run_job hook + approval helper | cron/* + gateway/run.py |
| `owner/diff_card/` | diff 卡片平台分发（飞书/QQ） | feishu/adapter.py |
| `owner/feishu/` | 飞书深度定制（含 queue_card / skill_approval_card 等）；另承载 API Server 侧 `resolve_api_identity_route` / `is_api_identity_whitelisted`（§15.1、§15.5，复用 `profile_endpoints`）、**子容器入口归属校验**（§16.6：`container_profile_identity()` 只认 `HERMES_PROFILE` / `user_routing.container_profile` 且**不猜默认值**；`verify_inbound_target_profile()` 对「两侧可识别且不等」拒绝、对「无法判定」放行并告警一次） | feishu/adapter.py（70 处标记）、gateway/platforms/api_server.py |
| `owner/gateway/` | inbound_context + hygiene_compression_notice + steer_vision + **ldap_auth**（LDAP bind 认证门：决策表 6 态 / 72h 正缓存 + 10s 负缓存 / RFC4514 转义，§15.2–§15.3；**§15.8 起 `enforce=seen` 为 `always` 的 fail-closed 别名**，`_seen_logins` 仅作诊断；**§15.9 起带密码但无法验证默认拒绝（503）**，`fail_open_on_error` 为显式 opt-in；**§15.7 新增路由接线状态诊断**） | gateway/run.py、gateway/platforms/api_server.py |
| `owner/gateway/session_salt.py` | API 会话 id 派生用的服务端盐（优先级 env > config > `<HERMES_HOME>/api_session_salt`；生成档 32 字节 `token_urlsafe`、原子写 0600、跨重启稳定；落盘失败降级为每进程盐并告警一次，§16.5）；另提供来源归因 `session_salt_source()` | gateway/platforms/api_server.py（`_owner_session_salt` 薄委托 + `_derive_chat_session_id` 改 HMAC） |
| `owner/patches/` | runtime patch（OpenViking recall + memory synthetic guard + pool base_url override + **queue_cancel** + **file_binary_detection**） | owner-extensions plugin / hermes_cli/runtime_provider.py |
| `owner/providers/credential_helpers.py` | GitHub token 校验等 credential helper | hermes_cli/model_switch.py |
| `owner/scripts/` | 运维脚本（备份/健康检查/汇率/todo 扫描/**HN Daily**/skill 同步/**Viking 记忆质量**/upstream_sync/周会/swagger） | — |
| `owner/semantic_audit/` | 工具分发前语义审计门（Tier0/1 + LLM + strike） | `run_agent.py` 1 处薄胶水 |
| `owner/sync/` | Upstream Sync 流水线（classify/fingerprint/merge/notify/kanban_ticket） | —（运维侧） |
| `owner/patches/queue_cancel_patch.py` | 飞书 queue 撤销/执行冻结 + 状态卡 runtime patch | owner-extensions plugin |
| `owner/feishu/queue_card.py` | `/queue` 状态卡（steer / 立刻处理 / 取消） | feishu/adapter.py + queue_cancel_patch |
| `owner/patches/file_binary_detection_patch.py` | `read_file` UTF-8 边界误判 binary（§8.5） | owner-extensions plugin（零官方侵入） |
| `owner/skins/` | ruolin 系列皮肤 YAML | — |
| `owner/tools/schema_patches.py` | 运行时 schema patch（legacy send_message card + image_generate model） | owner-extensions plugin（import/apply） |
| `owner/validation/` | merge 后健康检查（anchors + inventory + import/patch/marker checks + **merge_loss_audit**） | — |
| `gateway/platforms/api_server_media.py` | 产物媒体存储（接管字节 + 目录即索引，TTL / 容量淘汰，§16.1–§16.2）；归属摘要 `media_owner_token` + 超限回执 `rejected`（§16.4）；**对官方私有符号 `_resolve_media_to_data_urls` 的依赖改为「按名字运行时解析 + 可降级 + warn 一次」**（§16.13：裸导入在 HEAD `:517`，现包进 `_inline_image_data_urls()` 的 `try:`；降级 = 不内联 → 图片转为可下载附件） | **官方树内 owner 新增文件**（非 owner/ 目录） |

## 附录 B：官方文件侵入点速查

按侵入深度排序，优先用于 merge 冲突解决和上游重构后的死代码排查。

### B.1 重度侵入（inline 逻辑为主，sync 冲突大，hook/plugin 化首选）

| 文件 | 侵入内容 | owner/ 对应模块 | 相关 commit |
|------|----------|-----------------|-------------|
| `gateway/run.py` | cron env scrub ×3、executor-shutdown、inbound context、hygiene notice、auto-card、per-chat display、chained quick command、steer vision enrichment（§7.18）、**stale-run cancel（§7.23：/stop 后跳过提升的孤儿轮次补硬中断）**。**§16.16 起 `run.py` 已让位给上游拆包结构** —— 上述定制绝大多数已重落到 `gateway/run_*.py`（见下一行），`run.py` 里只剩 **4 处「原地」定制**：CR-004 白名单（模块级）、BOS/EOS 清洗（`_sanitize_gateway_final_response` 内）、`_resolve_gateway_display_bool` 的 `chat_id` 文档行、cron-env-leak 的模块级环境清洗 | owner/cron/、owner/gateway/、owner/feishu/、owner/display_overrides.py、owner/gateway/steer_vision.py | 几乎所有 §11/§17 commit；§16.16 |
| `gateway/run_*.py`（23 个，§16.16 新增） | 上游拆包后的新承运方。19 个与上游**逐字一致**（提前抵达的上游文件，零合并债）；**4 个承载我方定制**：`run_turn_runner.py` 9 处（diff-card 包装、飞书澄清超时停止、fence-safe、per-chat streaming…）、`run_busy.py` 4 处、`run_inbound.py` 4 处、`run_shutdown.py` 2 处。**§16.16 第二步另把 25 处标记重落进 `run_turn.py`**：per-chat display override ×11（`resolve_display_setting_for_source` 逐点传 `source=`）、auto-card ×3、progress_explainer ×6（安装点 + 停止点，后者落在上游抽取出的 `_run_agent_cleanup_turn_tasks` 内）、杂项 ×5（hygiene 压缩通知、§17.2 重启竞态、`_bg_session_key`、stop-orphan-run）。正式的前向移植代码**不带 `[owner]` 标记**（判据：merge 那一刻该以谁的一侧为准） | owner/cron/、owner/gateway/、owner/feishu/、owner/diff_card/、owner/progress_explainer/、owner/display_overrides.py、owner/patches/stop_orphan_run.py | fcae2029a0、21f32d86d6、58be2cbe98 |
| `plugins/platforms/feishu/adapter.py` | **70 处 `[owner]` 标记**（T2-14 迁移前 71，净 −1：`send_card` 两处随正文迁出、薄壳留一处，分派表 9 处随表迁入 `card_action.py`，其余 8 个新薄壳各补 1 处）：approval/auto_card/bot_menu/clarify/diff_card/model_picker/profile_routing/resume_card/sender_name/early-typing/**skill_approval_gate** / **queue_card** 委托；`_mentions_self` 不再把 `@_all` 当 @机器人（§4.14）；**merge_forward 二次拉取渲染**（§4.15）；`send_card` 内补 `hermes_profile` 标签（§4.1）；`_finalize_send_result` 全路径 message_id 日志（§7.21）；**reaction 归属决策记录**（§16.6，仅注释：群聊表情按反应者解析属已接受决策，钉在用例上）；**自有卡片胶水外移 + 11 个薄壳**（§16.11：`_dispatch_card_action` 111→49、`send_card` 63→19、`_get_card_send_lock` 23→12、`_send_media_guard_hint` 29→16、picker/guide/queue 六方法、`_normalise_card_action_value` 20→12；文件 7092→6900 行；兜底尾巴刻意留在 adapter，owner 侧以 `UNHANDLED` 哨兵表示「走兜底」；`anchors.yaml` / `inventory.yaml` 随之改指 `owner/feishu/card_action.py`） | owner/feishu/*（含 skill_approval_card、queue_card、card_sender、card_action） | §4.2/§5.3-5.7/§17.1/§3.11/§4.1/§4.11/§4.14/§4.15/§7.21/§16.6/§16.11 |
| `agent/conversation_loop.py` | MoA 注入（CR-005 已改为独立 message）、content-filter fallback、adaptive backoff、thinking-timeout、attribution 重建、tool_call_id 胶水 | owner/attribution.py、owner/api_error_hints.py | a6dcd6ed8、9a05e50b4、362304bc8 |
| `tools/approval.py` | home-prefix fold（CR-001 修复）、skill script 自动审批（3 处委托）、patch.yaml allowlist 合并、cron active helper | owner/approval/、owner/patch_config.py、owner/cron/approval_helper.py | 82fe8c962、5dd9580b4、99a374f64 |
| `gateway/platforms/base.py` | per-profile cache roots、SendResult rotate/retry_after、chained quick command（`[owner]`）、progress dedup code-fence 守卫 | — | 1d908072a、2be0af638 |
| `tools/cronjob_tools.py` | owner/scripts allowlist（mtime-based）、cron job args 三处 `[owner]` | — | 8a8f42455、3163d17e8、890869693 |
| `cron/jobs.py` / `cron/scheduler.py` | cron job args `[owner]` 参数 normalize + map | — | 3163d17e8 |
| `gateway/platforms/api_server.py` | identity routing 中间件（`X-Hermes-Identity` → 子 profile 反代，§15.1）、LDAP bind 二次认证门 + 三态 401 + **503（`ldap_backend_unavailable`，§15.9）**（§15.2–§15.3）、转发头剥离 + SSE 逐 chunk 透传（§15.4）、`GET /v1/ldap/identity/{identity}/access` + identity_whitelist 短路（§15.5）、finish chunk effective `session_id`（§15.6）、**dormant 状态显式化**（§15.7：中间件 `route is None` 分支区分未接线/未配置 + 端点响应 `routing_dormant` / `routing_keys_present`）、**认证门前移**（§15.10：`_owner_identity_gate_rejection` 独立步骤，白名单 / 已路由 / 未知身份一律先过门）、`GET /v1/media/{id}` + `hermes.files`（§16.1）、`ApiMediaStore.from_config()`（§16.2）、`tool.progress` 字段扩展（§16.3）、**产物下载归属断言 + 「未声明即放行」决策**（§16.4）、**会话 id 派生加服务端盐 + 归属摘要刻意不加盐**（§16.5：`_owner_session_salt` 薄委托 + `_derive_chat_session_id` 改 HMAC）、**`tool.progress` 出口强制脱敏 + 帧绑定断言**（§16.6：`_redact_for_sse` / `_redact_args_for_sse` / `_redact_result_for_sse` / `_bind_tool_frame` / `_tool_frame_is_ours` / `_stripped_tool_frame`，两条 SSE 通道的产出与写出点 + `/v1/runs` 的 `_tool_progress`）、**子容器入口归属校验**（§16.6：`_owner_inbound_profile_rejection` / `_profile_mismatch_response`，两个 feishu doorway 不匹配返 409 `profile_mismatch`） | owner/gateway/ldap_auth.py、owner/feishu/profile_routing.py、owner/gateway/session_salt.py、gateway/platforms/api_server_media.py | 6177923b26、531508e317、311f553550、4b6d187a2b、b14892be7c、8d42e4c199、3d9a9ceed4、943b6bf1ac、9df4372591、9f453c51e1、6613ac2146、571ba8c937、0925bdf088、a622691915、6b80b565f4 |
| `tools/browser_tool.py` | i18n 中文文案 `t()` 替换（**47 处** `[owner]` 标记） | agent/i18n.py + locales/ | i18n 批次（§12.2） |
| `tools/memory_tool.py` | i18n 中文文案 `t()` 替换（**33 处** `[owner]` 标记） | agent/i18n.py + locales/ | i18n 批次（§12.2） |
| `tools/computer_use/doctor.py` | i18n 中文文案 `t()` 替换（**20 处** `[owner]` 标记） | agent/i18n.py + locales/ | i18n 批次（§12.2） |

### B.2 中度侵入（薄胶水 + 列扩展，sync 冲突中）

| 文件 | 侵入内容 | 侵入类型 |
|------|----------|----------|
| `run_agent.py` | owner_provider_name 参数+属性+透传、attribution 重建（`[owner]`）、acp_args None 修复、schema patch import | 薄胶水 + 列扩展 |
| `agent/agent_init.py` | owner_provider_name 透传、acp_args 空列表→None（`[owner]`）、owner_provider_name 保留（`[owner]`）、`_auth_pool_refresh_counts` 初始化（CR-003） | 薄胶水 |
| `hermes_state.py` | sessions/messages 表加 owner_provider_name 列（INSERT/UPDATE/SELECT 全串联） | inline schema 扩展 |
| `agent/chat_completion_helpers.py` | owner_provider_name 剥离 + extra_body 注入点 | 薄胶水 |
| `agent/transports/chat_completions.py` | extra_body 注入 | 薄胶水 |
| `hermes_cli/runtime_provider.py` | pool base_url override ×2（`[owner]`）、env-var template P29 防泄露（`[owner]`） | 薄胶水 |
| `hermes_cli/model_switch.py` | credential_helpers 薄调用（GitHub token 校验）；自定义 provider 匹配去重防误报 `switch_multiple_providers`（§2.10） | 薄胶水 + inline |
| `agent/model_metadata.py` | env-var template P29 防泄露（`[owner]`） | 薄胶水 |
| `tui_gateway/server.py` | env-var template P29（`[owner]`）、Cmd+C fallback、skin 数据传递；live compression sync 回退 `get_custom_provider_context_length`（§6.4） | 薄胶水 |
| `agent/tool_executor.py` | checkpoint predictor 触发、file tool timeout 接线 | 薄胶水 |
| `agent/tool_guardrails.py` | warn/block/halt 消息增强（计数器/阈值/路径） | inline（字符串） |
| `tools/clarify_tool.py` / `clarify_gateway.py` | normalize_choices 薄调用 + stop sentinel | 薄胶水 |
| `tools/skills_tool.py` | track_session_skill_view 薄调用 | 薄胶水 |
| `gateway/platforms/qqbot/adapter.py` + `gateway/platforms/qqbot/constants.py` | WS 重连链（heartbeat/timeout/stop_retry/rebuild） | inline |
| `gateway/delivery_ledger.py` | `delivery_obligations` 加 `platform_message_id` 列 + 部分索引；`CREATE TABLE` 与 ALTER 对账循环双写；`mark_delivered` 非覆盖语义（§7.21）。**合并面收敛（§16.14）**：建列腿改用既有共享原语 `hermes_cli.sqlite_util.add_column_if_missing`（上游 `576accd92b` 对该文件采用的同形）；`_update_state` 逐字节还原基点、戳记内联进 `mark_delivered`；`[owner]` 标记 10 → 3 且缩进逃逸 6 → 0；删零生产调用者的 `recovered_reply_marker()`。冲突块 4 → 1 | inline 列扩展 + schema 对账 |
| `hermes_cli/plugins.py` | 后台插件发现锁超时语义（join 超时直接返回 + `acquire(timeout=15)`），修复启动空白屏（§7.20）；**薄壳 + `_discover_and_load_scoped()` 消除 40 行缩进重排**、`force=True` 上抛 `PluginDiscoveryLockBusy`、`_discovery_deferred` 可观测（§16.10，6 处标记） | inline |
| `hermes_cli/profiles.py` | `get_active_profile_name` 读 `HERMES_PROFILE` env 优先 + `_PROFILE_ID_RE` 校验 + 回落路径推断（§7.14） | inline |
| `plugins/memory/openviking/__init__.py` | `_ascii_peer_slug()` peer_id slug 化 + user/assistant fallback 链（§7.3） | inline |
| `hermes_cli/write_approval_commands.py` | i18n 中文文案 `t()` 替换（13 处） | inline（字符串） |
| `gateway/relay/adapter.py` | i18n 中文文案 `t()` 替换（8 处） | inline（字符串） |
| `agent/context_breakdown.py` | usage breakdown 分类标签本地化（`_localized_category_label`，优先 `gateway.usage.breakdown_cat_*` 与 `/usage` 共享键，回退 payload 标签） | inline（字符串）+ 薄委托 |
| `agent/conversation_compression.py` | 压缩完成状态行 i18n（`get_compaction_done_status`，运行期发射用） | inline（字符串） |
| `ui-tui/src/components/appChrome.tsx` | owner spinner/主题接线（`owner/spinner.js` 动态 faces + 最宽字形测量缓存）、无选区 Cmd+C 回落终端原生复制 | inline + 薄胶水 |
| `ui-tui/src/gatewayClient.ts` | graceful shutdown（`GRACEFUL_GATEWAY_EXIT_TIMEOUT_MS` 20s、`gracefulShutdownPromise` 去重） | inline |
| `tools/computer_use/backend.py` | 可选 typed-browser 适配器钩子（`@staticmethod` 探测，缺依赖则退化）+ i18n | inline（钩子）+ 字符串 |
| `tui_gateway/entry.py` | 退出前显式跑 `_shutdown_runtime`（session-end 事件 / 持久化 / 异步服务 flush，不依赖 atexit 时序） | 薄胶水 |
| `tui_gateway/methods_tools.py` | hardline / dangerous 判定描述本地化（委托 `tools.approval._translate_pattern_description`） | 薄委托 |

| `hermes_cli/models.py` | 静态模型目录 + owner providers 豁免（**41 处** `[owner]` 标记） | inline（数据表） |
| `agent/display.py` | per-chat display 覆盖 + i18n（20 处标记；含 3 处落在多行字符串内、1 处仅删除改动） | inline（字符串）+ 薄胶水 |
| `tools/feishu_drive_tool.py` | fallback client + 共享 `_do_request`（15 处标记；含 2 处仅删除改动） | 薄胶水 |
| `tools/file_tools.py` | 写入护栏文案：英文原文回归代码 + `_localized()` 渲染 + 漂移守卫（§16.9；12 处标记） | inline（字符串）+ 局部渲染助手 |
| `model_tools.py` | 向 hook 插件暴露稳定 per-chat key / agent platform / agent chat_id，并透传到 `post_tool_call` 与卡片桥回落路径（10 处标记） | 列扩展 |
| `ui-tui/src/theme.ts` | owner 主题扩展（10 处 `[owner]` 标记） | inline（数据表） |
| `plugins/model-providers/kimi-coding/__init__.py` | Kimi thinking 回显 + vision（8 处标记；含 1 处落在多行字符串内） | inline |
| `hermes_cli/providers.py` | provider 解析：`opencode-go` 补 `OPENCODE_GO_API_KEY`；`_LABEL_OVERRIDES` 加 `kimi-coding` / `kimi-coding-cn`；`get_label` 先查覆盖表再 normalize（4 处标记） | inline |
| `plugins/model-providers/xiaomi/__init__.py` | `XiaomiProfile` 子类（4 处标记） | inline |
| `agent/turn_finalizer.py` | `transform_llm_output` 记账初始化移到循环外 + 实时 transcript tail 同步（3 处标记，接 output_guard §14） | 薄胶水 |
| `agent/prompt_builder.py` | skills-visibility 缓存值为 `(manifest, prompt)`、LRU 命中要对照磁盘重校验、manifest 随缓存持久化（3 处标记） | inline（缓存） |
| `hermes_cli/send_cmd.py` | 输出 `message_id`（§7.21，3 处标记） | inline（字符串） |
| `hermes_cli/auth.py` | `api_key_prefixes` 非空时只认 env 来源键；只接受 Copilot 兼容 token 前缀；Coding Plan `sk-sp` 前缀与其它区分（3 处标记） | inline（安全校验） |

### B.3 轻度侵入（import 编排 / 单行，sync 冲突小）

| 文件 | 侵入内容 | 侵入类型 |
|------|----------|----------|
| `agent/anthropic_adapter.py` | MiniMax thinking-block 解析 | inline |
| `agent/credential_pool.py` | base_url override 钩子 | 薄胶水 |
| `agent/agent_runtime_helpers.py` | `_auth_pool_refresh_counts` defensive getter + file timeout | 薄胶水 |
| `agent/codex_runtime.py` | owner_provider_name 透传 | 薄胶水 |
| `gateway/display_config.py` / `gateway/slash_commands.py` | per-chat display source 透传 + i18n；`/new` 时 invalidate patch 配置缓存（§1.2）。**§16.16 另补上游符号**：`resolve_tool_progress`（含 per-chat 层）、`_configured_display_value`（含 per-chat 层），并把 owner 钩子的惰性 import + 优雅降级收敛成单点 `_owner_display_hooks()`（避免 fallback 在两个调用点之间漂移） | 薄胶水 |
| `agent/verification_stop.py` | 创意/视觉扩展名 suppress verify-on-stop（§8.4） | inline（allowlist） |
| `agent/models_dev.py` | models.dev 缓存 TTL 24h（§2.11）+ fetch 超时 5s | inline |
| `gateway/session_context.py` | cron session 隔离接线 | 薄胶水 |
| `tools/feishu_client_utils.py` / `tools/feishu_doc_tool.py` | `om_` 消息 ID 支持 + `offset`/`mf_limit` 分页读取合并转发（§4.15）；docx 内嵌 bitable 块读取（§4.13）；**对官方私有符号 `plugins.platforms.feishu.adapter._render_merge_forward_entries` 的依赖改为可降级**（§16.13：裸导入在 HEAD `:1593`，现包进 `try:`，降级走本函数既有的 `(None, msg)` 失败形态）；**请求管线并入上游 `tools/feishu_lark`**（§16.15：头部与上游逐字节相同、删 `set_client`/`get_client`/`_check_feishu` 三处重复实现、扩展块挪进 handler 体内；doc_tool 冲突块 6 → 4） | 薄胶水 |
| `tools/feishu_drive_tool.py` | fallback client + 共享 `do_request`（§16.15：头部对齐上游、删 `set_client`/`get_client`/`_check_feishu` 三处重复实现、`[owner]` 标记 15 → 9 且缩进逃逸 9 → 0；冲突块 7 → 5，余下 4 块属 **T2-20**） | 薄胶水 |
| `tools/feishu_lark.py` | **新增**，与上游 `6723628de9` 逐字相同（§16.15：预置上游共享管线，merge 侧零冲突；官方树新增文件的落点例外见 §16.15） | 上游同文（零合并债） |
| `pyproject.toml` / `uv.lock` | 新增 `ldap3==2.9.1`（exact-pin + uv lock 重生成，§15.2） | 依赖声明 |
| `plugins/platforms/discord/adapter.py` | clarify button `get_choice_display` | 薄胶水 |
| `plugins/platforms/telegram/adapter.py` | （sender 签名相关） | 薄胶水 |
| `cli.py` | owner_provider_name 透传 + chained quick command；冷启动先打印 `Starting Hermes…` 并完成插件发现（§7.20） | 薄胶水 |
| `hermes_cli/oneshot.py` | extra_body 透传 | 薄胶水 |
| `agent/usage_pricing.py` | attribution helper for billing | 薄胶水 |
| `agent/background_review.py` | 多行 bullet 格式 | inline（字符串） |
| `tools/code_execution_tool.py` / `tools/delegate_tool.py` | extra_body 透传 | 薄胶水 |
| `run_agent.py` | `_execute_tool_calls` 前 `maybe_audit_batch`（§3.9 semantic audit） | 薄胶水（fail-open） |
| `agent/codex_responses_adapter.py` | reasoning 后跳过/占位空 content（§7.15 方舟严格网关） | inline |
| `cli.py` / `hermes_cli/main.py` / TUI | Ctrl+C → `app.exit` / gateway drain via stdin EOF（§6.3） | inline |
| `cron/lifecycle_guard.py` / `tools/terminal_tool.py` | 二进制路径不当脚本扫（NUL → 空文本、fallback 跳过、`ValueError` 吞掉；§7.19） | inline |
| `hermes_cli/approvals_suggest.py` | 拦截判定与 SQL 预过滤锚点委托 `owner/approval/approval_history_policy.py`（§3.13）；英文 marker 表降级为 fail-open 兜底 | 薄委托 |
| `agent/image_gen_provider.py` | 仅允许 `http`/`https` 取图，其余 scheme（`file://`/`ftp://`/`gopher://`…）在网络与磁盘访问**之前**拒绝，防上游/调用方控制的 URL 被诱导读本地 | inline（安全校验） |
| `agent/message_sanitization.py` | 中断占位文案 i18n（`gateway.interrupt.placeholder`） | inline（字符串） |
| `agent/turn_context.py` | stale connections 等运行期状态 i18n | inline（字符串） |
| `acp_adapter/server.py` | steer 失败文案 i18n（`gateway.steer_failed`） | inline（字符串） |
| `gateway/platforms/whatsapp_cloud.py` | 审批卡标题 / 理由文案 i18n | inline（字符串） |
| `gateway/platforms/yuanbao.py` | cron 投递包装剥离（委托 `strip_cron_delivery_wrapper`） | 薄胶水 |
| `gateway/session_stall.py` | 会话停滞提示 i18n | inline（字符串） |
| `plugins/platforms/matrix/adapter.py` | 附件失败提示 i18n | inline（字符串） |
| `plugins/platforms/slack/adapter.py` | 图片 / 视频附件失败提示 i18n（分类型键） | inline（字符串） |
| `tools/computer_use/tool.py` | 危险输入 / 破坏性快捷键拦截提示 i18n | inline（字符串） |
| `tools/discord_tool.py` | pin / unpin 结果文案 i18n | inline（字符串） |
| `tools/mcp_tool.py` | `_watch_children` 协程判定修正（`inspect.iscoroutinefunction`） | inline |
| `tools/process_registry.py` | watch 禁用提示 i18n | inline（字符串） |
| `tools/session_search_tool.py` | browse hint / 无匹配文案 i18n | inline（字符串） |
| `tools/skill_manager_tool.py` | skill 创建 / 全量重写结果文案 i18n | inline（字符串） |
| `tools/website_policy.py` | 站点策略拦截提示 i18n | inline（字符串） |
| `hermes_cli/approvals_test.py` | 规则描述可读化（委托 `_translate_pattern_description`；JSON 载荷刻意保留英文原文，仅本地化人读渲染） | 薄委托 |
| `hermes_cli/config.py` | 模型 / provider / custom-endpoint 写入时失效 24h 目录缓存（P2-9）；其他 key 不动缓存 | 薄胶水 |
| `hermes_cli/credential_lifecycle.py` | 凭据变更时清 provider models 缓存 | 薄胶水 |
| `hermes_state_common.py` | 共享 DDL 加 `owner_provider_name` 列（与 §10.1 归因链配套） | inline 列扩展 |
| `apps/desktop/electron/main.ts` | 窗口半透明：`opacityForIntensity` 平台感知曲线（§13.1） | 薄胶水 |
| `ui-tui/src/app/createGatewayEventHandler.ts` | skin `help_header` / `spinner` 字段透传 | 薄胶水 |
| `ui-tui/src/app/useInputHandlers.ts` | macOS 无选区 Cmd+C 返回 false，回落终端原生复制 | inline |
| `ui-tui/src/lib/gracefulExit.ts` / `ui-tui/src/entry.tsx` / `ui-tui/src/__tests__/gracefulExit.test.ts` | graceful exit（§6.3）：信号退出码表、cleanup 链、failsafe 25s、gateway drain | inline（含测试） |

| `agent/error_classifier.py` | 429 硬配额耗尽（如 opencode-go「Weekly usage limit reached. Resets in 2 days.」）归类为不可重试 billing，不再空等 600s × 3 次（§7.9） | inline |
| `gateway/config.py` | `send_only` 子容器：`connection_mode` 走 `setdefault`、不覆盖 config.yaml（确立 config.yaml > env 的优先级） | inline |
| `gateway/platforms/qqbot/keyboards.py` | 审批键盘文案 i18n + approval_explainer 命令解说段（理由行之后、空串跳过；4 处标记） | 薄胶水 |
| `tools/clarify_gateway.py` | clarify choice display 助手 + 归一化 `{"display","key"}` dict 直传适配器 + 飞书 clarify 竞态防御（4 处标记） | 薄胶水 |
| `.gitignore` | `owner/examples/**` 反 allowlist（豁免 `examples/` 通配）+ 本机编辑器/agent 设置与 `state.db`、`owner/*/samples/` 等忽略项（5 处标记；含 1 处仅删除改动） | 忽略规则 |
| `hermes_cli/commands.py` | `GATEWAY_KNOWN_COMMANDS` 加 `/memory` `/skills`（2 处标记，落在多行字符串内） | inline（数据表） |
| `hermes_cli/gateway.py` | restart watcher 清理 `__pycache__`（1 处标记，落在 112 行 respawn 脚本模板内） | inline（字符串） |
| `hermes_cli/tips.py` | `get_random_tip` 按 `agent.i18n.get_language()` 走 `owner/tips_zh.py` 中文语料、失败回落英文；停用已删除功能的 tip（2 处标记） | 薄胶水 |
| `locales/en.yaml` / `locales/zh.yaml` | approval_explainer 审批卡命令解说段键（各 2 处标记）；**删除被 YAML 静默丢弃的重复键 `approval.hardline_blocked`**（§16.12：修复前 zh 34/55、en 44/65，两处值逐字相同 ⇒ **编辑第一处是静默无操作**；来源是 `e93f3148e7` 加在块消息段、`92e0787ea6` 新建块结果段时又加一次；保留块结果段那一处，消费方 `tools/approval.py::_hardline_block_result`）。现状口径：17 本 catalog **无重复键**；owner-only 键路径 1427、与上游共有键 412（其中 zh 45 / en 19 个取值与上游不同，属 T2-12 家族）。审查 T2-15 那条「收拢到 `approval:` 块尾」的修法经实测**零收益**（`approval` 早已是连续尾部块；换到真有交错的 `gateway` 上量，冲突块仍 1→1 / 0→0），按「不纳入」处置 | 目录（数据） |
| `ui-tui/src/app/createSlashHandler.ts` / `ui-tui/src/lib/rpc.ts` / `ui-tui/src/gatewayTypes.ts` | chained quick command：分发 + RPC + 类型声明（`gatewayTypes.ts` 的改动落在多行字符串内） | 薄胶水 |
| `ui-tui/src/app/useMainApp.ts` | graceful shutdown（§6.3；含 2 处仅删除改动） | inline |
| `ui-tui/src/components/branding.tsx` | branding 渲染：`t.brand.icon` + `t.brand.tagline`（1 处标记，JSX children 用 `{/* ... */}`） | inline |

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
| `gateway/platforms/api_server.py` | 重度 | ❌ 未单项评估 | **待评估**：本批新增侵入量最大的文件（identity middleware + LDAP gate + 媒体端点 + 路由注册 + capabilities 广告 + 流式事件字段）。评估问题：identity middleware 与 LDAP gate 是否可迁入 owner-extensions plugin，或至少收敛为 `owner/gateway/` 内的单一委托入口 |
| 轻度侵入全部（13 文件）| 轻度 | ❌ 未单项评估 | 无需评估：均为 1-3 行 import / 透传 / 字符串，迁移收益为零 |

**结论**：附录 B 列出的侵入文件中，附录 C 单独评估了主线项；剩余文件要么被间接覆盖（归因链、extra_body、clarify 等已归入对应章节），要么是 1-3 行薄胶水 / 字符串 / 平台适配器内部逻辑，迁移收益为零，无需单独评估。**唯一遗留未决项是 `gateway/platforms/api_server.py`** —— 它从轻度侵入升为重度的过程中没有伴随过迁移评估，已作为附录 C 第 11 项登记待评。

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
9. **cron job args / owner/scripts allowlist** — **已评估（2026-07-03）：部分可迁移，人工决定维持现状。** args 链（4 处 `[owner]`）可迁移但收益低（需 monkey-patch 3 个 core 函数：`cronjob`、`create_job`、`_run_job_script`，跨 tool 期/存储期/执行期 3 个生命周期；且 args 是通用功能更应提 upstream）；allowlist（2 处副本）不可迁移（cron 运行时零 hook——`invoke_hook` 在 scheduler/jobs 出现 0 次——加上安全边界 WR-03）。评估发现 CR-002 修复遗漏了 scheduler 副本 2（`scheduler.py:1556`，process-lifetime cache 永不刷新），已修复为 mtime re-scan 与副本 1 一致。评估报告：`/tmp/zcode-cron-args-eval-result.md`（291 行，每条结论附行号引用）。
10. **chained quick command（;;）** — 4 处 Python + 3 处 TS inline，是全平台语法增强，不适合 hook 化，建议保持。
11. **`gateway/platforms/api_server.py`** — **待评估。** 该文件的 owner 侵入在 §15/§16 落地后已从轻度升为重度（identity routing 中间件、LDAP bind 认证门、转发头剥离 + SSE 透传、两个新增只读端点、路由注册与 capabilities 广告、`ApiMediaStore` 接线、流式事件字段扩展）。评估问题：identity 中间件与 LDAP gate 是否可迁入 `owner-extensions` plugin（`pre_gateway_dispatch` 类钩子能否覆盖中间件时机），或至少把转发路径收敛为 `owner/gateway/` 内的单一委托入口，避免每次 merge 都要逐行解冲中间件内部逻辑。注意 `owner/gateway/ldap_auth.py` 与 `owner/feishu/profile_routing.py` 本身已在 owner/ 内，可迁移的只是接线与转发骨架。

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

### 2026-09-30：新增 §16.16 采纳上游 `run.py` 拆包，定制重落完毕（T2-20）

- **新建正文**：**§16.16**（23 个 `gateway/run_*.py` 结构落地；7 处 import-time 符号 + 5 个 import-time 模块 + `FailoverReason` 5 成员；`gateway/run_turn.py` 重落 25 处标记；`gateway/display_config.py` 补 `resolve_tool_progress` / `_configured_display_value` / `_owner_display_hooks`）。本清单 §16.16 正文 + §0.2 导航行 + 附录 B（新增 `gateway/run_*.py` 行、修订 `gateway/run.py` 与 `gateway/display_config.py` 两行）+ 本条
- **类型**：结构性采纳上游拆包 + 薄胶水重落；**正常路径零行为变更**（per-chat 解析逐点仍传 `source`，与 monolith 一致）
- **决策**（用户，2026-09-29）：**收窄为「按符号补齐」** —— 23 个上游模块整取，55 个依赖文件**一律不替换**，只把缺的符号移植进来。理由：真实 `git merge upstream/main` 的冲突面是 **117 文件 / 544 块 / ours 侧 124,755 行**，`run.py` 虽是第 1 名却**只占 20.0% 行、5.9% 块** —— 上游做的是全仓规模的模块化，单项治理的收益上限就是五分之一
- **口径决策**：per-chat 解析**逐点传 `source=`**，不收敛成 `functools.partial` 单点注入。后者标记更少、合并面更小，但会让 8 处站点共用 1 条标记 ⇒ 机检仪器对这 8 处**失明**，还须新增 `allow_drop` 假造塌缩。取舍 = **仪器灵敏度优先**。最终**未新增任何 `allow_drop`**
- **移植约定（本条确立）**：**前向移植的上游代码逐字复制、不加 `[owner]` 标记**（判据：merge 那一刻该以谁的一侧为准）；我方自己的定制必须标记
- **惰性闭包提前咬到一次**：上游 `run_turn.py` 运行期要 `display_config.resolve_tool_progress`，而该依赖文件里**没有**这个符号 —— 它属**惰性**闭包、非 import-time 依赖 ⇒ 「23/23 可 import」的检查**看不见它**，走到即 `ImportError`。按既定路线只补符号，并为展示阈值量纲给 `_HygienePlan` 增补 `context_length`。**等价性实测非抽样：`resolve_display_setting` 720 组比较 0 差异**
- **两处「正当塌缩」**（上游把我方重复定制收敛成单一 choke point，标记数合法下降，登记 `allow_drop`）：`cron-env-leak` → `GatewayShutdownMixin._restart_watcher_env()`（`run_shutdown.py:1348`）；`fence-safe` → `_progress_absorb`（`run_turn_runner.py`）
- **四处「不能机械套模板」的判定**：`_clear_planned_restart_notification` 上游已删但其标记**实为模块级代码**（AST 复核）⇒ run.py 原地；`track_agent` 上游改名 `_run_agent_track_agent` ⇒ 按新名落笔；`_interim_assistant_cb` 实测**不是定制** ⇒ 采纳上游；`_bg_session_key` 只作用于背景任务路径 ⇒ 主回合 `ctx.session_key` 不受影响
- **四处「run.py 原地」**（不迁移，换码收尾补回新 `run.py`）：CR-004 白名单（模块级）、BOS/EOS 清洗（`_sanitize_gateway_final_response` 内）、`_resolve_gateway_display_bool` 的 `chat_id` 文档行、cron-env-leak 的模块级环境清洗
- **验证**：机检 `verify` **PASS**（43 种标记文本全部未下降；全仓总数 869 ≥ 下限 54）、`ruler` **缺口归零**（39 已落位 + 4 原地登记 = 43）；定向 9 个测试文件 **9 failed / 221 passed**，9 项与基线**同一批**（`test_error_classifier` 的 429 归类，属 T2-21）⇒ **零新增失败**；`tests/gateway/test_display_config.py` 单跑 **23 passed**；**23/23** 个 `run_*.py` 可 import、`import gateway.run` 正常。**未跑全量**
- **仪器两次加固 + 一次扩展**：① 记录口径由整行改为「从 `# [owner]` 起的部分」（行内标记的接收者改名是**正当改写**，用整行做身份会误报 16 处；裸标记回退整行以防假阴性）；② 新增 `run_py_inplace.json` 分类报告（原地项不登记则永远留在待落清单，计数器无法收敛，真实缺口被已知项淹没）
- **Commit**：`fcae2029a0`（结构）→ `21f32d86d6`（import-time 闭包）→ `ab969baa80`（`display_config` 符号）→ `58be2cbe98`（`run_turn.py` 重落）
- **换码就绪性复核（2026-09-30，追加）**：本条「`ruler` 缺口归零」的**适用边界**被复核推翻 —— 该口径只数**标记文本**，对**换码**这一步不充分。实测：我方 `run.py` 相对 merge-base 的改动是 **+906 −475 / 240 个 hunk**（`[owner]` 只覆盖其中 56 行；**i18n `t(` 163 行完全无标记**，三方交叉验证 BASE 10 → 本地 172/159 键 → 上游 24 文件族 8）；行级核对**未覆盖 385 行**（i18n 133 / 代码 200 / 注释 46 / 标记 6），叠加「符号存续」判据后**换码后消失的符号所含未覆盖行 = 140**；**9 处生产惰性导入**指向**上游 `run.py` 没有**的符号（`_gateway_lifecycle_msg`、`_classify_edit_failure`、`_is_executor_shutdown_error`、`_append_dedup_counter`、`_load_gateway_runtime_config`；上游可用名 = 顶层 371 + 惰性再导出 41 = 412）⇒ **换码即 `ImportError`**。**判定：本条的重落是"调用点搬迁"而非"定义搬迁"；换码尚未就绪。** 独立交付物 `T2-20-换码暴露面与就绪性实测.md` + `T2-20-换码暴露面清单.tsv`；§16.16 标题与正文已按实测更正；处置选项（A′ / A / B / C / D）**待用户决策**
- **未纳入**：惰性闭包全量补齐（230 模块 / 142 符号，留到换码后按实际暴露路径驱动）；同批其余 116 个冲突文件（`run.py` 只占 20.0% 行）；`owner/docs/run-py-owner-mapping.md` 的逐模块计数差与「per-chat 簇收敛进 `owner/`」建议（需按本轮实测重写对齐）
- **顺带发现（P2）**：`_resolve_gateway_display_bool(..., chat_id=)` 的 `chat_id` **无任何生产调用方** —— 保守移植但应纳入「无使用者 owner 面」清理判定（激活或删除）

### 2026-09-29：新增 §16.15 飞书三件套管线并入上游 `feishu_lark`（T2-18）

- **新建正文**：**§16.15**（`tools/feishu_lark.py` 预置为上游逐字同文；`tools/feishu_doc_tool.py` / `tools/feishu_drive_tool.py` 头部换成上游形态并删 5 处重复实现（2× `set_client`/`get_client`、2× `_check_feishu`、`_do_request` 残影）；`tools/feishu_client_utils.py` 的 `do_request` 改走共享 `build_request` + `response_data` 并保留方法守卫与非文本响应体兜底；drive_tool 标记 15 → 9、缩进逃逸 9 → 0）。本清单 §16.15 正文 + §0.2 导航行 + 附录 B 三行 + 本条
- **类型**：合并面收敛 + 缺陷修复（标记形式缺陷、无对应改动的标记、装饰性分隔线）；**正常路径零行为变更**
- **决策**（用户）：方向 = **对齐上游 `feishu_lark`**（不采纳审计的「迁入 `owner/tools/`」）
- **口径校正**：① 报告写 1,596 行，实测 **1,621 行**；② 「MOD=0」属实但**被审文件不是风险所在** —— 上游 `6723628de9`（2026-09-02）另建 `tools/feishu_lark.py` 抽走 7 个符号，我方自建模块重实现同一套管线；真正的冲突面在两个官方兄弟：doc_tool **6 块 / 143 行**、drive_tool **7 块 / 249 行**（合计 **13 块 / 392 行**）
- **审计修法逐条量掉（零收益）**：口径 = `git merge-file -p --diff3` 的冲突块数（与 `git merge-tree` 独立判定互校）。对照 **13 块 / 392 行**；修法（迁入 `owner/tools/`，官方文件 import 路径随之改）**13 块 / 392 行** —— **第四例「缩块不消块」**，且首次证明**换路径也不改块数**
- **相撞分两类**：**管线重复类**（文件头的 `import`/`logger`/`_local`/`set_client`/`get_client`/`_check_feishu`，上游删、我方也删但换成自建模块的 import）⇒ **已清零**；**能力类**（env-fallback client、wiki 解析、bitable/sheet 读取、docx 图片物化 + vision OCR、`om_` 合并转发分页；drive 的 4 个显式 handler 与上游 `_comment_op` 正面相撞）⇒ **9 块全在此类**
- **等价性缺口（实测，「直接替换」不可行）**：上游 `raw_body` 只兜 `JSONDecodeError`/`AttributeError`，而媒体下载返回**二进制 PNG** ⇒ `UnicodeDecodeError` 穿出 ⇒ 照「删 60 行内联、直接调 `lark_call`」执行会**当场坏掉** `read_docx_with_images` 的 2 个用例。落盘改法 = 共享管线 + 只在非文本体上兜一层 + 保留 `GET`/`POST` 严格拒绝
- **结果**：冲突块 **13 → 9**（doc_tool 6 → 4、drive_tool 7 → 5；drive 下限为 5，余下 4 块是 `_comment_op` 相撞，属 T2-20）、我方侧行 **392 → 330**、两文件 **694 → 621** 行、新增 `tools/feishu_lark.py` 86 行（与上游逐字相同）
- **验证**：定向 **基线 199 → 202 passed / 6 failed**（Δ+3 = 3 个新用例；6 个失败与基线**逐节点相同**，全在 `tests/gateway/test_feishu.py`，为存量 ⇒ **本次引入 0 新失败**）；**变异 8 例 / 6 咬住 + 2 如实记缺**（`_typed_data` 恒 `{}`、`_check_feishu` 恒 `True` 无用例覆盖）；**仪器口径修正** —— 只数 `(\d+) failed` 会把模块级 `NameError` 的 `1 error` 读成 0 失败、把正确咬住的变异体误判 MISS，改为 `failed + error` 并加退出码兜底；爆炸半径 **135 路径 / 两腿同 30 failed / NEW 0 GONE 0 / Δ+3（3 个新用例）**，语料自证「收集到 518 个 feishu 节点」；健康检查 **7 passed / 1 warning**（Check 8 116/116、Check 6 28/28、Check 7 140/140；Check 4 标记 667 → 662）
- **未纳入**：审计修法「迁入 `owner/tools/`」（零块收益，登记为「官方目录新增文件」第 2 例，与 T2-16 `api_server_media.py` 一并决策）；`do_request` 直接替换（不可行）；drive_tool 剩余 5 块（属 **T2-20**）；`_RAW_CONTENT_URI` 成为无使用者常量（清理需 +1 块）；Check 8 对**新增**文件的盲区（第 5 例）；`tests/gateway/test_feishu.py` 的 6 个存量失败

### 2026-09-29：新增 §16.14 `delivery_ledger` 合并面收敛（T2-17）

- **新建正文**：**§16.14**（`gateway/delivery_ledger.py`：删我方注释噪声、`[owner]` 标记去重 10 → 3 并消除 6 处缩进逃逸、建列腿改用既有共享原语 `hermes_cli.sqlite_util.add_column_if_missing`、`_update_state` 逐字节还原基点并把戳记内联进 `mark_delivered`、删零生产调用者的 `recovered_reply_marker()` 及其 2 个纯单测）。本清单 §16.14 正文 + §0.2 导航行 + 附录 B `gateway/delivery_ledger.py` 行 + 本条
- **类型**：合并面收敛 + 缺陷修复（标记形式缺陷、零调用者死函数）；**正常路径零行为变更**（唯一差异是戳记走两条语句：先改状态、后补 id —— 崩溃窗口只丢可追溯 id，不会造成重复发送）
- **决策**（2026-09-29 用户）：修法方向 = **C1′ 最小冲突面**（4 块 → 1）；`recovered_reply_marker()` 处置 = **删掉**
- **口径校正（位置、标记数、修法三条）**：① 行号位移 —— 审查 `138/320/365`，实测我方 HEAD 为 `:140`/`:326`/`:372`；② 「零 `[owner]` 标记」是审查当时的旧数，现为 **10 处**（2026-09-28 `a77e345342` 随 T2-11 补上），但 10 处**文本逐字相同**且 **6 处缩进逃逸**，本身即是缺陷；③ **修法①要我们自建一个基点就已存在的原语** —— `hermes_cli/sqlite_util.py` 在基点 `00b2e03c80` 就含 `add_column_if_missing` / `write_txn`（`kanban_db.py:92` 一直在用），且**上游 `576accd92b` 对该文件采用的正是该形态**（`upstream/main` 的 `delivery_ledger.py:25` 即该 import），与 T2-16 修法①同型
- **审计两条修法逐条量掉（零收益）**：口径 = `git merge-file -p --diff3` 的冲突块数（与 `git merge-tree` 独立判定互校）。对照 **4 块 / 我方侧 123 行**；修法①（schema 抽 `owner/gateway/ledger_schema.py`）**4 块 / 89 行**；修法②（`mark_delivered` 改 `**kwargs`）**4 块**。两条只买到「我方侧行数」一个指标 —— **第三例「缩块不消块」**（前两例 §16.11、§16.12）
- **撑起冲突面的四件事与处置**：块 1（`RECOVERED_MARKER` 上方我方插的 3 行，上游同段也润色过）⇒ 清噪声消除；块 2（`apply_wal_with_fallback` 后的顶格标记，上游已把该函数头两行删掉）⇒ 去重消除；块 3（`_initialize_schema` 列对账，上游整体重写 + 我们必须在该函数建列）⇒ **消不掉**，已写下双重理由；块 4（`_update_state` 双方都改 + `mark_delivered` 紧邻并成一个基线区域）⇒ 还原基点 + 戳记内联消除。**落点阶梯**：4 → S1 清噪声 2 → S2 还原 `_update_state` 1 → S3 换共享原语 1（S3 不减块，买的是行数与「与上游同向」）
- **被否证 / 被刻意否掉的两条思路**：① 「挪落点」—— 上游**连 `_connect()` 都重写了**，把钩子挪进去实测 3 块 → 3 块但**新造一块**；② 「挪进 `record_obligation`」能到 **0 块**但 `debug_rows()` 无条件 `SELECT` 该列 ⇒ 先开库后建列会在读路径报 `no such column`。**列必须建库时就存在。**
- **结果**：冲突块 **4 → 1**、我方侧行 **123 → 49**、文件 **661 → 613**；相对基点我方足迹 **12 hunk/+119−20 → 9 hunk/+64−13**；**零新耦合**
- **验证**：定向 **75 passed**；**变异 7/8 咬住**（未咬住那 1 个是**正确预期**：DDL 里拿掉该列后 ALTER 腿在新建库上同样补上 ⇒ 运行时等价；首轮该变异体留下悬空逗号 ⇒ 非法 DDL ⇒ 39 个失败被误读成咬住，属**变异体不合格**）；爆炸半径 **138 路径 / 两腿同 30 failed / NEW 0 GONE 0 / Δ+1**（本轮修掉一处**语料缺口**：`tests/gateway/test_restart_notification.py` 原先不在语料里，B 腿对它的还原是空操作 ⇒ 已补入并加**自证断言**）；健康检查 **7 passed / 1 warning**（Check 8 116/116、Check 6 28/28、Check 7 140/140；Check 4 标记 674 → 667）
- **未纳入**：审计修法①②（零收益/降签名可读性）；hunk 级标记缺口（`CREATE TABLE` 的 DDL hunk 不再有紧邻标记 —— 补回去实测 1 块 → 2 块，归 **T2-11b**）；`mark_delivered` 搬入 `owner/`（语义决策已由 2 例钉住，登记不展开）

### 2026-09-29：新增 §16.13 官方私有符号依赖改为可降级 + 可观测（T2-16 + 同类普查）

- **新建正文**：**§16.13**（`gateway/platforms/api_server_media.py` 的裸私有导入改为按名字运行时解析、可降级、warn 一次；同类普查另 5 处一并处置、1 处登记为刻意 fail-loud；新建 `tests/owner/test_upstream_private_symbol_deps.py` 29 例）。本清单 §16.13 正文 + §0.2 导航行 + 附录 A `api_server_media.py` 行 + 附录 B `tools/feishu_client_utils.py` 行 + 本条
- **类型**：缺陷修复（私有符号依赖可降级 + 静默降级改可观测）；**正常路径零行为变更**
- **决策**（2026-09-29 用户）：修法方向 = **可观测降级 + 命名守卫**，**不复制实现**；同类普查发现的另外 5 处**一并改成可降级调用**（含把原本「静默降级」的 4 处改为 warn 一次）
- **口径校正（审查给的位置、量、修法三条）**：① 符号行号三处都不对 —— 实测**我方 `:1547` / 上游 `:873` / 基点 `:1165`**，审查说的 `:1272` 不存在于任何一版；② 「~25 行」实测是**函数本体 51 行**（+1 行 `_MEDIA_IMG_EXT`），且我方该函数与基点**逐字相同**（从未改过）；③ **修法①「复制实现」实测有害** —— 上游已两次重写该函数（`581d97e545` 2026-09-02 重写 docstring + 重构 `_to_data_url`；**`13f908f10d` 2026-09-14 修 `#111046` 尾部 `<|eos|>` 哨兵，属行为变更**），复制 = 把旧于 `#111046` 的语义永久冻结进我们的树 ⇒ **整条按「不纳入」处置**，审查的字面验收（`grep … import _` 为空）**有意不满足**。
- **审查没看到的四点**：① 失败模型**不是静默的**（原形态在 `finalize_api_media` 首条语句无条件导入，owner 新增的 `tests/gateway/test_api_server_media_files.py` 会直接 ERROR）；② **降级路径本来就可用**（不内联 → `extract_media` → `store.register` → 可下载附件；内联是装饰性而非功能性）；③ **普查比 grep 大** —— AST 得 **154 目标 / 9 文件 / 14 条符号引用 / 2 条裸导入**，审查的 grep 只找到 5（漏因：多行 `import (` 不匹配、前缀白名单漏 `hermes_cli` 与 `plugins`）；④ 反向 import 生产代码**唯一**调用点 `api_server.py:155-161`（5 个名字），但属 §2.3 可移除性问题，另立条目。
- **验证**：守卫 **29 passed**；定向套件 286 passed；媒体三件套 45 passed；8 个改动模块 `importlib` 全通过；**变异 12/12 咬住**；爆炸半径回归 **137 路径**（T2-14 的 134 + `test_i18n.py` + `test_locale_catalog_integrity.py` + 本守卫）**NEW 0 / GONE 0**，leg A 2645 passed / leg B 2616 passed（差 **29** = 本守卫整文件）；健康检查 **7 passed / 1 warning**（与 T2-15 后一致）。
- **变异装置两处首轮不合格，已修（记录在案）**：① 两个变异体只切了 `try:` / `logger.warning(` 一行，留下悬空 handler 体 / 字符串参数 ⇒ `SyntaxError` ⇒ 判 `INVALID`（锚点必须扩成整块正文）；② `test_finalize_api_media_degrades_when_the_resolver_is_gone` 的输入**不含 `MEDIA:`**，而该函数在无标签时提前返回 ⇒ 用例**绿得毫无意义**，两个变异体逃逸 —— 这是**测试的缺口**，改成真实输入后才咬住。
- **遗留登记（不展开）**：审查修法②「整体迁 `owner/gateway/`」（属 §2.3）；add/add 同路径风险（上游 `gateway/platforms/` 下**无** `api_server_media.py`，但其 6 个 `api_server_*` 文件 + `api_server.py` **195 次提交 / 3 月** 说明仍在系统拆分）；**Check 8 不覆盖 owner 在官方树内「新增」的文件**（口径是「被修改的」官方文件；`api_server_media.py` 在本次之前零 `[owner]` 标记）。

### 2026-09-29：新增 §16.12 `locales` 删掉被静默丢弃的重复键（T2-15）

- **新建正文**：**§16.12**：`cc8e245a1a`（`locales/{zh,en}.yaml` 各删掉 `approval.hardline_blocked` 的**第一处**重复定义、原位留说明注释；新建 `tests/owner/test_locale_catalog_integrity.py` 20 例）。本清单 §16.12 正文 + §0.2 导航行 + 附录 B 行 + 本条）
- **类型**：缺陷修复（删除被 YAML 静默丢弃的重复定义）+ 数据文件注释；**零行为变更**（改动前后 `yaml.safe_load` 取到的值逐字相同）
- **口径校正（审查给的位置、量、修法三者都不成立）**：审查说 owner 新增键「分散成两簇、插在上游活跃区间内」（引 `zh.yaml:36-69` / `:560-606`；上游 28 次/3 月），修法是「收拢到 `approval:` 块尾（~120 行移动）」。实测（`yaml.compose()` node 树，行号一律取**我方文件**行号）：① `approval` 段共有键 17 个占 4–20 行、owner-only 键 516 个，**区间内 owner 键 0 个、首个 owner 键之后再无共有键 0 个** ⇒ **它本来就是连续的尾部块，修法即现状**；② 真交错在 `gateway`（owner-only 条目 398 个，**388 个**落在共有键区间 609–1519 内），其余 8 个顶层块一个共有键都没有；③ 「~120 行」实际是 **1427 个 owner-only 键路径**（共有键 412）；④ 上游活跃度实测 **33 次/3 月**（审查说 28），且上游维护**同一套 17 本 catalog**。
- **修法被实测否掉**：把 `gateway` 下 398 个 owner-only 条目整块搬到映射末尾（语义等价已断言），冲突块 **1 → 1 / 0 → 0**（仪器 `git merge-file -p`，先用未改动字节与 `git merge-tree` 对账）。那唯一一个冲突块由 `gateway.status` **共有键的取值分叉**造成（我方 6 行中文 vs 上游 7 行英文 + `free_tier`），重排 owner-only 键碰不到它 ⇒ 按「不纳入」处置。
- **真缺陷与来源**：`approval.hardline_blocked` 在两本维护语种里各被定义两次（zh 34/55、en 44/65，值逐字相同）。YAML 后定义者胜出 ⇒ 运行期文案一直是对的，**编辑第一处却是静默无操作**。`e93f3148e7`（2026-07-01）先加在块消息段；`92e0787ea6`（2026-08-27，批量 i18n）新建块结果段时又加一次（两次各只新增 1 次出现）。保留块结果段那一处 —— 消费方 `tools/approval.py:936 _hardline_block_result()` 返回工具结果 dict。17 本 catalog 修复后**无重复键**。
- **既有守卫为什么抓不到**：`tests/agent/test_i18n.py` 走 `safe_load` + `_flatten`，重复键在比较之前就被合并掉了，两本 catalog 被**同等地**抹平 ⇒ 「键集一致」这条不变量在结构上永远发现不了「单册内有重复」。新守卫走 `compose()` node 行号，并把**修复对象**（保留哪一处）与**仪器选择**（compose 而非 safe_load）分别钉住。
- **验证**：守卫 **20 passed**（与上游 parity 同跑 27 passed / 30 skipped）；变异 **7/7 咬住**（含「搬回上一个小节」只被守卫 2 的「行号 > 标题行」半条抓到、「把仪器换成 safe_load」只被仪器钉住那一例抓到）；爆炸半径回归 **136 路径**（T2-14 的 134 + **补入 `tests/agent/test_i18n.py`** + 本守卫）**NEW 0 / GONE 0**，leg A 2616 passed / leg B 2596 passed（差 20 = 本守卫整文件）；冲突面 `zh` 1→1、`en` 0→0；健康检查 **7 passed / 1 warning**（与 T2-14 后一致）。
- **变异装置首轮 2/6，已修（记录在案）**：三个 `BAD ANCHOR`（锚点是拼接后不存在的串 ⇒ 命中 0 次；一个裸行锚点命中 2 次）+ 一个 `MISS`（注入的 `isinstance(node, dict)` 永远不成立，因为 `_mappings` yield 的是 `MappingNode`）—— **后者是变异体本身坏了，不是代码多了一层**。

### 2026-09-29：新增 §16.11 feishu adapter 自有卡片胶水迁入 `owner/feishu/`（T2-14）

- **新建正文**：**§16.11**：`881092cbe0`（`plugins/platforms/feishu/adapter.py` 11 个方法改薄壳：`_dispatch_card_action` / `_normalise_card_action_value` / `send_card` / `_get_card_send_lock` / `send_model_picker_card` / `_handle_model_picker_action` / `send_guide_card` / `_handle_guide_card_action` / `send_queue_status_card` / `_handle_queue_card_action` / `_send_media_guard_hint`；新建 `owner/feishu/card_action.py`；`owner/feishu/{card_sender,model_picker,steer_card,queue_card,media_guard}.py` 追加正文。`tests/owner/test_feishu_adapter_thinning.py` 新增 40 例。本清单 §16.11 正文 + 附录 B 行 + 本条）
- **跟随修正**：`f244475b09`（**校验锚点同步 + Check 6/7 收进 pytest**）。`owner/validation/{anchors,inventory}.yaml` 是**文本匹配**式断言，正文搬家后必须跟着搬：Check 6 原有 5 条 issue（4 条随正文迁出、1 条因 `handle_picker_action` 改名 `dispatch_model_picker_action`）、Check 7 原有 2 条（`feishu-diff-card-dispatch` 仍指向 adapter）。改后 Check 6 **28/28**、Check 7 **140/140**，0 issue。同时暴露：这两项检查**只跑在健康检查脚本里，pytest 里没有** ⇒ 134 路径回归语料虽含 `tests/owner/test_merge_health_check.py` 却不会因它们变红。补 3 例变常驻 pytest 门，变异 **7/7 咬住**。
- **类型**：结构可维护性（正文外移 + 薄壳委托，**零行为变更**）
- **决策**（2026-09-29 用户确认）：范围＝**只搬纯自有代码**（与上游零耦合的方法正文），不动「注入上游函数内」的那部分
- **口径校正（审查 §5.4 给的四条前提，三条不成立）**：① 标签注入**已经**收口到 `owner/feishu/card_sender.py::_maybe_tag_interactive_payload`，adapter 侧只有一处 5 行调用 ⇒ 新建 `profile_tag.py` 无收益；② profile 路由**已经**收拢到 `owner/feishu/profile_routing.py`（982 行 / 25 个公开符号）；③ adapter 内 **0** 个 `t()`，i18n 那一行不成立；④ notice/queue 卡那行原本就写着「保持」。另：审查 §5.5 的 `-w` 仪器在本文件上**方向是反的**（`-w` 给出 `+1476/−299`，比 plain `+1447/−270` 更大）。
- **实测口径**：文件 **7092** 行（改造前；改造后 6900）；`[owner]` 标记 **71**（审查说 67；改造后 70，净 −1 的构成见 §16.11）；52 hunk 中 **28** 个含删除（审查说 27；配 24 个纯插入，52 = 28 + 24 自洽）；plain `+1447/−270`（审查说 +1425）。
- **33 块的真实构成**：我方冲突侧 1193 行 = 可执行代码 **824** + 注释 274 + 空行 95；最大块 357（`_handle_update_prompt_card_action` 尾 + 卡片发送/澄清/选择器/引导/队列一族）、次大 135（`_on_card_action_trigger` + `_dispatch_card_action`）。根因是**自有卡片胶水内联在上游类体里**，不是标签/路由。上游同期还在同片区域做了三项结构性重构（新增 `_pop_validated_prompt_state`、`send_exec_approval` 改名 `_send_exec_approval_prompt` 并模板化、sender_name 一族签名改多行）。
- **结构与语义**：11 个方法合计 404 → 212 行；adapter 7092 → 6900 行；`steer_card.py` / `queue_card.py` 内已有同名 `handle_*`，故新增薄封装改名 `dispatch_*`。**兜底尾巴刻意留在 adapter**（构造适配器模块全局 `P2CardActionTriggerResponse`，网关测试正给该全局打补丁），owner 侧因此用 `UNHANDLED` 单例 + 身份比较表示「走兜底」——**不能用 `None`**，处理器可以合法返回 `None`。
- **验证**：冲突块 **33 → 33**、我方冲突侧 **1193 → 1033**（最大块 357 → 259、次大 135 → 73，缩减量与方法行数对得上）；**变异 17/17 全部咬住**（并借变异当场补上 `normalise_card_action_value` 的一处守卫缺口：原先没喂「JSON 字符串编码的非 dict」，补齐后该参数化用例由 6 例变 9 例）；爆炸半径 134 路径 **NEW 0 / GONE 0**（leg A 2586 passed / leg B 2546 passed，差 **40** = 薄壳守卫整文件 40 例在对照腿中被移走；两侧 30 个失败同一集合，均存量）。补 3 例 pytest 门后复跑同一语料：leg A **2589** passed / leg B **2546** passed，差 **43** = 40（薄壳守卫）+ 3（新增健康检查门），**NEW 0 / GONE 0** 不变。
- **未闭合边界**：审查预期「冲突块 33 → 8–10」**判定不可达** —— 块数是**计块**不是计行，缩小块不消块；要到 8–10 必须把我们在约 15 个上游函数里的存在彻底移走，而审批按钮派发、reaction 转发等结构上离不开。注入上游函数内的约 436 行（占我方新增 30%）**未纳入**，属需另行决策的另一半。`_render_merge_forward_entries` 未动（`tools/feishu_client_utils.py:1593` 从 adapter import 它，搬走等于新增合并债）。审查 §5.5 的 `check-reindent.sh` 仍未实现。
- **教训（可复用）**：「期望值从被测文件自身推导」的断言（`checked == total`、`issues == []` 配「条目可被删除」）**删掉被测对象就自证通过** —— 必须另有一条**按 id/位置钉住**的用例，否则最省事的假修法恰好是最绿的那条。

### 2026-09-29：新增 §16.10 `discover_and_load` 消除 40 行纯缩进重排 + 取锁失败可观测（T2-13）

- **新建正文**：**§16.10**：`bae086a304`（`hermes_cli/plugins.py` 新增 `PluginDiscoveryLockBusy`；`__init__` 增 `_discovery_deferred`；`discover_and_load` 抽成薄壳 + 新增 `_discover_and_load_scoped`；`discover_plugins` 由 `-> None` 改 `-> bool`；`start_background_plugin_discovery` docstring 补例外。`tests/owner/test_plugins_discovery_guard.py` 新增 19 例。本清单 §16.10 正文 + §7.20 指针 + 附录 B 行 + 本条）
- **类型**：结构可维护性 / 上游改动传导（**零缩进重排**）+ 两处行为修正（`force=True` 不再被静默丢弃、取锁失败可观测）
- **决策**（2026-09-29 用户两次确认）：① 修法＝**同文件抽 `_scoped` 方法**（而非审查原文的 `owner/plugins/discovery_guard.py` 委托）；② 范围＝**结构重构与两处行为修正一并做**
- **口径校正（审查给的三处前提全不成立）**：审查建议的 `if not _discovery_lock_or_bail(self): return` 依赖 `_discovery_lock` 不可重入，而它是 **RLock**（`:3749`）⇒ 该 helper 持锁不释放会让外层永久多持一层（后续 discovery 全死锁）、取完就释放则护栏被静默删除；修正它必须补 `finally: release()`，又必然把 40 行退回 +4 缩进。审查指定的落点 `owner/plugins/` 目录**不存在**，§5.5 提议的 CI 门禁 `owner/scripts/check-reindent.sh` 也**不存在**。另：把正文搬到 `owner/` 在冲突维度上是反向的（留在原文件上游可干净合并）。
- **实测口径**：plain `+111/−40` vs `-w` `+72/−1` ⇒ 40 个删除里 **39 行是纯缩进**（正文 40 行，`if force:` 两处被 git 交叉匹配成上下文）；真删除只有那 1 行 `with`。
- **结构与语义**：`_discover_and_load_scoped(force)` 内的 `with self._discovery_lock, _plugin_home_scope(self.home_path):` 逐字保留、缩进不变；正文回到上游缩进。与本文件上游自身的 `unload()`→`_unload_scoped()`、`_load_plugin()`→`_load_plugin_scoped()` 同构（`discover_and_load` 原是全文件唯一「持锁却不抽方法」的异类）。RLock 重入**已是上游既有依赖**（体内调 `self.unload()` 与 `_load_plugin()`，两者都 `with self._discovery_lock`），故保留内层锁不引入新依赖。
- **两处行为修正**：① `force=True` 拿不到锁改为上抛 `PluginDiscoveryLockBusy(RuntimeError)` —— 6 处 force 调用点**本来就**在 `try/except Exception` 里按非致命处理；默认路径刻意不上抛（几十个 getter 会受影响）。② 新增 `_discovery_deferred` + `discover_plugins() -> bool`，并把 `start_background_plugin_discovery()` docstring 里「no caller can observe a half-loaded registry」补上 join 超时这一例外。
- **被守卫测试抓出的自身判断错误**：把 `discover_plugins()` 的 `not force` 当缺陷删除是错的 —— 它是承重的（删了 `force=True` 会被同一早返回吞掉）。静默丢弃在 `discover_and_load` 的护栏里，不在那处早返回里；已原样保留并加守卫钉住。
- **验证**：plain == `-w`（`+123/−2`）⇒ 全文件零仅空白改动；`discover_and_load` 区域删除 **40 → 0**（该 hunk 纯插入 `+29/−0`）；**变异 17/17 全部咬住**（并加了 `compile()` 前置校验，把两个不可导入的变异体判为不合格、换成合法变异体）；定向回归（爆炸半径 27 个路径：所有引用 `discover_plugins` / `discover_and_load` / `_discovery_lock` 的用例 + force 重试路径 + `tests/owner/`）**1381 通过 / 15 跳过 / 0 失败**，两腿失败集合完全相同（NEW: 0 / GONE: 0）；健康检查 7 passed / 1 warning（Check 5 的 4 条既有 warning 不变，属 merge `315551234`）、Check 8 116/116
- **未闭合边界**：§5.5 的 `check-reindent.sh` 未实现（需上游 ref）；`_delivery_manager()` 仍不看 `_discovery_deferred`（延迟窗口内 hook 投递会静默落空，未改）

### 2026-09-28：新增 §16.9 写入护栏文案英文原文回归代码 + `_localized()` 渲染与漂移守卫（T2-12）

- **新建正文**：**§16.9**：`dfedb2ec74`（`tools/file_tools.py` 新增 12 个英文原文常量 + `_GUARD_EN_TEXTS` + `_localized`；`_blocked` 由 `(why)` 改 `(why_key, why_en)` 并改写 15 个调用点；import 面加 `DEFAULT_LANGUAGE` / `get_language`。`tests/owner/test_file_tools_guard_text_i18n.py` 新增 11 例。本清单 §16.9 正文 + 附录 B 收口 25 行 + 本次条目）
- **类型**：可维护性 / 上游改动传导（**零行为改动、零输出变化**）
- **决策**（2026-09-28 用户确认）：**原文回归代码**（而非「只加漂移守卫」或「完全退回上游形态」）
- **口径校正**：实测这 12 条字符串**当前与上游逐字一致**（唯一差异是 SSH 模板占位符名 `{display_targets}` → `{targets}`）⇒ 修的是**潜在分叉**、改动无损；且 `t()` 是目录键查找、没有接收英文原文的参数，故审查给的「只把最终文案交给 `t()`」无法字面实现，必须另加一层渲染
- **守卫与技巧**：7 类守卫（漂移 / zh 覆盖 / 结构完整 / 禁 `t()` 直取 / 机械配对核对 / 哨兵法双向 / 回落 + 端到端语言一致性）。「en 不查目录」用**哨兵法**证明 —— 污染目录后 en 输出必须不变，非 en 再做反向哨兵（哨兵**必须出现**）
- **被变异测试抓出的自证陷阱**：端到端 zh 断言原写作「与 `t(template, why=t(why_key))` 逐字相等」，而改造前后 zh 路径**都**走目录 ⇒ 对目录改动零敏感（变异实测不失败）；改为与目录无关的性质（三段文案互不相同 + 英文原文不得出现在中文输出里）
- **同类普查**：官方 `.py` 共 **827 个 `t()` 键**，其中 **229 个**（**28 个文件**）同属此缺陷类 —— 上游代码里有该文案、`t()` 替换后只存在目录里（`gateway/run.py` 73、`agent/conversation_loop.py` 33、`cli.py` 25、`hermes_cli/models.py` 18、`tools/memory_tool.py` 15 …）。本条只覆盖含安全指令的这 12 条，其余未逐条改造
- **验证**：输出零变化（12 键 × en/zh/ja 与改造前逐字比对 0 处不一致）；**变异 14/14 全部咬住**（含 G7b 证明 why 片段本地化那一层不可省、G8b 证明「常量对但键配错」在 en 输出里看不出来、机械配对守卫必要）；定向回归 1325 通过 / 7 失败，与改造前**失败集合完全相同**（7 例既有：2 例 macOS 符号链接、5 例 `tests/tools/test_approval.py` webhook/timeout）；健康检查 7 passed / 1 warning、Check 8 116/116
- **顺带收口（T2-11 遗留的附录 B 缺口）**：补齐本仓 **28 个官方改动文件**的速查条目（25 行），使 116 个官方改动文件在附录 B 中**全部**有全路径条目；`hermes_cli/tips.py` 此前在全文任何位置均无路径提及，一并补上。§16.8 正文里的条目数由「22」更正为实际登记的 **39**，与附录 E 记载一致
- **未闭合边界**：漂移守卫为纯本地比对（不依赖上游 ref，CI 单分支亦可跑）；`t()` 公共签名未改；普查出的其余 217 个同类键未改造

### 2026-09-28：新增 §16.8 官方改动文件 `[owner]` 标记全量补齐 + 覆盖率守卫（T2-11）

- **新建正文**：**§16.8**：`a77e345342`（58 个官方文件逐 hunk 插标记 +365 行；33 个文件共 90 处 `[owner-patch]` → `[owner]`；`owner/validation/merge_health_check.py` 新增 Check 8 及其 4 个助手/常量并注册；`tests/owner/test_merge_health_check.py` 新增 3 例；`owner/docs/二次开发规范.md` §2.2 新增「标记细则」+ §5 补注；本清单 §16.8 正文 + 附录 B 补 39 个文件条目 + 本条）
- **类型**：可维护性 / 解冲安全（**零逻辑改动**，纯注释 + 校验器）
- **口径校正**：审查原文「67 个官方文件」实测应为 —— 「无 `[owner]`」68 个、「无任何标记」**58 个**，本条落地对象是后者（另 10 个由 `[owner-patch]` 归一覆盖）。统计一律 `--diff-filter=M`：官方目录下**新增**文件按 §2.2 走 commit message 前缀，不需要文件内标记
- **决策**（2026-09-28 用户两次确认）：① 粒度 = **逐 hunk 全标**（而非只补文件级）；② 拼写 = **统一为 `[owner]`**（而非两前缀并存）；③ 范围 = **按文件级收口**、hunk 级铺开只覆盖零标记的 58 个文件，其余 902 个未标记 hunk 另立 T2-11b
- **三类边界情形均不跳过**：字符串内部 12 处（含 `hermes_cli/gateway.py` 落在 112 行 respawn 模板里的唯一 hunk——不上移则该文件保持零标记）→ **上移到字符串 token 起始行之前**并注明；JSX children 1 处 → 改用 `{/* ... */}`（裸 `//` 在 children 里会渲染成文本）；纯删除 hunk 6 处 / 4 文件 → 文件顶部登记小块
- **标记格式取舍**：§2.2 原写「短描述 + 指向 owner/ 位置」，但 361 个插入点各带指针会给官方文件灌进约 19KB 注释、与 §2.1 冲突 ⇒ **标记只留短描述，指针改由清单的每文件条目承担**，并为此补齐附录 B 缺失条目（使「指针可查」成立）；§2.2 已同步写入
- **生成物豁免**：`uv.lock` 的 4 处标记实测后**撤回**（`uv lock` 会整文件重写、标记必失，且解冲时会诱导保留本应重生成的产物）；pin 标记挂 `pyproject.toml`
- **归一的 5 处刻意保留**：`owner/code-review/00-REVIEW.md` 3 处（冻结评审报告，改写会抹掉证据）、`merge_health_check.py` 2 处（正则容错分支 + `_normalize_owner_marker_line` 的旧拼写剥离，**承重**：Check 5 要比对 merge `315551234` 的历史删除行，那里就是旧拼写）
- **新增守卫**：Check 8「Changed-file `[owner]` marker coverage」—— 以 `git merge-base HEAD {upstream/main,origin/main,main}` 为基准取官方 `--diff-filter=M` 文件，逐个断言含标记，命中即 **FAIL**（非 WARN）。把「零标记官方文件」从一次性人工普查变成每次跑检查都验的不变量
- **效果**：零标记官方文件 **58 → 0**（覆盖 116/116，117 减 1 个生成物）；健康检查 **6 passed / 1 warning → 7 passed / 1 warning**（Check 5 的 4 条既有 warning 不变）；Check 4 识别 670 个标记 / 99 个文件
- **验证**：改建 43 个 `.py` 全过 `py_compile`；**改名纯度逐行校验** 84 对每对只差 `[owner-patch]` → `[owner]`、58 个插入文件 `--numstat` 删除列为 0；`tests/owner/` **837 通过 / 0 失败**；**Check 8 变异 4/4 咬住**（A 反向：47 标记文件删 1 个不报错 / B 删唯一标记 → 115/116 报错 / C 撤生成物豁免 → 点名 `uv.lock` 117/116 / D 清空基准 ref → 优雅降级 `skipped`）
- **未闭合边界**：**T2-11b** —— 官方文件共 1528 个带新增行 hunk，626 已标记、**902 未标记**，分布 55 个「已有标记但不完整」文件（前 15 名占 692 处 = 76%，`gateway/run.py` 190/233 居首）。这些文件清单里均已有条目、Check 8 亦守住文件级覆盖，故本轮按文件级收口，hunk 级按冲突权重分批另办

### 2026-09-28：新增 §16.7 `output_guard` 复读判据由 O(n²) 正则改为线性扫描（T2-10）

- **新建正文**：**§16.7**：`958594ce6f`（`owner/owner-extensions/output_guard/__init__.py` 新增 `_find_word_repeat` / `_repeat_after` / `_token_at` / `_WS_RE` 与两个常量、删去 `_WORD_REPEAT` 正则、`_degenerate_scan` 改调用点、docstring 记录成因；`tests/owner/test_output_guard.py` 新增 8 例；`owner/docs/output-guard-design.md` 同步改写把判据写成该正则的句子）
- **类型**：性能缺陷修复（守卫自身击穿模块的 O(n) 契约）+ 零官方侵入
- **决策**（2026-09-28 用户确认）：审查给的二选一里选**线性扫描 + 完整复刻原语义**，而非「量词加上界」。理由：`(\S{1,64})` 逐例比对后确认**不是语义等价**（重复单元 >64 字符时漏判，且 `dirty_run` / `comp_belt` 都不会补位）
- **实测比原记录更重**：原记录「40000→2745ms / `_MAX_CHARS` 外推约 20s」把 16000 的实测值当成了 40000；真值为 40000→18 735ms、50000→**30 360ms**（翻倍 ×4）
- **等价性证明**：以**被替换掉的原正则**为 oracle 做差分测试，比对「命中与否 + 最左匹配起点」，开发期 140 536 例、提交进仓约 22 400 例，全部零不一致；原语义里两处**未写档的既成行为**（可从 token 中间起步；run 边界是任意空白而分隔符是字面单空格）照旧保留并钉了用例
- **效果**：50000 字符 30 360ms → 0.26ms；端到端 `analyze()` 4.8ms
- **同类普查**：`owner/` 树内 8 处 `re.compile` 逐个核对，反向引用仅此一处 ⇒ 该二次回溯组合在本仓不存在第二处；`stream_guard._MARKER_RE` 经核查不构成 ReDoS
- **验证**：新增 8 例 + 变异 9 条全部咬住（含「退回原正则」→ 时间上界用例以 30.43s 失败）；定向回归 977 通过 / 0 失败、父提交基线 969 / 0、`comm -23` 为空；健康检查 6 passed / 1 warning（既有）
- **未闭合边界**：无（本条为等价替换）；`_degenerate_scan` 的其余信号本就 O(n)

### 2026-09-28：新增 §16.6 `tool.progress` 出口强制脱敏 + 帧绑定断言；飞书转发补子容器归属校验（T2-9）

- **新建正文**：**§16.6**：`6b80b565f4`（`gateway/platforms/api_server.py` 新增出口脱敏与帧绑定助手 `_redact_for_sse` / `_redact_args_for_sse` / `_redact_nested_for_sse` / `_redact_result_for_sse` / `_bind_tool_frame` / `_tool_frame_is_ours` / `_stripped_tool_frame` + 新增 `_owner_inbound_profile_rejection` / `_profile_mismatch_response`，改两处 clip 助手、两条 SSE 通道的产出与写出点、`/v1/runs` 的 `_tool_progress`、两个 feishu doorway；`owner/feishu/profile_routing.py` 新增 `container_profile_identity` / `verify_inbound_target_profile` / `reset_ownership_notices` 与 `TARGET_PROFILE_KEY` 载荷；`plugins/platforms/feishu/adapter.py` reaction 归属决策记录（仅注释）；`tests/gateway/test_api_server_tool_progress_egress.py` 新增 18 例；`tests/owner/test_feishu_profile_transport.py` 新增 14 例）
- **类型**：安全修复（出口泄密）+ 官方文件薄胶水 + 已接受决策钉在用例上
- **决策**（2026-09-28 用户确认）：S2-3 **强制脱敏 + 帧绑定断言**；S2-4 **补子容器身份校验 + 钉语义，路由行为不变**
- **与审查原文的分歧（两处）**：① 审查称「隔离完全依赖『SSE 只回发起者』这一隐式前提」—— 该前提在仓内**成立**（`_stream_q` 按请求新建、回调闭包绑死），问题不在隔离被破坏而在**出口本身原样放行**，故 P2 评级合理。② 审查给 S2-4 的修法（维护 `message_id → origin profile`，出站落库）**不成立** —— `d74762a04e` 落在发送方容器自己 `state.db` 的 `delivery_obligations.platform_message_id` 且无 profile 列，主网关与子容器是不同 `HERMES_HOME`；即便同类可用，7 天保留期 + 行数上限 + 开关 + best-effort 写入也会让旧消息上的表情被误丢
- **现网拓扑实测**：群聊下 `resolve_profile_route` 跳过白名单 ⇒ 全员同容器（去向一致），容器内 `group_sessions_per_user` 默认 True ⇒ 表情落在反应者自己的会话 ⇒ **当前拓扑下不存在跨边界误投**；S2-4 维持 P2，工作台把 T2-9 升 P1 的叠加理由只在 `tool.progress` 那一半成立
- **实质收获**：遗漏通路比原记录多一条 —— `label` 由 `build_tool_preview` 从**原始** args 派生，只脱敏 `args` 仍会从 label 漏出密钥；另确认「先脱敏再截断」的顺序是逻辑的一部分（反过来留下 `…ghp_abc` 碎片，模式表与 dict 级兜底都救不回来）
- **验证**：新增 32 例 + 变异验证 11 条**全部咬住**；定向回归 12 失败 / 1090 通过（12 例经 `git stash` 对照证实为既有失败）；健康检查 6 passed / 1 warning（4 处 merge 残留死标记，属既有，T2-11 范围）。A1 与 A6 的守卫一度测不出来（A1 被 dict 级兜底遮蔽、A6 变异模式同时命中相邻字典），解法分别是把断言下沉到密钥碎片、给变异脚本加命中数期望并收窄范围，两条已沉淀为 skill 第 23–24 条
- **未闭合边界**：帧绑定只保护**本进程内**的投递对象（会话 id 仍可由调用方用 `X-Hermes-Session-Id` 指定）；容器自身身份不可判定时校验自动让行；群聊 per-user 路由的语义张力未解
- **未纳入**：SSE 扇出逻辑本身（**不在本仓**，无法核实）；`/api/sessions/{id}` 归属模型（上游既有设计）；群聊 per-user 路由模型的改造；`tool.progress` 对「能力型工具只发摘要」的收紧

### 2026-09-28：新增 §16.5 会话 id 派生加服务端盐 + 归属摘要刻意不加盐（T2-8，含两处连带修复）

- **新建正文**：**§16.5**：`a622691915`（`owner/gateway/session_salt.py` 新增；`gateway/platforms/api_server.py` 新增 `_owner_session_salt` 薄委托并把 `_derive_chat_session_id` 改为 HMAC；`tests/owner/test_session_salt.py` 新增 23 例；`tests/gateway/test_api_server_media_owner.py` 新增 2 例）
- **类型**：安全修复（可离线推导的 bearer 凭据）+ 官方文件薄胶水
- **决策**（2026-09-28 用户确认）：**盐只加在会话 id 派生上，不加入归属摘要**；盐源为新增独立持久化密钥（不在 API key / LDAP 口令上搭车）
- **与该条原修法的分歧**：安全官 S2-2 建议「两处摘要都掺盐」。对归属摘要**零收益** —— `_media_owner_matches` 比对的是 `media_owner_token(调用方送来的串)`，盐作用于「送到的那串本身」，只能关掉离线推导，关不掉「提交一个已知 id」与「什么都不声明」
- **本条实质**：派生 id 不只是连续性键，`/api/sessions/{id}`（GET / PATCH / DELETE / fork）只认 API key + 路径里的 id、无归属校验 ⇒ 可离线推导的 id 等于可推导地读到、改到、删掉他人会话。这才是要关掉的东西
- **未闭合边界**：盐**不解决会话碰撞**（部署共享一个盐 + 同 prompt 同首句 ⇒ 同 id），已显式记录并钉在 `test_the_same_salt_still_collides_on_identical_inputs`
- **连带修复**（建立基线时发现的既有缺陷，与 T2-8 无关）：`test_sweep_evicts_oldest_past_entry_cap` 用 `split("__", 1)[0]` 解析条目名，而 id 是 `med_` + token、token 首字符可为 `_` ⇒ 约 **3.1% 假失败**；`_LdapGateProbe.patch()` 退出时未清 `_owner_lazy` ⇒ 假门漏给同一 pytest 会话的后续模块，`test_ldap_identity_auth.py` 有 7 例把本应被拒的请求真的反代到本机监听中的网关
- **验证**：变异验证 6 条全部失败（撤销加盐 → 3 例 / 接受过短盐 → 1 / 删缓存提前返回 → 1 / 覆盖短文件 → 1 / 权限放宽 → 1 / 空盐当有效 → 1）+ 污染修复的变异 1 条（去掉退出清缓存 → 7 例复现）；回归 `tests/owner/` + `tests/gateway/test_api_server*.py` **963 例全通过**（修复前 7 例失败 / 956 通过）；与父提交对照无回归。**需网关重启生效**
- **未纳入**：`/api/sessions/{id}` 端点自身的归属模型（上游既有设计）；`tool.progress` 的按会话隔离（T2-9）

### 2026-09-28：新增 §16.4 产物下载归属断言 + 「未声明即放行」决策（T2-7，含补录）

- **新建正文**：**§16.4**：`0925bdf088`（**补录** —— 该提交此前既不在正文、也不在待补录梳理清单中，§16 原先只列 3 个 commit）+ T2-7 决策（本次，无代码行为改动）
- **类型**：留档补齐（归属断言的实现与「未声明即放行」的决策依据）+ 决策钉在测试上
- **决策**（2026-09-28 用户确认）：**维持现状 + 显式记档**。`_media_owner_matches` 在请求未声明身份头时放行，含义是「对未声明的下载，`media_id` 即唯一归属凭据」。依据：id 96 bit 不可枚举且只交给登记方、收紧会锁掉设计上要服务的持 key 调用方、且单改下载侧并非完整修复（注册侧 `owner=""` 是第二条独立通路）
- **代码侧**：仅 docstring 改写（`_media_owner_matches` + `_handle_media_download`），明写「已接受的决策」、残余风险与本文出处，并点出姊妹机制 `/v1/artifacts/download/{id}` 用服务端推导 scope、本身 fail-closed
- **测试**：新增 `TestAcceptedUnattributedAccess` 3 例（下载侧放行、注册侧落空 owner、docstring 记档存在）—— 决策钉在行为上，未来收紧必须先改测试
- **验证**：变异验证两条（均失败）：把 `return True` 改成 `return False`（即悄悄收紧）→ **4 例失败**；去掉 docstring 中的本文指针 → 1 例失败
- **同类普查**：产物下载的两个机制（`/v1/media/{id}` 与 `/v1/artifacts/download/{id}`）信任模型不一致已查明并记录；归属凭据无服务端盐 → 由 **T2-8** 跟踪；跨用户暴露面 → **T2-9**
- **未纳入**：前端侧「下载时回带会话头」的适配（本仓无法核实）

### 2026-09-28：新增 §15.10 认证判定与路由判定解耦（T2-6）

- **新建正文**：**§15.10**：`571ba8c937`（`gateway/platforms/api_server.py` 抽出模块级 `_owner_identity_gate_rejection()` 并把调用点移到白名单短路与路由解析之前、dormant 告警文案改写；`owner/feishu/profile_routing.py` 与 `owner/gateway/ldap_auth.py` 的 docstring 改写；`tests/owner/test_ldap_identity_auth.py` 新增 5 例；`tests/owner/test_identity_routing_dormant.py` 反向改写 1 例 + 新增 2 例）
- **类型**：安全修复（认证绕行）+ 官方文件侵入（流程重排）
- **根因**：`ldap_gate` 位于「路由解析成功之后」，认证是否发生由路由决定 —— 白名单短路与「路由解析返回 None」两条路都能跳过它；后者还让一条 `profile_endpoints` 配置错误变成免认证通路
- **决策**：带 `X-Hermes-Identity` 的请求一律先过认证门；接受「未知身份不再透传」这一行为变更（身份头是声明，未验证的声明不应被当作普通请求处置）
- **验证**：新增 5 例 + T2-3 侧反向改写 1 例/新增 2 例；变异验证三条（均失败，其中「门移回路由解析之后」失败 6 例、helper 内 503 映射失效失败 1 例）；回归 74 文件 / 1165 例全通过
- **同步修正**：T2-3 的 dormant 告警原宣称「no sub-profile reverse-proxy AND no LDAP second-factor gate」，该后果已不成立；§15.2「认证门在当前配置下不可达」、§15.7 后果表 `ldap_gate` 行、§15.5 白名单优先级说明均按新事实改写
- **同类普查**：`X-Hermes-Identity` 生产读取点仅中间件与 `_media_owner_matches`（后者由 T2-7 / T2-8 跟踪）；另确认「门的摆放位置本身就是安全属性」，与 §15.8（判据方向）、§15.9（失败归因）同列为「门看起来在、实际不设防」的三种形态

### 2026-09-28：新增 §15.9 带密码但无法验证时默认拒绝（T2-5）

- **新建正文**：**§15.9**：`6613ac2146`（`owner/gateway/ldap_auth.py` 新增 `DENY_BACKEND_UNAVAILABLE` + `_verdict_on_unverifiable` 按成因分流 + `fail_open_on_error` 默认翻转；`gateway/platforms/api_server.py` 新增 503 映射；`owner/config/patch_feishu_profile.yaml` `fail_open_on_error: true → false`；`tests/owner/test_ldap_identity_auth.py` 新增/改写 5 例）
- **类型**：安全修复（DoS → 认证降级），官方文件侵入为单个 verdict 分支
- **决策**：默认翻转 + 保留开关 —— 若带密码一律拒绝，该开关将失去全部作用面而退化为死配置
- **验证**：变异验证三条（均失败）+ 密码错与无法验证两种结果必须不同的对照用例
- **同类普查**：另查出 `_load_ldap_config()` 把「配置读不到」与「未启用」压成同一 `{}`，配置故障即静默关闭认证门 → 单独立项 **T2-23**（修复涉及共享加载器，需独立决策）

### 2026-09-28：新增 §15.8 enforce=seen 改为 fail-closed（T2-4）

- **新建正文**：**§15.8**：`ed0c3dfb21`（`owner/gateway/ldap_auth.py`：`seen` 降为 `always` 的 fail-closed 别名 + `enforce` 取值校验 + `_seen_logins` 退出判定链；`owner/config/patch_feishu_profile.yaml` `enforce: seen → always`；`tests/owner/test_ldap_identity_auth.py` 改写 3 例并让两处传输用例改用种子化有效缓存）
- **类型**：安全修复（门只拦「已认证过的账号」→ 攻击者挑从未登录的 uid 即零密码通过），纯 owner/ 内部，**零官方侵入**
- **决策依据**：该链路当时 dormant（§15.7），不存在需要灰度保护的现有流量
- **验证**：变异验证两条（均失败）+ 回归 57 文件 / 908 例全通过
- **同类普查**：`_cache_get` 先剪枝再取值 ⇒ 无过期条目放行泄漏；`_has_seen` 不剪枝但已退出判定链（docstring 标注 diagnostic-only）；另查出「未识别 `enforce` 取值静默等价于 `off`」并一并修复

### 2026-09-28：新增 §15.7 未接线状态显式化（T2-3）

- **新建正文**：**§15.7**：`9f453c51e1`（`owner/feishu/profile_routing.py` 新增 `identity_routing_diagnostics()`、`gateway/platforms/api_server.py` 中间件告警分支 + 准入端点 `routing_dormant` / `routing_keys_present`、`owner/config/patch_feishu_profile.yaml` 标注接线状态与启用前置、`tests/owner/test_identity_routing_dormant.py` 新建 14 例）
- **类型**：可观测性修复（「门存在但未生效」显式化）+ 官方文件侵入
- **背景**：§15.1–§15.5 的整套身份准入体系始终未被 `identity_routes` / `identity_whitelist` 接线 —— `ldap_gate` 因位于路由解析之后而永久不可达（门的这一位置已由 **§15.10** 改变），准入端点对任何 uid 返回 `allowed:false`，而文档此前按「已生效」描述
- **决策**：暂不接线（接线会把三处语义缺口从「不可达」变成「可用」，须先修完），改为显式化；§15.1 / §15.2 / §15.5 同步补接线状态说明
- **验证**：14 例 + 变异验证三条（均失败）+ 回归 67 文件 / 1056 例全通过
- **同类普查**：`X-Hermes-Identity` 生产读取点仅 `api_server.py`（其余已由 T2-7 / T2-8 跟踪）；其他「配置驱动门」均有显式开关且文档一致，无同类缺陷

### 2026-09-28：新增 §3.13 审批历史挖掘改按结构标记判定（T2-1）

- **新建正文**：**§3.13**：`91007c9b58`（`owner/approval/approval_history_policy.py` 新建 439 行、`hermes_cli/approvals_suggest.py` 薄委托 2 处、`tests/owner/test_approval_suggest_i18n_blocks.py` 新建 27 例）
- **类型**：安全修复（i18n 击穿逻辑匹配）+ 官方文件侵入
- **根因**：`5d85ec89ac`（2026-08-17）把 `tools/approval.py` 拦截文案搬进 `locales/*.yaml`，`approvals_suggest.py` 只补了一行中文 marker，导致中文环境下判定表与 SQL 粗筛同时失效，被拒绝的命令被挖掘为「隐含批准」
- **验证**：真实库 46,582 条 tool 结果标定（真拦截漏检 0 / 误报 0 / 命中 92 / 1.04s）；变异验证两条；`scripts/run_tests.sh` 57 文件 / 788 例全通过
- **同类普查**：生产侧仅此一处；测试侧英文硬断言缺口另立 **T2-22**

### 2026-09-23：新增 §7.27 outbound_special_token_scrub（出站剥 BOS/EOS）

- **新建正文**：**§7.27**：`owner/outbound_special_token_scrub.py` + `gateway/run.py` / `run_agent.py` 三处 fail-open 薄胶水；全 provider 字面剥；tests 8 例

### 2026-09-22：新增 §7.26 english_explainer（英文回复中文解说）

- **新建正文**：**§7.26**：`9d4f17a6a1`（`owner/english_explainer/` 新增 6 模块、owner-extensions `transform_llm_output` + `pre_gateway_dispatch` 接线、`auto_card`/patch notice、`tests/owner/test_english_explainer.py` 11 例、设计稿 `owner/docs/design/english-reply-explainer/`）

### 2026-09-20：新增 §7.25 approval_explainer（审批卡命令解说）

- **新建正文**：**§7.25**：owner/approval_explainer/ 新增 4 模块、feishu/qqbot adapter + keyboards 三处 `[owner]` 胶水、locales zh/en 各 +2 key、patch.yaml §7.25 段、tests/owner/test_approval_explainer.py 20 例、设计稿 owner/docs/design/approval-command-explainer/
- **同批对齐**：§7.24 progress_explainer 模型改 auxiliary auto 语义 + timeout 30s（config/explain/patch.yaml）
- **验证**：20 例新测 + 回归（approval 128/审批卡系列/qqbot keyboards 无既有测试）全绿；4 例存量环境性失败与本功能无关

### 2026-09-20：新增 §7.24 progress_explainer（沉默期进度旁白）

- **新建正文**：**§7.24**：gateway/run.py +27 行 `[owner]` 胶水、owner/progress_explainer/ 新增 7 模块、tests/owner/test_progress_explainer.py 18 例、stream_guard snapshot() +34 行、设计稿状态行更新
- **背景**：长任务 10 分钟用户零信息（QQ 面包屑丢弃/reasoning 不流式可见/心跳 600s 且原地编辑）；设计稿 2026-09-17 已 commit 未实现
- **验证**：18+20 passed；run.py py_compile ok；默认 enabled=false 零行为变化

### 2026-09-20：新增 §7.23 stop-orphan-run（/stop 打在 runner 构造窗口期的「孤儿轮次」）

- **类型**：代码修复（gateway 薄胶水 + owner patch）+ 设计文档
- **新建正文**：**§7.23**：`2110ea27eb`（`gateway/run.py` +8 行 `[owner]` 委托、`owner/patches/stop_orphan_run.py` 新增、`tests/owner/patches/test_stop_orphan_run.py` 11 例、`owner/docs/design/gateway-stop-orphan-run/stop-orphan-run.md`）
- **同步状态**：代码已推 origin + gitlab 并 pull 到 node010；**未重启任何 gateway**（生效需下次重启）

### 2026-09-10：本机 commit 补录（09-02～09-10 全量 + 08-14～09-01 窗口）

- **类型**：文档补录（对照 `owner` 本机作者提交与正文 diff）
- **新建正文**：
  - **§15** API Server：LDAP 身份准入与多 profile 路由（8 commit）：`6177923b26`（能力起点，09-01）、`531508e317` / `6790f1ba6c` / `db78cdd871`（LDAP bind 二次认证 + 依赖 + 配置）、`8f533aaa0c`（seen 语义权限提升修复）、`311f553550` / `4b6d187a2b`（转发头剥离 + SSE 透传）、`b14892be7c`（准入查询端点 + identity_whitelist）、`8d42e4c199`（finish chunk session_id）
  - **§16** API Server：产物媒体与流式事件契约（3 commit）：`3d9a9ceed4`（MEDIA 下载 + `hermes.files`）、`9df4372591`（媒体存储接管字节 + 目录即索引，**含破坏性变更**）、`943b6bf1ac`（`tool.progress` 参数与摘要）
  - **§3.12** 2026-08-19 代码审查修复（P0/P1/P2）：`0c48c2a8b6`、`56fa158790`
  - **§4.15** 合并转发消息展开 + 消息分页读取：`2079a79fab`
  - **§6.4** live compression sync 误清 per-model `context_length`：`efb42e6e39`
  - **§7.20** 后台插件发现超时死锁（启动空白屏）：`211614adf2`
  - **§7.21** 出站 message_id 落库 + 全路径日志：`d74762a04e`
- **已有章节后续**（一句话挂 hash）：
  - §3.1 审批卡 operator 中文名缓存：`191e5a3287`
  - §3.11 skill 审批 `allow_skills` 白名单 / `HERMES_PROFILE` env + `profiles: *` / 默认关闭门闩：`5e9d88bc79`、`7515dd7e03`、`d7d4a0fd43`、`fa44610162`
  - §4.1 `send_card` 补 `hermes_profile` 标签：`31a8005791`
  - §4.4 diff card patch.yaml 开关：`c27120b97e`
  - §4.6 bot menu xy-damodel 菜单 / `/new` ack / 三层去重 / 路由 NameError：`b83d1da12c`、`a1604a1b20`、`78269d5972`、`7c759411d9`
  - §4.7 接通 `_classify_edit_failure`：`d510908961`
  - §4.11 队首开始执行补发底栏通知：`7ce75a8df5`
  - §4.13 docx 内嵌 bitable 块读取：`c5e0f9beda`
  - §7.3 Viking peer_id slug 化（修复 3 周结构化同步降级）：`eb6a97beb2`
  - §7.14 `HERMES_PROFILE` env 优先（110 个调用点）：`98236ad2ed`
  - §11.9 swagger-kanban T4 自修复卡 / review 人审门闩 / `token_cost_estimate.py`：`fde14c096d`、`ac1a3b9f4a`、`61375e20c5`
- **附录 A/B**：新增 `owner/gateway/ldap_auth.py`、`gateway/platforms/api_server_media.py`（官方树内 owner 新增文件单列）；`owner/gateway/` 与 `owner/feishu/` 行扩写；`gateway/platforms/api_server.py` 由 **B.3 轻度升 B.1 重度**；新增 delivery_ledger / plugins / profiles / openviking / feishu tools / tui_gateway / cli / ldap3 依赖等侵入行；附录 B.4 结论改写（api_server.py 列为唯一待评估项）
- **元数据**（§0.1）：Commit 数 / 改动文件总数 / owner/ 纯新增 / 官方文件侵入 四行按实测值回填，并新增统计口径脚注
- **刻意不记**：纯 i18n、纯 docs、merge main、test-only


### 2026-09-02：合入 upstream/main @ 00b2e03c80

- **类型**：sync fork + owner 解冲
- **Commit**：`3155512347`（merge main）、`7768ec4b26`（锚点适配 batch row dict）
- **策略**：70 个冲突文件按改动清单解冲；locales 非 en/zh 取官方；bugfix 官方已覆盖则取官方（models_dev 24h TTL、terminal NUL/二进制、anthropic adapter 抽模块、Layer1 `_probe_live`）；各自解决一部分则手合（§2.2.2）；owner 独有能力回贴胶水（api_key_prefixes、damodel `${VAR}`、Feishu 全套、归因链）。
- **验证**：`merge_health_check.py` 6 passed / 0 failed / 1 warning；`merge_loss_audit.py` FAIL=0 WARN=3（官方已覆盖的旧 marker / cron ContextVar 原生实现 / owner.utils 孤儿）。


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
- **评估范围**：4 处 `[owner]` args 链 + 2 处 allowlist 副本
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
- **Commit**：`7230d71e9`
- **背景**：`feishu_doc_read` 仅调用 docx `raw_content` API，飞书会把 image block 压成文本 `image.png`。agent 看不到真实截图；完整链路是 blocks 取 `image.token` → `drive/v1/medias/{token}/download` → 本地文件 → `vision_analyze`。
- **方案**：
  - `tools/feishu_client_utils.py`：新增 `list_docx_image_tokens`（分页读 blocks，`block_type=27`）、`download_media`、`download_docx_images`（落盘 `$HERMES_HOME/cache/feishu_doc_images/<doc>/`）、`inject_image_paths_into_content`（按序替换 `image.png` 为 `[Image N: /path]`）、`read_docx_with_images` 编排。上限 40 张 / 10MiB 每张。
  - `tools/feishu_doc_tool.py`：docx 分支改走 `read_docx_with_images`；返回 `content` + `images[]` + `image_count`；schema 说明可把本地路径交给 `vision_analyze`。
- **涉及文件**：`tools/feishu_client_utils.py`、`tools/feishu_doc_tool.py`、`tests/tools/test_feishu_client_utils.py`
- **测试**：`scripts/run_tests.sh tests/tools/test_feishu_client_utils.py tests/tools/test_feishu_tools.py` → 54 passed
- **后续（同日）**：用户反馈 `[Image N: path]` 仍被视为占位符。补 `analyze_docx_images`：下载后自动 auxiliary vision OCR，正文嵌入转录文字；返回增加 `vision_analyzed`。并发 3 / 上限 40。测试 59 passed。

### 2026-07-24：feishu_doc_read 图片上限 40→500 + 429 退避重试

- **类型**：体验调参 / 可靠性
- **Commit**：`e5e90f874`
- **变动**：`_DOCX_MAX_IMAGES` / `_DOCX_MAX_VISION_IMAGES` 从 40 提到 500；并发仍为 3。媒体下载与 vision OCR 共用 `_call_with_rate_limit_retry`（识别 HTTP 429 / Feishu 99991400 / rate limit 文案，指数退避最多 5 次，上限 60s）。
- **涉及文件**：`tools/feishu_client_utils.py`、`tests/tools/test_feishu_client_utils.py`

### 2026-07-30：漏写功能点补录（近 30 天本机作者 commit 审计）

- **类型**：文档补录（无代码变更）
- **范围**：本机作者「杨天宝 / yangtb」近 30 天 commit，排除 i18n 专向、纯 docs、纯 test 噪音；对照本清单发现的遗漏功能点。
- **高优先（新建正文）**：
  - **§3.9 Semantic Audit Gate**：`f07bdf6b8`、`0f28e4bde`
  - **§11.7 Upstream Sync**：`f05e2dd7e`、`4e076c9b0`、`1f24486b5`、`81afb5256`、`8ee7ca57d`（部分）
  - **§11.6 Viking 记忆质量治理流水线**：`f1d1fb109`、`1a1f0e7fa`、`80434b966`、`573f7ac52`、`195996b48`
- **中优先（新建/扩展）**：
  - **§6.3** Ctrl+C /exit drain：`300160673`、`5d1539c99`
  - **§7.14** lifecycle `{profile_tag}`：`8676ad980`
  - **§4.1** profile transport harden：`bc1feb536`
  - **§3.10** Smart DENY one-shot + QQ DM 鉴权：`ec98dff9b`、`ae912986f`
  - **§7.15** codex 空 content：`952be6814`
  - **§7.3** viking_add_resource 超时：`7733cabf7`
  - **§7.16 / §7.17** exhausted pool / display resolution：`217bd8589`、`6d5c00b51`
- **§11 运维扩写**：§11.8 rsync/NewAPI/OpenViking 备份；§11.9 周会脚本 / swagger-kanban / image_gen 预设
- **钉 hash**：§4.11 queue 撤销 `89fa171bc` + 锁 `306fb0be8`；§4.13 feishu 文档图 `7230d71e9`/`e5e90f874`/`4ca60433a`/`749f68abb`；§4.6 `agents` 菜单 `ee1e29084`
- **附录 A/B**：补 `owner/semantic_audit/`、`owner/sync/`、queue_cancel、run_agent/codex/TUI 轻度侵入行
- **刻意不记**：yangtb provider 移除（已退役约定）、纯 i18n、tips 清理等琐碎维护

### 2026-08-03：近 15 天本机 commit 补录

- **类型**：文档补录（无代码变更；对照 `owner` 本机作者 07-21～08-03 与正文 diff）
- **新建正文**：
  - **§3.11** skill 写入飞书审批门：`55b070fd8`（v1 gate）、`cd937b412`（v2 自建卡 + origin 通知 + profile 配置）
  - **§8.4** verify-on-stop 创意/视觉产物抑制：`21543bcfc`
- **已有章节后续**（一句话挂 hash）：
  - §1.2 session reset 清 patch 缓存：`88336be4f`
  - §2.2.4 model_picker idle：`63fa17e1b`
  - §2.11 models.dev 超时 5s：`8c00a813f`（部分）
  - §3.1 审批失败 CallBackCard：`cd11a5ff8`
  - §4.2 auto_card `load_config_readonly`：`5c750982d`
  - §4.10 memory 审批卡 invisible 根治：`c812f9df5`
  - §7.3 召回 emoji 📚：`2da7512f4`
  - §11.8 备份脚本解析 cron `--BACKUP_QUIET`：`8c00a813f`
- **附录 A/B**：skill_manage_gate / skill_approval_card / skill_manage_bridge；adapter skill_approval_gate；slash_commands 清缓存；verification_stop / models_dev
- **刻意不记**：纯 docs / 纯 i18n / tips 清理 / merge main / 运维白名单注释配置

### 2026-08-12：feishu_doc_read bitable 读取增强 + wiki 文件夹一层子节点列表

- **类型**：功能增强（现有 §4.13 的后续）
- **新建正文**：无（挂到已有 §4.13）
- **已有章节后续**（挂 hash）：
  - §4.13 bitable 读取增强：`9cceec46f`
  - §4.13 wiki 文件夹一层子节点列表：`a1b607d2e`
- **背景**：bitable 无差别全量拉取（23 表×500 条×21 字段≈24 万字段值）token 爆炸/截断；wiki 文件夹节点原只吐标题无法列子文档
- **验证**：单测 74 passed；实测真实 bitable structure 模式只出目录、真实 wiki 文件夹 24 个子节点全列出（需重启 gateway 生效）

### 2026-08-13：近 10 天本机 commit 补录（含 output_guard / @所有人 / queue 状态卡）

- **类型**：文档补录（对照 `owner` 本机作者 08-03～08-13 与正文 diff）
- **新建正文**：
  - **§4.14** 禁用 @所有人 自动响应：`470148013`
  - **§7.19** lifecycle guard 遇二进制路径崩溃：`e13cce770`
  - **§8.5** `read_file` UTF-8 边界误判 binary：补钉 hash `f457a0fb8`
  - **§14** output_guard：补钉 hash `824c95d5d`
- **已有章节后续**（一句话挂 hash）：
  - §2.10 自定义 provider 匹配去重：`84418c339`
  - §3.11 skill 审批卡 UI → gateway token：`9ce7369dc`
  - §4.6 `/new` `/stop` 关掉 bot-menu ack：`c6156c16f`
  - §4.9 `/providers` 库存异步加载：`04387001a`
  - §4.11 queue 状态卡：`354222f43`
  - §7.14 `HERMES_PROFILE` / `HERMES_LIFECYCLE_LABEL`：`c0d01276f`、`f348617f9`
  - §12.4 `merge_loss_audit` + schema-split anchors：`e21239389`
- **附录 A/B**：queue_card / file_binary_detection_patch；adapter §4.14 + queue_card；model_switch 去重；lifecycle_guard / terminal_tool
- **刻意不记**：纯 docs / 纯 i18n / tips 清理 / merge main / 运维白名单注释 / 备份脚本静默与 ovpack / compare_skills 运维脚本 / 活 checkout skip update 测试

### 2026-09-16：skills 索引手动落盘可见性修复

- **类型**：bug 修复（新建正文 §7.22）
- **新建正文**：**§7.22** Skills 索引 LRU 命中按磁盘 manifest 复验（手动落盘 skill 免重启可见）：`48f8a6e6f8`
- **背景**：node010 手动 scp 部署的 kuaidi100-skill 在新会话的 `<available_skills>` 索引里不可见，agent 无视 skill 自行 curl 撞反爬；根因是 LRU 命中短路了磁盘快照校验层，缓存 key 不含磁盘状态
- **部署**：node010 pull + restart-all-gateways.sh（13 进程 0 失败）；部署后磁盘快照 137→138 条，实测索引含新 skill。此后手动落盘 skill 新会话即入索引，无需重启网关
- **附带修正**：viking 事件「kuaidi100-skill 同步部署」中「gateway 无需重启，新会话自动发现」的旧结论被本次案例证伪（当时只验证了 md5 + 手动跑脚本，未验证索引可见性）



### 2026-09-17：output_guard v2（degenerate 判定 + transcript 同步）

- **类型**：功能增强（新建正文 §14.1）
- **新建正文**：**§14.1** v2：degenerate 判定 + transcript 同步（切断乱码反馈环）：`9649e49275` / `6f042b3aac` / `ffc196ff8b` / `57a886171e`
- **背景**：2026-09-01 xy-max 乱码输出事故复盘；v1 三检测器全漏判（模板 token 泄漏/语料乱拼形态不在 v1 语义内），且 transform 钩子只修发送层、乱码落库后继续污染后续上下文
- **验证**：selfcheck 9 场景全绿 + 定向 pytest 9 passed + 真实样本回归 3/3（事故本体判退化、两条合法引用不误伤）
- **部署**：插件目录是仓内 owner-extensions 的符号链接，改仓内即生效；网关重启需手动（launchd ai.hermes.gateway）

### 2026-09-17：stream_guard（生成中退化闸门 + output_guard 三处收口）

- **类型**：功能增强（新建正文 §14.2）+ 核心薄 seam
- **新建正文**：**§14.2** 生成中退化闸门：stream_guard + 三处收口（thinking / 输出边界循环）：`dd4ab46bfb` / `1411019452` / `8bed0660f8`
- **背景**：2026-09-17 xy-max 单轮生成 30,742 字符的思考→输出阶段边界循环，持续 4 分 16 秒后由**人工 Ctrl-C** 结束。四道既有防线全落空：output_guard 事后判定、续写护栏未到边界、TurnLivenessWatchdog 被流式活动时钟喂饱而永不触发、钩子门槛 `not interrupted` **恰在被打断时失效**。缺的是进展（progress）看门狗。
- **方案**：C1 去掉钩子 `not interrupted` 门槛；C2 钩子与 transcript 回写前移到落库之前（append-only flush 无法改写已落库的非空行，故必须前移）；C3 钩子载荷补 `reasoning_text`、思考通道只告警不替换；P1 新增 `run_agent.py::_request_stream_stop` 薄 seam + `owner-extensions/stream_guard/` 插件（三信号滑窗投票，命中则中止本轮 + 告警）。
- **验证**：**8 条正例全命中 / 318 条真实长回复零误伤**；今日事故在生成到 50%（15,360 字符）即命中，早于人工打断约 2 分钟。pytest 14 + 7 + 4 全通过，selfcheck 通过。
- **部署**：`~/.hermes/plugins/owner-extensions` 是仓内符号链接，新增子目录即生效；插件仅对**新启动**的 agent 进程生效，需重启。
- **灰度**：`action: warn_only` 先行一周，按 `agent.log` 中 `stream_guard trip` 行的 `signals` 分布与误伤数决定是否切 `interrupt`。
