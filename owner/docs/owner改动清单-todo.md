# owner 改动清单（v2 todo · 从新开始）

> 生成：2026-10-23 · Asia/Shanghai
> **不是**源清单 3000 行粘贴；从源清单提炼为可勾选 todo。

## 元信息

| 项 | 值 |
|----|----|
| 源清单 | `/Users/yangtb/.hermes/hermes-agent/owner/docs/owner改动清单.md` |
| 源仓 tip | `299e23205b66df082a2615aa1a4f3ed1edc69d25` |
| v2 worktree | `/Users/yangtb/.hermes/hermes-agent`（主 worktree 检出分支 `v2`；`owner` 分支另在 `hermes-agent-owner`） |
| v2 分支 tip（快照） | `cc2ed00a5b`（已双推 `origin`/`gitlab` 的 `v2`；SHA 随提交前进，以 `git log -1` 为准） |
| v2 tip（官方 main 基点） | `3ba2b0787ed3a73ec3b08085ed0137f235209cf4` |
| 规范 | 同目录 `二次开发规范.md` |
| 实现顺序 | 同目录 `v2实现顺序.md` |
| 背景说明 | 同目录 `v2背景说明.md` |
| bug 对照提示词 | 同目录 `小模型-bug对照提示词.md` |

**原则**：① 先整体过 **§ Bug**，对照官方 main 填验证状态（已完成）；② 再落 **§ 定制**，**执行顺序以四阶段为准**（见下「落地顺序」与 [`v2实现顺序.md`](./v2实现顺序.md)）；P0/P1/P2 分组仅作优先级参考；③ yaml 整合穿插在定制落地时，不大爆炸；④ 部署继续 Linux 用户隔离，**不吃**官方 multiplex 换舰队路由；**C05 多 profile 仅第四阶段**。

**验证状态枚举**（bug 段）：`待对照官方 main` | `官方已修` | `仍存在/需自研` | `部分` | `不适用(纯 owner)` | `已退役`

勾选约定：`- [ ]` 未处理；`- [x]` 已结论（状态字段已填）。

**子点记法（按功能点，不按日期流水）**：条目内子点以**功能点**命名（`- **功能点**：…`）；同一功能点的多次改动**并入同一条**、按子项分行，日期只作括注（`- **功能点（2026-11-04）**：…`）。**不**按「一行一次改动、以日期开头」流水记账；标签不写「补丁 / 复审修 / 热修 / follow-up / 核实」这类过程词。依据：`二次开发规范.md` §6.2。

## § 二次开发可复用基建（后续 AI 优先看）

> **开新能力前先扫本表。** 已落地的接现成入口；未落地的按「约定」接线，勿另起一套。
> 细则仍以各 C 条目 / 设计稿为准；本节只钉**接哪、怎么调、挂哪配置**。

### 1. `overlay.yaml` 加载器 · **C01 · 已落地**

- **是什么**：owner 层统一配置入口；文件第一层键即能力段（**无**顶层 `owner:` / `patch:` / `overlay:` shell），运行时 fuse 进 `config.owner.*`。
- **入口**：`owner/patch_config.py`
  - `load_patch_config()` / `load_owner_config()` → 读 `~/.hermes/overlay.yaml`（本仓常软链到 `owner/config/overlay.yaml`）
  - `apply_owner_overlay(config)` → 官方 `load_config` 薄挂点后的叠层
  - `invalidate_owner_config_cache()` → 强制重读
  - 舰队路由主读 overlay `feishu.bots.*.user_routing`（C05）；`load_patch_feishu_profile_config()` 在 `patch_feishu_profile.yaml` 缺失时返回 `{}`（该文件已于 2026-11-17 退役删除，不再回落）
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
- **配套目录**：平台中文名的 **sqlite 持久目录**见下方 §2b（`platform_users`）；JSON cache 仍是热路径，二者双写、互不替代。

### 2b. 平台用户名 sqlite 目录 · **C28 · 已落地**

- **是什么**：`state.db` 旁路表 `platform_users(platform, user_id, display_name, updated_at)`，持久保存飞书等平台侧显示名（中文名），可 SQL 查询；**不**改 `sessions.display_name` 语义。
- **入口**：
  - `owner/platform_users/store.py` — `ensure_table` / `upsert_display_name` / `get_display_name` / `backfill_from_feishu_user_entries` / `dual_write_feishu_name`
  - 双写挂点：`owner/feishu/user_store.py` `_store_resolved_name`（C04 JSON 照旧）+ 启动时从已加载 cache 回填
- **规范**：运行时 `CREATE TABLE IF NOT EXISTS`（仿 delivery_ledger）；**禁止**改官方 SCHEMA 字面
- **设计**：`owner/docs/design/platform-users/README.md`
- **测**：`tests/owner/test_platform_users.py`
- **非目标**：不替代 C04 TTL/审批预热；本轮仅飞书接通

### 3. skill 脚本自动审批 + skill_manage 飞书门 · **C09 · 已落地**

- **是什么**：本会话已 `skill_view` 的白名单 skill 脚本可跳过危险命令提示；飞书上 `skill_manage` 写操作走自建审批卡（YOLO 不绕过）。
- **入口**：
  - `owner/approval/skill_script_approval.py` — `track_session_skill_view` / `is_skill_script_allowed` / `reset_session_skills_viewed`
  - `owner/approval/skill_manage_gate.py` — `run_gate` / `should_escalate` / `apply_all_patches`
  - `owner/feishu/skill_approval_card.py` — `send_skill_approval_card` / `handle_card_click`
  - Hook 桥：`owner/owner-extensions/skill_manage_bridge/`（`pre_tool_call` + `pre_gateway_dispatch`）
- **配置**：`config.owner.approvals.skill_script_allowlist`（overlay.yaml）；`feishu.skill_approval`（**主读 overlay.yaml**；`patch_feishu_profile.yaml` 已于 2026-11-17 退役删除，不再回落）
- **路径口径**：绝对/`./`/`../`/嵌套路径须落在已 view skill 根内；**纯 basename** 仍免目录校验（approval 未传 workdir）
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
    enabled: true         # 第四 kind：/recap 按需回顾（notice；正文落 messages 审计，不入主会话模型）
    max_output_chars: 350
    auto:                 # 长耗时或长结束消息才自动；结束后不再空等
      enabled: true
      min_turn_seconds: 180     # 本轮用户消息 → session_end；旧键 idle_seconds 作回退，不再表示空等
      min_assistant_chars: 800
