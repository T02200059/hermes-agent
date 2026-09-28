# `gateway/run.py` owner 定制落点映射表

**用途**：`gateway/run.py` 迁移（T1-5）的前置台账。上游正在拆包该文件，迁移时必须逐块判断每个定制该落到哪个新模块——漏搬 = 定制静默消失，且没有任何测试能发现。

**建立日期**：2026-09-28
**基线**：`b83d1da12c`（owner 分支自身提交，2026-08-27）
**当前 HEAD**：`efec7a3696`
**上游参照**：`upstream/main` = `9573f44ca5`

---

## 1. 上游拆包现状

| 项 | owner 侧（HEAD） | 上游（`upstream/main`） |
|---|---|---|
| `gateway/run.py` 行数 | 34,113 | 5,676 |
| `gateway/run_*.py` | 0（未拆） | 23 个（合计 21,369 行） |
| 本文件 `MOD` 增量 | +8,123 / −1,215（vs BASE） | — |

上游 23 个新模块与本次映射相关的落点（已逐条用 `git grep "def <符号>" upstream/main` 核实）：

| 上游模块 | 承载的类 | 本次涉及 |
|---|---|---|
| `gateway/run.py` | 模块级 helper（**未搬**） | 5 处 |
| `gateway/run_turn_runner.py` | `TurnRunner` | 9 处 |
| `gateway/run_turn.py` | `GatewayTurnMixin` | 33 处 |
| `gateway/run_busy.py` | `GatewayBusySessionMixin` | 4 处 |
| `gateway/run_inbound.py` | `GatewayInboundMixin` | 4 处 |
| `gateway/run_shutdown.py` | `GatewayShutdownMixin` | 2 处 |
| `gateway/run_startup.py` | `GatewayStartupMixin` | 0 处（本次未涉及） |
| 其余 16 个 `run_*.py` | — | 0 处（本次未涉及） |

---

## 2. 上游落点信号对照（迁移时的锚点）

| 我方函数（`gateway/run.py`） | 上游落点 | 上游行号 |
|---|---|---|
| 模块级常量 `_GATEWAY_RAW_TEXT_PLATFORMS` | `gateway/run.py` | 356 |
| `_sanitize_gateway_final_response` | `gateway/run.py` | 686 |
| `_resolve_gateway_display_bool` | `gateway/run.py` | 852 |
| `TurnRunner._roll_progress_overflow_if_needed` | `gateway/run_turn_runner.py` | 599 |
| `TurnRunner._clarify_callback_sync` | `gateway/run_turn_runner.py` | 1327 |
| `TurnRunner.run_sync` | `gateway/run_turn_runner.py` | 1872 |
| `GatewayBusySessionMixin._handle_active_session_busy_message` | `gateway/run_busy.py` | 744 |
| `GatewayShutdownMixin._launch_detached_restart_command` | `gateway/run_shutdown.py` | 1405 |
| `GatewayInboundMixin._handle_message` | `gateway/run_inbound.py` | 1264 |
| `GatewayInboundMixin._prepare_inbound_message_text` | `gateway/run_inbound.py` | 1682 |
| `GatewayTurnMixin._handle_message_with_agent` | `gateway/run_turn.py` | 2126 |
| `GatewayTurnMixin._run_background_task_inner` | `gateway/run_turn.py` | 2363 |
| （嵌套）`run_sync` in `_run_background_task_inner` | `gateway/run_turn.py` | 2415 |
| （嵌套）`_run_still_current` in `_run_agent_inner` | `gateway/run_turn.py`（`_run_still_current_fn`） | 2665 |
| （嵌套）`_display_surface_mode` in `_run_agent_inner` | `gateway/run_turn.py` | 2929 |
| （嵌套）`_generic_status_phrase` in `_run_agent_inner` | `gateway/run_turn.py` | 2947 |
| （嵌套）`track_agent` in `_run_agent_inner` | `gateway/run_turn.py`（`_run_agent_track_agent`） | 3234 |
| （嵌套）`_stream_confirmed_final_delivery` | `gateway/run_turn.py`（`_run_agent_stream_confirmed_final_delivery`） | 3343 |
| （嵌套）`_notify_long_running` in `_run_agent_inner` | `gateway/run_turn.py`（`_run_agent_notify_long_running`） | 4087 |
| `GatewayRunner._run_agent_inner` | `gateway/run_turn.py` | 4162 |

