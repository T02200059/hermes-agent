# owner 改动清单（v2 todo · 从新开始）

> 生成：2026-10-23 · Asia/Shanghai  
> **不是**源清单 3000 行粘贴；从源清单提炼为可勾选 todo。

## 元信息

| 项 | 值 |
|----|----|
| 源清单 | `/Users/yangtb/.hermes/hermes-agent/owner/docs/owner改动清单.md` |
| 源仓 tip | `299e23205b66df082a2615aa1a4f3ed1edc69d25` |
| v2 worktree | `/Users/yangtb/.hermes/hermes-agent-v2` · 分支 `v2` |
| v2 tip（官方 main） | `3ba2b0787ed3a73ec3b08085ed0137f235209cf4` |
| 规范 | 同目录 `二次开发规范.md` |
| 实现顺序 | 同目录 `v2实现顺序.md` |
| 背景说明 | 同目录 `v2背景说明.md` |
| bug 对照提示词 | 同目录 `小模型-bug对照提示词.md` |

**原则**：① 先整体过 **§ Bug**，对照官方 main 填验证状态（已完成）；② 再落 **§ 定制**，**执行顺序以四阶段为准**（见下「落地顺序」与 [`v2实现顺序.md`](./v2实现顺序.md)）；P0/P1/P2 分组仅作优先级参考；③ yaml 整合穿插在定制落地时，不大爆炸；④ 部署继续 Linux 用户隔离，**不吃**官方 multiplex 换舰队路由；**C05 多 profile 仅第四阶段**。

**验证状态枚举**（bug 段）：`待对照官方 main` | `官方已修` | `仍存在/需自研` | `部分` | `不适用(纯 owner)` | `已退役`

勾选约定：`- [ ]` 未处理；`- [x]` 已结论（状态字段已填）。

## § 二次开发可复用基建（后续 AI 优先看）

> **开新能力前先扫本表。** 已落地的接现成入口；未落地的按「约定」接线，勿另起一套。  
> 细则仍以各 C 条目 / 设计稿为准；本节只钉**接哪、怎么调、挂哪配置**。

### 1. `overlay.yaml` 加载器 · **C01 · 已落地**

- **是什么**：owner 层统一配置入口；文件第一层键即能力段（**无**顶层 `owner:` / `patch:` / `overlay:` shell），运行时 fuse 进 `config.owner.*`。
- **入口**：`owner/patch_config.py`
  - `load_patch_config()` / `load_owner_config()` → 读 `~/.hermes/overlay.yaml`（本仓常软链到 `owner/config/overlay.yaml`）
  - `apply_owner_overlay(config)` → 官方 `load_config` 薄挂点后的叠层
  - `invalidate_owner_config_cache()` → 强制重读
  - 舰队/LDAP 另文件：`load_patch_feishu_profile_config()` → `patch_feishu_profile.yaml`（C05/C06）
- **配置**：读写一律 `config.owner.<section>.*` 或直接 `load_patch_config().get("<section>")`；新开关进对应 section，不要散落 `config.yaml`。
- **文件名**：运行时定制文件为 **`overlay.yaml`**（不再用 `patch.yaml`），与老版 owner 分支的 `patch.yaml`（含顶层 `owner:` 外壳）隔离；加载器**禁止**回退读 `patch.yaml`。
- **规范**：[`二次开发规范.md`](./二次开发规范.md) §2.2.1；[`v2背景说明.md`](./v2背景说明.md)「定制化 yaml」。

### 2. 飞书 name cache / user_store · **C04 · 已落地**

- **是什么**：`open_id` → 中文显示名 + p2p `chat_id`；24h soft TTL（过期不毁落盘名，避免卡面漏 `ou_xxx`）。
- **入口**：
  - `owner/feishu/user_store.py` — `FeishuUserStore`：`resolve_name` / `operator_display_name` / `pre_warm_name` / `get_p2p_chat_id` / `cache_p2p_chat_id`；工厂 `get_user_store(adapter)`
  - `owner/feishu/user_cache.py` — 落盘结构与 TTL 原语：`get_cached_display_name` / `set_cached_display_name` / `cache_p2p_chat_id` / `load_user_cache` / `save_user_cache`
  - 审批卡预热：`owner/feishu/approval.py` + `sender_name_helpers.py`（发卡前 `pre_warm`）
- **配置**：无独立 patch 段；路径随 adapter 缓存文件。需要显示名时走 store，**不要**再造进程内短 TTL dict。
- **与 bot 菜单关系**：`p2p_chat_id` 映射 + debounce/`atexit` flush 是菜单点击路由的前置；缺映射会表现为「菜单键未配置」。

### 3. skill 脚本自动审批 + skill_manage 飞书门 · **C09 · 已落地**

- **是什么**：本会话已 `skill_view` 的白名单 skill 脚本可跳过危险命令提示；飞书上 `skill_manage` 写操作走自建审批卡（YOLO 不绕过）。
- **入口**：
  - `owner/approval/skill_script_approval.py` — `track_session_skill_view` / `is_skill_script_allowed` / `reset_session_skills_viewed`
  - `owner/approval/skill_manage_gate.py` — `run_gate` / `should_escalate` / `apply_all_patches`
  - `owner/feishu/skill_approval_card.py` — `send_skill_approval_card` / `handle_card_click`
  - Hook 桥：`owner/owner-extensions/skill_manage_bridge/`（`pre_tool_call` + `pre_gateway_dispatch`）
- **配置**：`config.owner.approvals.skill_script_allowlist`（overlay.yaml）；`feishu.skill_approval`（**主读 overlay.yaml**；`patch_feishu_profile.yaml` 仅回落）
- **下游接线**：复用 C04 name cache / `send_card`；卡片 `hermes_action=skill_approval_gate`；永久按钮不展示（门内 `allow_permanent=False` + C01 策略）

### 4. Bot menu 按钮响应 · **C11-bot-menu · 已落地**

- **是什么**：飞书 `application.bot.menu_v6` 点击 → 三层去重 → overlay `feishu.bot_menu` 映射 → 合成 COMMAND/TEXT 入会话；缺 p2p 缓存时明确提示（不误报「未配置」）。
- **状态**：**已落地**。
- **入口**：
  - `owner/feishu/bot_menu.py` — `handle_bot_menu_event` / `resolve_bot_menu_command` / `admit_bot_menu_event`
  - adapter 薄胶水：`register_p2_application_bot_menu_v6`、`_on_bot_menu_event`、p2p/inbound `cache_p2p_chat_id` 暖缓存
- **配置**：`owner.feishu.bot_menu` / `owner.feishu.bot_menu_dedup`（`overlay.yaml`）
- **测**：`tests/owner/test_owner_feishu_bot_menu_cold_cache.py`
- **说明**：`owner/docs/c11-bot-menu.md`

### 5. C13 Explainers 统一配置与 auxiliary · **C13 · 已落地**

旧树三套顶层段（`progress_explainer` / `approval_explainer` / `english_explainer`）各自 `load_config` + 各自解析 provider/model。**v2 禁止再分叉**：配置与取模入口收成一套，三 kind 共用 helper。

#### 4.1 选定 schema（`owner/config/overlay.yaml` → `config.owner.explainers`）

```yaml
# 现网活键（见 owner/config/overlay.yaml；说明 owner/docs/c13-explainers.md）
explainers:
  # 共用默认；各 kind 可覆盖同名键
  provider: auto          # 空或 auto → 交给 call_llm auxiliary 链
  model: auto
  timeout_ms: 30000       # 统一毫秒；取代旧 explainer_timeout_ms / 混用 timeout_ms
  max_input_chars: 64000  # 设计前提：辅助模型 ≥256k 上下文；输入默认 64k
  progress:
    enabled: true         # 代码默认 false；本机活键 true
    # kind 专有：silence_seconds / min_interval_seconds / max_per_turn / platforms 等
  approval:
    enabled: true
    # kind 专有：cache_ttl_seconds / platforms 等
  english:
    enabled: true
    # kind 专有：platforms 等
  recap:
    enabled: true         # 第四 kind：/recap 按需回顾（notice；不写主会话）
    max_output_chars: 350
```

