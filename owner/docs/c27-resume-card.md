# C27-resume-card · 飞书 `/resume` 交互卡

## 行为

1. 飞书侧发无参 `/resume`（且有已命名会话）→ 发 v2 schema 数字按钮卡（1–10，每行 3 个），正文为会话列表 markdown。
2. 点数字按钮 → 校验点击者 open_id == 发卡时 source.user_id → 合成 `/resume N` COMMAND → 走 `_handle_message_with_guards`（与 model_picker confirm 同流水线）。
3. 发卡失败 → 纯文本列表兜底（`adapter.send`）。

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
- `source_dict`: 发卡时 `SessionSource.to_dict()`，回调还原 source

## 操作者鉴权

保留点击者 == 卡主校验。与审批卡不同：审批冻结文案已显示「由 xx 批准」；resume 会切会话状态，群成员冒充属 IDOR。

## 测

`tests/owner/test_c27_resume_card.py`

## 不做

不改 overlay 主 schema；不开 C05 多 profile；不重做 memory-approval / C11-diff。