```

- **块名**：`explainers`（对齐清单「yaml 整合方向」）。
- **kind 子键**：`progress` / `approval` / `english` / `recap`（短、可扫；勿写成 `explainers.progress_explainer`）。
- **输入预算**：共用 `max_input_chars` 默认 **64000**（`owner.explainers.common.DEFAULT_MAX_INPUT_CHARS` / `clip_input`）；kind 可覆盖。按 **≥256k** 上下文模型设计。
- **旧键迁移目标**：顶层 `progress_explainer` 等 → 本块；超时键统一 `timeout_ms`（共用或 kind 覆盖）。
- **`call_llm` 的 `task=`**（与 config.yaml `auxiliary.*` 对齐，**保持长名**）：
  - `task="progress_explainer"` / `"approval_explainer"` / `"english_explainer"` / `"recap_explainer"`

#### 4.2 模型解析优先级（对齐旧约定，收口到一个 helper）

已走共享入口：`owner/explainers/llm.py` → `resolve_explainer_call(kind)` / `call_explainer_llm(kind, messages, **kw)`；包布局 `owner/explainers/{progress,approval,english,recap}/`，**禁止**各 kind 各写 provider/model 解析。 旁白中文门亦挂在此共享入口（`looks_like_non_chinese_output` → 纠偏重试 1 次 → fail-open）。

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
| 飞书 `/resume` 交互卡 | C27-resume-card | `owner/feishu/resume_card.py`（`try_send_resume_card_list` / `send_resume_card` / `handle_resume_card_action`）；adapter `send_resume_card` + card-action `resume_select`；slash 列表薄胶水 | — |
| stream / output guard | C14 | `owner/stream_guard.snapshot`；`owner/output_guard`（`transform_llm_output`） | `owner.stream_guard.*` / `owner.output_guard.enabled` |
| Checkpoint 预测 | C17 | `owner/checkpoint_predictor`（`predict_and_checkpoint`） | `owner.checkpoints.*` |
| 护栏 i18n | C10 | `owner/i18n/localized.py` → `localized` | locales + 调用方 `_localized` |
| 审批历史结构判定 | B11 | 与 C10 同批；历史挖掘勿再靠英文文案子串 | （见 `c10-b11-*.md`） |
| 飞书 WS 重连守卫 | C29 | `owner/feishu/ws_reconnect_guard.py`（apply / supervise / note_*）；adapter 薄挂 | `feishu.ws_reconnect_guard` |

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

- [x] **B12** · 源 §6.3 · Ctrl+C /exit 与 graceful drain（SIGINT 逃出清理链） · **验证状态：已核实 · 暂不实施**
  - **核实结论（2026-10-30）**：不加 OS SIGINT handler —— 按键 Ctrl+C 已由 prompt_toolkit `c-c` 覆盖；`cli_terminal_input` 注明 raw mode clears ISIG；TUI `SIGINT→SIG_IGN` 有意（SIGTERM/SIGHUP→exit）；单查询路径已有 handler。无「逃出清理链」廉价复现 → 暂不实施（见阶段一旁注）。
- [x] **B13** · 源 §6.4 · live compression sync 误清 per-model `context_length` · **验证状态：官方已修**
  - owner：`tui_gateway/server.py` 缺顶层时回退 `get_custom_provider_context_length`。v2：`tui_gateway/session_compression.py` + `agent_init.config_context_length_for_runtime`，引脚缺失时强制重新推断，`get_model_context_length` 步骤 0c 精确匹配 `providers.*.models`。
- [x] **B14** · 源 §7.20 · 后台插件发现超时死锁（启动空白屏） · **验证状态：官方已修**
  - owner：`discover_and_load` 改 `acquire(timeout=15)` + join 超时直接返回。v2 本树已用 **O3**：`_TimedLock` 15s + join 超时返回 bool，不再无限持锁空白屏。

### Gateway / Agent 运行时

- [x] **B15** · 源 §7.1 · QQ Bot WebSocket 重连链不稳 · **验证状态：官方已修**
  - owner：`_stop_retry` + `receive_timeout=120` + `_rebuild_http_client`。v2：重连链已重写（backoff、close-code 分类、`is_reconnect` kwarg、`disconnect()` 置 `_running=False` 停止重试）；**O4** 已补读路径 `wait_for` 90s + 心跳静默关 socket；本批补 **`_rebuild_http_client`**（重连前关旧 httpx + `platform_http_client()` 新建 + 清 OAuth 缓存）。见 §「v2 已落地官方 fix」。
- [x] **B16** · 源 §7.5 · executor-shutdown 不友好提示 · **验证状态：官方已修**
  - owner：`owner/gateway/turn_helpers.py::is_executor_shutdown_error` → 友好重启提示。v2：`agent/turn_loop_errors.py` 识别 interpreter/executor shutdown 后走 `site_copy("interpreter_shutdown", resume=…)`，不再抛裸 RuntimeError。
- [x] **B17** · 源 §7.6 · Clarify 清理路径缺 stop sentinel / 飞书 clarify 超时未中断 · **验证状态：已修（官方半边 + 飞书半边）**
  - **官方半边已修**：`CLARIFY_STOP_SENTINEL`（= `clarify_gateway.CANCELLED`）+ `wait_for_response` 在 entry 消失 / event 空应答时返回 CANCELLED（不再伪造成用户超时）。见 §「v2 已落地官方 fix」。
  - **飞书半边已落地（2026-10-27）**：`owner/clarify/feishu_timeout_stop.py` + `gateway/run_turn_runner.py` `_ask_clarify_question` 薄钩；飞书真超时（`[user did not respond…]`）补发提示并返回 CANCELLED → outcome=`cancelled` 停转。测：`tests/owner/test_b17_feishu_clarify_timeout_stop.py`。
  - **超时提示 i18n（2026-10-27）**：`locales/{zh,en}.yaml` 补 `gateway.clarify_timeout_notice`；`timeout_notice_text` 经 `display_language()` 取语言，不再默认死 zh。
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

- **B17**（clarify）：**官方半边 + 飞书半边均已落地**（见下表）。
- **B12**（CLI OS 级 SIGINT）：**2026-10-30 核实 · 暂不实施**。证据：① v2 按键层已由 prompt_toolkit `c-c` 覆盖；② `hermes_cli/cli_terminal_input.py` 注明 raw mode clears ISIG，内核 INTR 从未涉入交互 CLI；③ `tui_gateway/entry.py` 对 SIGINT 设 `SIG_IGN` 为有意（用 SIGTERM/SIGHUP → `app.exit`）；④ 单查询路径已有 SIGINT handler。无廉价可复现「OS SIGINT 逃出清理链」证据，故不加 handler（避免与 SIG_IGN / ISIG 假设打架）。若日后有子 shell PTY 回弹 / 后台线程投递 SIGINT 的实机复现，再最小补。
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
| B17 飞书半边 | B17 | 飞书真超时补发提示 + 返回 CANCELLED 停转；文案走 `gateway.clarify_timeout_notice` + `display_language()`（2026-10-27 i18n harden） | `owner/clarify/feishu_timeout_stop.py`；`gateway/run_turn_runner.py`；`locales/{zh,en}.yaml` | `tests/owner/test_b17_feishu_clarify_timeout_stop.py` |

O3–O8 代码 commit：`acbc2074c5`。B15/B17 见本批随后 commit。

---

## § 落地顺序（四阶段）

> **执行顺序以本表 + [`v2实现顺序.md`](./v2实现顺序.md) 为准。**
> 下方「P0 / P1 / P2」分组仍保留作**优先级参考**（现网必保 vs 可后移），但**不要**再按 P0→P1→P2 当落地节奏。
> Bug 对照与 O/B15/B17 官方半边已完成；定制从阶段一起步。

| 阶段 | 主题 | 条目（保留原 C 编号） |
|------|------|----------------------|
| **一** | 非渠道 / 终端 / 加载器 | **C01**（最先）→ C02 → C08 → C03 → **C26** → C21（忽略）→ C16 → C17 → C19 → C18（忽略）→ C14 → C13 → C22（忽略）；旁注 B12 不强制 |
| **二** | 飞书**核心**底座 | **C04**（审批卡 + 中文名/sender 缓存 + inbound + 签名）→ **C10**（+B11 同批）→ **C11 底座**（auto-card / early-typing）；diff/clarify/bot 菜单可延阶段三 |
| **三** | 飞书定制 + 杂项 | **C09**（依赖 C04）→ C11 余下 → **C12** → C15 → C25（`/providers` 已归 C26）→ **C06** LDAP / **C07** API media（延后） → C20（忽略）→ C23（运行时脱钩 + §11.2 args→CLI ✅，整包迁仓不做）→ **B17 飞书半边** ✅；**C24** 全量战役不排 |
| **四** | 飞书多 profile | **仅 C05**（`profile_endpoints` / bots 路由；不吃 multiplex）。勿提前；与阶段三 LDAP **文件边界**分开 |

**依赖速记**：C01 万物前置 → 阶段二 C04 先于一切飞书体验/skill 门 → C09/C12 依赖 C04 → **C05 最后**。yaml 随 C01 / 阶段三 LDAP / 阶段四路由穿插缩文件，不大爆炸。**C29** 飞书 WS 重连守卫见「§ 渠道运行时加固」（穿插；不进四阶段必做）。

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
| **C29** | 飞书 WS 重连守卫 | hung `_get_conn_url` timeout + 有限 ladder + ~10min 封顶 supervisor（不整进程重启） |
| **C17** | Checkpoint Mutation Predictor | `owner/checkpoint_predictor/`；tool_executor terminal 薄胶水 |
| **C19** | 链式快捷命令 `;;` + Quick Alias | `owner/commands/chained_quick.py`；CLI/gateway/TUI 薄胶水 |
| **H01** | 官方 test 污染梳理 | 优先项已修（#1/#2/#5/#6/#7 R1/#10 等） |
| **H02** | CLI `input()` 僵尸 reader | 已落地 |
| **C28** | 平台用户名 sqlite 目录（`platform_users`） | C04 JSON 双写；state.db 旁路表 |
| **C12-at-all** | 群 `@_all` 不再当提到自己 | `_mentions_self` 极小 P2；官方测已改 |
| **C12-upload-guard** | 出站图/文件超限中文提示 | `owner/feishu/media_guard.py` + adapter 薄胶水 |
| **C12-queue-card** | 飞书 queue 状态卡（cancel/now/steer/freeze） | `owner/feishu/queue_card.py` + `queue_cancel_patch` + adapter 薄胶水 |

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
  - **落盘列（2026-10-27）**：`_CONVERSATION_ROW_COLUMNS` 补 `owner_provider_name` + 四列 token，避免第二轮飞书 `history_unavailable`（`transcript_row_snapshot` IndexError）
  - **出站剥离字段（2026-10-27）**：`PERSISTENCE_ONLY_MESSAGE_FIELDS` 增 `model`/`provider`（不落盘 DDL）；attribution docstring 改为「仅内存」
  - **provider 名归一（2026-10-30）**：`/model` mid-switch 传入的 `new_provider` 对 named-custom 多为 `custom:<slug>`（`resolve_provider_full`），会把 init 时 runtime 盖成的 slug 名冲掉；`bind_agent_attribution` 剥离 `custom:` 前缀，与 named-custom runtime stamp（`custom_provider["name"]`）对齐；裸 `custom` 仍记 `custom`。测：`tests/owner/test_attribution.py`
  - **密钥前缀判定（2026-11-04，与 C26 共用）**：`_lap_canonical_rows` 改走 `_any_env(..., provider=slug)`（修 copilot `ghp_*` / coding-plan 裸 `sk-` 假阳性）；`credential_helpers` 增 coding-plan-cn 等 `sk-sp` 前缀。测：`tests/owner/test_credential_helpers.py`、`tests/owner/test_listing_filters.py`
- [x] **C03** · 源 §2.7–2.8 · damodel provider/proxy · **优先级：P0**
  - 落地：`owner/providers/damodel.py` + `plugins/model-providers/damodel/`；测 `tests/owner/test_damodel_provider.py`
  - **anthropic cache_control 委托（2026-10-27）**：`is_damodel_route` + `anthropic_prompt_cache_policy` 3 行 `# [owner]` 委托，恢复 damodel cache_control（成本回归）；thinking/extra_body 仍延后
  - **手工验证（可选）**：本机对 damodel（含非 qwen 如 deepseek-v4-flash）发一枪，确认无 400 且 `cache_read_tokens > 0`；若某 upstream 拒 envelope，再按模型家族收窄
- [x] **C04** · 源 §3.1–3.4 · 飞书审批卡片 + sender_name 缓存 + inbound 身份 + 多平台审批签名 · **优先级：P0**（阶段二首项）
  - helper：`owner/feishu/{approval,user_store,user_cache,sender_name_helpers,inbound_context}.py` + `owner/gateway/inbound_context.py`
  - 胶水：`plugins/platforms/feishu/adapter.py`（委托 + 24h soft TTL + store migrate）；`gateway/run_inbound.py`；`gateway/run_turn_runner.py`（metadata sender）；`cron/scheduler.py`（Cron context）
  - locales：`platform.feishu.approval.fail_*` / `operator_fallback`
  - 发送仍官方 ExecApprovalPrompt；C01 `gate_allow_permanent` 继续管 Always 按钮
  - 设计：`owner/docs/design/feishu-approval-base/README.md`
  - 测：`tests/owner/test_c04_feishu_base.py`；官方 `test_feishu_approval_buttons.py` 对齐冻结卡 / soft TTL
  - **配套 C28**：平台显示名 sqlite 目录（`platform_users`）已落地；与本条 JSON cache **双写**，见「§ 二次开发可复用基建 §2b」
- [x] **C28** · **平台用户名 sqlite 目录**（`platform_users` 旁路表）· **优先级：P1**（C04 配套 / C05 可复用基建）
  - 表：`platform_users(platform TEXT, user_id TEXT, display_name TEXT, updated_at REAL)` PK `(platform, user_id)`；库=`state.db`
  - helper：`owner/platform_users/`；飞书双写：`FeishuUserStore._store_resolved_name` + 启动 backfill
  - 设计：`owner/docs/design/platform-users/README.md`
  - 测：`tests/owner/test_platform_users.py`
  - **不改**官方 SCHEMA；不改写 `sessions.display_name`
- [x] **C05** · 源 §4.1 · **飞书多 profile 舰队路由**（`profile_endpoints` HTTP 转发；**不吃**官方 `profile_routes`） · **优先级：P0** · **C05a/C05b 与三层挂载已完成**
  - 设计稿：`owner/docs/design/c05-feishu-user-routing/README.md`（配置结构已定稿；按人 **`fleet_profiles`**）
  - 开户自动化：`owner/docs/design/c05-feishu-user-routing/fleet-add.md`；**O1–O5 已落地**（2026-10-29：`fleet_add*.py` + `test_fleet_add_o1/o2/o3/o4.py`；对话 UX = 现网 skill）
  - 开户步骤提醒：对话收集到 `ou_*` 时，**apply 前/中**同批写入 **目标 profile + Hub** 的 `FEISHU_ALLOWED_USERS`（ou ± 已知 tenant user_id；或钉死 Hub `FEISHU_ALLOW_ALL_USERS`）与目标 **`FEISHU_HOME_CHANNEL`**（优先 DM `oc_*`；兼写 `platforms.feishu.home_channel`）；勿等首条私聊被丢弃或事后 `/sethome`（见 fleet-add.md §2 / O2）。inject 绕过子 adapter `_admit`，但 gateway authz 仍读子白名单；Hub `_admit` 在路由前执行
  - **子网关/路由/allowlist 审查修补（2026-10-29）**：S1 卡打标改 `container_profile_identity`；M1 inbound 仅 send_only；M2 overlay 加载失败 ERROR + last-good；M3 缺 api_server 不回落 Hub；M4/M5 文档钉死 allowlist 口径
  - **O5 已落地（2026-10-29）**：完全更新现网 `~/.hermes/skills/westcloud/xy-user-onboarding/SKILL.md`（仓外；备份 `SKILL.md.bak-pre-o5-20261029`）；skill 只编排，mutating → `fleet_add`（allowlist + home channel）；对齐三层挂载 / `fleet_profiles` / LDAP uid；去掉旧整挂与平行 endpoints / heredoc invent；仓内仅文档勾选（见 fleet-add.md §5 / D1）
  - **C05a（Mac v2）已落地已 push** 2026-10-29：`owner/feishu/profile_routing.py` + card_action + adapter/api_server 薄胶水 + `send_only` + 审查修补（S1/M1–M5）+ 单测；已 dual-push `origin`/`gitlab` `v2`；生产部署见下方 C05b 完成记录
  - **fleet_add O1（2026-10-29）**：dry-run 内核已落地（默认 dry-run）
  - **fleet_add O2（2026-10-29）**：`--apply` 写 overlay 人卡 + `user_profile_routes`、目标/Hub `FEISHU_ALLOWED_USERS`、目标 `FEISHU_HOME_CHANNEL` + `platforms.feishu.home_channel`；备份与回滚说明；默认拒 `/data/hermes`；**不** docker/useradd；假夹具单测；后续已随 O1–O5 入库推送
  - **fleet_add O3（2026-10-29）**：`--apply-host` 种子 `profiles/<uid>` + 三层挂载 compose（代码/venv RO + home→/root + profiles→/root/.hermes）；`useradd` 默认只列（Mac=`unsupported`，`--run-useradd` 门闩）；默认拒生产路径；**不** compose up（O4）；测 `test_fleet_add_o3.py`；后续已随 O1–O5 入库推送
  - **fleet_add O4（2026-10-29）**：`--apply-up` → `docker compose -f … up -d` + 探活 `api_server.url`（`/health` 或 `/`）；可注入 `compose_runner`/`health_get`（单测 mock，不依赖真 Docker）；失败结构化错误 + compose stop/回滚文案；默认 dry；拒 `/data/hermes`；测 `test_fleet_add_o4.py`；已随 O1–O4 双推
  - **fleet_add O5（2026-10-29）**：对话 UX — 现网 `xy-user-onboarding` 全更（只编排 → dry-run → apply / apply-host / apply-up）；仓外 skill，仓内 docs 勾选并 push
  - **C05b 准备（2026-10-29）**：node010 survey + v2 preview worktree + overlay 草稿（`/data/hermes/c05b-draft/`）；当时未切生产 / 未重启；后续完成记录见下方。计划见 `owner/docs/design/c05-feishu-user-routing/c05b-node010-plan.md`
  - **C05b 已完成（2026-11-06）**：正式 overlay `fleet_profiles` 已启用；13 个 LDAP uid 短名 Linux 用户/容器已对齐；`liry` / `wuyj` 已停；`gaor` LDAP 已建；Viking 保持方案 B。切流 tip `7be19213ff`，后续 PM fix `8cfb9d975b` 已进 gitlab。切流当时旧 `patch_feishu_profile.yaml` 曾留作回退；该文件已于 **2026-11-17 退役删除**，overlay 为唯一来源，加载器对缺失文件返回 `{}`
  - **三层挂载已完成（2026-11-06）**：home → `/root`、`profiles/<uid>` → `/root/.hermes`、代码/venv RO；compose 软链与 `xy-user-onboarding` / `fleet_add` O3 一致；叠挂探针与 `/health` 13/13 = 200 通过；切流/三层窗口内未无故重启 Hub（见同目录 `c05b-node010-plan.md`）
  - **fleet_add 模板对齐 3.14.9（2026-11-17）**：O3 草稿挂共用 `/data/hermes/tools`（RO）与 `/data/hermes/installs`（RW）、`sqlite-fixed/entrypoint-fleet.sh`，容器内代码/venv 路径改为 `/data/hermes/hermes-agent` 与 `.../venv`，并设 `HERMES_SUPERVISED_CHILD=1`；**不要**把共用树 bind 到 `/root/.hermes/tools|installs`。venv-docker 仍可挂，启动不用 3.11.0rc1。测 `test_fleet_add_o3.py`。`xy-user-onboarding` 文档在 westskill 仓同步（先本机再 node010 pull）
  - **fleet_add 模板对齐现网 compose 布局与运维卷（2026-11-18）**：O3 实体写到 `profiles/<uid>/docker-compose.yml`，并在 `compose/docker-compose.fleet-<uid>.yml` 建软链；服务名=`<uid>`、`container_name=hermes-<uid>`；补现网 13 份共性运维卷（`/root/.ssh`、ansible.cfg、inventory、scripts、cron、ansible tmpfs）与 `OPENVIKING_ENDPOINT=http://host.docker.internal:1933`。`FEISHU_HOME_CHANNEL` 仍由 O2 写 `.env`，不把频道 ID 写进仓内 compose 模板（现网 12/13 份 compose 另有一份）。测 `test_fleet_add_o1/o3/o4.py`（含 `gateway.standalone: true`、软链与运维卷断言）。
  - **C05a 补丁**：子网关 `FEISHU_CONNECTION_MODE=send_only`（`plugins/platforms/feishu/adapter.py` connect 早退、不抢 Hub app_id WS lock）；测 `tests/owner/test_c05_feishu_send_only.py`；**勿**把实地测 `overlay.yaml` / profile `.env` 入库
