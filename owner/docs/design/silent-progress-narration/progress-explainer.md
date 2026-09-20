# progress-explainer 设计稿（沉默进度说明）

> 状态：**已实现（2026-09-20）**，代码在 `owner/progress_explainer/`（7 模块），官方胶水在 `gateway/run.py` 心跳创建点（`[owner]` 标记）；`on_stream_delta` 经 owner-extensions 聚合器注册（`plugin.yaml` 声明 + 聚合器调用）。单测 `tests/owner/test_progress_explainer.py` 18 项全绿。默认 `enabled: false`（patch.yaml `owner.progress_explainer`）。E2E（真网关 + 临时 HERMES_HOME）尚未跑 [未验证]。
> 起草：2026-09-17
> 存放约定：设计稿统一放 `owner/docs/design/<功能短名>/`，一个功能一个目录。
> 本功能目录：**`silent-progress-narration`**（静默期进度旁白），与代码模块 `owner/progress_explainer/` 对号。
> 遵循 [`../../二次开发规范.md`](../../二次开发规范.md)：P0/P1 优先、官方源码最小侵入、核心逻辑全在 `owner/`。

---

## 1. 一句话与边界

**做什么**：网关一轮 turn 运行时，若**连续 N 秒没有用户能读懂的内容**（只有工具面包屑、或什么都没有），就调用辅助模型生成一条"现在在做什么 / 依据 / 接下来打算做什么"的**系统提示**消息，投递给用户。

**非目标（明确不做）**：
- 不做救援：不自动中止、不自动重试、不改 provider 配置。（那是 `stream_guard` / `turn_liveness` / 网关超时的职责，见 §8）
- 不做退化检测：不重复实现复读/膨胀判定。
- 不改 conversation：**不往 messages 注入任何合成消息**、不动 toolsets —— 保住 per-conversation prompt 缓存（`AGENTS.md` 红线）。
- v1 不含 CLI/TUI（它们的进度渲染是另一套），只做网关平台。

---

## 2. 现状机制（全部为源码实测，含行号）

### 2.1 用户现在看到的 `⏳ 工作中 — 10 分钟 — iteration 27/120…`

| 环节 | 位置 | 说明 |
|---|---|---|
| 心跳任务 | `gateway/run.py:31372-31480` | 每轮 turn 起 `_notify_long_running`，`await asyncio.sleep(_NOTIFY_INTERVAL)` |
| 间隔 | `gateway/run.py:31377` | 默认 180s；本机 `agent.gateway_notify_interval = 600` |
| 存活守卫 | `gateway/run.py:12047` `_should_emit_long_running_notification` | 只在 run 仍持有 session 时发（防僵尸气泡 #12029） |
| 文案 | `locales/zh.yaml:623` | `gateway.still_working` |
| status_detail | `gateway/run.py:31433-31445` | `agent.get_activity_summary()`；`iteration N/M` 受 `display.busy_ack_detail` 控制 |
| 投递 | `gateway/run.py:31453-31474` | 优先 `edit_message` 原地改，失败则 `send` |
| 生命周期 | 创建 `31480`；cancel `32204` / `32260` | 随 run 结束回收 |

### 2.2 活动时钟（判断"是否在干活"的权威）

`run_agent.py:4421 _touch_activity`；读取入口 `run_agent.py:4782 get_activity_summary()`（`current_tool / api_call_count / max_iterations / last_activity_at / last_activity_desc`）。

打点来源（**长任务期间时钟不会 stale**）：

| 来源 | 位置 | 频率 |
|---|---|---|
| 工具开始 | `agent/tool_executor.py:1093-1094` | 每次工具 |
| API 调用 | `agent/conversation_loop.py:2264` / `4796` | 每次迭代 |
| provider 流建立 | `agent/chat_completion_helpers.py:4255` | 每次请求 |
| **进程型工具执行中** | `tools/environments/base.py:1266`（doc 见 `1029-1031`） | **每 10s**，desc 形如 `terminal command running (120s elapsed)` |
| 等用户 clarify | `tools/clarify_gateway.py:197` | 每 10s |
| 等审批 | `tools/approval.py:4922` / `5042` / `5229` | 每 10s |
| modal 执行 | `tools/environments/modal_utils.py:151` | 每 10s |

### 2.3 三条用户可见通道