> **注意**：上游把多处以**嵌套函数**存在的符号提升为**类方法**（如 `_clarify_callback_sync`、`_roll_progress_overflow_if_needed`、`_stream_confirmed_final_delivery`）。迁移委托时须按上游的新作用域（类方法 / mixin）而非我方现有嵌套位置落笔，否则委托调用点会找不到符号。

---

## 3. 57 处 `[owner]` 标记逐条映射

**类别说明**：`C` = 真定制代码（需迁 owner 模块） · `K` = 常量/模块级 `D` = 纯注释或 docstring

### 3.1 留在 `gateway/run.py`（上游未搬，5 处）

| # | 行 | 位置 | 定制内容 | 类 | 迁移动作 |
|---|---|---|---|---|---|
| 1 | 577 | 模块级 | `_GATEWAY_RAW_TEXT_PLATFORMS` 由 `{"local","api_server","webhook","msgraph_webhook"}` 收紧为 `{"local"}`（CR-004，#39293） | K | 保留常量，值改由 `owner/gateway/raw_text_policy.py` 提供（官方文件 1 行委托） |
| 2 | 1043 | `_sanitize_gateway_final_response` | DeepSeek BOS/EOS 特殊 token 出站清洗 | C | 已是 1 行委托（`owner/outbound_special_token_scrub.py`）；**无需迁移**，仅保留委托 |
| 3 | 1268 | `_resolve_gateway_display_bool` docstring | 文档说明 `chat_id` 启用 per-chat override | D | 与上游 docstring 合并，无行为变更 |
| 4 | 2353 | 模块级 | 进程启动期 cron env 清洗 | C | 已是 1 行委托（`owner/cron/restart_scrub.py`）；保留 |
| 5 | 4818 | 模块级（**孤儿注释**） | §17.2 executor-shutdown 说明，其下无代码 | D | 删除孤儿注释；说明移至真实调用点（第 30 项）与 `_is_executor_shutdown_error` 定义处 |

### 3.2 `TurnRunner` → `gateway/run_turn_runner.py`（9 处）

| # | 行 | 位置 | 定制内容 | 类 | 上游落点 |
|---|---|---|---|---|---|
| 6 | 5543 | `_roll_progress_overflow_if_needed` | progress bubble 轮换（rotate：弃旧开新） | C | `run_turn_runner.py:599` |
| 7 | 5598 | 同上 | fence-safe 去重计数（`_append_dedup_counter`） | C | 同上 |
| 8 | 5647 | 同上 | 编辑失败委派共享分类器（Feishu 230072/230075 编辑上限） | C | 同上 |
| 9 | 5658 | 同上 | bubble 耗尽后保留 `can_edit=True` | C | 同上 |
| 10 | 5727 | 同上 | fence-safe 去重计数（调用点） | C | 同上 |
| 11 | 5759 | 同上 | rotate/reset 后无 bubble id → 缓冲内容改新消息投递 | C | 同上 |
| 12 | 6079 | `run_sync` | per-chat streaming 开关（`source=ctx.source`） | C | `run_turn_runner.py:1872` |
| 13 | 6476 | `run_sync` | Diff card 支持（包装 `tool_start` / step 回调） | C | 同上 |
| 14 | 6789 | `_clarify_callback_sync` | 仅飞书生效的 clarify 超时停止 | C | `run_turn_runner.py:1327` |

### 3.3 `GatewayBusySessionMixin` → `gateway/run_busy.py`（4 处）

| # | 行 | 位置 | 定制内容 | 类 | 上游落点 |
|---|---|---|---|---|---|
| 15 | 11342 | `_handle_active_session_busy_message` | steer 图像视觉富化（`owner/gateway/steer_vision.py`） | C | `run_busy.py:744` |
| 16 | 11349 | 同上 | 富化后放开「TEXT+media」闸门（§7.18） | C | 同上 |
| 17 | 11484 | 同上 | per-chat display override | C | 同上 |
| 18 | 11503 | 同上 | per-chat display override | C | 同上 |

### 3.4 `GatewayShutdownMixin` → `gateway/run_shutdown.py`（2 处）