- **块名**：`explainers`（对齐清单「yaml 整合方向」）。
- **kind 子键**：`progress` / `approval` / `english` / `recap`（短、可扫；勿写成 `explainers.progress_explainer`）。
- **输入预算**：共用 `max_input_chars` 默认 **64000**（`owner.explainers.common.DEFAULT_MAX_INPUT_CHARS` / `clip_input`）；kind 可覆盖。按 **≥256k** 上下文模型设计。
- **旧键迁移目标**：顶层 `progress_explainer` 等 → 本块；超时键统一 `timeout_ms`（共用或 kind 覆盖）。
- **`call_llm` 的 `task=`**（与 config.yaml `auxiliary.*` 对齐，**保持长名**）：
  - `task="progress_explainer"` / `"approval_explainer"` / `"english_explainer"` / `"recap_explainer"`

#### 4.2 模型解析优先级（对齐旧约定，收口到一个 helper）

已走共享入口：`owner/explainers/llm.py` → `resolve_explainer_call(kind)` / `call_explainer_llm(kind, messages, **kw)`；包布局 `owner/explainers/{progress,approval,english,recap}/`，**禁止**各 kind 各写 provider/model 解析。

优先级（高 → 低）：

1. **patch** `explainers.<kind>.provider|model`（显式非空且非 `auto`）  
2. **patch** 共用 `explainers.provider|model`（显式非空且非 `auto`）  
3. 传给 `call_llm(task="<kind>_explainer", provider=None, model=None)` → 官方 **`config.yaml` `auxiliary.<task>.*`**  
4. auxiliary 未配 → **主聊天模型**（`call_llm` auto 链）

`timeout_ms`：kind 覆盖 > 共用 `explainers.timeout_ms` > 代码默认 30000；显式传入 `call_llm(timeout=...)`。

#### 4.3 与已落地基建的衔接（实现时复用，勿旁路）

| 依赖 | 用途 |
|------|------|
| **C14** `owner.stream_guard.snapshot(session_id, turn_id)` | progress：guard 已 `tripped` 则让位不发旁白 |
| **C11** `feishu_card.notice_titles` | 已预留 `🧭` / `🔤` / `📋 系统提示：` 前缀 → notice 卡 |
| **C11** `owner/feishu/card_sender.send_card` / `auto_card.make_notice_card` | 旁白投递 |
| **C04** 审批卡发送点 | approval 解说嵌卡（fail-open，超时无解说段照发） |
| **C01** `load_patch_config` | 只读 `explainers` 段 |

官方 auxiliary 链本身已存在（`agent.auxiliary_client.call_llm`）；C13 只约定 **task 名 + patch 块 + 共享 helper**，不另起 HTTP 客户端。参考已落地旁路：C17 `owner/checkpoint_predictor/llm_predict.py`（`task="approval"`）。

### 5. 同级已落地、开飞书/旁白时常接

| 基建 | 编号 | 入口（要点） | 配置 |
|------|------|--------------|------|
| 永久审批门 | C01 | `owner/approval/permanent_policy.py` → `gate_allow_permanent` / `get_allow_permanent` | `owner.approvals.allow_permanent`（默认 false） |
| 飞书 auto-card / notice / early-typing | C11 底座 | `owner/feishu/auto_card.py`（`try_auto_card` / `match_notice_rule` / `make_notice_card`）；`card_sender.send_card`；`agent_end.try_auto_card_on_end`；adapter early-typing | `owner.feishu_card.*` |
| 飞书 bot 菜单 menu_v6 | C11-bot-menu | `owner/feishu/bot_menu.py`（`handle_bot_menu_event`）；adapter 注册 + p2p/inbound 暖缓存 | `owner.feishu.bot_menu*` |
| 飞书 clarify 交互卡 | C11-clarify | `owner/feishu/clarify_card.py`（`send_clarify` / `retire_clarify_card` / `handle_clarify_card_action`）；`owner/clarify/gateway_helpers.py` | — |
| 飞书 /providers model picker | C26-feishu-picker | `owner/feishu/model_picker.py`（`send_model_picker_card` / `handle_picker_action`）；adapter `_model_picker_state` + card-action `hermes_model_picker` | — |
| stream / output guard | C14 | `owner/stream_guard.snapshot`；`owner/output_guard`（`transform_llm_output`） | `owner.stream_guard.*` / `owner.output_guard.enabled` |
| Checkpoint 预测 | C17 | `owner/checkpoint_predictor`（`predict_and_checkpoint`） | `owner.checkpoints.*` |
| 护栏 i18n | C10 | `owner/i18n/localized.py` → `localized` | locales + 调用方 `_localized` |
| 审批历史结构判定 | B11 | 与 C10 同批；历史挖掘勿再靠英文文案子串 | （见 `c10-b11-*.md`） |

---

---

## § Bug / 修复类（优先对照官方）

> 目标：区分「官方最新已修」vs「仍需我们带」。对照时在 v2 干净树搜代码/测例，**只读**。细节以源清单对应 § 为准。
>
> **对照基准**：v2 `56ab1b6d86`（= 官方 main `3ba2b0787e` + 2 个 docs）· 2026-10-23 完成 38/38 结论；随后本树落地 **O3–O8**、**B15 残留**、**B17 官方半边**（fork 自用、不提上游），B 段状态已回写。

### Provider / 模型切换

- [x] **B01** · 源 §2.2.1 · credential pool `_seed_from_env` 不校验 key 格式（`ghp_` 误入 copilot 等） · **验证状态：部分**
  - owner：`agent/credential_pool.py::_seed_from_env` 前缀门控（L3495）+ `hermes_cli/auth.py::ProviderConfig.api_key_prefixes`。v2：`KNOWN_PROVIDER_KEY_PREFIXES` 只声明 openrouter、只在 credential 解析路径生效，未接入 pool env seeding；copilot 因早退不再从 env 播种，alibaba-coding-plan 仍接受裸 `sk-` 的 `DASHSCOPE_API_KEY`。
- [x] **B02** · 源 §2.2.2 · provider discovery 慢探测（anthropic 无条件）+ 共享 models.dev 显示名退化 · **验证状态：官方已修**
  - owner：`hermes_cli/model_switch.py` 注释掉 `_cred_signal_slugs.add("anthropic")` + `get_label` 先查原 slug 。v2：discovery 重写为 `model_switch_providers.py`，无强制 anthropic 信号，catalog 走磁盘缓存/SWR+并行 prefetch（`non_blocking`），显示名统一 `get_label` + `_lossy_alias_registry_pdef`（`kimi-coding` / `-cn` 不再塌成同一名）。
- [x] **B03** · 源 §2.2.3 · env-only providers 未进 `/providers` 显示列表 · **验证状态：官方已修**
  - owner：`model_switch.py` 合并 env-only 行。v2：`_lap_canonical_rows`（section 2b）按 `api_key_env_vars` 存在即出行，env-only provider 可见。
- [x] **B04** · 源 §2.2.4 · 飞书 model_picker stale session 卡 loading / action_value 形态 · **验证状态：不适用(纯 owner)** · **依赖模块已迁（C26-feishu-picker）**
  - owner：`owner/feishu/model_picker.py` + adapter 薄胶水；过期走 toast（不空响应）。v2 已迁同模块（见 **C26-feishu-picker**）；官方飞书 adapter 本身仍无 picker，`model_picker_expired` 文案仅 Slack 用。
- [x] **B05** · 源 §2.8.1 · damodel `/model` 校验时 `${ENV}` 未展开导致 crash · **验证状态：官方已修**
  - owner：`hermes_cli/models.py::probe_api_models` 入口展开 `${VAR}` + 残留即返回 `models=None`。v2 不做模板展开，但每个候选 URL 都在 `try/except` 内，`unknown url type` 的 ValueError 被吞 → `models=None` → 静态 catalog 兜底，不 crash（净效果等价）。
