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
- [x] **B04** · 源 §2.2.4 · 飞书 model_picker stale session 卡 loading / action_value 形态 · **验证状态：不适用(纯 owner)**
  - owner：`owner/feishu/model_picker.py`（405 行）+ adapter 薄胶水。v2 无 `model_picker` 模块，官方飞书 adapter 只有审批卡 / update_prompt 卡（`model_picker_expired` 文案仅 Slack 用）。
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
- [x] **B11** · 源 §3.13 · 审批历史挖掘依赖英文文案，i18n 后漏检（应改结构标记） · **验证状态：仍存在/需自研**
  - owner：`owner/approval/approval_history_policy.py` 结构标记三层判定。v2：`hermes_cli/approvals_suggest.py` 仍用英文 `_BLOCK_MARKERS` 子串匹配，且审批文案硬编码英文 —— i18n 一旦落地（C10）即复现漏检。

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
- [x] **B27** · 源 §7.27 · 出站 DeepSeek BOS/EOS 可见泄漏 · **验证状态：官方已修**
  - owner：outbound BOS/EOS scrub。v2 本树已用 **O8**：`_strip_deepseek_special_tokens` 接入 `_sanitize_gateway_final_response`。

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

**结论分布**：官方已修 23 · 部分 5 · 仍存在/需自研 2 · 不适用(纯 owner) 8。（O3–O8 后本批：B15 部分→官方已修；B17 仍存在→部分。仍剩硬挂 B11/B12。）

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
- **B11**（审批历史按英文文案判定）：官方功能本身的脆弱点，但**只有在我们落地 i18n（C10）后才会暴露**；建议与 C10 同批做，或直接改用结构字段。

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
| **一** | 非渠道 / 终端 / 加载器 | **C01**（最先）→ C02 → C08（确认/回归）→ C03 → C21 → C16 → C17 → C19 → C18 → C14 → C13 → C22（可选）；旁注 B12 不强制 |
| **二** | 飞书**核心**底座 | **C04**（审批卡 + 中文名/sender 缓存 + inbound + 签名）→ **C10**（+B11 同批）→ **C11 底座**（auto-card / early-typing）；diff/clarify/bot 菜单可延阶段三 |
| **三** | 飞书定制 + 杂项 | **C09**（依赖 C04）→ C11 余下 → **C12** → C15 → C25 → **C06** LDAP / **C07** API media（现网必保·杂项）→ C20（可后移）→ C23（按需）→ **B17 飞书半边**；**C24** 明确不做全量 |
| **四** | 飞书多 profile | **仅 C05**（`profile_endpoints` / bots 路由；不吃 multiplex）。勿提前；与阶段三 LDAP **文件边界**分开 |

**依赖速记**：C01 万物前置 → 阶段二 C04 先于一切飞书体验/skill 门 → C09/C12 依赖 C04 → **C05 最后**。yaml 随 C01 / 阶段三 LDAP / 阶段四路由穿插缩文件，不大爆炸。

---

## § 定制功能类（bug 对照完成后再落）

> **落地节奏见上方「落地顺序（四阶段）」**，勿按本组标题当执行顺序。  
> 本组仍按 P0 必保 / P1 可后移 / P2 暂缓标优先级，便于对照源清单。路由：**维持自研**跨进程转发，不对齐吃官方 multiplex；**C05 仅第四阶段**。

### P0 必保

- [ ] **C01** · 源 §1.1–1.4 · `patch.yaml` 统一加载器 + 审批白名单合并 + 归因骨架 · **优先级：P0**
- [ ] **C02** · 源 §2.1–2.3 / §10 · per-turn 归因 + credential 合并 + billing 落盘 · **优先级：P0**
- [ ] **C03** · 源 §2.7–2.8 · damodel prompt cache / NewAPI proxy / MiMo thinking wire · **优先级：P0**
- [ ] **C04** · 源 §3.1–3.4 · 飞书审批卡片 + sender_name 缓存 + inbound 身份 + 多平台审批签名 · **优先级：P0**
- [ ] **C05** · 源 §4.1 · **飞书多 profile 舰队路由**（`profile_endpoints` HTTP 转发；**不吃**官方 `profile_routes`） · **优先级：P0**
- [ ] **C06** · 源 §15.1–15.6 · API Server LDAP 身份准入 + identity_routes + 头剥离/SSE · **优先级：P0**
- [ ] **C07** · 源 §16.1–16.6 · API 产物媒体 / `hermes.files` / tool.progress 脱敏与归属 · **优先级：P0**
- [ ] **C08** · 源 §7.27 / design · outbound BOS/EOS scrub · **优先级：P0**（旁注：B27/O8 已在本 v2 官方树落地 sanitize；重放时收窄为**确认/回归**，勿从零再实现一遍）
- [ ] **C09** · 源 §3.6 / §3.11 · skill 脚本自动审批 + skill_manage 飞书审批门 · **优先级：P0**
- [ ] **C10** · 源 i18n 层 · 显示层 i18n / `_localized` 与护栏文案（源 §12.2 / §16.9 相关） · **优先级：P0**