| # | 行 | 位置 | 定制内容 | 类 | 上游落点 |
|---|---|---|---|---|---|
| 19 | 12466 | `_launch_detached_restart_command` | watcher env 中 cron env 清洗 | C | `run_shutdown.py:1405` |
| 20 | 12558 | 同上 | 同上（第二处 watcher 分支） | C | 同上 |

### 3.5 `GatewayInboundMixin` → `gateway/run_inbound.py`（4 处）

| # | 行 | 位置 | 定制内容 | 类 | 上游落点 |
|---|---|---|---|---|---|
| 21 | 18955 | `_handle_message` | 只读插件 slash 命令允许中轮执行（`/providers`、`/feishu-guide`） | C | `run_inbound.py:1264` |
| 22 | 18994 | 同上 | `/memory`、`/skills approve\|reject` 必须中轮执行 | C | 同上 |
| 23 | 19010 | 同上 | 兜底：插件注册但不在 `_COMMAND_LOOKUP` 的命令 | C | 同上 |
| 24 | 20473 | `_prepare_inbound_message_text` | 入站上下文注入（open_id / chat_id / user_name） | C | `run_inbound.py:1682` |

### 3.6 `GatewayTurnMixin` → `gateway/run_turn.py`（33 处）

| # | 行 | 位置 | 定制内容 | 类 | 上游落点 |
|---|---|---|---|---|---|
| 25 | 22177 | `_handle_message_with_agent` | hygiene 压缩通知（`owner/gateway/hygiene_compression_notice.py`） | C | `run_turn.py:2126` |
| 26 | 22734 | 同上 | `for_source` helper 取 reasoning style | C | 同上 |
| 27 | 22741 | 同上 | per-chat display override | C | 同上 |
| 28 | 22792 | 同上 | auto-card：`agent:end` 时长回复包装为交互卡片 | C | 同上 |
| 29 | 22806 | 同上 | auto-card 异常日志 | C | 同上 |
| 30 | 23274 | 同上 | §17.2 executor-shutdown RuntimeError → 友好重启提示 | C | 同上 |
| 31 | 24906 | `_run_background_task_inner` | 后台任务稳定 per-chat session key | C | `run_turn.py:2363` |
| 32 | 24941 | 同上（嵌套 `run_sync`） | `gateway_session_key` 透传 | C | `run_turn.py:2415` |
| 33 | 30230 | 嵌套 `_run_still_current` | per-chat display override | C | `run_turn.py:2665` |
| 34 | 30662 | `_run_agent_inner` | 统一 `for_source` helper | C | `run_turn.py:4162` |
| 35 | 30670 | 嵌套 `_run_still_current` | per-chat display override | C | `run_turn.py:2665` |
| 36 | 30681 | 同上 | per-chat display override | C | 同上 |
| 37 | 30690 | 同上 | per-chat display override | C | 同上 |
| 38 | 30714 | `_run_agent_inner` | per-chat tool_progress_grouping | C | `run_turn.py:4162` |
| 39 | 30718 | 嵌套 `_run_still_current` | per-chat display override | C | `run_turn.py:2665` |
| 40 | 30743 | 嵌套 `_display_surface_mode` | per-chat display override | C | `run_turn.py:2929` |
| 41 | 30780 | 嵌套 `_generic_status_phrase` | per-chat display override | C | `run_turn.py:2947` |
| 42 | 30879 | 同上 | per-chat display override | C | 同上 |
| 43 | 30921 | 同上 | 注入 `resolve_display_setting` 回调 | C | 同上 |
| 44 | 31045 | `_run_agent_inner` | auto-card：标记 progress bubble 元数据 | C | `run_turn.py:4162` |
| 45 | 31300 | 嵌套 `track_agent` | stop-orphan-run 硬中断 | C | `run_turn.py:3234` |
| 46 | 31445 | 嵌套 `_notify_long_running` | per-chat display override | C | `run_turn.py:4087` |
| 47 | 31497 | `_run_agent_inner` | progress_explainer 安装说明 | C | `run_turn.py:4162` |
| 48 | 31500 | 同上 | 方案①：agent 在 executor 线程内才 spin-up | C | 同上 |
| 49 | 31502 | 同上 | `_pe_explainer = None` 初始化 | C | 同上 |
| 50 | 31503 | 同上 | `try:` 包裹 | C | 同上 |
| 51 | 31504 | 同上 | import `install_progress_explainer` | C | 同上 |
| 52 | 31505 | 同上 | 调用 `install_progress_explainer(...)` | C | 同上 |
| 53 | 31511 | 同上 | `except` 兜底 | C | 同上 |
| 54 | 32238 | 嵌套 `_stream_confirmed_final_delivery` | progress_explainer 停止说明 | C | `run_turn.py:3343` |
| 55 | 32239 | 同上 | `try:` 包裹 | C | 同上 |
| 56 | 32240 | 同上 | import + 调用 `stop(_pe_explainer)` | C | 同上 |
| 57 | 32242 | 同上 | `except` 兜底 | C | 同上 |