- [x] **B06** · 源 §7.16 · merge 后 exhausted credential pool 语义被冲掉 · **验证状态：官方已修**
  - owner：`model_switch.py` 恢复 exhausted 短路分支。v2：`_credential_pool_is_usable` 明确「all-exhausted/dead pool 不算 authenticated」（picker 例外保留 cooldown 行）。

### 审批 / 安全

- [x] **B07** · 源 §3.7 · CR-001~006 安全加固（path-token `\\n`、cron allowlist mtime 等） · **验证状态：部分**
  - 对照更新：CR-001 经 **O1** 实测为 no-op（`_PATH_TOKEN_STOP` 已含 `\s`，再加 `\n\r` 无差）——不再当缺陷。仍存设计面：CR-004（`gateway/run.py:362` raw-text 平台集；**O2** 判定不改）。已修：CR-003、CR-005。纯 owner：CR-002、CR-006。
- [x] **B08** · 源 §3.8 · SSRF（非 http scheme）+ Feishu user_name sanitize · **验证状态：部分**
  - SSRF 官方已修且更强：`tools/url_safety.is_safe_url` 拒非 http(s) + 私网/元数据 + 重定向逐跳校验，`provider_media.save_url` 全 hop 校验。user_name sanitize 属 owner 自建 inbound context（`owner/feishu/inbound_context.py`），v2 无该块。
- [x] **B09** · 源 §3.10 · QQ DM 审批按钮鉴权（`dm` vs `c2c`） · **验证状态：官方已修**
  - owner：`gateway/platforms/qqbot/adapter.py:1216` 把 `{"c2c","dm"}` 同等处理。v2：`plugins/platforms/qqbot/adapter.py::_is_authorized_interaction_for_session` 同判据，含「approval 键来自 build_source(dm)、update-prompt 来自 scene(c2c)」注释。
- [x] **B10** · 源 §3.12 · `_mask_quoted_newlines` 命令替换绕过硬黑名单；queue token 未 retire · **验证状态：部分**
  - mask 半边官方已修：v2 `_mask_quoted_newlines_span` 递归进入 `$(...)` / 反引号。queue token retire 属 `owner/patches/queue_cancel_patch.py`，v2 无对应模块。
- [x] **B11** · 源 §3.13 · 审批历史挖掘依赖英文文案，i18n 后漏检（应改结构标记） · **验证状态：已修（与 C10 同批）**
  - helper：`owner/approval/approval_history_policy.py`（status/outcome → catalog 片段 → 英+中兜底；`sql_like_anchors` 与判定同源）
  - 胶水：`hermes_cli/approvals_suggest.py` `_blocked_tool_call_ids`（owner 不可用时回落 `_BLOCK_MARKERS`）
  - 测：`tests/owner/test_approval_suggest_i18n_blocks.py`

### TUI / CLI 稳定性

- [x] **B12** · 源 §6.3 · Ctrl+C /exit 与 graceful drain（SIGINT 逃出清理链） · **验证状态：仍存在/需自研**
  - owner：`cli.py` OS SIGINT 路由到 `app.exit()`（26 处中断处理）+ TUI 先 session-end 再 MCP teardown。v2：`cli.py` 仅 2 处提及 KeyboardInterrupt、无 SIGINT handler；`tui_gateway/entry.py` 把 SIGINT 设 `SIG_IGN`、SIGTERM 只 `_log_signal`。
- [x] **B13** · 源 §6.4 · live compression sync 误清 per-model `context_length` · **验证状态：官方已修**
  - owner：`tui_gateway/server.py` 缺顶层时回退 `get_custom_provider_context_length`。v2：`tui_gateway/session_compression.py` + `agent_init.config_context_length_for_runtime`，引脚缺失时强制重新推断，`get_model_context_length` 步骤 0c 精确匹配 `providers.*.models`。
- [x] **B14** · 源 §7.20 · 后台插件发现超时死锁（启动空白屏） · **验证状态：官方已修**
  - owner：`discover_and_load` 改 `acquire(timeout=15)` + join 超时直接返回。v2 本树已用 **O3**：`_TimedLock` 15s + join 超时返回 bool，不再无限持锁空白屏。

### Gateway / Agent 运行时

- [x] **B15** · 源 §7.1 · QQ Bot WebSocket 重连链不稳 · **验证状态：官方已修**
  - owner：`_stop_retry` + `receive_timeout=120` + `_rebuild_http_client`。v2：重连链已重写（backoff、close-code 分类、`is_reconnect` kwarg、`disconnect()` 置 `_running=False` 停止重试）；**O4** 已补读路径 `wait_for` 90s + 心跳静默关 socket；本批补 **`_rebuild_http_client`**（重连前关旧 httpx + `platform_http_client()` 新建 + 清 OAuth 缓存）。见 §「v2 已落地官方 fix」。
- [x] **B16** · 源 §7.5 · executor-shutdown 不友好提示 · **验证状态：官方已修**
  - owner：`owner/gateway/turn_helpers.py::is_executor_shutdown_error` → 友好重启提示。v2：`agent/turn_loop_errors.py` 识别 interpreter/executor shutdown 后走 `site_copy("interpreter_shutdown", resume=…)`，不再抛裸 RuntimeError。
- [x] **B17** · 源 §7.6 · Clarify 清理路径缺 stop sentinel / 飞书 clarify 超时未中断 · **验证状态：部分**
  - **官方半边已修**：`CLARIFY_STOP_SENTINEL`（= `clarify_gateway.CANCELLED`）+ `wait_for_response` 在 entry 消失 / event 空应答时返回 CANCELLED（不再伪造成用户超时）。见 §「v2 已落地官方 fix」。
  - **飞书半边仍待 C 段/混合**：adapter 超时中断 agent loop + 超时补发提示属 owner 胶水，本批**不做**。
- [x] **B18** · 源 §7.9 · 429 配额耗尽被当 transient 静默重试；长等待无即时状态 · **验证状态：官方已修**
  - owner：`error_classifier.py` `_has_long_reset_window` 单向降级 + `conversation_loop.py` `wait_time >= 60` 立即出状态。v2 本树已用 **O5**：天/周配额墙单向降为 billing，不再白等。即时状态（≥60s 立即出）未单独追平，主痛点（长墙当 transient）已消化。
- [x] **B19** · 源 §7.10 · 运行中 agent 时 plugin 斜杠命令被当普通文本注入 · **验证状态：官方已修**
  - owner：running-agent guard 增 `is_gateway_known_command()`。v2：`gateway/run_busy.py::_busy_skill_turn` 用同一函数把已注册（含 plugin）命令排除出 busy-input 改写路径。
- [x] **B20** · 源 §7.11 · `/memory` `/skills` 不能 mid-turn · **验证状态：官方已修**
  - owner：二者加入 `GATEWAY_KNOWN_COMMANDS` + guard 豁免。v2：`memory` 为 gateway 命令（非 cli_only）、`skills` 带 `gateway_config_gate` 故入 `GATEWAY_KNOWN_COMMANDS`；`should_bypass_active_session` 对任何 `resolve_command` 命中即放行。
- [x] **B21** · 源 §7.12 · gateway restart 未清 `__pycache__` 致 ImportError · **验证状态：官方已修**
  - owner：restart watcher 内 `find … __pycache__` + Python 侧遍历清理。v2：改为启动时 `_sweep_stale_bytecode_if_checkout_changed()`（`hermes_cli/main.py:3477`）按 checkout 指纹扫一次，覆盖同一失效面（restart 也是新进程启动）。
- [x] **B22** · 源 §7.15 · Codex Responses reasoning 后空 `assistant content` 被严格网关拒 · **验证状态：官方已修**
  - owner：`codex_responses_adapter.py` 有 tool_calls 则跳空、否则发空格占位。v2 同一处理：`follower = " " if fallback == "" else fallback`，且注释明确「strict providers reject "" with 400」。
- [x] **B23** · 源 §7.19 · lifecycle guard 遇二进制路径 `embedded null byte` 崩溃 · **验证状态：官方已修**
  - owner：按 syscall 逐个 catch。v2：`cron/lifecycle_guard.py::_expand_candidate_path` 在 ingestion 边界一次性拒 NUL/烂 token（注释点名整类修复 #76762/#77703/#77780/#78256）。
