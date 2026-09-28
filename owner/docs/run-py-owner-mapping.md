# `gateway/run.py` owner 定制落点映射表

**用途**：`gateway/run.py` 迁移（T1-5）的前置台账。上游正在拆包该文件，迁移时必须逐块判断每个定制该落到哪个新模块——漏搬 = 定制静默消失，且没有任何测试能发现。

**建立日期**：2026-09-28
**基线**：`b83d1da12c`（owner 分支自身提交，2026-08-27）
**当前 HEAD**：`ef4b4a8876`
**上游参照**：`upstream/main` = `9573f44ca5`

---

## 1. 上游拆包现状

| 项 | owner 侧（HEAD） | 上游（`upstream/main`） |
|---|---|---|
| `gateway/run.py` 行数 | 34,115 | 5,676 |
| `gateway/run_*.py` | 0（未拆） | 23 个（合计 21,369 行） |
| 本文件 `MOD` 增量 | +8,123 / −1,215（vs BASE） | — |

上游 23 个新模块与本次映射相关的落点（已逐条用 `git grep "def <符号>" upstream/main` 核实）：

| 上游模块 | 承载的类 | 本次涉及 |
|---|---|---|
| `gateway/run.py` | 模块级 helper（**未搬**） | 4 处 |
| `gateway/run_turn_runner.py` | `TurnRunner` | 9 处 |
| `gateway/run_turn.py` | `GatewayTurnMixin` | 32 处 |
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

### 3.1 留在 `gateway/run.py`（上游未搬，4 处）

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

### 3.6 `GatewayTurnMixin` → `gateway/run_turn.py`（32 处）

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

- T1-5 的迁移工作量应按 **53 处真定制代码**计，而非「约 12 处」——原估值低估约 4 倍；
- 反过来，T1-4（i18n 展示层化）与 T1-5 **无交集**：run.py 中可直接按「未标记且含 `t(` 的行」定位 i18n 足迹，与标记块互不干扰，两者可并行推进。

### 4.2 上游会把嵌套函数提升为类方法

上游 23 个模块中，`run_turn_runner.py` / `run_busy.py` / `run_inbound.py` / `run_shutdown.py` / `run_startup.py` 均为 **mixin 类**（`TurnRunner`、`GatewayBusySessionMixin`、`GatewayInboundMixin`、`GatewayShutdownMixin`、`GatewayStartupMixin`），`run_turn.py` 为 `GatewayTurnMixin`。我方在 `run.py` 中作为**嵌套函数**存在的符号（`_clarify_callback_sync`、`_roll_progress_overflow_if_needed`、`_stream_confirmed_final_delivery`、`_run_still_current`、`_display_surface_mode`、`_generic_status_phrase`、`track_agent`、`_notify_long_running`）在上游已被提为类方法。委托落点必须以**上游形态**为准。

### 4.3 定制集中在三个能力簇

53 处真定制中，**per-chat display override** 簇最大——**18 处标记**、对应 **11 个实际调用点**（`resolve_display_setting_for_source(`）；其余为 **progress bubble 轮换** 6 处、**progress_explainer** 11 处（含 `try`/`except` 包裹行）、**cron env 清洗** 3 处、**auto-card** 3 处。迁移时应按能力簇整体收口到 `owner/` 侧模块，而不是逐行搬运。

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