**分类汇总**：`C` 真定制代码 **53** 处 · `K` 常量 **1** 处 · `D` 注释/docstring **3** 处（其中 1 处为孤儿注释）。

---

## 4. 关键发现（对既有估值的修正）

### 4.1 「约 45 处是 i18n」不成立——57 处全部是真定制

复核方法：逐条提取标记行的后 4 行内容，并统计 `t(` 调用行与最近标记行的距离。

```
markers: 57    t()-lines: 173
t() 行距最近 marker < 5 行的数量: 0
```

**结论**：`gateway/run.py` 中的 i18n 改动（173 处 `t()` 调用点）**全部没有 `[owner]` 标记**，与 57 处标记**零重叠**。因此：

- T1-5 的迁移工作量应按 **52 处真定制代码**计（57 处标记 − 5 处留在 `gateway/run.py`），而非「约 12 处」——原估值低估约 4 倍；
- 反过来，T1-4（i18n 展示层化）与 T1-5 **无交集**：run.py 中可直接按「未标记且含 `t(` 的行」定位 i18n 足迹，与标记块互不干扰，两者可并行推进。

### 4.2 上游会把嵌套函数提升为类方法

上游 23 个模块中，`run_turn_runner.py` / `run_busy.py` / `run_inbound.py` / `run_shutdown.py` / `run_startup.py` 均为 **mixin 类**（`TurnRunner`、`GatewayBusySessionMixin`、`GatewayInboundMixin`、`GatewayShutdownMixin`、`GatewayStartupMixin`），`run_turn.py` 为 `GatewayTurnMixin`。我方在 `run.py` 中作为**嵌套函数**存在的符号（`_clarify_callback_sync`、`_roll_progress_overflow_if_needed`、`_stream_confirmed_final_delivery`、`_run_still_current`、`_display_surface_mode`、`_generic_status_phrase`、`track_agent`、`_notify_long_running`）在上游已被提为类方法。委托落点必须以**上游形态**为准。

### 4.3 定制集中在三个能力簇

下表 57 处标记（52 处待迁出 `gateway/run.py`、5 处留在其中）中，**per-chat display override** 簇最大——**18 处标记**、对应 **11 个实际调用点**（`resolve_display_setting_for_source(`）；其余为 **progress bubble 轮换** 6 处、**progress_explainer** 11 处（含 `try`/`except` 包裹行）、**cron env 清洗** 3 处、**auto-card** 3 处。迁移时应按能力簇整体收口到 `owner/` 侧模块，而不是逐行搬运。

分簇实测（按标记文案归并）：

| 簇 | 标记数 | 行号 |
|---|---|---|
| per-chat display override | 18 | 1268, 6079, 11484, 11503, 22734, 22741, 30230, 30662, 30670, 30681, 30690, 30714, 30718, 30743, 30780, 30879, 30921, 31445 |
| progress bubble 轮换 / fence-safe | 6 | 5543, 5598, 5647, 5658, 5727, 5759 |
| progress_explainer | 11 | 31497, 31500, 31502, 31503, 31504, 31505, 31511, 32238, 32239, 32240, 32242 |
| cron env 清洗 | 3 | 2353, 12466, 12558 |
| auto-card | 3 | 22792, 22806, 31045 |
| 其余单项定制 | 16 | 577, 1043, 4818, 6476, 6789, 11342, 11349, 18955, 18994, 19010, 20473, 22177, 23274, 24906, 24941, 31300 |

### 4.4 已在 `owner/` 侧实现的簇（迁移只需保留委托）

以下簇的实现体**已经在 `owner/` 目录内**，官方文件中仅剩调用点，迁移成本极低：