- [x] **B24** · 源 §7.21 · 出站 `message_id` 不落库 / 难撤回编辑 · **验证状态：官方已修**
  - owner：`delivery_ledger` 加 `platform_message_id` 列 + `mark_delivered(oid, message_id)`。v2 本树已用 **O6**：CREATE+ALTER 落列 + `mark_delivered(oid, message_id)` + `platform_message_id_for()`。
- [x] **B25** · 源 §7.22 · Skills 索引 LRU 命中不按磁盘 manifest 复验（手动落盘 skill 不可见） · **验证状态：官方已修**
  - owner：缓存值带 manifest，命中时重建比对。v2：manifest 直接进 `cache_key`（`agent/prompt_builder.py:1405` `files` 元素），磁盘一变即 miss 重建。
- [x] **B26** · 源 §7.23 · `/stop` 打在 runner 构造窗口留下孤儿轮次占租约 · **验证状态：官方已修**
  - owner：`gateway/run.py::track_agent` stale 分支 5 行委托 + `owner/patches/stop_orphan_run.py`。v2 本树已用 **O7**：stale 分支 `_cancel_stale_run()`（`request_hard_interrupt`，按 session_key+generation 去重）。
- [x] **B27** · 源 §7.27 · 出站 DeepSeek BOS/EOS 可见泄漏 · **验证状态：官方已修**（终局）；interim 见 **C08**
  - owner：outbound BOS/EOS scrub。v2 本树已用 **O8**：`_strip_deepseek_special_tokens` 接入 `_sanitize_gateway_final_response`。**C08** 补 interim/status 薄挂点（复用 O8，不重写 scrub）。

### 工具链 / Desktop / 性能

- [x] **B28** · 源 §8.2 · read_file/search_files 无单执行超时 · **验证状态：官方已修**
  - owner：`owner/file_tool_timeout.py` 按终端 env 预算（默认 180s）单独守 read_file/search_files。v2：`agent/tool_executor.py::_resolve_sequential_tool_timeout` 对**每次顺序工具调用**套 `timeouts.tools.sequential_call`（默认回落 420s，`0` 关闭），read_file/search_files 不在豁免集，已被通用 deadline 覆盖；若要对齐 180s 体验，只需配 `timeouts.tools.sequential_call: 180`，无需代码。
- [x] **B29** · 源 §8.3 · delegate_task batch ACP 变量 NameError · **验证状态：官方已修**
  - owner：fallback 只用 `t.get("acp_command")` / `creds.get(...)`。v2 `delegate_tool.py` 已改 `override_acp_command` + `creds.get("command")`，无越界局部变量引用。
- [x] **B30** · 源 §8.5 · read_file UTF-8 边界误判 binary · **验证状态：官方已修**
  - owner：运行时 patch 剥尾部 U+FFFD。v2 原生 `_is_likely_binary_bytes`（`tools/file_operations.py:445`）：允许末尾一个不完整多字节序列，中部非法仍判 binary（#80308），read 路径已用它。
- [x] **B31** · 源 §13.1 · Windows 透明度档位过激 · **验证状态：官方已修**
  - owner：`translucency.cjs` `opacityForIntensity(intensity, isWindows)`，macOS 逐字节不变、Windows 走缓曲线。v2 换成全局二次曲线 `1-0.7*ratio^2`（`apps/shared/src/translucency.ts:386`）：5% 档位落到 0.998（原 0.965），可读区间不再挤在头几个百分点，Windows「几乎半透明」症状消失。差异仅在曲线族（非平台感知、macOS 取值随之改变），不再是缺陷。
- [x] **B32** · 源 §16.7 · output_guard 复读判据 O(n²) 拖住长回复 · **验证状态：不适用(纯 owner)**
  - owner：`owner/owner-extensions/output_guard/__init__.py` 线性扫描替代 `(\S+)( \1){5,}` 正则。v2 的 `agent/repetition_guard.py` 是另一套算法（倍增窗口），无该正则。

### API Server / LDAP 门（安全修复向）

- [x] **B33** · 源 §15.3 · seen 缓存状态机权限提升 · **验证状态：不适用(纯 owner)**（官方无 LDAP 则「不适用」或「仍需自研」）
  - 官方无 §15 identity/seen 模块。v2 只有社区 `dashboard-auth-ldap` 插件（Web 面板登录），与我们的 API Server 准入面不同；重放时随 C06 一起带。
- [x] **B34** · 源 §15.8 · `enforce=seen` fail-closed · **验证状态：不适用(纯 owner)**
  - 同上：v2 无 `enforce=seen` 语义（`grep seen` 只命中无关的 room event_seq）。
- [x] **B35** · 源 §15.9 · 带密码但无法验证时默认 fail-open 过宽 · **验证状态：不适用(纯 owner)**
  - 同上，官方无该判定分支。
- [x] **B36** · 源 §15.10 · 认证门在路由之后可被白名单/错配绕过 · **验证状态：不适用(纯 owner)**
  - 同上，v2 无 `identity_routes` / 门前移逻辑；重放 C06 时一并实现。

### 标记为「多半纯 owner / merge 债」（仍要填状态）

- [x] **B37** · 源 §7.7 · `_owner_import` 不缓存瞬时 ImportError · **验证状态：不适用(纯 owner)**
  - `_owner_import` 是我们写在官方文件里的 helper（`plugins/platforms/feishu/adapter.py:175`、`gateway/platforms/api_server.py:217`），v2 无此符号；重放时直接带改好的版本。
- [x] **B38** · 源 §7.13 / §7.17 · merge 后死代码与 display resolution wiring 恢复 · **验证状态：不适用(纯 owner)**（重放时再验）
  - merge 债条目：v2 无 `resolve_display_setting_for_source`（per-chat display override 属 C18），无 `_append_inbound_context` 同名接线，无从对照；随 C18 重放时验。

**Bug 段合计：38 条。**

**结论分布**：官方已修 23 · 部分 5 · 仍存在/需自研 2 · 不适用(纯 owner) 8。（O3–O8 后本批：B15 部分→官方已修；B17 仍存在→部分。B11 已与 C10 同批落地；仍剩硬挂/可选 B12。）

---

## § 纯官方 bug 待办（v2 可直接改官方代码 / 可上游化）

> 筛选口径：① 官方最新 main 仍有缺陷；② bug 位于**官方功能代码**，修法不需要 `owner/` 能力包或胶水；③ 不含「功能本身是我们自建」的条目（model_picker、inbound context、LDAP 门、output_guard、`_owner_import`、per-chat display、queue 卡）。
>
> **状态：O 段 9 条已分流完毕（6 修 + 1 撤回 + 2 不改）；另续做 B15 残留 + B17 官方半边。** 详见下方与 §「v2 已落地官方 fix」。
>
> **范围声明**：以上 fix **仅留在本 fork 的 `v2` 分支自用**，**不提上游**、不做 PR。与二次开发规范一致：先修官方树上的自有缺陷，再重放定制。

### 已实施（6 条）