| 通道 | 产生者 | 链路 | 本机可见性 |
|---|---|---|---|
| 工具面包屑 | agent 回调 | `tool_executor.py:1109`(started) / `1939`,`2881`(completed) → `TurnRunner.progress_callback` `gateway/run.py:4871` → `send_progress_messages` `run.py:5383` | 飞书：可实现编辑（`plugins/platforms/feishu/adapter.py:2311`），累积成一个可编辑气泡；**QQ 无 `edit_message`**（`gateway/platforms/qqbot/adapter.py:183` 未覆盖基类）→ `run.py:5404-5411` 直接丢弃，QQ 上工具面包屑一条都不显示 |
| 助手散文 | 模型 | `run_agent.py:7297 interim_assistant_callback` → `run.py:6127-6148`，独立消息；开关 `display.interim_assistant_messages` | 两端可见，但模型不说话就没有 |
| 心跳 `⏳` | 网关自己 | §2.1 | 两端可见，间隔 600s |

补充：**reasoning 不是流中可见**——它只在最终回复里被前置成 `💭 Reasoning` 块（`gateway/run.py:22742-22761`），所以思考期间用户其实是"零信息"。

### 2.4 可复用的两个基座

- **辅助模型侧路**：`agent/auxiliary_client.py:10075 call_llm(task=…, messages=…, timeout=…)`；task 配置读 `config.yaml auxiliary.<task>`（`auxiliary_client.py:8701`），未配置走 auto 链（实测 `_resolve_auto(task="progress_explainer")` 正常返回、无白名单拦截）。成熟先例：`owner/checkpoint_predictor/llm_predict.py`（3s 超时、失败返回空、LRU 缓存、永不抛）。
- **owner 包装官方回调**：`owner/diff_card/dispatcher.py:248 install_diff_card_support` + `gateway/run.py:6474-6490` 的 `[owner]` 胶水，约 15 行。本功能照此结构。

---

## 3. 架构与落点

```
owner/progress_explainer/
├── __init__.py      # 导出 install / stop
├── config.py        # 读 patch.yaml owner.progress_explainer，fail-open 默认值
├── tracker.py       # per-turn 状态：静默计时、事件环形缓冲、流统计、去重 hash
├── digest.py        # 证据 → 有界 prompt 输入（截断策略集中在此）
├── explain.py       # 调 aux LLM（temperature 0 / 有界 max_tokens / 硬超时 / 异常静默）
├── prompt.py        # 提示词模板与输出约束
└── dispatcher.py    # install_progress_explainer(...) / stop()；注册 on_stream_delta 观察者 + tick 任务
```

官方胶水（预计 ≤8 行，全部 `# [owner]` 标记）：`gateway/run.py` 心跳任务创建点（`31480` 附近）安装本模块，并在 `32204` / `32260` 的 cancel 列表追加一个任务名。

`install_progress_explainer(runner, ctx, agent, loop)` 做三件事：
1. 包装 `agent.tool_progress_callback`、`agent.tool_gen_callback`（原值可 None）→ 打点；
2. 注册插件钩子 `on_stream_delta` 观察者 → 流统计（`kind` = `text` / `reasoning`）；
3. 起一个 `tick_seconds` 周期的 asyncio 任务 → 判定 + 调辅助模型 + 投递。

---

## 4. 四个证据源

| # | 证据 | 来源 | 解决的问题 |
|---|---|---|---|
| E1 | 工具执行进度 | `tool_progress_callback`：started(name/args preview) / completed(duration, is_error, result)（`tool_executor.py:1109`,`1939`） | 长工具在跑什么 |
| E2 | 推理流 | `on_stream_delta(kind="reasoning")`（`run_agent.py:7571-7580`） | 十分钟 thinking 在推敲什么 |
| E3 | 正文流 | `on_stream_delta(kind="text")` | 一次性超大 output 的字符数与速率 |
| E4 | 工具参数生成 | `agent.tool_gen_callback` / `_fire_tool_gen_started`（`run_agent.py:7584-7593`，注释即 45KB write_file 场景）。**当前无人挂载**（`agent_init.py:900` 赋值后网关/CLI 都没设），owner 包装即可白捡 | "在生成 write_file 参数，尚未执行" |

E2 的开通门槛（`agent/plugin_stream_hooks.py:154-165`）：`plugins.stream_reasoning_deltas: true` 且至少一个 `on_stream_delta` 订阅者。
**本机已开**（`~/.hermes/config.yaml:639`，2026-09-17 经 `hermes config set` 写入，`hermes config get` 复核 = `true`）。开启后 `stream_guard` 也会开始对思考通道做流中判定——这是已知且认可的行为变化。
生效无需重启：`load_config()` 按 `(mtime_ns, size)` 缓存（`hermes_cli/config.py:3840-3848`），`has_reasoning_stream_observer_hooks()` 每次 API 调用重判（`chat_completion_helpers.py:3794`）。