- [x] **C06** · 源 §15.1–15.6 · API Server LDAP 身份准入 + `fleet_profiles`/`hub_only.api`（旧 `api_identity`/`identity_*` 只读别名）+ 头剥离/SSE · **优先级：P0**
  - **LDAP 身份准入（2026-10-29，v2 重做，不照搬 owner）**：设计稿 `owner/docs/design/c06-ldap-identity-auth/`；`owner/gateway/ldap_auth.py` + `identity_routing.py`；api_server 薄胶水；overlay 非机密连接字段 + `enabled:false`；`HERMES_LDAP_*` env；探针 `c06_ldap_probe.py`；单测+E2E（负向真 LDAP 已过）；C05b 已完成；生产 LDAP 门闸另开 / 本机默认仍不开门
- [ ] **C07** · 源 §16.1–16.6 · API 产物媒体 / `hermes.files` / tool.progress 脱敏与归属 · **优先级：P0** · **延后**（2026-10-27 用户拍板；与 C05/C06 一并靠后，非当前主线）
- [x] **C08** · 源 §7.27 · outbound BOS/EOS scrub · **优先级：P0**
  - 落地：终局走官方 O8；interim/status 薄补复用 `_strip_deepseek_special_tokens`（`owner/outbound_special_token_scrub.py` + stream_delivery / gateway status 胶水）
  - 测：`tests/owner/test_outbound_special_token_scrub.py`
- [x] **C09** · 源 §3.6 / §3.11 · skill 脚本自动审批 + skill_manage 飞书审批门 · **优先级：P0**（阶段三）
  - skill 脚本：`owner/approval/skill_script_approval.py`；`approvals.skill_script_allowlist`；胶水 `tools/approval.py` + `tools/skills_tool.py`
  - skill_manage 门：`owner/approval/skill_manage_gate.py` + `owner/owner-extensions/skill_manage_bridge/`；卡 `owner/feishu/skill_approval_card.py`
  - 配置：`feishu.skill_approval`（**主读** `overlay.yaml`；`patch_feishu_profile.yaml` 已于 2026-11-17 退役删除；默认 enabled:false）
  - 适配：超时补丁挂 `tools.approval_context._get_approval_timeout`；发卡走 `send_card`；adapter `_on_card_action_trigger` 薄分支
  - 设计：`owner/docs/design/skill-approval/README.md`
  - 测：`tests/owner/test_skill_script_approval.py` / `test_skill_manage_gate.py`
  - **配置迁移（2026-10-27）**：`skill_approval` 迁入 overlay（含旧树 `approval_home_chat_id` 真值）
  - **脚本白名单路径判定（2026-10-27）**：白名单要求「绝对/相对路径须落在 skill 目录内」；`./`/`../` 前缀不再被 Path 规范化成纯 basename 免审；纯 basename 仍豁免（approval 未传 tool workdir，暂不接 ②）
- [x] **C10** · 源 i18n 层 · 显示层 i18n / `_localized` 与护栏文案（源 §12.2 / §16.9 相关） · **优先级：P0**（阶段二 · 与 B11 同批）
  - helper：`owner/i18n/localized.py`（`localized` / `GUARD_EN_TEXTS`）
  - 胶水：`tools/file_tools_write_guards.py`（受保护指令 / SSH 配置写入护栏走 `_localized`/`_blocked`）
  - locales：`approval.protected_file_*` / `ssh_config_*` / `gate_why_*`（en↔代码漂移守卫）
  - 说明：`owner/docs/c10-b11-i18n-approval-history.md`
  - 测：`tests/owner/test_file_tools_guard_text_i18n.py`
  - **思考展示标签口语化（2026-11-04）**：不改 bundled `locales/zh.yaml`；用官方 `$HERMES_HOME/locales` overlay → `owner/config/locales/zh.yaml`（本机 `~/.hermes/locales` 软链），仅覆盖 `gateway.reasoning.quote_label_*` / `block`：`💭 推理`→`💭 想法`。测：`tests/owner/test_reasoning_label_zh_overlay.py`。生效需软重启（catalog 进程内缓存）。
  - 范围：护栏文案层（T2-12）；非废弃的 display_filter；官方 `tools/approval.py` agent-facing 大段英文模板未整迁（B11 已用 summary.* + 护栏键 + 兜底覆盖历史挖掘）
  - **用户可见串前缀与图标**：
    - 生命周期/关停提示：⚠️→♻（`gateway.shutdown.{notice_restart,notice_shutdown,cron_interrupted}`，与 `startup.restarted` 一致）；zh/en 语气收紧，其它 locale 仅换 emoji；lifecycle 三键保持 ♻，正文未改
    - 故障/告警类：开头 `⚠️`/`⚠`→`❕`（更柔和）；`locales/*.yaml` + `.tui.yaml` 同前缀
    - 审批/告警类：代码硬编码前缀 ⚠️→💡（飞书卡 `_card`、多平台 `_EA_HEADER`、C13 stream-guard notice 键与 overlay 同步）；locales 保持 💡/🔄，不回滚

- [x] **C10b** · 审批卡「标记原因」description 展示中文（保留英文键与术语） · **已落地**（2026-11-16）
  - helper：`owner/i18n/approval_reasons.py`（`REASON_ZH` / `translate_reason` / 漂移用 `collect_static_detector_descriptions`）
  - 胶水：`gateway/platforms/base.py::_format_exec_approval`；`gateway/run.py::_format_exec_approval_fallback`；`tools/approval_prompt.py::_ask_human`（CLI header only）
  - 设计：`owner/docs/design/approval-reason-i18n/README.md`
  - 测：`tests/owner/test_approval_reason_i18n.py`
  - 约束：英文 description 仍是 allowlist/pattern 键；`ExecApprovalPrompt.description` / smart-approve / 检测器原文不改

- [x] **C10c** · 诊断提示（供应商自动重试等）展示层中文（2026-11-17）· **已落地**
  - 背景：官方 `ladder_notice()` 拼出 `⏳ Provider temporarily unavailable — retrying automatically in {N}s (cycle {c}/{t}); send /stop to cancel`，经 `_emit_diagnostic_status` → 飞书/QQ 等 messaging 状态气泡原文直出；不是「回完后再空等 180 秒」那类问题，是未译。
  - helper：`owner/i18n/diagnostic_notices.py`（`translate_diagnostic_notice`；参数与 `/stop` `/retry` `/model` / `Esc` 原样保留；缺译/英文 UI 回落原文）
  - 胶水：`gateway/run.py::_prepare_gateway_status_message`（provider-error 官方 `t()` 改写之后；local/api_server 仍走 raw 诊断）；`owner/explainers/progress/activity_i18n.py` 进度戳未命中时复用同一翻译（wait line）
  - **不改**官方英文原句（部分形状同时是 noisy-filter / provider-error 匹配键）；未覆盖：日志、给模型的说明、已被 `_TELEGRAM_NOISY_STATUS_RE` 吞掉的重试刷屏、已被 `_gateway_provider_error_reply` 改写的 API/限流信封、动态 `❌ {label}: {summary}`
  - 测：`tests/owner/test_diagnostic_notice_i18n.py`
  - 生效：需重启本机 gateway（此次未重启、未 push）

- [x] **C10d** · 定时任务出错/未运行等投递文案展示层中文（2026-11-17）· **已落地**
  - 背景：自动回顾之外，定时任务失败会把英文模板直接投到飞书/QQ（`scheduler_failure_copy` / 看门狗 / 监视器 / 自动暂停 / 包装头）。上次 C10c 扫描按「emoji + 大写英文」做过诊断气泡，这类报错多为 `💡 Cron '{name}' failed:` / `⛔ Cron '{name}' did not run:`，不走 `_prepare_gateway_status_message`，因此当时未覆盖。
  - helper：`owner/i18n/cron_notices.py`（`translate_cron_delivery`；任务名、id、路径、时间、连续失败次数、时长，以及 `hermes cron …` / `/login` / `hermes setup` / `hermes fallback add` / `hermes gateway restart` / `cron.model` 等命令与配置键原样保留；`💡`/`⛔` 前缀保留；缺译/英文 UI 回落原文）
  - 胶水：`cron/scheduler_delivery.py::_deliver_result`（redact 之后、live/standalone/bot-chat 发送之前；包装头与正文一并翻译；镜像进会话的正文同步翻译）。官方英文原句不改（仍是匹配键）。
  - **已译**：供应商分类失败（含 cause/action/备用供应商句）、通用失败、脚本超时、任务停滞、配置预检未运行（含若干稳定预检原因）、看门狗脚本失败、监视器数据源失败、自动暂停、连续失败提醒、额度窗口暂挂、网关代码偏斜、以及 `Cronjob Response` 包装头。
  - **仍跳过**：日志和给模型的说明（含 prompt 里「请以 💡 Skill(s) not found… 开头」的指示）；CLI/`hermes cron status` 专用打印；成功任务的正文（agent 输出不译）；通用失败里的原始异常摘要（`cleaned_error` 当参数保留）；已走官方 `t()` 的中断通知（`gateway.shutdown.cron_interrupted`）和 Cron 存储不可写/恢复通知。
  - 测：`tests/owner/test_cron_notice_i18n.py`
  - 生效：需重启本机 gateway（此次未重启、未 push）

### P1

- [x] **C11 底座** · 源 §4.2–4.3 · auto-card / early-typing · **优先级：P1**（阶段二）
  - helper：`owner/feishu/auto_card.py` / `agent_end.py` / `card_sender.py`
  - 配置：`owner/config/overlay.yaml` → `feishu_card.*`（threshold / split / notice_titles）
  - 胶水：`plugins/platforms/feishu/adapter.py`（`send` try_auto_card / `send_card` / early-typing）；`gateway/run_turn.py`（`try_auto_card_on_end` + progress bubble 标记）
  - **notice 卡规则**（`_DEFAULT_NOTICE_RULES`：前缀 → 标题 → 模板色）：recap 规则标题色 `template=orange`（橘黄；`yellow` 偏浅黄，2026-11-04）；前缀字面须与 overlay `notice_titles` 及 C13 各 kind 的 PREFIX 三处一致，否则旁白/告警不会升格为 notice 卡
  - 说明：`owner/docs/c11-feishu-auto-card-base.md`
  - 测：`tests/owner/test_c11_auto_card.py`（含 `recap["template"] == "orange"` 断言）、`tests/owner/test_feishu_agent_end_media.py`
  - 依赖：C04 已落地；卡发送复用官方 `_feishu_send_with_retry` / `_finalize_send_result`
  - **话题交互卡（2026-11-11）**：`send_card` / `send_card_via_rest` 在有 `metadata.thread_id` 时走 reply API（`reply_in_thread=True`），不按 `receive_id_type=thread_id` 创建（99992402）。详见 C13「飞书话题发卡」。测：`tests/owner/test_c13_feishu_thread_cards.py`
