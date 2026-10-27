# C11-clarify · 飞书 Clarify 交互卡

> 状态：**已落地**（阶段三）

## 做什么

`clarify` 工具在飞书侧发 Schema 2.0 交互卡（选项按钮 +「其他」输入表单）；点击同步回卡并 `resolve_gateway_clarify`。超时 / 取消 / 自由文本覆盖时走官方 `retire_clarify_card(clarify_id, notice)` 灰卡。

## 入口

| 层 | 路径 |
|----|------|
| 逻辑 | `owner/feishu/clarify_card.py` |
| 选择文案 | `owner/clarify/gateway_helpers.py` |
| 胶水 | `plugins/platforms/feishu/adapter.py`（`send_clarify` / `retire_clarify_card` / `_handle_clarify_card_action` + card action 分支） |
| 依赖 | C11 `send_card`；官方 `tools.clarify_gateway` |

## 行为要点

1. **有 choices**：发卡并缓存 `_clarify_state[clarify_id]`（session_key / choices / question / message_id）。
2. **无 choices**：纯文本 + `mark_awaiting_text`（网关文本拦截）。
3. **点击**：选项 → resolve + 冻结绿卡；`__other__` → 输入表单；表单提交 → resolve + 冻结；返回 → 恢复选项卡。
4. **retire**：gateway 调用 `retire_clarify_card`，REST PATCH 灰卡（避开 WS token 刷新）。
5. **本批范围**：不做 B17 超时中断 agent、不做 multi_select 专用 UI。

## 测

`tests/owner/test_c11_clarify_card.py`