> 性能纪律：`stream_reasoning_deltas_enabled()` 每个 reasoning delta 会 `load_config()`（含 deepcopy，~265µs，上游写法）。**本模块的观察者禁止在任何 delta 里读配置**，配置只在 tick 时读一次；delta 路径只做计数与切片。

---

## 5. 判据与状态机

### 5.1 "用户可见内容"的口径（已确认）

- **算**：助手散文（interim）、本模块自己发的系统提示。
- **不算**：工具面包屑、心跳 `⏳`、reasoning（它只在最终回复里出现）。
- 派生规则：自己发的系统提示必须计入，否则刚发完就再次触发。

### 5.2 tick 决策（每 `tick_seconds` 醒一次）

```
if not enabled:                          return
if not run_still_current:                return
if silence < silence_seconds:            return          # 默认 60
if last_explainer_ago < min_interval:    return          # 默认 120，生成型 120，停滞型 180
if explain_count_this_turn >= max_per_turn: return       # 默认 5
if stream_guard.tripped:                 return          # §8 让位
if digest_hash == last_digest_hash and not 该分支允许重复: return
→ 调辅助模型（to_thread + 硬超时）→ 投递 → 更新计时与计数
```

`silence` 从 `last_content_ts` 起算；`last_content_ts` 初值 = turn 开始时间。

### 5.3 四个分支（按证据决定说什么）

| 分支 | 判据 | 文案骨架 | 节奏 |
|---|---|---|---|
| **工具型** | `current_tool` 非空 / 最近有 tool.started | `正在执行 terminal（已 120s，第 27/120 轮）` | ≥60s |
| **生成型·有推理流** | 30s 内有 `kind="reasoning"` 增量 | `正在推敲 X 与 Y 的取舍（已生成 1.2 万字符）` | ≥120s |
| **生成型·无推理流**（降级） | 30s 内有 `kind="text"` 增量，但无 reasoning | `模型已生成 1.2 万字符（约 45 字/秒），仍在继续` | ≥120s |
| **停滞型** | 无 chunk、无工具活动 > `stall_seconds`（默认 120）+ 已捕获推理流则另述 | `已 N 分钟无任何输出；watchdog 10 分钟会中止本轮，网关 inactivity 超时 30 分钟；建议 /stop` | ≥180s，最多 2 条 |

**停滞型必须带上"系统会怎么处理"**（watchdog / 网关超时的具体值），这是卡死场景下最有用的内容。

### 5.4 去重规则（修正）

原设想"digest 不变就不发"会让一个 10 分钟的单工具只得到一次解释。**改为**：允许每 `min_interval` 重发，但 prompt 里喂"同一工具已持续 N 秒 / 已生成 N 字符"，让文案随事实自然变化（禁止逐字重复由 prompt 约束 + 本模块对一模一样的输出做丢弃）。

---

## 6. 投递（已确认：独立消息）

- 走 `adapter.send` 单独一条消息（不复用可编辑进度气泡，也不编辑心跳气泡）。
  理由：① 编辑气泡在 QQ 上根本不可用（§2.3）；② 飞书进度气泡会被折叠/滚动，独立消息更显眼；③ 语义上"解释"是内容，不是面包屑。
- 固定前缀，标明不是模型在说话：`🧭 系统提示：…`
- 第二行给**实时事实**（取自 `get_activity_summary()` / 计数器，**不由模型生成**）。
- `cleanup_progress` 开启时，把消息 id 登记进 `ctx._cleanup_msg_ids`，随成功收尾清理（失败则留作线索）。
- 投递后立即把 `last_content_ts = now`。

---

## 7. 配置面

全部放 `patch.yaml`（**不动 `config.yaml`**，也不动 `gateway/display_config.py`），复用 `owner.patch_config.load_patch_config()`（60s TTL + mtime 失效 → 改完不重启）。