- [x] **C11-bot-menu** · 源 §4.6 · bot 菜单 menu_v6 + p2p 暖缓存 · **优先级：P1**（阶段三）· **已落地**
  - `owner/feishu/bot_menu.py`；adapter 注册/委托 + p2p/inbound cache warm；`overlay.yaml` → `feishu.bot_menu*`
  - 测：`tests/owner/test_owner_feishu_bot_menu_cold_cache.py`；说明：`owner/docs/c11-bot-menu.md`
- [x] **C11-clarify** · 源 §4.5 · Feishu clarify 交互卡 · **优先级：P1**（阶段三）· **已落地**
  - `owner/feishu/clarify_card.py` + `owner/clarify/gateway_helpers.py`；adapter `send_clarify` / `retire_clarify_card` / card-action `clarify_id` 分支
  - 测：`tests/owner/test_c11_clarify_card.py`；说明：`owner/docs/c11-clarify.md`
- [x] **C26-feishu-picker** · 源 §4.9 · Feishu `/providers` 模型切换交互卡 · **优先级：P1**（阶段三）· **已落地**
  - `owner/feishu/model_picker.py`；adapter `send_model_picker_card` / `_handle_model_picker_action` / `_model_picker_state`
  - 测：`tests/owner/test_c26_model_picker.py`；说明：`owner/docs/c26-model-picker.md`
- [x] **C27-resume-card** · 源漏记 · Feishu `/resume` 数字按钮交互卡 · **优先级：P1**（阶段三余量）· **已落地**
  - `owner/feishu/resume_card.py`；adapter `send_resume_card` / `_handle_resume_card_action` + card-action `hermes_action==resume_select`（须先于审批泛分支）；`gateway/slash_commands_session.py` 列表分支薄胶水
  - i18n：`gateway.resume.card_title`（en/zh）
  - 测：`tests/owner/test_c27_resume_card.py`；说明：`owner/docs/c27-resume-card.md`
  - 操作者鉴权：保留 clicker==owner（切会话 IDOR；与审批卡「由 xx 批准」展示不同）
  - **点选提交流程（2026-10-28）**：`_submit_on_loop` 失败 → 失败卡（仿 C12）；成功点选后回冻卡 `build_done_card`（仿 model_picker confirm，防连点）；按钮 value 顺带 stash `session_title`
- [ ] **C11-diff** · 源 §4.4 · Feishu diff 卡 · **忽略（不做）**
- [x] **C12** · 源 §4.10–4.15 · memory write-approval 卡 / feishu-guide / 上传守卫 / doc_read 图 OCR / @所有人 / merge_forward / **queue 状态卡** · **优先级：P1**（子点分批；已落地 C12-at-all + C12-upload-guard + C12-feishu-guide + C12-merge-forward-recv + C12-doc-ocr + **C12-queue-card**；**C12-memory-approval 忽略（不做）**）
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
  - [x] **C12-feishu-guide** · 源 §4.12 · 菜单点了真出引导卡（依赖 bot-menu 桩）· **优先级：P1** · **已落地**
    - 意图：bot 菜单 / `/feishu-guide` 弹出两步引导卡（选 queue/steer/goal/subgoal/background → 填表单），合成斜杠命令注入会话；菜单有卡则直发，勿只走 fail-open
    - helper：`owner/feishu/steer_card.py`（建卡 / 回调 / `_route_guide_command` 重建 dm source 防 p2p 键失配）+ `owner/commands/feishu_guide.py`
    - 胶水：`plugins/platforms/feishu/adapter.py` `_guide_card_state` / `send_guide_card` / `_handle_guide_card_action` + `hermes_feishu_guide` 分支（`# [owner] C12-feishu-guide`）；`owner/owner-extensions` 注册；`hermes_cli/commands.py` `should_bypass_active_session` 复用 `is_gateway_known_command`（plugin busy bypass）
    - 测：`tests/owner/test_c12_feishu_guide.py`
    - 验证：`python -m pytest tests/owner/test_c12_feishu_guide.py -q`
    - 影响面：飞书引导卡路径；queue 提交经 C12-queue-card 变身状态卡；不改其它卡片
  - [x] **C12-merge-forward-recv** · 源 §4.15 · 合并转发二次拉取成可读记录 · **优先级：P1** · **已落地**
    - 意图：用户发「合并转发」时，bot 看到可读聊天记录（二次 `GET /im/v1/messages/{id}`），而非占位/浅层最多 8 行；失败静默回退占位
    - helper：`owner/feishu/merge_forward.py`（`render_merge_forward_entries`；adapter + 后续 doc 工具共用）
    - 胶水：`plugins/platforms/feishu/adapter.py` `_extract_message_content` 展开 + `_expand_merge_forward_text`（`# [owner] C12-merge-forward-recv`）
    - 测：`tests/owner/test_c12_merge_forward_recv.py`
    - 验证：`python -m pytest tests/owner/test_c12_merge_forward_recv.py -q`
    - 影响面：仅入站 merge_forward 接收路径；工具侧 `om_` 再读属文档增强 commit
  - [x] **C12-doc-ocr** · 源 §4.13 · 飞书文档完整增强（图 OCR + 类型读取 + om_ 工具侧）· **优先级：P1** · **已落地**
    - 核对范围（旧树 §4.13 + §4.15 P2，本 commit 一次落地）：
      1. docx 内嵌图物化下载 + 可选 `vision_analyze` OCR（图 cap 100 / 429 退避 / 缓存预算）
      2. sheet / bitable / wiki 类型推断与读取；wiki 一层子节点；docx 内嵌 bitable
      3. bitable `mode=structure` / `table_index` / `limit` / `filter`
      4. `extract_token` 3-tuple（token, is_wiki, inferred_type）
      5. DM/群聊 env-fallback client（`resolve_client`；drive 薄接）
      6. 工具侧 `om_` 合并转发再读（`read_merge_forward_as_text` + `offset`/`mf_limit`；renderer 复用 C12-merge-forward-recv）
    - helper：`owner/feishu/client_utils.py`（原 `tools/feishu_client_utils` 迁入 owner）
    - 胶水（0b1e269dc0 审查整改后）：`tools/feishu_doc_tool.py` 回上游字面，仅 handler 3 行薄委托 + 顶部标记（`# [owner] C12-doc-ocr`）；schema 扩展与 handler 编排全在 `owner/feishu/doc_tool.py`（post-registration `dynamic_schema_overrides`）；`tools/feishu_drive_tool.py` 回上游字面，env fallback 走 `owner/feishu/drive_tool_patch.py` 运行时改绑 `get_client`（见 C37）
    - 测：`tests/owner/test_c12_feishu_doc_enhancements.py`、`tests/owner/test_c12_feishu_doc_tool_thin.py`（官方文件字面/行为/幂等守卫）
    - 验证：`python -m pytest tests/owner/test_c12_feishu_doc_enhancements.py -q`
    - 影响面：`feishu_doc_read` 全能力；drive 仅 client fallback；不含 memory-approval（queue 状态卡见 **C12-queue-card**）
    - 原可后移的 **C12-doc-types** / **C12-merge-forward-tool（om_）** 随本波一并落地，不另开子点
  - [x] **C12-queue-card** · 源 §4.11 / design queue-steer-lifecycle · 飞书 queue 状态卡（cancel / process_now / steer / freeze）· **优先级：P1** · **已落地**
    - 意图：busy 排队不再只有纯文本 ack；飞书发可操作状态卡（取消 / 立即执行 / 转向），引导卡 queue 提交变身同卡；空闲提交走 freeze + 跳过二次 dispatch
    - helper：`owner/feishu/queue_card.py`（建卡 / 回调 / send）；`owner/patches/queue_cancel_patch.py`（runtime patch `_enqueue_fifo` / `_dequeue_pending_event` / `_busy_queue_command`；token=`_owner_queue_token`）；`owner/feishu/steer_card.py`（guide morph + should_skip / notify）；`owner/feishu/card_sender.py`（`send_card_via_rest`）
    - 胶水：`plugins/platforms/feishu/adapter.py` `send_queue_status_card` / `_handle_queue_card_action` + `hermes_queue_card` 分支（`# [owner] C12-queue-card`）；`owner/owner-extensions` `apply_patch`
    - **patch 导入时机（2026-11-04）**：`queue_cancel_patch.apply_patch` 禁止在插件 `register()` 里 `import gateway.run`（与主线程导入死锁 → `plugins.load_timeout_seconds` 弃载 owner-extensions → 飞书 bot menu `/providers` 报未知命令）；改为 `sys.modules.get` + 延迟 apply。生效需软重启 gateway。
    - 设计：`owner/docs/design/queue-steer-lifecycle/queue-steer-lifecycle.md`
    - 测：`tests/owner/test_c12_queue_card.py`
    - 验证：`python -m pytest tests/owner/test_c12_queue_card.py -q`
    - 影响面：飞书 busy/queue 体验；其它平台仍文本 ack。v2 相对旧树：跳过 MemoryManager prefetch patch（官方已有 `_PREFETCH_GATE`）；i18n 键用 `gateway.queue.usage`；token 无绑定时允许按文案匹配以便 guide morph 复用卡
    - **范围决策（2026-10-27）**：用户指示覆盖原「queue-card 不做」备注
    - **队列容错（2026-10-27）**：`_enqueue_fifo` 整体 fail-open；overlay `feishu.queue_card.enabled`（默认 true）；guide submit `_submit_on_loop` 失败 → `coro.close()` + 失败卡（禁假「已排队」）。**操作者鉴权暂不做**（注释说明；靠「由 xx …」显示名，同审批卡思路）