| # | 状态 | 改动 | 落点 | 回归 |
|---|---|---|---|---|
| O3 | ✅ 已修 | `_TimedLock` 限时上下文管理器（15s）+ join 超时返回 bool；`discover_plugins` 增量调用不再抢锁、`_go_live` 同样限时 | `hermes_cli/plugins.py`（`_TimedLock`、`discover_and_load`、`_join_background_discovery`、`_delivery_manager`）、`hermes_cli/plugins_activation.py` | 新增 7 例 + 既有 127 例 |
| O4 | ✅ 已修 | 读路径 `wait_for` 90s 上限；`_last_frame_at` 记录任意入站帧；heartbeat 静默超 2.5 个周期即关 socket 唤醒重连 | `plugins/platforms/qqbot/adapter.py` | 新增 5 例 + 既有 55 例 |
| O5 | ✅ 已修 | 天/周级配额墙单向降级为 billing（词法 + reset 字段 ≥1 天）；显式 rate-limit 文案仍优先 | `agent/error_classifier.py`（`_LONG_QUOTA_WINDOW_RE`、`_quota_window_exceeds_retry_horizon`） | 新增 5 例 + 既有 191 例 |
| O6 | ✅ 已修 | `platform_message_id` 列（CREATE TABLE + ALTER 对账两处）+ `mark_delivered(oid, message_id)` 双 UPDATE 语义 + `platform_message_id_for()` 查询 + 两处调用点透传 | `gateway/delivery_ledger.py`、`gateway/platforms/base.py`、`gateway/run_startup.py` | 新增 7 例 |
| O7 | ✅ 已修 | stale 分支补 `_cancel_stale_run()`：`request_hard_interrupt` 中止孤儿轮次，按 `(session_key, generation)` 去重、fail-open | `gateway/run_turn.py` | 新增 6 例 + 既有 130 例 |
| O8 | ✅ 已修 | `_strip_deepseek_special_tokens()`：全角 `｜`+`▁` 字形串任意位置剥离，纯特殊符→空串；`local` 仍 passthrough | `gateway/platforms/base.py`、`gateway/run.py`（`_sanitize_gateway_final_response`） | 新增 17 例 + 既有 183 例 |

### 撤回（1 条：不是缺陷）

- **O1**（CR-001 路径 token 换行）— **实测为 no-op**。`_PATH_TOKEN_STOP` 已含 `\s`，而 `\s` 覆盖 `\n\r`；把 `\n\r` 再拼进字符类对正则毫无影响。实测 `cat /foo\n/home/alice/.hermes/.env` 在「原版」与「修复版」下折叠结果逐字节相同（都得到 `cat /foo\n~/.hermes/.env`）。当年 commit 自述的 verification 误判。**不改**。

### 不改（2 条：属设计决策，非 bug）

- **O2**（`_GATEWAY_RAW_TEXT_PLATFORMS` 收窄）— 官方有明确表态：测试 `test_programmatic_surfaces_keep_raw_status` 断言 `api_server`/`webhook`/`msgraph_webhook` **必须**保留 raw 诊断文本（docstring 原文 "must keep raw diagnostics"）。收窄会推翻该设计并破坏 programmatic 消费方语义。CR-004 的论证（webhook 未认证 POST 可诱导错误泄漏凭据）仍有价值，但需上游讨论或实证，不应单方面改。
- **O9**（coding-plan 共享 `DASHSCOPE_API_KEY`）— 官方把该变量**有意**设计为该 provider 的 fallback alias（`api_key_env_vars` 的 index≥1），并有测试断言 `provider_primary is False`。属我们的部署偏好（希望更严格），在 v2 不设该变量即可规避，不需改官方代码。

### 次级（需先解决口径，暂不实施）

- **B17**（clarify）：**官方半边已落地**（见下表）；飞书 adapter 超时中断 agent 仍属混合，跟 C 段，不当第一步硬开。
- **B12**（CLI OS 级 SIGINT）：v2 已用 prompt_toolkit `c-c` 覆盖按键层，且 `hermes_cli/cli_terminal_input.py:394` 明确表态「raw mode clears ISIG，内核 INTR 路径从未涉入 CLI」——上游认为无需处理。我们的场景（子 shell PTY 回弹 / 后台线程投递 SIGINT）上游大概率判 invalid，需先备证据再提。
- **B11**（审批历史按英文文案判定）：**已与 C10 同批落地**（结构标记三层判定）。

---

## § v2 已落地官方 fix（fork 自用 · 不提上游）

> 本树在干净官方代码上直接改的缺陷修复。**不提上游 PR**。产品 `owner/` 代码未动（仅 docs）。

| 批次 | 条目 | 改动摘要 | 落点 | 回归 |
|------|------|----------|------|------|
| O3–O8 | O3 | 插件发现 `_TimedLock` 15s + join 超时返回 bool | `hermes_cli/plugins.py` 等 | 见 O 段表 |
| | O4 | QQ WS 读超时 90s + 心跳静默关 socket | `plugins/platforms/qqbot/adapter.py` | 见 O 段表 |
| | O5 | 天/周配额墙单向降为 billing | `agent/error_classifier.py` | 见 O 段表 |
| | O6 | 出站 `platform_message_id` DDL + mark_delivered | `gateway/delivery_ledger.py` 等 | 见 O 段表 |
| | O7 | `/stop` stale 分支 cancel 孤儿 run | `gateway/run_turn.py` | 见 O 段表 |
| | O8 | 出站 DeepSeek BOS/EOS scrub | `gateway/platforms/base.py` 等 | 见 O 段表 |
| B15 残留 | B15 | `_rebuild_http_client`：重连前关旧 httpx、`platform_http_client()` 新建、清 token | `plugins/platforms/qqbot/adapter.py` | `tests/gateway/test_qqbot_ws_liveness.py` +2 |
| B17 官方半边 | B17 | `CLARIFY_STOP_SENTINEL`（= `CANCELLED`）；entry 消失 / 空 event → CANCELLED，真超时仍 `None` | `tools/clarify_tool.py`、`tools/clarify_gateway.py` | `tests/tools/test_clarify_gateway.py`（StopSentinel 组） |
| （不做） | B17 飞书半边 | adapter 超时中断 agent + 超时补发提示 | — | 待 C 段/混合 |

O3–O8 代码 commit：`acbc2074c5`。B15/B17 见本批随后 commit。

---

## § 落地顺序（四阶段）

> **执行顺序以本表 + [`v2实现顺序.md`](./v2实现顺序.md) 为准。**  
> 下方「P0 / P1 / P2」分组仍保留作**优先级参考**（现网必保 vs 可后移），但**不要**再按 P0→P1→P2 当落地节奏。  
> Bug 对照与 O/B15/B17 官方半边已完成；定制从阶段一起步。

| 阶段 | 主题 | 条目（保留原 C 编号） |
|------|------|----------------------|
| **一** | 非渠道 / 终端 / 加载器 | **C01**（最先）→ C02 → C08 → C03 → **C26** → C21（未展开）→ C16 → C17 → C19 → C18 → C14 → C13 → C22（可选）；旁注 B12 不强制 |
| **二** | 飞书**核心**底座 | **C04**（审批卡 + 中文名/sender 缓存 + inbound + 签名）→ **C10**（+B11 同批）→ **C11 底座**（auto-card / early-typing）；diff/clarify/bot 菜单可延阶段三 |
| **三** | 飞书定制 + 杂项 | **C09**（依赖 C04）→ C11 余下 → **C12** → C15 → C25（`/providers` 已归 C26）→ **C06** LDAP / **C07** API media → C20 → C23 → **B17 飞书半边**；**C24** 全量战役不排 |
| **四** | 飞书多 profile | **仅 C05**（`profile_endpoints` / bots 路由；不吃 multiplex）。勿提前；与阶段三 LDAP **文件边界**分开 |

**依赖速记**：C01 万物前置 → 阶段二 C04 先于一切飞书体验/skill 门 → C09/C12 依赖 C04 → **C05 最后**。yaml 随 C01 / 阶段三 LDAP / 阶段四路由穿插缩文件，不大爆炸。

---

## § 定制功能类（bug 对照完成后再落）

> **落地节奏见上方「落地顺序（四阶段）」**，勿按本组标题当执行顺序。  
> 本组仍按 P0 必保 / P1 可后移 / P2 暂缓标优先级，便于对照源清单。路由：**维持自研**跨进程转发，不对齐吃官方 multiplex；**C05 仅第四阶段**。


### 已落地功能点（目录）

