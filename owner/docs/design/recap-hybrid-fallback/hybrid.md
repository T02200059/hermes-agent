# recap 超预算混合输入兜底

状态：**已落地**（2026-11-17；owner 改动，未改官方源码）

## 问题

`recap` 每次把当前 tip 的可见 User/Agent 正文全量压平后送给 explainer。超过 `max_input_chars`（默认 64k）时从**尾部**截断，被砍掉的前半段不再进入 prompt。旧回顾虽已落在 `messages`（`role=notice`、`display_kind=recap`），组 prompt 时故意不用，以避免「回顾套回顾」。

超长会话一旦触发截断，前半段进度只能靠近期原文间接体现。本方案只在即将/已经截断时，把上一次进度回顾当作被省略前半段的说明，再拼上保留的尾部原文。

不到预算的会话行为不变。混合阈值、校准规则、`max_tokens` / 超时也不改。自动回顾的触发口径见 `owner/docs/c13-explainers.md`（长耗时或长结束消息，回合结束立刻判定；不再空等）。

## 方案

入口仍是 `/recap` 与自动回顾，生成仍走 `owner/explainers/recap/`。新增 `hybrid.py` 在调用 LLM 前规划输入：

| 条件 | `input_mode` | prompt |
|------|----------------|--------|
| 可见正文 ≤ 预算 | `full` | 现有全量压平 |
| 超预算且有旧回顾，且本轮不是校准 | `hybrid` | 「先前回顾」+ 尾部原文 |
| 超预算但没有旧回顾 | `tail` | 现有尾部截断（不失败） |
| 超预算、有旧回顾，但命中校准 | `calibration` | 同 `tail`，不引用旧回顾 |

规则要点：

1. 阈值跟随当前 `max_input_chars`（默认 64000），不是另起一套硬编码长度。
2. 混合时必须保留截断后的近期原文，不能改成「只丢旧回顾 + 很小一段增量」。
3. 旧回顾定位：当前 tip 的 **compression 链**（`get_compression_tip` + `get_compression_lineage`）里最近一条 `role=notice AND display_kind=recap`。不沿 `session_reset` / branch / delegate 链，不用 watermark 文件当正文来源。进度卡（`display_kind=progress`）一律忽略。
4. flatten 仍只留 User/Agent 可见正文；notice / 回顾 / 进度不进对话流。旧回顾只作为单独的「先前回顾」块。
5. 定期全量校准：在超预算路径里，只统计先前 `input_mode` 为 `hybrid` 或 `calibration` 的回顾。每 3 次混合后，第 4 次做一次不依赖旧回顾的纯尾部截断（`counted % 4 == 3`）。没有 `input_mode` 的旧行不计入，避免升级后误校准。
6. 若现有消息带 `_row_id` / `id` / `message_uid`，把覆盖到的最后一条写入 `display_metadata.covered_last_message_id`，同时记下 `input_mode`、`full_chars`、`truncated`、`prior_recap_id`。不改表结构或官方 schema。

## 模块

- `owner/explainers/recap/hybrid.py`：规划输入、查找旧回顾、校准计数
- `owner/explainers/recap/prompt.py`：混合模板（中文回顾约束不变）
- `owner/explainers/recap/explain.py` / `command.py` / `auto.py`：组输入时接入；落盘时把规划元数据写入 `display_metadata`
- 测：`tests/owner/test_c13_recap_hybrid.py`

## 非目标

不改混合阈值与校准规则。自动回顾是否在回合结束立刻出卡，由自动触发口径决定（与混合兜底正交）。