- [x] **C13** · 源 §7.24–7.26 · progress / approval / english / **recap** explainer · **已落地** · 飞书底座（C04/C10/C11）已齐
  - **统一基建**：单一 `owner.explainers` 块 + `owner/explainers/`（config/llm/registry）；`register_kind` 可扩。详见「§ 二次开发可复用基建 §4」与 `owner/docs/c13-explainers.md`
  - **统一约定（已敲定，代码已做）**：单一 `owner.explainers` 块 + 共享取模 helper；禁止各 kind 各写 provider/model。详见上方「§ 二次开发可复用基建 §4」
  - **配置迁移**：旧顶层 `progress_explainer` / `approval_explainer` / `english_explainer` → `explainers.{progress,approval,english,recap}`；`call_llm(task=…_explainer)` 长 task 名保留
  - **输入预算**：共用 64k（`max_input_chars`）；按辅助模型 **≥256k** 上下文设计；`clip_input` 保尾截断
  - **输出帽**：progress/approval/english 读 `merged.get("max_output_chars")`（模块默认 900/800/1000 仍保留；overlay `explainers.{progress,approval,english}.max_output_chars` 已补同值，H03 #3）；recap 仍 350。**仅 `max_output_chars` 可配**，`max_tokens`/`_MAX_TOKENS` 仍硬编码（2026-10-28 文档澄清）
  - **告警前缀 = notice 匹配键**：默认 `💡 [stream-guard]` 须与 overlay `feishu_card.notice_titles` + `owner/feishu/auto_card.py` 内置表 + C13 各 kind 的 PREFIX 三处同步；`💡 [output-guard]` 有可见串但不在 `notice_titles`（见 `owner/docs/c13-explainers.md`）
  - **kind · recap**
    - 入口：按需 `/recap`（第四 kind）；notice `📋 系统提示：`；正文落 `messages`（`role=notice`）作审计，不入主会话模型；watermark 只管自动门控
    - 自动触发：本轮耗时 ≥ `min_turn_seconds`（默认 180，用户消息 → `on_session_end`）**或** 末条助手可见字数 ≥ `min_assistant_chars`（默认 800，按 Unicode 字符计；`0` 关闭）。有新主回合才发（watermark 防刷）；**不再**用「用户回合数 ≥ 3」单独触发，也**不再**在结束后空等下一条输入。配置 `explainers.recap.auto`；判定逻辑 `owner/explainers/recap/gate.py`。旧键 `idle_seconds` 仅作 `min_turn_seconds` 回退，语义不再是空等（2026-11-17）
    - 自动路由：`pre_gateway_dispatch` 读 `event.source` 并记下本轮起点；`on_session_end` 经 session_store origin 回补 chat_id。打断 / 失败 / 未完成跳过；`agent_loop_stopped` 若先到，仅在结束标志含糊时据此跳过（2026-11-17）
    - **飞书话题发卡（2026-11-11）**：主对话 + 话题并发时，progress / recap / english 只把 `chat_id` 传给 `adapter.send`，丢掉 `source.thread_id`，回顾/进度/英文卡会落到主对话。现于 explainer 路由记住并下发 `metadata.thread_id`（及 `reply_to_message_id`）；主对话（无 thread_id）行为不变，不把 `root_id` 当话题。交互卡在 owner `card_sender` 走官方 reply API（`reply_in_thread=True`，必要时回复话题内最近一条），避免 `receive_id_type=thread_id` 创建触发 99992402。REST 旁路同样认识 thread_id，不再回落到只发 chat_id。测：`tests/owner/test_c13_feishu_thread_cards.py`、`tests/owner/test_c13_recap_auto.py`、`tests/owner/test_c11_auto_card.py`
    - 文案取向：进度条文案（做到哪了/完成度/下一步），禁文件名/表 id 罗列；硬帽仍 350（`clean_output`；提示词要求 ≤220 汉字，2026-11-05）
    - **超预算混合兜底（2026-11-17）**：可见正文超过 `max_input_chars`（默认 64k）才启用；prompt 用同一 compression 链最近一条 recap notice 说明被省略的前半段，并保留尾部原文；无旧回顾则退回纯尾部截断。不沿 session_reset 链，不用 watermark 正文，进度卡忽略。每 3 次混合后做 1 次纯尾部校准。混合阈值与校准规则不变；自动触发已改为「长耗时 / 长结束消息，回合结束立刻判定」，不再空等 180 秒。实现 `owner/explainers/recap/hybrid.py`；设计稿 `owner/docs/design/recap-hybrid-fallback/hybrid.md`；测 `tests/owner/test_c13_recap_hybrid.py`。
    - 卡片：标题色见 C11「notice 卡规则」（2026-11-04）
  - **kind · approval**：审批卡发出前 2–3 句事实解说；飞书冻结卡保留 C13 命令说明附录（send 写入 `_approval_state.body_text` → `build_resolved_card`，2026-11-03）
  - **kind · progress**：沉默期进度旁白；飞书 notice 蓝标题 **「🧭 当前进度」**（原「进度旁白」，`auto_card._DEFAULT_NOTICE_RULES`）；`stream_guard.snapshot.tripped` 时让位；活动戳中文映射 `owner/explainers/progress/activity_i18n.py`（当前进度卡底栏/`_fact_line`/`busy`/长跑心跳的 `current_tool` 复用官方 `display.verb.*`→如 terminal=`正在运行命令`；无工具时译 `last_activity_desc`：精确+模板+裸 tool id；未命中原文；en UI 透传句子仍映射裸 tool id，2026-11-05）；**clarify/审批等待期暂停**：查 `clarify_gateway.has_pending` / `approval.has_blocking_approval`（非事件回放，回调被重绑也有效），整段跳过且不消耗 `max_per_turn`、静默计时冻结并在门消失时重起算，`pause_while_awaiting_user` 可关；测 `tests/owner/test_c13_explainers.py::test_progress_tick_silent_while_awaiting_user_and_resets_after`
  - **kind · english**：`display.language=zh` 且终局整段英文 → 侧路中文解说；不改原文
  - **旁白中文门**：共享 `call_explainer_llm` 在期望中文时，对输出跑 `looks_like_non_chinese_output`（复用 `english/detect.looks_like_english_reply` + 短旁白 latin 回落）；命中则带纠偏 nudge 重试 **1** 次；仍非中文 → 打日志 + fail-open 发最后一次文本。english kind 只门控**译文旁白**，不改被解说的英文原文。`require_chinese` 可在 kind cfg 覆盖；progress/approval 默认跟 `display.language`（2026-11-02）。测：`tests/owner/test_c13_explainers.py`（含 retry / fail-open）
  - **旁白落盘（notice）**：recap/progress/english 正文落同表 `messages`（`role=notice` + `display_kind`）；helper `owner/explainers/persist.py`（`persist_notice`，fail-open；`owner_provider_name` 事后 UPDATE 补列）；trigger：recap `manual`/`auto`、progress `tick`、english `reply`；送模 / 导出 / TUI 一律排除 `role=notice`；设计稿 `owner/docs/design/explainer-notice-persist/README.md`；测 `tests/owner/test_c13_notice_persist.py`；**需软重启 gateway 后生效**（2026-11-05）
- [x] **C14** · 源 §14 · output_guard + stream_guard · **优先级：P1**（阶段一 · 完整版）
  - helper：`owner/output_guard/`（`transform_llm_output`）+ `owner/stream_guard/`（`on_stream_delta`；S1/S2/S3，S3=`is_repetition_dominated`）
  - 注册：`owner/owner-extensions` `register()` + `plugin.yaml` hooks
  - 配置：`owner/config/overlay.yaml` → `stream_guard.*`（默认 `action: interrupt`）+ `output_guard.enabled`
  - **暂缓**：代码 `DEFAULTS["action"]` 仍 `warn_only`（overlay 缺段时的 fail-open 灰度默认）；现网靠 overlay `interrupt`。是否把 DEFAULTS 改成 interrupt 另议
  - **owner 标记拼写归一（H03 #2）**：`owner/output_guard/__init__.py` 注释已归一为 `# [owner] P2-3: …`（唯一拼写）
  - 胶水：`agent/stream_delivery.py`（`request_stop` + latch）；`turn_finalizer.apply_llm_output_transform`（C1 interrupted + reasoning）；`turn_final_response`（C1）；`turn_api_call.handle_api_interrupt`（C2 early-persist 前 transform）
  - 落地说明：`owner/docs/c14-output-stream-guard.md`
  - 测：`tests/owner/test_c14_guards.py`；自检 `python -m owner.{output,stream}_guard.selfcheck`
  - 依赖：无硬依赖未做定制；C13 只读 stream_guard.snapshot（方向 C13→C14）
- [x] **C15** · 源 §7.2–7.3 · Memory synthetic guard + OpenViking sync recall（**无召回卡**） · **优先级：P1** · **本机落地**
  - **用户拍板**：Viking **不做召回卡**（飞书交互卡 / QQ 文本卡均不迁）；清单原「sync recall/card」收窄为 sync recall + advisory + dedup。
  - **§7.2 Memory 合成护栏**：
    1. `owner/patches/memory_synthetic_guard_patch.py` — 合成前缀 / 多数 slash 控制命令跳过 prefetch+sync；`/queue` `/steer` `/goal` `/subgoal` `/background` 例外
    2. 设计：`owner/docs/memory-synthetic-recall-guard.md`
    3. 测：`tests/owner/patches/test_memory_synthetic_guard_patch.py`
  - **§7.3 OpenViking（无卡）**：
    1. 同步召回本身已在用户插件 `hermes_plugins.openviking`（官方 bundled `plugins/memory/openviking` 已移除）
    2. `owner/patches/openviking_owner_recall_patch.py` — advisory 语气（`agent.memory_context.build_memory_context_block`）+ peer-mirror URI 去重；**无发卡路径**
    3. `owner/patches/openviking_recall_config.py` — `openviking:`（兼读 legacy `openviking_sync_recall`）
    4. 配置：`owner/config/overlay.yaml` → `openviking.{advisory,dedup}`（**无 `recall_card` 段**）
    5. 测：`tests/owner/patches/test_openviking_owner_recall_patch.py`
  - 胶水：`owner/owner-extensions/__init__.py` `register()` fail-open apply（护栏 + OV）
  - **未迁（明确不做）**：旧树 `openviking_owner_recall_patch` 召回卡发送/防抖/执行器；ChatLog 截断（仍仅旧树 bundled 插件侧）；`recall_card` overlay 段
- [x] **C16** · 源 §7.4 · Cron env 隔离（ContextVar + restart scrub） · **优先级：P1** · **验证状态：官方已修 + 薄缺口已补（2026-10-30）**
  - v2：`gateway/session_context._VAR_MAP["HERMES_CRON_SESSION"]` + `cron/scheduler._CronRunScope` set/reset；gateway/ACP/TUI bind `cron_session=""`；`tools/approval_context` ContextVar 感知；外部 worker 剥离 presence vars。无进程级 `os.environ["HERMES_CRON_SESSION"]=1` 写入。
  - **env 残留清理**：`owner/cron/restart_scrub.py`（`owner_cron_scrub_process_env` / `owner_cron_scrub_watcher_env`）清 `HERMES_CRON_SESSION`/`HERMES_SESSION_KEY`/`HERMES_SESSION_ID`；胶水：`gateway/run.py`（dotenv 后）+ `gateway/run_shutdown._restart_watcher_env`。测：`tests/owner/test_c16_cron_env_scrub.py`。
- [x] **C17** · 源 §8.1 · Checkpoint Mutation Predictor · **优先级：P1**（阶段一）
  - **破坏性覆盖判定（2026-10-27）**：官方 `_REDIRECT_OVERWRITE` 不再把 `2>&1`/`>&2` 当成破坏性覆盖（消 checkpoint 误报）
  - helper：`owner/checkpoint_predictor/`（`predict_and_checkpoint` / static_parser / llm_predict）
  - 配置：`owner/config/overlay.yaml` → `checkpoints.*`（predict_enabled / llm timeout / cache / static threshold）
  - 胶水：`agent/tool_executor.py` `_begin_tool_execution` terminal 分支（替换 destructive+cwd；保留 container skip）
  - 设计：`owner/docs/checkpoint-mutation-predictor.md`
  - 测：`tests/owner/test_checkpoint_predictor.py`
  - 依赖核验：无硬依赖未做定制；硬依赖 = 官方 CheckpointManager + 已落地 C01 `patch_config`；LLM（auxiliary `task=approval`）与 `_owner_warn_callback` 为软依赖 fail-open
  - **预测失败 / 静态为空的告警与兜底（2026-10-27）**：`agent_init` 挂 `_owner_warn_callback=_emit_warning`；预测失败回落 `_emit_warning`；静态为空且 `_is_destructive_command` → cwd 窄兜底快照（跳过 home/`/`，`ensure_checkpoint` 返回 False 不算成功）；静态+LLM 皆空时只读命令降 `logger.debug`，破坏性才用户可见 warn
  - **相对路径基准 + 快照根收窄（2026-11-08 · tip `b757e421b2`）**：`static_parser.effective_cwd` 消费命令开头的 `cd` 链，相对预测路径按**生效目录**解析（原来一律按 session cwd：`cd /data/... && python x.py > out.txt` 在 cwd=`/root` 时被算到 home，触发"预测路径均被安全过滤"误报并弹卡）。`_root_is_blacklisted` 把 `/dev /proc /sys /tmp /var/cache /mnt`、`.git`/`__pycache__`/`node_modules`/`.venv`、Hermes 自身 `cache|tmp|logs|sandboxes|checkpoints` 排除出快照根；落在 home/root 的**非破坏性**写入与黑名单命中降 `logger.debug`，只有破坏性命令弹卡。根因数据：`agent.log` 10/30–11/06 该类 warn 406 条（≈ 同期 terminal 调用的 1/3），`cd` 开头占大头。
  - **oversize 过滤修复（2026-11-08 · tip `b757e421b2`）**：`tools/checkpoint_manager._drop_oversize_from_index` 的 `git rm --cached` 加 `-f` —— 热文件（浏览器缓存/活动 DB）在 `add -A` 与 `rm` 之间仍在变化时，git 以 `staged content different from both the file and the HEAD` 拒绝删除，`max_file_size_mb: 10` 因此失效（`/tmp` 快照里进了 1.7GB blob，store 涨到 1.9GB）。
  - **heredoc 比较误判降噪（2026-11-09）**：`static_parser.strip_heredoc_bodies` + 收紧 `_REDIRECT_OVERWRITE`（排除 `>=`）；`_command_looks_destructive` 先剥 heredoc 再调官方启发式， 避免 Python `n>=maxn` / `printed>0` 被当成 shell 重定向而发飞书 tip；home/`/` 过滤与真 `echo > file` tip 保留。 测：`tests/owner/test_checkpoint_predictor.py`（heredoc 比较 / 外壳重定向 / 不弹 tip）。
  - **store 运维（2026-11-08）**：node010 跑 `hermes checkpoints prune -f`：311 → 13 个项目，删 19 orphan + 279 stale，回收 525MB。`config.yaml` 打开 `checkpoints.auto_prune: true`（此前网关 housekeeping 不 prune、`git gc` 从不执行，`.gc-pending` 长期悬挂；每拍一次即丢一个最旧快照，`/rollback` 实际只剩一拍）。测：`tests/owner/test_checkpoint_predictor.py`（新增 cd 前缀 / 黑名单 / 降噪 8 例）。