| 编号 | 功能点 | 要点 |
|------|--------|------|
| **C01** | patch + 审批 + 归因骨架 | `patch_config` / 永久审批禁用 / `attribution` |
| **C02** | 归因整链 + credential + token 用量 | 透传与剥离；credential 合并；sessions/messages 四列 token |
| **C08** | 出站 BOS/EOS | 终局 O8 + interim/status 薄补 |
| **C03** | damodel provider/proxy | `owner/providers/damodel.py` + model-providers 插件 |
| **C26** | providers 白名单 / 缓存 TTL / `/providers` | 白名单沿用官方；TTL 24h + 无变更不写盘；斜杠命令；飞书卡见 **C26-feishu-picker** |
| **C16** | Cron env 隔离 | **官方已修**：ContextVar + `_CronRunScope`；审批 ContextVar 感知 |
| **C17** | Checkpoint Mutation Predictor | `owner/checkpoint_predictor/`；tool_executor terminal 薄胶水 |
| **C19** | 链式快捷命令 `;;` + Quick Alias | `owner/commands/chained_quick.py`；CLI/gateway/TUI 薄胶水 |
| **H01** | 官方 test 污染梳理 | 优先项已修（#1/#2/#5/#6/#7 R1/#10 等） |
| **H02** | CLI `input()` 僵尸 reader | 延后 |
| **C12-at-all** | 群 `@_all` 不再当提到自己 | `_mentions_self` 极小 P2；官方测已改 |
| **C12-upload-guard** | 出站图/文件超限中文提示 | `owner/feishu/media_guard.py` + adapter 薄胶水 |

### P0 必保

- [x] **C01** · 源 §1.1–1.4 · `overlay.yaml` 统一加载器 + 审批白名单合并 + 归因骨架 · **优先级：P0**
  - 记：运行时文件已改名为 **`overlay.yaml`**，与老版 `patch.yaml` 隔离（加载器不回退读旧名）。
  - 落地：
    1. `owner/patch_config.py` + `config.owner` 叠层（官方 config 薄 overlay）
    2. `owner/approval/permanent_policy.py`（飞书/QQ 永久审批禁用；官方 approval 薄委托）
    3. `owner/attribution.py`（官方 agent_init / chat_completion_helpers / run_agent / messages 薄委托）
- [x] **C02** · 源 §2.1–2.2（credential）+ §10 token 用量数量落盘 · **优先级：P0**
  - 落地：
    1. 归因整链透传 + `api_messages` 剥离（runtime/oneshot/cli/tui/gateway/cron/delegate/mid-switch）
    2. `owner/providers/credential_helpers.py`；`model_switch_providers` 薄委托
    3. `sessions.owner_provider_name` + messages 四列 token 用量落盘
  - **2026-10-27 补丁**：`PERSISTENCE_ONLY_MESSAGE_FIELDS` 增 `model`/`provider`（出站剥离；不落盘 DDL）；attribution docstring 改为「仅内存」
- [x] **C03** · 源 §2.7–2.8 · damodel provider/proxy · **优先级：P0**
  - 落地：`owner/providers/damodel.py` + `plugins/model-providers/damodel/`；测 `tests/owner/test_damodel_provider.py`
  - **C03+ 2026-10-27**：`is_damodel_route` + `anthropic_prompt_cache_policy` 3 行 `# [owner]` 委托，恢复 damodel cache_control（成本回归）；thinking/extra_body 仍延后
- [x] **C04** · 源 §3.1–3.4 · 飞书审批卡片 + sender_name 缓存 + inbound 身份 + 多平台审批签名 · **优先级：P0**（阶段二首项）
  - helper：`owner/feishu/{approval,user_store,user_cache,sender_name_helpers,inbound_context}.py` + `owner/gateway/inbound_context.py`
  - 胶水：`plugins/platforms/feishu/adapter.py`（委托 + 24h soft TTL + store migrate）；`gateway/run_inbound.py`；`gateway/run_turn_runner.py`（metadata sender）；`cron/scheduler.py`（Cron context）
  - locales：`platform.feishu.approval.fail_*` / `operator_fallback`
  - 发送仍官方 ExecApprovalPrompt；C01 `gate_allow_permanent` 继续管 Always 按钮
  - 设计：`owner/docs/design/feishu-approval-base/README.md`
  - 测：`tests/owner/test_c04_feishu_base.py`；官方 `test_feishu_approval_buttons.py` 对齐冻结卡 / soft TTL
- [ ] **C05** · 源 §4.1 · **飞书多 profile 舰队路由**（`profile_endpoints` HTTP 转发；**不吃**官方 `profile_routes`） · **优先级：P0**
- [ ] **C06** · 源 §15.1–15.6 · API Server LDAP 身份准入 + identity_routes + 头剥离/SSE · **优先级：P0**
- [ ] **C07** · 源 §16.1–16.6 · API 产物媒体 / `hermes.files` / tool.progress 脱敏与归属 · **优先级：P0**
- [x] **C08** · 源 §7.27 · outbound BOS/EOS scrub · **优先级：P0**
  - 落地：终局走官方 O8；interim/status 薄补复用 `_strip_deepseek_special_tokens`（`owner/outbound_special_token_scrub.py` + stream_delivery / gateway status 胶水）
  - 测：`tests/owner/test_outbound_special_token_scrub.py`
- [x] **C09** · 源 §3.6 / §3.11 · skill 脚本自动审批 + skill_manage 飞书审批门 · **优先级：P0**（阶段三）
  - skill 脚本：`owner/approval/skill_script_approval.py`；`approvals.skill_script_allowlist`；胶水 `tools/approval.py` + `tools/skills_tool.py`
  - skill_manage 门：`owner/approval/skill_manage_gate.py` + `owner/owner-extensions/skill_manage_bridge/`；卡 `owner/feishu/skill_approval_card.py`
  - 配置：`feishu.skill_approval`（**主读** `overlay.yaml`；`patch_feishu_profile.yaml` 仅回落；默认 enabled:false）
  - 适配：超时补丁挂 `tools.approval_context._get_approval_timeout`；发卡走 `send_card`；adapter `_on_card_action_trigger` 薄分支
  - 设计：`owner/docs/design/skill-approval/README.md`
  - 测：`tests/owner/test_skill_script_approval.py` / `test_skill_manage_gate.py`
  - **2026-10-27 补丁**：skill_approval 迁入 overlay（含旧树 `approval_home_chat_id` 真值）；脚本白名单增加「绝对/相对路径须落在 skill 目录内」
- [x] **C10** · 源 i18n 层 · 显示层 i18n / `_localized` 与护栏文案（源 §12.2 / §16.9 相关） · **优先级：P0**（阶段二 · 与 B11 同批）
  - helper：`owner/i18n/localized.py`（`localized` / `GUARD_EN_TEXTS`）
  - 胶水：`tools/file_tools_write_guards.py`（受保护指令 / SSH 配置写入护栏走 `_localized`/`_blocked`）
  - locales：`approval.protected_file_*` / `ssh_config_*` / `gate_why_*`（en↔代码漂移守卫）
  - 说明：`owner/docs/c10-b11-i18n-approval-history.md`
  - 测：`tests/owner/test_file_tools_guard_text_i18n.py`
  - 范围：护栏文案层（T2-12）；非废弃的 display_filter；官方 `tools/approval.py` agent-facing 大段英文模板未整迁（B11 已用 summary.* + 护栏键 + 兜底覆盖历史挖掘）

### P1

- [x] **C11 底座** · 源 §4.2–4.3 · auto-card / early-typing · **优先级：P1**（阶段二）
  - helper：`owner/feishu/auto_card.py` / `agent_end.py` / `card_sender.py`
  - 配置：`owner/config/overlay.yaml` → `feishu_card.*`（threshold / split / notice_titles）
  - 胶水：`plugins/platforms/feishu/adapter.py`（`send` try_auto_card / `send_card` / early-typing）；`gateway/run_turn.py`（`try_auto_card_on_end` + progress bubble 标记）
  - 说明：`owner/docs/c11-feishu-auto-card-base.md`
  - 测：`tests/owner/test_c11_auto_card.py`、`tests/owner/test_feishu_agent_end_media.py`
  - 依赖：C04 已落地；卡发送复用官方 `_feishu_send_with_retry` / `_finalize_send_result`
- [x] **C11-bot-menu** · 源 §4.6 · bot 菜单 menu_v6 + p2p 暖缓存 · **优先级：P1**（阶段三）· **已落地**
  - `owner/feishu/bot_menu.py`；adapter 注册/委托 + p2p/inbound cache warm；`overlay.yaml` → `feishu.bot_menu*`
  - 测：`tests/owner/test_owner_feishu_bot_menu_cold_cache.py`；说明：`owner/docs/c11-bot-menu.md`