| 能力 | owner 侧实现 | 官方文件剩余 |
|---|---|---|
| 出站特殊 token 清洗 | `owner/outbound_special_token_scrub.py` | 1 行委托 |
| cron env 清洗 | `owner/cron/restart_scrub.py` | 3 处 1 行委托 |
| 入站上下文 | `owner/gateway/inbound_context.py` | 1 行委托 |
| steer 视觉富化 | `owner/gateway/steer_vision.py` | 1 行委托 |
| hygiene 压缩通知 | `owner/gateway/hygiene_compression_notice.py` | 1 行委托 |
| auto-card | `owner/feishu/agent_end.py` | 1 行委托 |
| stop-orphan-run | `owner/patches/stop_orphan_run.py` | 1 行委托 |
| progress_explainer | `owner/progress_explainer/dispatcher.py` | 安装 + 停止两组 |
| per-chat display override | `gateway/display_config.resolve_display_setting_for_source`（**official 侧**） | 11 个调用点 / 18 处标记 |

> **例外**：`per-chat display override` 的实现体 `resolve_display_setting_for_source` 位于**官方文件** `gateway/display_config.py`，不是 owner 侧。该簇若不做收口，11 个调用点仍会持续产生冲突。

---

## 5. 迁移批次建议（供 T1-5）

| 批次 | 内容 | 处数 | 依据 |
|---|---|---|---|
| B1 | 留在 `gateway/run.py` 的模块级定制：常量收紧 + 出站清洗 + cron scrub + docstring + 孤儿注释清理 | 5 | 零/低风险，先做 |
| B2 | → `run_turn_runner.py`（`TurnRunner`）：progress bubble 轮换 + diff card + per-chat streaming + clarify 超时 | 9 | 内聚，可整体收口到 `owner/gateway/progress_rotate.py` |
| B3 | → `run_busy.py` / `run_shutdown.py` / `run_inbound.py`：steer 富化 + cron scrub + 中轮 slash 白名单 + 入站上下文 | 10 | 分散但每处独立 |
| B4 | → `run_turn.py`（`GatewayTurnMixin`）：per-chat display override 全簇 | 14 | 最大簇，需先决定是否把 `resolve_display_setting_for_source` 收口到 owner 侧 |
| B5 | → `run_turn.py`（`GatewayTurnMixin`）其余：progress_explainer + auto-card + §17.2 + hygiene 通知 + 后台任务 key + stop-orphan-run | 19 | 已有 owner 实现，主要工作是委托形态对齐上游 |

**覆盖校验**：B1–B5 合计 **57** 处，与 `grep -c "\[owner\]" gateway/run.py` 完全一致，无遗漏、无重复。

**验收**：`gateway/run.py` 的 `MOD` hunk 由 **119 → 约 12**，冲突块由 **25 → 约 3**（迁移后按 `git merge-tree --write-tree upstream/main HEAD` 复测）。

---

## 6. 一致性声明

本表覆盖 `grep -c "\[owner\]" gateway/run.py` 报出的全部 **57** 处标记，无遗漏、无重复计数（逐条编号 #1–#57）。每行均已指到上游某个具体模块/行号，或明确标注「上游未搬，仍留 `run.py`」。

---

## 7. 冲突块归属实测（2026-09-28）——对本表第 5 节「验收」的修正

**方法**：取三方内容合并（等价于 git 对该文件的合并），逐块解析冲突标记。

```
base   = merge-base(HEAD, upstream/main) = 00b2e03c80   33,682 行
ours   = HEAD:gateway/run.py                            34,115 行
theirs = upstream/main:gateway/run.py                    5,676 行
git merge-file → 22 个冲突块，ours 侧合计 25,020 行
```

该结果与 TODO 里写的「试算合并后 = 25,296 行 + 25 冲突块」基本一致（实测 22 块 / 25,020 行），即清单确实观察到了这个现象。

### 7.1 冲突块规模分布（ours 侧行数降序）

| 合并行 | ours 行数 | 含 `[owner]` 标记 | 首行特征 |
|---|---|---|---|
| 6905–26861 | **19,945** | 是 | 上游整段删除/拆走的区域，owner 保留旧代码 |
| 4219–6332 | 2,108 | 是 | `_run_still_current` 相关区域 |
| 27656–29628 | 1,936 | 是 | `async def _run_agent_inner` |
| 27338–27555 | 204 | 否 | — |
| 27067–27286 | 196 | 是 | `_build_stream_consumer_config` |
| 3706–3868 | 152 | 否 | progress 相关 |
| 4053–4206 | 126 | 是 | `_track_progress_result` |
| 3568–3659 | 88 | 是 | `_append_dedup_counter` |
| 其余 14 块 | 各 ≤ 52（合计 265） | 4 是 / 10 否 | 多为 i18n 与零散改动 |