```yaml
owner:
  progress_explainer:
    enabled: true                 # 总开关（默认 false，落地时不改变现有行为）
    silence_seconds: 60           # 静默多久触发
    stall_seconds: 120            # 多久没 chunk/工具算"停滞"
    min_interval_seconds: 120
    max_per_turn: 5
    tick_seconds: 5
    events_in_digest: 8           # 进入 prompt 的工具事件条数
    chars_per_event: 200
    reasoning_tail_chars: 1500    # 思考尾部的摘录长度上限
    explainer_timeout_ms: 15000
    platforms:                    # 平台覆盖 enabled
      feishu: true
      qqbot: true
      telegram: false
    chats:                        # 可选，chat_id 覆盖
      feishu:
        "oc_xxx": false
```

查找顺序：`chats.<platform>.<chat_id>` → `platforms.<platform>` → `enabled`（owner 侧自行实现三级查找，与 `owner.diff_card` 的写法一致）。

模型侧（`config.yaml` 的 `auxiliary` 段，属既有机制，非本功能新增配置面；未配置则回落主模型）：

```yaml
auxiliary:
  progress_explainer:
    provider: damodel
    model: xy-pro
    timeout: 15
    max_concurrency: 1     # 同一时刻只允许一次解释调用
```

---

## 8. 与既有机制的分工与让位

| 场景 | 负责者 | 本模块行为 |
|---|---|---|
| 生成中退化（复读/膨胀） | `owner/owner-extensions/stream_guard`（`action: warn_only`，`DEFAULTS` 见 `stream_guard/__init__.py:76-95`；通知链 `_notify`(284) → `agent._emit_warning`(run_agent.py:1107)） | `tripped=True` → **静默让位** |
| 真卡死（零 token） | `agent/turn_liveness`（默认 `timeout_s: 600` / `poll_s: 15`）+ 网关 `agent.gateway_timeout: 1800` / `gateway_timeout_warning: 900` | 只**说明**系统会怎么处理 + 建议 `/stop` |
| 工具跑很久 | 无（正常） | 报工具名 + 已耗时 |
| 心跳 `⏳` | 网关 `_notify_long_running` | 解释计入"可见内容"，下一个心跳自然顺延；心跳本体不改 |

**让位的实现**：在 `stream_guard` 增加一个**公开只读函数** `snapshot(session_id, turn_id) -> dict`（返回 `total_chars / tripped / signals`），本模块读它。它 `__init__.py` 已有 `config()` / `evaluate_window()` 这类公开函数，加同类只读函数比读私有 `_STATE` 更守规范。
若不愿引入这层依赖，退化为：本模块纯计数 + 发后 `min_interval` 去抖 + 阈值语义不同（它用窗口重复度，本模块用"字符数 > 该模型 per-model `max_output_tokens`"）→ 两种提示不会真撞车。

**划界**：本模块只读不写——不 kill、不重试、不改 provider。

---

## 9. 降级与兼容

| 情形 | 判定方式 | 行为 |
|---|---|---|
| 未开 `plugins.stream_reasoning_deltas`（如 node010 / win11，本模块不主动同步配置） | **观测**：本 turn 是否真收到过 `kind="reasoning"` | 走"生成型·无推理流"或"停滞型 + 超时风险"文案，不假装知道在推敲什么 |
| provider 不返回 reasoning_content | 同上（观测自适应） | 同上 |
| 非进程型长工具（无 10s 心跳） | `run 存活` 判据兜住 | `正在执行 <tool>（已 Ns），暂无输出` |
| adapter 不支持 `edit_message`（QQ） | `getattr(type(adapter), "edit_message", None)` 判定 | 不影响：本模块本来就发独立消息 |
| 辅助模型超时/报错 | 硬超时 + `except` 吞 | 静默丢弃，不发半成品；下个 tick 自然重试 |
| 平台不支持消息长度 | 复用 adapter 的长度限制 | 文案本身就短（≤3 行），超限则截断 |

---

## 10. 官方源码改动清单（预估）

| 文件 | 改动 | 行数 |
|---|---|---|
| `gateway/run.py` | 心跳任务创建点附近安装本模块；cancel 列表追加任务名 | ~6-8 行，`# [owner]` 标记 |
| `owner/owner-extensions/stream_guard/__init__.py` | 新增公开只读 `snapshot()`（§8） | ~6 行 |
| `agent/*`、`gateway/display_config.py` | **不动** | 0 |

`agent/tool_executor.py` 也不需要动：`tool_progress_callback` 已携带全部所需数据。

---

## 11. 提示词约束（要点）