- [x] **C11-clarify** · 源 §4.5 · Feishu clarify 交互卡 · **优先级：P1**（阶段三）· **已落地**
  - `owner/feishu/clarify_card.py` + `owner/clarify/gateway_helpers.py`；adapter `send_clarify` / `retire_clarify_card` / card-action `clarify_id` 分支
  - 测：`tests/owner/test_c11_clarify_card.py`；说明：`owner/docs/c11-clarify.md`
- [x] **C26-feishu-picker** · 源 §4.9 · Feishu `/providers` 模型切换交互卡 · **优先级：P1**（阶段三）· **已落地**
  - `owner/feishu/model_picker.py`；adapter `send_model_picker_card` / `_handle_model_picker_action` / `_model_picker_state`
  - 测：`tests/owner/test_c26_model_picker.py`；说明：`owner/docs/c26-model-picker.md`
- [ ] **C11-diff** · 源 §4.4 · Feishu diff 卡 · **忽略（不做）**
- [ ] **C12** · 源 §4.10–4.15 · memory write-approval 卡 / feishu-guide / 上传守卫 / doc_read 图 OCR / @所有人 / merge_forward · **优先级：P1**（子点分批；本轮 C12-at-all + C12-upload-guard；**C12-memory-approval 忽略（不做）**）
  - [x] **C12-at-all** · 源 §4.14 · 群 `@_all`（@所有人）不再当提到自己 · **优先级：P2** · **已落地**
    - 意图：群里发 `@所有人` 只是通知大家，不应自动开一轮；须明确 @机器人（或其它策略）才触发
    - 胶水：`plugins/platforms/feishu/adapter.py` `_mentions_self`（极小 P2：去掉 `@_all → True`；`# [owner] C12-at-all`）
    - 测：`tests/gateway/test_feishu.py` `TestGroupMentionAtAll`（allowlist + 仅 `@_all` → 拒；显式 @bot → `_mentions_self` True）
    - 验证：`python -m pytest tests/gateway/test_feishu.py::TestGroupMentionAtAll -q`
    - 影响面：仅 mention 门；不改 `_build_mentions_map` 的 `is_all` 记录，也不改文本 `@all` 渲染
  - [x] **C12-upload-guard** · 源 §4.11 · 出站图/文件超限中文提示 · **优先级：P1** · **已落地**
    - 意图：出站图/文件超飞书上限（图 10MB / 文件 30MB）或 SDK 空体崩时，用户看到中文提示，而非静默失败
    - helper：`owner/feishu/media_guard.py`（预检 + 异常翻译；提示经 `send_media_guard_hint` 由 adapter 委托发出）
    - 胶水：`plugins/platforms/feishu/adapter.py` `send_image_file` / `_send_uploaded_file_message`（try-import 预检与异常翻译；`_send_media_guard_hint` 委托；`# [owner] C12-upload-guard`）
    - 测：`tests/owner/test_c12_upload_guard.py`
    - 验证：`python -m pytest tests/owner/test_c12_upload_guard.py -q`
    - 影响面：仅出站图/文件上传失败可见性；不改上传 API 成功路径、不改入站媒体、不改限值以外策略
  - [ ] **C12-memory-approval** · 源 §4.10 · memory 写入飞书审批卡（依赖 C04）· **忽略（不做）** · 用户拍板不做；现网保持 `memory.write_approval=false`，不打开
  - [ ] **C12-feishu-guide** · 源 §4.12 · 菜单点了真出引导卡（依赖 bot-menu 桩）· **未做**
  - [ ] **C12-merge-forward-recv** · 源 §4.15 · 合并转发二次拉取成可读记录 · **未做**
  - [ ] **C12-doc-ocr** · 源 §4.13 · docx 内嵌图物化 + 可选 OCR · **未做**
- [x] **C13** · 源 §7.24–7.26 · progress / approval / english / **recap** explainer · **已落地** · 飞书底座（C04/C10/C11）已齐
  - **统一基建**：单一 `owner.explainers` 块 + `owner/explainers/`（config/llm/registry）；`register_kind` 可扩。详见「§ 二次开发可复用基建 §4」与 `owner/docs/c13-explainers.md`
  - **输入默认 64k**（`max_input_chars`）；按辅助模型 **≥256k** 上下文设计；`clip_input` 保尾截断
  - **recap**：第四 kind；`/recap` 按需；notice `📋 系统提示：`；不写主会话
  - **统一约定（已敲定，代码已做）**：单一 `owner.explainers` 块 + 共享取模 helper；禁止各 kind 各写 provider/model。详见上方「§ 二次开发可复用基建 §4」。
  - 旧顶层 `progress_explainer` / `approval_explainer` / `english_explainer` → 迁入 `explainers.{progress,approval,english,recap}`；`call_llm(task=…_explainer)` 长 task 名保留
- [x] **C14** · 源 §14 · output_guard + stream_guard · **优先级：P1**（阶段一 · 完整版）
  - helper：`owner/output_guard/`（`transform_llm_output`）+ `owner/stream_guard/`（`on_stream_delta`；S1/S2/S3，S3=`is_repetition_dominated`）
  - 注册：`owner/owner-extensions` `register()` + `plugin.yaml` hooks
  - 配置：`owner/config/overlay.yaml` → `stream_guard.*`（默认 `action: interrupt`）+ `output_guard.enabled`
  - 胶水：`agent/stream_delivery.py`（`request_stop` + latch）；`turn_finalizer.apply_llm_output_transform`（C1 interrupted + reasoning）；`turn_final_response`（C1）；`turn_api_call.handle_api_interrupt`（C2 early-persist 前 transform）
  - 落地说明：`owner/docs/c14-output-stream-guard.md`
  - 测：`tests/owner/test_c14_guards.py`；自检 `python -m owner.{output,stream}_guard.selfcheck`
  - 依赖：无硬依赖未做定制；C13 只读 stream_guard.snapshot（方向 C13→C14）
- [ ] **C15** · 源 §7.2–7.3 · Memory synthetic guard + OpenViking sync recall/card · **优先级：P1**
- [x] **C16** · 源 §7.4 · Cron env 隔离（ContextVar + restart scrub） · **优先级：P1** · **验证状态：官方已修**
  - v2：`gateway/session_context._VAR_MAP["HERMES_CRON_SESSION"]` + `cron/scheduler._CronRunScope` set/reset；gateway/ACP/TUI bind `cron_session=""`；`tools/approval_context` ContextVar 感知；外部 worker 剥离 presence vars。无进程级 `os.environ["HERMES_CRON_SESSION"]=1` 写入。
  - 薄缺口（未扩 scope）：进程启动 scrub 继承的 `HERMES_CRON_SESSION`/`SESSION_KEY`/`SESSION_ID`；restart watcher env 未特判 pop（子进程 builder 仍可能拷贝 `os.environ`）。
- [x] **C17** · 源 §8.1 · Checkpoint Mutation Predictor · **优先级：P1**（阶段一）
  - helper：`owner/checkpoint_predictor/`（`predict_and_checkpoint` / static_parser / llm_predict）
  - 配置：`owner/config/overlay.yaml` → `checkpoints.*`（predict_enabled / llm timeout / cache / static threshold）
  - 胶水：`agent/tool_executor.py` `_begin_tool_execution` terminal 分支（替换 destructive+cwd；保留 container skip）
  - 设计：`owner/docs/checkpoint-mutation-predictor.md`
  - 测：`tests/owner/test_checkpoint_predictor.py`
  - 依赖核验：无硬依赖未做定制；硬依赖 = 官方 CheckpointManager + 已落地 C01 `patch_config`；LLM（auxiliary `task=approval`）与 `_owner_warn_callback` 为软依赖 fail-open
  - **2026-10-27 补丁**：`agent_init` 挂 `_owner_warn_callback=_emit_warning`；预测失败回落 `_emit_warning`；静态为空且 `_is_destructive_command` → cwd 窄兜底快照
