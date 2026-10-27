# C26-feishu-picker · 飞书 /providers 模型切换交互卡

> 状态：**已落地**（补齐 C26 飞书半边）

## 做什么

飞书上执行 `/providers` 时发 Schema 2.0 交互卡：选 provider → 选模型 → 合成 `/model … --provider … --global`。过期/异常用 toast，避免卡面一直 loading。

## 入口

| 层 | 路径 |
|----|------|
| 逻辑 | `owner/feishu/model_picker.py`（`build_*` / `send_model_picker_card` / `handle_picker_action` / `dispatch_model_picker_action`） |
| 命令 | `owner/commands/providers.py`（`hasattr(send_model_picker_card)` → 发卡并 `return None`） |
| 胶水 | `plugins/platforms/feishu/adapter.py`（`_model_picker_state` / `send_model_picker_card` / `_handle_model_picker_action` + card-action `hermes_model_picker`） |
| 依赖 | C11 `send_card`；C04 `operator_display_name` |

## 行为要点

1. **发卡前写 state**：`picker_id → {providers, source}`，避免点击竞态。
2. **步骤**：`provider` / `back` / `confirm`；confirm 走 `_message_handler` 同步处理合成 COMMAND，再用 `adapter.send` 回文本结果。
3. **过期**：无 state 时 toast「请重新执行 /providers」，不返回空响应。
4. **action_value 键**：`hermes_model_picker`（与 `hermes_action` / `clarify_id` / `skill_approval_gate` 并存）。

## 测

`tests/owner/test_c26_model_picker.py`（+ 既有 `test_providers_command.py` 飞书卡路径）

## 不做

resume_card / guide_card；不改 overlay 主 schema。