- [x] **C18** · 源 §9.1 · per-chat display overrides · **优先级：P1** · **忽略（不做）**（2026-10-27 用户拍板）
  - 范围（未落地，仅记）：`owner/display_overrides.py` 机制 — `owner.display.per_chat.<platform>.<chat_id>.*` 覆盖显示族（示例 yaml：`tool_progress` / `streaming` / `interim_assistant_messages` / `tool_preview_length`；解析器还可覆盖 `show_reasoning`、`long_running_notifications`、`tool_progress_grouping` 等经 `resolve_display_setting_for_source` 的键）+ 多处 `source=` 透传胶水。**不是**只有 tool_progress/streaming 两项。
- [x] **C19** · 源 §5 · 链式快捷命令 `;;` + Quick Alias · **优先级：P1**（阶段一）
  - helper：`owner/commands/chained_quick.py`（`parse_chained_commands` / `expand_chained_quick_alias`）
  - 胶水：`cli.py` `_run_quick_command`；`gateway/run_inbound.py` `_hm_resolve_command`；`tui_gateway/methods_tools.py` `_dispatch_quick`（`type: chain`）
  - TS：`apps/shared/src/slash.ts` + `ui-tui/src/app/createSlashHandler.ts`；i18n `gateway.chained_commands_executed`
  - 测：`tests/owner/test_chained_quick.py`
- [x] **C20** · 源 §3.9 · Semantic Audit Gate · **优先级：P1** · **忽略（不做）**（2026-10-27 用户拍板：飞书人在环审批已够用，非刚需；成本/误拦不划算）
- [x] **C26** · 源 §2.10–2.11 + §4.9 · providers 白名单 / 缓存 TTL / `/providers` · **优先级：P1**（阶段一）
  - 白名单：官方 `has_explicit_models` / `_models_config_is_allowlist` 已覆盖，沿用
  - 缓存：`_PROVIDER_MODELS_CACHE_TTL` 24h；`_store_cache_entry` 目录无变更不写盘
  - `/providers`：`owner/commands/providers.py` + `owner/owner-extensions`（`plugins/owner-extensions` 符号链接）；文本列表；飞书交互卡见 **C26-feishu-picker**
  - 测：`tests/owner/test_providers_command.py`、`tests/owner/test_provider_models_cache_ttl.py`
  - **deepseek-v4-flash alias（2026-11-04）**：`owner/providers/deepseek_aliases.py` — 原生 DeepSeek 上把已下架公开 id `deepseek-v4-flash` 折到 `deepseek-flash`（`GET /v1/models` 现仅 `deepseek-flash`/`deepseek-v4-pro`；wire 仍接受旧 id）。`hermes_cli/model_normalize.py` 薄胶水 update `_DEEPSEEK_RETIRED_ALIASES`。damodel 等聚合商 id 不动。测：`tests/owner/test_deepseek_aliases.py`。
  - **listing tighten（2026-11-04）**：`owner/providers/listing_filters.py` — 剔除 Alibaba Coding Plan、按量只留优先 `alibaba-cn`；`allow_ambient_anthropic_listing()→False` 挡住 Claude Code 钥匙串假阳性；`_finalize_picker_rows` 薄胶水。测：`tests/owner/test_listing_filters.py`。
- [x] **C26-feishu-picker** · 源 §4.9 飞书半边 · `/providers` 交互卡（provider→model→确认）· **优先级：P1**（阶段三）· **已落地**
  - `owner/feishu/model_picker.py`；adapter `_model_picker_state` / `send_model_picker_card` / card-action `hermes_model_picker`
  - 测：`tests/owner/test_c26_model_picker.py`；说明：`owner/docs/c26-model-picker.md`
- [x] **C21** · 源 §2.4–2.6 / §2.9 · 模型杂项 · **优先级：P1** · **忽略（不做）**（2026-10-27 用户拍板：MiniMax/Kimi 不要；其余官方/C10/C26 已覆盖或现网无感；§2.6 Qwen debris 若飞书再出现截断 thinking 再单开）

### P2 暂缓

- [x] **C22** · 源 §6.1–6.2 · TUI skin / ruolin · **优先级：P2** · **忽略（不做）**（2026-10-27 用户拍板：仅皮肤/ruolin，不迁）
- [x] **C23** · 源 §11 · 运维脚本包 · **优先级：P2** · **运行时已与仓库软链脱钩**（2026-10-27 用户拍板方案 B）
  - **现况**：`~/.hermes/scripts` 为独立真目录（不再 → `hermes-agent/owner/scripts`）；备份在 `~/.hermes/scripts.bak-20261027-1831`。worktree `owner/scripts/` 仍可留作源拷贝（未入库 `??`），**整包迁仓不再主线**。
  - **仍在跑（运行时目录已有，不必迁仓）**：日备三件套、`cron-health-check`、`todo-scan`、Viking quality kanban、周报 `feishu_weekly_ops`、`swagger-kanban`。
  - **可忽略（现网 paused/不用）**：HN Daily、Skill 同步、Upstream Sync、汇率、mac backup-configs、swagger-collector。
  - **§11.2 job args→CLI**：✅ 已落地（2026-10-27）。逻辑 `owner/cron/job_args.py`；薄胶水 `cron/scheduler_script.py` / `cron/scheduler_prompt.py`（`# [owner] §11.2`）；调度跑 script 时把 `job["args"]` 映射为 `--key value`（`True`→裸 flag；`False`/`None`/空串跳过）。现网样例：`viking`→`--mode pref-card`，backup→`--BACKUP_QUIET 1` 等。测：`tests/owner/test_cron_job_args.py`。**整包迁仓仍不做**。§11.1 目录豁免视官方/软链现状可再议。
  - 舰队开户自动化（O1–O5 已落地）：见 `owner/docs/design/c05-feishu-user-routing/fleet-add.md`（对话触发 → Hermes 执行；归属 C05/Ops，非整包迁仓；非人手敲 CLI 主路径）
  - **开户 skill 对齐（归属 C05 O5，非 C23 整包迁仓）**：westcloud `xy-user-onboarding` 已与开户内核对齐（allowlist + home channel；同 fleet-add.md §5 / D1）；skill 仍在仓外 skills 树
  - 开户 allowlist + home channel：收集 ou 时同步写 **目标 + Hub** `FEISHU_ALLOWED_USERS` 与目标 `FEISHU_HOME_CHANNEL`（同 fleet-add.md §2）
- [ ] **C24** · 源 §12 / §16.8–16.16 · 治理标记、T2-11~20 换码债、全量 `[owner]` 铺开 · **优先级：P2**（v2 **不做**「官方测全绿」与全量标记战役；H03 #4 仅轻量补了本轮相对上游官方运行时 hunk 标记，不算 C24 收口）
- [x] **C25** · 源 §4.7–4.8 · 编辑上限轮转 / progress dedup / 中文摘要等体验项 · **优先级：P2**（`/providers` 已归 **C26**）
  - 编辑上限轮转：`SendResult.rotate` + Feishu 230072/230075；`classify_edit_failure`；`run_turn_progress` rotate/drain
  - progress dedup：`append_dedup_counter` 防 ``` 污染；薄胶水 `_append_progress_repeat_count`
  - 压缩中文摘要：`owner/feishu/compression_summary.py` + `hygiene_compression_notice.py`；auto/manual/hygiene 薄胶水
  - 测：`tests/owner/test_c25_*.py`

**定制段：原 C01–C25 + C26（providers）+ C27（resume 卡）+ C28（platform_users）+ C29（飞书 WS 重连守卫，见「§ 渠道运行时加固」）。执行顺序：四阶段（见上）；C29 穿插、非阶段阻塞。**

---

## § 排期 / 卫生（非阶段一阻塞）

> 不进四阶段必做；有空再开。与「明确不做」不同：这里是**以后要做、现在不排**。

- [x] **H01** · **官方 test 污染梳理** · 审计见 WorkBuddy `tests-pollution-audit-2026-10-23.md`；优先项已修：`73fa8f53e3`…`de3dc9ecff`（#1/#2/#5/#6/#7 R1/#10 等）。#7 仅守卫登记第一步；网络守卫等后置。
- [x] **文案硬编码 ⚠️→💡（审批门等）** · 2026-10-28 · 飞书/多平台 `_EA_HEADER`、`gateway/run` 审批回落、`tools/approval` 模型侧、owner 飞书告警/queue/media/skill、C13 `stream-guard` notice 匹配键与 overlay 同步为 💡；cron 失败告警同改。刻意未动：agent 轮次诊断刷屏、CI/doctor/Slack emoji map、setup allowlist print。
- [x] **H02** · CLI approval `input()` 超时僵尸 reader · 仅无 callback 且非 PT 路径。落地：`owner/approval/cli_read_choice.py`（POSIX TTY + 原装 `input` → `select`+`os.read`；否则回落官方 daemon `input()`）；`tools/approval_prompt.py` `_read_choice` 薄委托。gateway/飞书/QQ/微信与正常 TUI **无感**。测：`tests/owner/test_h02_cli_read_choice.py`。
- [x] **H03** · **审核遗留（2026-10-30 核实收口）** · 勿再当「漏做」：
  1. ~~C14 `stream_guard.DEFAULTS["action"]=warn_only`~~ → **已改** `interrupt`（与 overlay 完整版对齐；缺 overlay 不再 fail-open）。测：`test_stream_guard_defaults_action_interrupt`；`warn_only` 仍可显式配置。
  2. ~~`[owner-patch P2-3]` 旧拼写~~ → **已落地**：`# [owner] P2-3: …`
  3. ~~C13 三 kind 输出帽硬编码~~ → **已落地**：读 overlay `max_output_chars`（见 C13 条）
  4. **标记纪律**：~~本轮未批量扫~~ → **轻量已补**（相对 `upstream/main...HEAD` 官方运行时缺标 12 文件补 `# [owner]`；**未**做 `owner/validation/` 迁入、**未**开 C24 全量 inventory / 官方测全绿；`tests/owner/*` 整文件属 owner 域跳过；其余官方 test 改动本轮不铺标）
  5. `owner/validation/` 仅 `samples/`、无 `inventory.yaml`（Check 7/8 工具未迁）— **旁置保留**（绑 C24；本轮不删不发明 inventory）
  6. ~~C02 `/model` → wire `custom` 归因~~ → **已核实并修**（见 C02「已核实并落地」：`custom:<slug>` 剥前缀）
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
- [x] **C22** · TUI skin / ruolin（源 §6.1–6.2）— **明确不做**（用户拍板；仅皮肤引擎与 ruolin 系列，不迁）
- [x] **C20** · Semantic Audit Gate（源 §3.9）— **明确不做**（用户拍板；人在环审批已覆盖主线，不迁语义审计门）
- [x] **C21** · 模型杂项（源 §2.4–2.6 / §2.9）— **明确不做**（用户拍板；MiniMax/Kimi 不迁；其余已覆盖/现网无感）

---

## § 渠道运行时加固（穿插）

- [x] **C29** · 飞书 WS 重连守卫（2026-11-02）· **优先级：P1** · **已落地** · tip `a10f7c49f1`
  - **根因**：keepalive ping timeout 后 SDK `trying to reconnect for the 1st time` 卡在无 timeout 的 `requests.post`（`_get_conn_url`）；线程仍活 → supervisor 不重建；进程看似健康、入站全哑。
  - **策略**：不整进程 `gateway restart`；强制有限 SDK ladder；conn-url timeout；supervisor 首次快、其后约 **10 min** 单飞重建；连续失败达上限 → 告警并停止自动重试（`note_link_up` 清零；防数天空转占资源）。
  - **落地**：`owner/feishu/ws_reconnect_guard.py`；adapter 薄挂（apply / supervise / note_*）；设计 `owner/docs/design/feishu-ws-reconnect/README.md`
  - **配置**：overlay 可选 `feishu.ws_reconnect_guard`（DEFAULTS：`supervisor_retry_interval_s=600`，`max_failures=18`，`conn_url_timeout_s=30`，`sdk_reconnect_count=2`）
  - **测**：`tests/owner/test_feishu_ws_reconnect_guard.py`；官方 multiplex supervise 测已接短 interval policy
  - **生效**：需重启 gateway 后新 WS client 才带 guard