合计 22 块 / 25,020 行；**含 `[owner]` 标记的仅 9 块**，但其中 3 块（19,945 + 2,108 + 1,936 = 23,989 行）就占了 96%。

### 7.2 对本表第 5 节「验收」的修正

**「冲突块由 25 → 约 3」按 B1–B5 的修法（迁出 52 处定制、每处留 1–3 行委托）达不到**，理由：

1. **主导块是结构性的**：19,945 行那一块不是「某几处定制」，而是上游把该文件的
   大部分逻辑搬进了 23 个 `run_*.py` 之后 owner 侧仍保留的旧单体。逐处迁定制
   无法消除它——只有**采纳上游拆包**（用上游的 `run.py` + 23 个 `run_*.py`，
   再把 52 处定制重新落到对应新模块）才能消除。
2. **标记与冲突块不对应**：22 块里 13 块 ours 侧不含任何 `[owner]` 标记（多为
   i18n 与未标记的 owner 改动），B1–B5 完全不覆盖这块。
3. **部分「定制」是整方法级重写**：如 `_run_agent_inner`（1,936 行）、
   `_run_still_current` 区域（2,108 行）——迁出后不可能只留「1–3 行委托」。

### 7.3 修正后的价值判断

| 做法 | 可达成 | 成本 | 风险 |
|---|---|---|---|
| B1–B5 逐处迁定制（原 T1-5 修法） | `MOD` hunk 显著下降（评论/实现体搬出）；冲突块最多改善 9 块中的小者（合计约 500 行） | ~2 人日 | 低（纯搬移 + 委托） |
| **采纳上游拆包**（真正消除结构性块） | 冲突量可降到与「上游文件逐字节一致 + 53 处委托」同量级 | 远超 2 人日，需重落 52 处定制到 23 个新模块 | 高（漏搬 = 定制静默消失，无测试可发现） |

**建议**：T1-5 按「**价值重定**」处理，二选一后明确立项：

- **A（推荐，先做）**：只做 B1（5 处，零风险），并把 B2–B5 降级为 P2；
  同时把「采纳上游拆包」单独立项（这是唯一能真正消除 19,945 行结构性冲突的路径，
  且它是 T2/T3 里多处 run.py 相关条目的共同前置）。
- **B**：整项不做，改为在每次 sync 时按 §7.1 的块清单人工解冲，并把
  「`gateway/run.py` 不采纳上游拆包」作为**已知接受项**记录。

无论选哪条，**本表第 5 节「冲突块 25 → 约 3」的验收口径都应作废**。

---

## 8. B1 执行记录（2026-09-28）

**提交**：`efec7a3696`（`fix(owner): T1-5 B1 —— raw-text 常量收口到 owner 侧 + 清理孤儿注释`）。
B1 是 T1-5 唯一执行的批次；B2–B5 按 §7.3 建议 A **降级 P2**，「采纳上游拆包」另立单项。

### 8.1 逐条处置（对照 §3.1）

| # | 处置 | 说明 |
|---|---|---|
| 1 | **已执行** | 常量收口至 `owner/gateway/raw_text_policy.py`；`gateway/run.py` 改为 **fail-closed 薄委托**——委托失效时保留 `{"local"}`，绝不回落到上游更宽集合 |
| 2 | 无需改动 | 已是 1 行委托（`owner/outbound_special_token_scrub.py`） |
| 3 | 无需改动 | docstring 说明，无行为变更 |
| 4 | 无需改动 | 已是 1 行委托（`owner/cron/restart_scrub.py`） |
| 5 | **已执行** | 删除孤儿注释（其下无代码）。真实调用点（行 23272）与 `_is_executor_shutdown_error` 的 docstring 均已承载同义说明 |

### 8.2 标记数订正：57 → 56

#5 本身计入 `[owner]` 标记，删除后**活动标记数为 56**。