- 输入：用户原始请求（`ctx.message`，≤300 字符）+ 最近 `events_in_digest` 条工具事件（名/参数/结果摘要）+ 流统计（累计字符/速率/是否有推理流）+ 思考尾摘录（≤`reasoning_tail_chars`）+ 硬事实（迭代 N/M、已耗时、watchdog/网关超时值）。
- 要求输出**三段**：① 现在在做什么 ② 依据（读了什么/跑了什么） ③ 接下来打算做什么 + 粗估（允许说"不确定还需多久"，**禁止硬承诺**）。
- **硬约束**：只输出自然语言概述，**绝不引用思考原文**（防 CoT 泄漏进群聊）；不带 markdown 标题/代码块；≤3 句；语言随 `display.language`。
- `temperature=0`、`max_tokens≈200`。

---

## 12. 测试计划

**单测** `tests/owner/test_progress_explainer.py`（mock `call_llm`，不打真网络）：
1. 打点：tool started/completed、`on_stream_delta` 两种 kind、`tool_gen_callback`
2. 阈值边界：59/60/61s；`min_interval` / `max_per_turn` 封顶
3. 分支选择：工具型 / 生成型（有/无推理流）/ 停滞型 各一例
4. 降级：从未收到 reasoning 增量 → 文案不含"推敲"类描述，含超时风险
5. 让位：`snapshot().tripped=True` → 不调 `call_llm`、不发送
6. 静默失败：`call_llm` 抛异常 / 超时 → 无出站消息、无异常上抛
7. 生命周期：run 结束 / interrupt → 任务退出、锁与缓冲清理
8. 配置：三级查找 + 非法值回落默认

**E2E**（临时 `HERMES_HOME`，真 import）：`tick=1s / silence=1s` 调小 → 断言 `adapter.send` 恰好一次且带 `🧭 系统提示：` 前缀；注入一条 interim 散文 → 断言不触发；把 `stream_guard` 的 `snapshot` 打桩为 `tripped` → 断言静默。

**手工**：飞书 + QQ 各跑一个长任务，检查频率与可读性；再做一次"故意让单工具跑 3 分钟"验证 §5.3 工具型分支。

---

## 13. 风险与对策

| 风险 | 对策 |
|---|---|
| 跨线程状态（回调在工具线程写、tick 在事件循环读） | 只共享锁保护的标量与短列表；**不读 `agent.messages`**，digest 只来自回调事件 + `ctx.message` |
| 辅助调用阻塞事件循环 | `asyncio.to_thread` + 硬超时 + 异常吞；发送前重验 run 存活 |
| 成本失控 | `min_interval` + `max_per_turn` + `max_concurrency: 1` 三重封顶；思考长流拉长到 120s |
| **破 prompt 缓存** | 不外发即不改 conversation；不注入合成 user 消息（`AGENTS.md` 红线） |
| 与 stream_guard 双报 | §8 让位 + 阈值语义不同 |
| 自己刷屏 | 每 turn 上限 + 静默计时由自己的消息重置 |
| reasoning 泄漏 | prompt 硬约束 + 只发概述不发原文 |

---

## 14. 二次开发规范 checklist

- [x] 能用 hook/包装实现 → 主体是包装 `agent.*callback` + 注册 `on_stream_delta`，不新造 hook
- [x] 核心逻辑全在 `owner/progress_explainer/`
- [x] 新配置 key 不改官方字面定义（patch.yaml + owner 侧三级查找，不进 `display_config.py`）
- [x] 官方文件只剩 import + 委托，且都带 `# [owner]`
- [x] 新文件都在 `owner/` 下
- [x] 设计文档位于 `owner/docs/design/silent-progress-narration/`（本文件）
- [ ] 落地时在 `owner/docs/v16改动清单.md` 立独立条目（用户可感知能力点）
- [x] 删除 `owner/progress_explainer/` 后其余功能不受影响（官方侧只留 import 失败退化路径）
- [x] 官方文件字面 diff ≤8 行，sync fork 冲突面极小

---

## 15. 待定 / 后续

1. `patch.yaml` 里 `owner.display` 那套 per-chat 机制不用于本功能（本功能走自己的三级查找）；若将来想和 `display` 的 per_chat 统一，再评估。
2. `stream_guard` 切 `action: interrupt` 后，本模块的"疑似复读"兜底提示（§5.3 生成型）应删掉或改为纯说明——依赖 P2 的灰度数据。
3. CLI/TUI 的对应体验（`cli_refresh_interval` 那套）不在 v1；若要做，走同一 tracker + 另一套渲染。
4. 若解释文案质量不足（例如总说套话），优先改 prompt 的输入证据（加"最近一次工具结果摘要"），而不是加长输出。