- [x] **C30** · systemd TimeoutStop 启动误报（2026-11-06）· **优先级：P2** · **已落地** · tip `578ec5c72b`
  - **根因**：系统级 unit（cgroup `system.slice`）时 `systemctl --user show` 对未加载同名 unit 仍返回默认 `TimeoutStopUSec=1min 30s`（LoadState=not-found），对齐检查误报 90s < expected。
  - **策略**：按 cgroup scope 优先探测；仅 `LoadState=loaded` 才解析 TimeoutStopUSec；不关检查。
  - **落地**：`owner/patches/systemd_timeout_probe.py`；`gateway/shutdown_forensics.py` 薄委托 + prefer_scope。
  - **测**：`tests/owner/patches/test_systemd_timeout_probe.py`；`tests/gateway/test_shutdown_forensics.py` alignment 段。
  - **生效**：需重启 gateway 后启动对齐检查才走新探针。
- [x] **C31** · Docker profile 网关重启/上线通知带中文名（2026-11-11）· **优先级：P1** · **已落地** · tip `f42d862ab9`
  - **现象**：profile 容器的「Hermes 正在重启」「网关已上线」与 Hub 文案完全相同，分不清是哪个人的网关。
  - **策略**：复用旧 owner §7.14 `{profile_tag}`：`owner/gateway/lifecycle_copy.py`；default / custom / Hub 不加标签。标签解析：`HERMES_LIFECYCLE_LABEL`（手工覆盖，非官方）→ overlay `fleet_profiles.<id>.display_name`（人卡短中文名，集中管理；主来源）→ `profile.yaml` `display_name` → `profile.yaml` `description` → `HERMES_PROFILE`。overlay 查找：`HERMES_OVERLAY_PATH` → `$HERMES_HOME/overlay.yaml`（Hub/本机；容器内该路径是 per-profile 目录，不是舰队 overlay）→ 约定路径 `/etc/hermes/overlay.yaml`、`/data/hermes/overlay.yaml`。`fleet_add` compose 模板增加 `{hermes_root}/overlay.yaml:/etc/hermes/overlay.yaml:ro` 并设 `HERMES_OVERLAY_PATH`。本机 overlay 仍不写舰队段。node010 人卡已补短中文名（含张文国、曹灿、谢劼丹等；hermesxiyun 仍为默认服务号）；现网 13 个短名容器 compose 已加 overlay 只读挂载。
  - **落地**：`gateway/run_shutdown.py`、`gateway/run_notifications.py` 薄委托，fail-open；不改官方 locale 骨架，按锚点插入标签（`Hermes` / `网关` / `Gateway`）。
  - **测**：`tests/owner/gateway/test_lifecycle_copy.py`；`tests/owner/test_fleet_add_o1.py` / `test_fleet_add_o3.py` 覆盖 compose 挂载与 `HERMES_OVERLAY_PATH`。
  - **生效**：需软重启对应 Docker profile 网关（USR1）；Hub 不重启。
- [x] **C32** · 图像路由 `prefer-native` 档位（2026-11-12）· **优先级：P1** · **已落地** · tip `14d4eccc6c`
  - **根因**：`auto` 下只要显式配了 `auxiliary.vision`，`decide_image_input_mode` 就无条件返回 `text`（维护者 2026-08-28 决策：命名的视觉后端即 de-facto 路由），主模型原生视觉被旁路；而官方 `providers.md` 又承诺 `model.supports_vision: true` 是单旋钮 —— 两者冲突，实测 `auto + supports_vision + aux 显式 = text`。根子是 `auxiliary.vision` 一键背三职（入站路由开关 / `vision_analyze` 后端 / 文本模型兜底描述器），无法表达「主模型能看图就用主模型，不能看再用 aux」。
  - **策略**：**不动** `auto` / `native` / `text` 既有语义（保上游可合并），新增第四档 `prefer-native`：先查主模型 `supports_vision`，`True` → `native`，否则 → `text`（走 `auxiliary.vision` 描述器）；显式 aux 后端在该档只作 fallback。
  - **落地**：`agent/image_routing.py`（`_VALID_MODES` 加档位、`decide_image_input_mode` 新增分支并前移 `extra`、模块 docstring）；`website/docs/user-guide/features/vision.md` 路由表补 `prefer-native` 行。
  - **测**：`tests/agent/test_image_routing.py`（`_coerce_mode` 认可新档位；主模型支持→native、不支持→text），该文件 53 passed。
  - **配置**：本机与 node010 `config.yaml` → `agent.image_input_mode: prefer-native`；`auxiliary.vision` 保持 `deepseek/deepseek-v4-flash` 非空，作文本模型兜底。
  - **生效**：需重启 gateway；旧进程不认识新档位会回落 `auto`（即 `text`）。cron 等子进程启动时即读到新代码。
- [x] **C33** · `feishu_doc_read` 读取 docx 嵌入式电子表格（2026-11-16）· **优先级：P1** · **已落地** · tip `58522ff021`
  - **根因**：docx 的「插入 → 电子表格」是 `block_type=30` 的 inline sheet block，`raw_content` 对它**不产出任何文本**（连占位符都没有）。旧实现只回填了 image(27) 与 bitable(18)，于是数据全在表格里的文档读回来只剩标题骨架——实测某拓扑分析文档 5 个表格共 111 个单元格 = 正文 50.4% 字符、**全部 14 个 IP 与 5 个 MAC 全丢**，且失败是静默的（模型拿到的是一段没有 IP/端口的定性叙述）。
  - **策略**：不重写读取管线（raw_content 还负责拍平 grid/样式），沿用 bitable 的「扫块 → 追加」写法；`sheet.token` 形如 `{spreadsheet_token}_{sheet_id}`，按 sheet 元数据取行列数后只读该 sheet 的范围（不是整个 spreadsheet），渲染 TSV。raw_content 不提供位置线索，故扫描时记录**最近的前置标题**作为小节锚点。读取失败输出「（读取失败：<token>）」占位，杜绝静默丢弃。
  - **同族 bug**：sheets API 的带样式单元格是 segment 列表（`[{"text": "Partner "}, {"text": "e4:84…"}]`），旧代码借用 bitable 的 `_stringify_field` 会在片段间插 `", "`，把 `Partner e4:84:29:fc:43:2f` 变成 `Partner , e4:84…`（MAC/`{ACDEF}`/`0xa` 全部被污染）。新增 `_sheet_cell_text` 逐段拼接，`read_sheet_as_text` 与嵌入式表格共用。
  - **落地**：`owner/feishu/client_utils.py`（`_sheet_cell_text`、`_block_plain_text`、`list_docx_sheet_blocks`、`_sheet_meta_by_id`、`_render_embedded_sheet`、`read_docx_embedded_sheets`；`read_docx_with_images` 追加 sheet 段）；schema 描述句落在 `owner/feishu/doc_tool.py` 的 `SCHEMA_OVERRIDES`（0b1e269dc0 整改后 schema 扩展居 owner 侧，官方文件回上游字面）。
  - **测**：`tests/owner/test_c12_feishu_doc_enhancements.py` 105 passed（新增 16 条：顺序/跨页标题继承/坏 token/失败占位/元数据复用/富文本单元格）。注意 test 环境 `.venv` 无 `lark_oapi`（该文件 69 条用例在 `scripts/run_tests.sh` 下本就红），需用 `venv/bin/python -m pytest` 跑。
  - **生效**：需重启 gateway（模块已在旧进程内存里）。cron 等子进程启动即生效。
- [x] **C34** · gateway 生命周期守卫豁免远端 ssh（2026-11-19）· **优先级：P1** · **已落地** · tip `429b611a4e`
  - **根因**：生命周期守卫按**文本**匹配 `systemctl restart` / `launchctl` / `hermes gateway …`，无法区分作用于哪台机器。`ssh node010 '<命令>'` 重启的是另一台主机的网关，SIGTERM 只沿本地进程树下传，本进程不会被杀；execute_code 里 `subprocess.run(["ssh", …])` 同理 —— 两者都是纯误报，2026-11-19 实际卡住了 node010 主网关的重启操作。
  - **策略**：**先解析、后剥离、再扫描**，不做"见 ssh 就放行"。① terminal：按 `;`/`&&`/`||`/`|`/换行分段（引号内不切），识别 `sudo/env/timeout/nice/stdbuf/nohup/time/command/exec` 包装与 ssh 带值选项，远端段从扫描目标里剥掉，剩余本地段照原样过 `scan_gateway_lifecycle`；② execute_code：用 AST 找出 argv 全为字面量的 `subprocess.*` / `os.system|popen` 调用，判定远端 ssh 后把调用 span 用空格抹掉（保留行号），其余代码照扫。
  - **仍拦（fail-closed）**：ssh 目标为本机（hostname/短名/loopback/unspecified IP）、`ProxyCommand`/`LocalCommand`（本地执行）、`| bash` 等本地 shell 消费远端输出、同一命令行/同一 cell 里残留的本地生命周期调用、argv 含变量或 f-string 的调用。
  - **落地**：`tools/terminal_tool_guards.py`（`_split_shell_segments`、`_strip_command_wrappers`、`_ssh_target_host`、`_remote_ssh_host`、`_command_without_remote_ssh_segments`、`code_without_remote_ssh_calls`；`gateway_lifecycle_block` 改为扫 `scan_command`）；`tools/code_execution_tool.py`（`scan_code = code_without_remote_ssh_calls(code)` 薄挂，host-kill 判定同步改用 `scan_code`）。
  - **测**：`tests/tools/test_remote_ssh_lifecycle_exemption.py` 13 passed（7 条命令侧 + 6 条源码侧，含本机/ProxyCommand/管道/mixed/非字面量反例）；同批 `test_launchctl_guard_diagnostic.py`、`test_execute_code_lifecycle_guard_deadline.py` 4 passed。
  - **生效**：需重启 gateway（运行中的进程仍持有旧函数）；cron / 子进程启动即生效。
- [x] **C35** · 飞书 queue 状态卡按钮操作者鉴权（2026-11-19）· **优先级：P0（安全审查）** · **已落地**
  - **根因**：C12 queue 状态卡（`06c604c04a` / `d0e0f7e4fd`）三按钮（引导/立即处理/取消）**不校验点击者**（d0e0f7e4fd 明确"暂不做"）——群内任何成员都能取消 / 插队 / 转向**他人**的排队消息（越权 + 可打断他人任务）。旧引导卡的「撤销队列」按钮同样裸奔。
  - **策略**：复刻 resume 卡（`26d3f202cc`）的操作者比对语义：`event.operator.open_id == get_token_meta(token)["source"].user_id`（两条注册路径——busy `/queue` 与引导卡提交——都已在 token meta 存发起者 `source`，其 `user_id` 即发起者 open_id）。按审查要求 **fail-closed**（resume 缺 open_id 是放行的，此处收紧）：点击者 open_id 缺失、token 未知 / 未携带归属者身份 → 一律拒绝。不做角色体系，仅归属者可操作。
  - **拒绝反馈**：toast-only、**不**更新卡片——状态卡是群内共享消息，回调回 card 会原地替换全员可见卡片；若用终态卡回拒绝，任何群成员点一下就销毁归属者的三个按钮（变相 DoS）。文案走 i18n 覆盖键 `gateway.queue_card.action_denied`（`owner/config/locales/zh.yaml`），代码内同款中文兜底（缺键不裸显 dotted key）。
  - **落地**：`owner/feishu/queue_card.py`（`is_queue_operator_authorized` / `queue_owner_open_id` / `queue_operator_open_id` / `queue_denied_response` + `handle_queue_card_action` 单点拦截）；`owner/feishu/steer_card.py`（旧 `_handle_cancel_queue` 同款守卫）。
  - **测**：`tests/owner/test_c12_queue_card.py` 23 passed（新增 7 条：归属者 cancel/steer/process_now 通过、他人四步全拒且不触发生命周期、缺 operator/open_id/归属者/未知 token fail-closed、i18n 命中与缺键回退、yaml↔代码漂移守卫、旧撤销按钮双路径）；同批 guide/resume/C04/C05 卡片套件 89 passed。
  - **生效**：需重启 gateway；重启前旧进程仍无鉴权。已存在于群内的旧状态卡点击同样受控（token meta 在内存里，跨重启丢失 → fail-closed 拒绝，与既有"已消费/清理"行为一致）。
  - **相关 commit**：`df7c06b8bf`（2026-11-19 审查修复批）