### P1

- [ ] **C11** · 源 §4.2–4.6 · auto-card / early-typing / diff·clarify 卡 / bot 菜单 · **优先级：P1**
- [ ] **C12** · 源 §4.10–4.15 · memory write-approval 卡 / feishu-guide / 上传守卫 / doc_read 图 OCR / @所有人 / merge_forward · **优先级：P1**
- [ ] **C13** · 源 §7.24–7.26 · progress / approval / english explainer · **优先级：P1**
- [ ] **C14** · 源 §14 · output_guard + stream_guard · **优先级：P1**
- [ ] **C15** · 源 §7.2–7.3 · Memory synthetic guard + OpenViking sync recall/card · **优先级：P1**
- [ ] **C16** · 源 §7.4 · Cron env 隔离（ContextVar + restart scrub） · **优先级：P1**
- [ ] **C17** · 源 §8.1 · Checkpoint Mutation Predictor · **优先级：P1**
- [ ] **C18** · 源 §9.1 · per-chat display overrides · **优先级：P1**
- [ ] **C19** · 源 §5 · 链式快捷命令 `;;` + Quick Alias · **优先级：P1**
- [ ] **C20** · 源 §3.9 · Semantic Audit Gate · **优先级：P1**（可后移若负担大）
- [ ] **C21** · 源 §2.4–2.6 / §2.9–2.11 · reasoning 转义 / MiniMax / Qwen debris / kimi-coding / model-switch 白名单 / cache TTL · **优先级：P1**

### P2 暂缓

- [ ] **C22** · 源 §6.1–6.2 · TUI skin / ruolin · **优先级：P2**
- [ ] **C23** · 源 §11 · 运维脚本 / HN Daily / Skill 同步 / Viking 治理 / 备份 / 周会脚本 · **优先级：P2**（按需拣）
- [ ] **C24** · 源 §12 / §16.8–16.16 · 治理标记、T2-11~20 换码债、全量 `[owner]` 铺开 · **优先级：P2**（v2 **不做**「官方测全绿」与全量标记战役）
- [ ] **C25** · 源 §4.7–4.9 · 编辑上限轮转 / 中文摘要 / `/providers` 等体验项 · **优先级：P2**（可拣进 P1）

**定制段合计：25 条（P0×10 / P1×11 / P2×4）。执行顺序：四阶段（见上），非本 P0→P1→P2 标题顺序。**

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

---

## § yaml 整合方向（只写方向，不改现网）

现状（源仓）：`owner/config/patch.yaml`（~436 行）+ `patch_feishu_profile.yaml`（~156 行，含 bots 路由与 LDAP）+ `upstream_sync.yaml`。

**目标**：定制 yaml **更小、更好读**；密钥仍可内网提交，对外另做 template。

建议（落地时穿插，非一次性大爆炸）：

1. **拆「路由/身份」与「行为开关」**  
   - 保留独立「舰队路由」文件亦可，但结构对齐：`feishu.bots.*.user_routing` / `profile_endpoints` 与 `ldap` / `identity_*` 分节清晰；避免 LDAP 埋在飞书文件里却无索引。  
   - **不**为对齐官方而改成 `gateway.profile_routes`（语义不覆盖跨进程）。
2. **`patch.yaml` 合并同类开关**  
   - `progress_explainer` / `approval_explainer` / `english_explainer` → 单一 `explainers:` 块。  
   - `openviking_sync_recall` + `openviking_recall_card` → `openviking:`。  
   - `feishu_card` notice_titles 与 auto_card 阈值保留一张表，删注释噪声。  
   - 长期 `enabled: false` 且无现网依赖的（如部分 `diff_card`）可迁「默认关 + 文档」，不占主文件行。
3. **行为默认进代码，yaml 只留差异**  
   - 与源规范一致：缺省 section = 合理默认；yaml 只写覆盖项。
4. **上游 sync 配置独立**  
   - `upstream_sync.yaml` 保持单独，不并进 patch。
5. **v2 落地顺序**  
   - 先按 C01 重接加载器 → 再迁键名（一次改加载器+文档+软链说明）→ 最后缩行数。

---

## 附录：对照时怎么用源清单

- 打开源 `owner改动清单.md`，按本 todo 的「源 §x.y」跳转。  
- 不要把附录 B 侵入流水账搬进 v2。  
- 官方已修的 bug：在本文件标 `官方已修`，定制重放时**跳过**或只留回归测。  
- 仍需自研：进入对应 C0x 或新建薄能力包条目。