- [ ] **C18** · 源 §9.1 · per-chat display overrides · **优先级：P1**
- [x] **C19** · 源 §5 · 链式快捷命令 `;;` + Quick Alias · **优先级：P1**（阶段一）
  - helper：`owner/commands/chained_quick.py`（`parse_chained_commands` / `expand_chained_quick_alias`）
  - 胶水：`cli.py` `_run_quick_command`；`gateway/run_inbound.py` `_hm_resolve_command`；`tui_gateway/methods_tools.py` `_dispatch_quick`（`type: chain`）
  - TS：`apps/shared/src/slash.ts` + `ui-tui/src/app/createSlashHandler.ts`；i18n `gateway.chained_commands_executed`
  - 测：`tests/owner/test_chained_quick.py`
- [ ] **C20** · 源 §3.9 · Semantic Audit Gate · **优先级：P1**（可后移若负担大）
- [x] **C26** · 源 §2.10–2.11 + §4.9 · providers 白名单 / 缓存 TTL / `/providers` · **优先级：P1**（阶段一）
  - 白名单：官方 `has_explicit_models` / `_models_config_is_allowlist` 已覆盖，沿用
  - 缓存：`_PROVIDER_MODELS_CACHE_TTL` 24h；`_store_cache_entry` 目录无变更不写盘
  - `/providers`：`owner/commands/providers.py` + `owner/owner-extensions`（`plugins/owner-extensions` 符号链接）；文本列表；飞书交互卡见 **C26-feishu-picker**
  - 测：`tests/owner/test_providers_command.py`、`tests/owner/test_provider_models_cache_ttl.py`
- [x] **C26-feishu-picker** · 源 §4.9 飞书半边 · `/providers` 交互卡（provider→model→确认）· **优先级：P1**（阶段三）· **已落地**
  - `owner/feishu/model_picker.py`；adapter `_model_picker_state` / `send_model_picker_card` / card-action `hermes_model_picker`
  - 测：`tests/owner/test_c26_model_picker.py`；说明：`owner/docs/c26-model-picker.md`
- [ ] **C21** · 源 §2.4–2.6 / §2.9 · 模型杂项 · **优先级：P1** · **未展开**（白名单·TTL 已归 C26）

### P2 暂缓

- [ ] **C22** · 源 §6.1–6.2 · TUI skin / ruolin · **优先级：P2**
- [ ] **C23** · 源 §11 · 运维脚本 / HN Daily / Skill 同步 / Viking 治理 / 备份 / 周会脚本 · **优先级：P2**（按需拣）
- [ ] **C24** · 源 §12 / §16.8–16.16 · 治理标记、T2-11~20 换码债、全量 `[owner]` 铺开 · **优先级：P2**（v2 **不做**「官方测全绿」与全量标记战役）
- [ ] **C25** · 源 §4.7–4.8 · 编辑上限轮转 / 中文摘要等体验项 · **优先级：P2**（`/providers` 已归 **C26**）

**定制段：原 C01–C25 + C26（providers）。执行顺序：四阶段（见上）。**

---

## § 排期 / 卫生（非阶段一阻塞）

> 不进四阶段必做；有空再开。与「明确不做」不同：这里是**以后要做、现在不排**。

- [x] **H01** · **官方 test 污染梳理** · 审计见 WorkBuddy `tests-pollution-audit-2026-10-23.md`；优先项已修：`73fa8f53e3`…`de3dc9ecff`（#1/#2/#5/#6/#7 R1/#10 等）。#7 仅守卫登记第一步；网络守卫等后置。
- [ ] **H02** · CLI approval `input()` 超时僵尸 reader · 仅无 callback 且非 PT 路径；超时后线程仍堵 `read(0)`，可能吞后续输入/连锁 deny；gateway/飞书/QQ/微信与正常 TUI **无感**；fail-closed 非安全问题。**暂时不做**。
- **限流（暂不做）**：本清单 **无独立限流定制项**（C 段无 RPM/TPM/throttle/客户端主动限流条目）。最接近已消化项：
  - **B18**（已勾）/ 源 §7.9 — 429 配额耗尽当 transient 静默重试 → 本树用 **O5** 天/周配额墙单向降为 billing
  - 官方自带：`agent/rate_limit_tracker.py`、pairing `_rate_limits`、渠道 flood 等（非 owner 待做）
  - 若日后从源补录「客户端主动限流 / RPM·TPM 闸」等 → **暂时不做**，勿塞进阶段一～三

---

## § 明确不做 / 已退役（勿再做）

来源：源清单 **附录 D** 等。

- [x] Mixture-of-Agents 去 OpenRouter 硬绑定（旧 §18.2）— 已退役
- [x] Qdrant 记忆召回（旧 §9.2/§17.21）— 被 OpenViking 取代
- [x] Session Archiver 插件（旧 §13.2）
- [x] `hermes_mon` 性能监控（旧 §13.1）
- [x] memory_propose 批量提案（旧 §4.5/§17.5）
- [x] Copilot PAT 拒绝策略（旧 §4.1）
- [x] 频道级 `channel_prompts`（旧 §5.1）
- [x] 用官方 `multiplex_profiles` **替换** node010 Linux 用户舰队隔离 — **明确不做**
- [x] 把「官方测试套件全绿」当 v2 目标 — **明确不做**
- [x] 推倒 `owner/` 换魔法 patch 框架 — **明确不做**（减负靠能力包 + 短名单）
- [x] owner 金钱估价 / `token_cost_estimate.py` / 依赖 estimated_cost 的 owner 定制 — **明确不做**（C02 瘦身：保留 token **数量**落盘，废弃算钱）
- [x] **C12-memory-approval** · memory 写入飞书审批卡 / 打开 `memory.write_approval` — **明确不做**（用户拍板；现网保持 `memory.write_approval=false`）

---

## § yaml 整合方向（只写方向，不改现网）

现状（源仓）：`owner/config/overlay.yaml`（v2 扁平）+ `patch_feishu_profile.yaml`（含 bots 路由与 LDAP）+ `upstream_sync.yaml`。老版 owner 分支仍用独立的 `patch.yaml`（含 `owner:` 外壳）。

**目标**：定制 yaml **更小、更好读**；密钥仍可内网提交，对外另做 template。

建议（落地时穿插，非一次性大爆炸）：

1. **拆「路由/身份」与「行为开关」**  
   - 保留独立「舰队路由」文件亦可，但结构对齐：`feishu.bots.*.user_routing` / `profile_endpoints` 与 `ldap` / `identity_*` 分节清晰；避免 LDAP 埋在飞书文件里却无索引。  
   - **不**为对齐官方而改成 `gateway.profile_routes`（语义不覆盖跨进程）。
2. **`overlay.yaml` 合并同类开关**  
   - `progress_explainer` / `approval_explainer` / `english_explainer`（+ `recap`）→ 单一 `explainers:` 块（共用 `provider`/`model`/`timeout_ms`/`max_input_chars=64000` + kind 子段；见「§ 二次开发可复用基建 §4」）。  
   - `openviking_sync_recall` + `openviking_recall_card` → `openviking:`。  
   - `feishu_card` notice_titles 与 auto_card 阈值保留一张表，删注释噪声。  
   - 长期 `enabled: false` 且无现网依赖的（如部分 `diff_card`）可迁「默认关 + 文档」，不占主文件行。
3. **行为默认进代码，yaml 只留差异**  
   - 与源规范一致：缺省 section = 合理默认；yaml 只写覆盖项。
4. **上游 sync 配置独立**  
   - `upstream_sync.yaml` 保持单独，不并进 overlay。
5. **v2 落地顺序**  
   - 先按 C01 重接加载器 → 再迁键名（一次改加载器+文档+软链说明）→ 最后缩行数。

---

## 附录：对照时怎么用源清单

- 打开源 `owner改动清单.md`，按本 todo 的「源 §x.y」跳转。  
- 不要把附录 B 侵入流水账搬进 v2。  
- 官方已修的 bug：在本文件标 `官方已修`，定制重放时**跳过**或只留回归测。  
- 仍需自研：进入对应 C0x 或新建薄能力包条目。