- [x] **C36** · 近月 commit 审查修复批（2026-11-19）· **已落地**
  - **背景**：对 2026-10-19 起近月 188 条本地 commit 做规范+逻辑双维审查（4 子代理分批），本批收口全部审查发现。
  - **逐项**：
    - `472f69e731` **C26 活性缺陷**：`_store_cache_entry` 跳写不刷 `at` → 首过 24h TTL 后永远 stale、每次读取触发 SWR 实拉。加 60s 对称跳写窗口。
    - `6e2a7074a2` **C17 回归（06d7cdbcc9）**：`&> file`/`>&file` 覆盖写漏判破坏性（叠加 190a300a16 后告警也消失）。官方端三分支正则 + static_parser fd 判定收窄，39 例矩阵双端对齐。
    - `df7c06b8bf` **C35**（见上条目）。
    - `cded74eae3` **C05 M1 缺口**：`/v1/feishu/card-actions` 缺 send_only 门。判定收敛 `owner/feishu/profile_routing.send_only_gate_rejection`，官方两端薄调用 fail-closed。
    - `d8fb4c173d` **fleet_add 安全**：apply 四层重跑共享校验器（uid 正则 + 路径白名单），useradd 全 argv 去 `shell=True`，`--fixture`×apply 拒绝；34 项注入新测。
    - `bfef32505e` **C04 缓存 + B17 边界**：`resolve_name` 短路只认未过期热表（24h 后不再永久陈旧）；clarify 空串答案改 `entry.response is None` 判定。
    - `69068d7bc3` **image-hub + C02**：owner 导入失败显式 `owner_import_error` 不静默落 FAL；`switch_model` 裸 custom 时经 `canonical_custom_identity` 恢复命名 alias。
    - `a5a355d93e` **a6e7e0e672 P2 违规整改**：`format_running_tool` 迁 `owner/i18n/running_tool.py`，`agent/display.py` 留 3 行委托 + 标记；19 项新测钉行为一致。
    - `76dc056a20` **locales 补齐**：C04/C10/C19/C27/B17 共 30 键只写了 en+zh，其余 15 个 bundled locale 全缺（`test_i18n` 30 项红灯）；14 语言英占位 + zh-hant 繁体真译，`SQL_LIKE_ANCHORS` 补攔截/審批/拒絕繁体锚点。
    - `7f54daabe3` **pm_tar_compat 补测**：安全敏感 fallback 此前零测试，24 项回归（逃逸三态/SymlinkOrder×2/mode 归一/setuid 清除）。
    - `099c63f22b` **标记收口**：补 12 个官方文件缺失的 `[owner]` 标记（含恢复 79b1b181ed 删掉的 session_ingress 标记、O 段 run.py/run_turn.py/base.py 残留 hunk、14d4eccc6c image_routing），零行为改动。
  - **补登（审查发现的历史漏登）**：`a4d5a41f70`（C17 引号感知+只读闸门，2026-11-12）此前未按 §6.1 登记，现补记于本批。
  - **验收**：合并跑 `tests/owner` + 触及的 agent/tools/pm 套件 **1430 passed, 2 skipped**；`test_i18n` 54/54 全绿。
  - **流程教训（审查结论，留档）**：三个"落地即坏"（recap kwargs 误配 / queue patch 注册期死锁 / resume 卡空 ack）共性根因是单测用自造 kwargs/mock 未对接真实官方调用点——hook/patch 类功能应补真实调用点契约测试。
- [x] **C37** · `0b1e269dc0` 结构性违规整改：feishu 官方工具文件回上游字面（2026-11-19）· **已落地** · tip `b39336057a`
  - **违规**：`0b1e269dc0` 把官方 `tools/feishu_doc_tool.py` 从上游 70 行原地重写为 247 行（schema 15-95 行加 7 参数、handler 98-235 行编排内联），`tools/feishu_drive_tool.py` 亦内联 `resolve_client` + 错误文案改写——违反 §2.1「官方 schema 字面不动、扩展走运行时 patch」。
  - **整改**：① `tools/feishu_doc_tool.py` 回上游字面，仅保留 handler 3 行薄委托（函数内 import `owner.feishu.doc_tool.handle_feishu_doc_read`）+ 顶部 2 行标记，`git diff main --numstat` = **5 插入 / 28 删除**；② schema 扩展（7 参数 + C33 嵌入式表格描述句）收进 `owner/feishu/doc_tool.py::SCHEMA_OVERRIDES`，`apply_patch()` 经 `registry.get_entry().dynamic_schema_overrides` 整键替换（`get_definitions` 浅合并，官方静态 schema 零改动），幂等、entry 缺失 fail-open；③ handler 编排（om_ 分页/wiki/文件夹/bitable/sheet/docx OCR）原样迁 `handle_feishu_doc_read`；④ `tools/feishu_drive_tool.py` 回上游字面（0 diff），env fallback 改 `owner/feishu/drive_tool_patch.py` 运行时改绑模块局部 `get_client`（唯一行为损失：无 client 错误文案回退上游短句，纯 cosmetic）。
  - **接线时序**：gateway 启动 `discover_plugins()` 先于 `model_tools` 导入工具栈（`run_startup.py::_start_register_plugins_relay_hooks`），register() 时 entry 常不存在 → `apply_patch` 对轻模块 `tools.feishu_doc_tool` force-import 触发注册（`feishu_lark` 只 import json/threading，无 queue_cancel_patch 式死锁风险），非 defer 线程模式。
  - **测**：新增 `tests/owner/test_c12_feishu_doc_tool_thin.py` 9 条（上游字面护栏含注册 entry schema 等值断言、官方源无扩展字面、委托透传 args/kwargs、apply 后 `get_definitions` 出全 7 参数、双 apply 幂等、drive 改绑单次包裹/注入优先/无 client 报错）。
  - **验收**：c12 feishu 三套件 125 passed（116 + 守卫 9）；`tests/owner` + `tests/tools` 合并全量 552 failed / 10484 passed——经 stash 基线复跑证明 552 项失败在 HEAD 原文件上逐条复现（沙箱文件系统/子进程/缺 `mcp`·`jsonschema`·`fal_client` 可选依赖/网络类），**当前态相对基线零新增失败**，且基线多出的 5 条失败恰为本守卫对旧 247 行文件的正确拒绝。`tests/owner` 子集 0 失败。
- [x] **C38** · 审查三项政策性开放项收口（2026-11-20）· **已落地** · tips `dadb5a6175`/`6b5c77f269`/`f33a47cec9`
  - **① Check 8 标记校验迁回**（`6b5c77f269`）：源仓 `merge_health_check.py` Check 8 的 v2 精简重写 `owner/validation/check_owner_markers.py`（280 行；inventory 逐文件断言**不迁**，由能力包守卫测试替代）。基线=本地 main merge-base；只查相对基线已修改的官方文件（非 owner/、非 tests/owner/、非 *.md）；生成物内置豁免（uv.lock 等 13 名+2 模式）；债务登记 `marker_debt.txt` 只能收缩（stale 判红）；`--staged` 查 index（~1.7s）挂 lefthook pre-commit，`--all` 全量人工/CI；无 main/非 git 仓 fail-open。10 项临时 git 仓测试（tests/owner/validation/）。
  - **② Check 8 首跑清账**（`dadb5a6175`）：补 102 处遗漏标记（tui.yaml 16 文件 64 处——⚠→💡/❕ 图标偏好改动当年未标；官方测试 22 文件 37 处；tui_gateway/session_history.py 1 处），顺带清 6 处既有 lint 债（sorted→min、% 格式化、未用变量×3、未用解包×2）。`--all` 对 161 个改动官方文件全绿（160 查验 160 带标，uv.lock 豁免），债务登记 0 条。注意 lefthook 的 marker job 查的是 index 全量偏离文件——补标与 checker 落地的提交顺序必须先标记后接线（本批已按此序）。
  - **③ 规范两处口径拍板**（`f33a47cec9`）：§2.2.1 locale 分工——**新增 owner 键进 bundled**（en+zh 真译、其余语言英占位、zh-hant 繁体真译），**改上游已有键译文走 overlay**，旧「一律走 overlay」作废（test_i18n 一致性保护价值经 2026-11-19 实证）；§5 前缀表收编 `test(owner)`/`chore(owner)`、`fix(官方模块)` 改 `fix(<官方模块>)`（scope 填实际模块名）、`fix(v2)` 冻结认可仅限 O/B 历史段、禁造新 scope、`perf:` 并入 chore。
  - **遗留（环境性预存，与本批无关）**：`tests/cron/test_due_scan_save_failure.py` 的 home_io_guard（读真实 `~/.hermes/manifest.json`）与 `tests/gateway/test_native_http_auth.py` 的真实网卡绑定两条，干净 HEAD 同样红，待测试隔离专项。


## § yaml 整合方向（穿插落地；不大爆炸）

现状（源仓）：`owner/config/overlay.yaml`（v2 扁平）+ `upstream_sync.yaml`（独立）。`patch_feishu_profile.yaml` 已于 2026-11-17 退役删除，不再作为回落源。老版 owner 分支仍用独立的 `patch.yaml`（含 `owner:` 外壳）；v2 加载器**不读** `patch.yaml`。

**目标**：定制 yaml **更小、更好读**；密钥仍可内网提交，对外另做 template。

**本机现状（2026-11-02）**：
- ① **缩 DEFAULTS 重复** · **已做**：overlay 去掉与代码 DEFAULTS 相同的段/键（`stream_guard` 整段、`openviking`、`output_guard`、`approvals` 空默认、`queue_card.enabled`、checkpoints 除 `predict_llm_timeout_ms`、explainers 共用默认与 kind 内重复数值、`feishu_card.split_*`）；`notice_titles` 的 recap 规则已进 `auto_card._DEFAULT_NOTICE_RULES`，overlay 不再复写整表。
- ② **削注释噪声** · **已做**：压缩 feishu_card / bot_menu 旁大段说明。
- ③ **身份/路由边界** · **本机不写舰队段；生产已完成**：本机 overlay **不写** `fleet_profiles` / `user_routing`；node010 已随 C05b 安装正式人卡 overlay。`patch_feishu_profile.yaml` 已于 2026-11-17 退役删除。`ldap:` 连接字段可留仓内，`enabled` 仓内默认 `false`（节点用 overlay/env 开门）。
- ④ **`~/.hermes/patch.yaml` 软链** · **已撤**（2026-11-06）：软重启 + 飞书真实生图验收后，确认无运行时读者；软链移至 `~/.hermes/backups/patch.yaml.symlink-pre-remove-20261106`。主定制继续走 `overlay.yaml`。`patch_feishu_profile.yaml` 已于 2026-11-17 退役删除，不再作 LDAP / skill_approval 回落。
- [x] ⑤ **image-hub 配置与注册迁移** · 2026-11-06 · **完成** · 实现 `25d883e93b` / tip `bea9b4a508`：源码收至 `owner/image_hub`，读 overlay 顶层 `image_gen:`，官方 `ImageGenProvider` + 动态 model/alias；43 测通过；软重启后飞书真实生图验收 OK；`patch.yaml` 软链已撤。详见 `owner/docs/design/image-hub-overlay/README.md`。
- 回落面大迁（人卡进 overlay）→ **已随 C05b 完成**；`patch_feishu_profile.yaml` 已于 2026-11-17 退役删除，不再留作回退材料。

方向备忘（未改语义的中长期）：

1. **拆「路由/身份」与「行为开关」**
   - 终态结构：`feishu.bots.*.user_routing` / `profile_endpoints`；顶层 **`api_identity`** + **`ldap`**；避免 LDAP/身份埋在飞书 bot 节。
   - **不**为对齐官方而改成 `gateway.profile_routes`（语义不覆盖跨进程）。
2. **`overlay.yaml` 合并同类开关**（已大部分完成）
   - `explainers:` / `openviking:` 已合并；行为默认进代码后 yaml 只留差异。
   - 长期 `enabled: false` 且无现网依赖的可继续迁「默认关 + 文档」。
3. **上游 sync 配置独立** — `upstream_sync.yaml` 不并进 overlay。

---

## 附录：对照时怎么用源清单

- 打开源 `owner改动清单.md`，按本 todo 的「源 §x.y」跳转。
- 不要把附录 B 侵入流水账搬进 v2。
- 官方已修的 bug：在本文件标 `官方已修`，定制重放时**跳过**或只留回归测。
- 仍需自研：进入对应 C0x 或新建薄能力包条目。
