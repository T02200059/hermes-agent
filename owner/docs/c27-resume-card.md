# C27-resume-card · 飞书 `/resume` 交互卡

## 行为

1. 飞书侧发无参 `/resume`（且有已命名会话）→ 发 v2 schema 数字按钮卡（1–10，每行 3 个），正文为会话列表 markdown。
2. 点数字按钮 → 校验点击者 open_id == 发卡时 source.user_id → 合成 `/resume N` COMMAND → 走 `_handle_message_with_guards`（与 model_picker confirm 同流水线）。
3. **点选后冻卡**：成功调度后立刻回 `build_done_card`（无按钮，仿 model_picker confirm），防连点多次 `/resume N`；按钮 value 顺带 stash `session_title`（回调时没有列表）。
4. **提交失败反馈**：`_submit_on_loop` 返回 False（或 loop 不可用 / 缺 source / 非卡主）→ `build_failed_card`（💡，仿 C12 queue / C04 approval），禁止空 ack 留下可点按钮。
5. 发卡失败 → 纯文本列表兜底（`adapter.send`）。

双击竞态：冻卡与现网其它卡同级，极端连点仍可能盖不全，可接受。

## 入口

| 层 | 位置 |
|----|------|
| 逻辑 | `owner/feishu/resume_card.py`（`build_*` / `try_send_resume_card_list` / `send_resume_card` / `handle_resume_card_action` / `dispatch_resume_card_action`） |
| 命令 | `gateway/slash_commands_session.py` `_handle_resume_command` 列表分支（`hasattr(send_resume_card)` → 发卡并 `return ""`） |
| 胶水 | `plugins/platforms/feishu/adapter.py`（`send_resume_card` / `_handle_resume_card_action` + card-action `hermes_action==resume_select`，**须排在**泛 `hermes_action`→审批之前） |
| i18n | `locales/en.yaml` / `zh.yaml` → `gateway.resume.card_title`（其它语言回落英文） |

## action_value 键

- `hermes_action`: `"resume_select"`
- `resume_index`: 1-based
- `session_key`: 相关会话键（调试）
- `session_title`: 对应条目标题（冻卡正文用；点击时无列表）
- `source_dict`: 发卡时 `SessionSource.to_dict()`，回调还原 source

## 操作者鉴权

保留点击者 == 卡主校验。与审批卡不同：审批冻结文案已显示「由 xx 批准」；resume 会切会话状态，群成员冒充属 IDOR。

## 测

`tests/owner/test_c27_resume_card.py`

## 不做

不改 overlay 主 schema；不开 C05 多 profile；不重做 memory-approval / C11-diff。