§3 仍完整保留 **57 条**编号（#1–#57）——它是 T0-1 建立时的**基线映射**（已脚本核验：
57 行、编号连续、无缺号、无重复），不因 B1 的删除而删行；#5 的「迁移动作」栏即为
本次执行内容。故 §3.1 的 5 行里，#1 与 #5 已处置，#2–#4 无需改动。

### 8.3 顺带订正的文档计数错误

此前文档存在**四处互相矛盾的计数**（均与本 B1 改动无关，属原稿笔误）：

| 位置 | 原值 | 订正 | 依据 |
|---|---|---|---|
| §1 落点表 `gateway/run.py` 行 | 4 处 | **5 处** | §3.1 实有 #1–#5 共 5 行 |
| §1 落点表 `gateway/run_turn.py` 行 | 32 处 | **33 处** | §3.6 实有 #25–#57 共 33 行 |
| §3.1 标题 | 4 处 | **5 处** | 同上 |
| §3.6 标题 | 32 处 | **33 处** | 同上 |

派生数字随之订正：**待迁定制 53 → 52 处**（57 − 5）。原 53 源自 §3.1 被误计为 4 处。

逐节实测行数（脚本核对）：

| 节 | 行数 | 编号 |
|---|---|---|
| §3.1 留在 `run.py` | 5 | #1–#5 |
| §3.2 `run_turn_runner.py` | 9 | #6–#14 |
| §3.3 `run_busy.py` | 4 | #15–#18 |
| §3.4 `run_shutdown.py` | 2 | #19–#20 |
| §3.5 `run_inbound.py` | 4 | #21–#24 |
| §3.6 `run_turn.py` | 33 | #25–#57 |
| **合计** | **57** | 无缺号 |

§5 批次表（B1=5、B2=9、B3=10、B4=14、B5=19，合计 57）与实测一致——可见此前矛盾的
只是 §1/§3.1/§3.6 的**标题数字**，表内容本身无误。§4.3 的分簇表（18+6+11+3+3+16=57）
同样以基线 57 为准，保持不变。

### 8.4 防回归

`tests/owner/test_contract_entrypoints.py` 新增 identity 断言。委托的**两个分支产出
同一个值**，故仅凭取值无法区分「委托生效」与「静默兜底」——而那正是本改动唯一的真实
风险面。因此断言比对**对象身份**，并附「owner 集严格窄于上游集」与「三项外部面必须为
`False`」的行为断言。

已做变异验证：手工模拟 `except` 分支时该断言如期失败，证明它并非恒真。

该文件属 `owner/scripts/check-merge-residue.sh` 的**固定项**，每次 sync 都会被执行到。

### 8.5 验证

| 项 | 结果 |
|---|---|
| `tests/owner` + `tests/gateway/test_telegram_noise_filter.py` | **866 passed** |
| 委托生效 | gateway 常量与 owner 常量**同一对象**（`is` 为 `True`） |
| 严格收紧 | `{"local"} ⊂ {local, api_server, webhook, msgraph_webhook}`（真子集） |

### 8.6 对 §7.3「共同前置」表述的核实

§7.3 建议 A 中把「采纳上游拆包」描述为「**T2/T3 里多处 run.py 相关条目的共同前置**」。
对该表述做了核实：全量扫描 TODO 清单的阶段 2（T2-1…T2-20）与阶段 3（T3-1…T3-22）
全部条目后，**未发现任何一条引用 `gateway/run.py`**——命中的 `run_agent.py:9096-9102`
（T3-7）与 `run_agent.py:7459`（T3-17）属**另一个文件**，与本表讨论的 `gateway/run.py` 无关。

因此该「共同前置」的范围被收窄为：在当前台账中，「采纳上游拆包」只对**本次另立的
T3-22（T1-5 的 B2–B5 余量，52 处）**构成前置。原先的宽泛表述缺乏清单依据，不宜沿用。

> 说明：该核实针对的是**清单条目**层面的依赖关系，不否定 §7 的实测结论——即
> 19,945 行的结构性主导块只能靠采纳上游拆包消除，这一点由三方合并实验直接支撑。

> §7 的实测数字（`ours` 34,115 行 / 25,020 行 / 22 块）系 **B1 之前**的基线；B1 后
> `gateway/run.py` 为 34,113 行（−2 行）。该 2 行差异不影响 §7 结论——结构性主导块
> （19,945 行）只能靠采纳上游拆包消除，与逐处迁定制的行数增减无关。
