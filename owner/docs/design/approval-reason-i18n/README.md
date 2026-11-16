# 审批 reason 展示 i18n

已落地（v2）。

## 动机

审批卡标签「标记原因：」已走 `gateway.exec_approval.reason_label` i18n，但后面的
`description`（例如 `shell execution via heredoc`）仍是检测器英文原文。

## 硬约束：英文键不可译

`detect_dangerous_command` 返回的 `pattern_key` / `description` **同源**，并作为
always-allow / session allowlist 的匹配键。因此：

- **禁止**改 `tools/approval_detection.py` / `_EXECUTE_CODE_DESCRIPTION` 英文原文；
- **禁止**把中文写进 allowlist 持久化；
- `ExecApprovalPrompt.description`、smart-approve 给模型的文案保持英文。

## 做法：仅展示层翻译

`owner/i18n/approval_reasons.py`：

- `REASON_ZH`：英文原文 → 简体中文（逐字匹配）；
- 动态模板：`^arbitrary program execution via (.+)$` → `通过 \1 执行任意程序`；
- `translate_reason(description)`：
  - 活跃语言为 `en`（或非 `zh*`）→ 原样返回，**不读译表**；
  - 精确命中 / 模板命中 → 译文；
  - 缺译 → 回落英文；永不抛、永不把内部 key 漏给用户。

术语保留：`shell` / `heredoc` / `sudo` / `docker` / `git` / `PowerShell` / 具体 flag 与命令名不译。

## 胶水调用点（P2 极薄）

| 文件 | 函数 | 说明 |
|------|------|------|
| `gateway/platforms/base.py` | `_format_exec_approval` | 默认 reason 填入后、budget fit 前 translate；卡片正文中文 |
| `gateway/run.py` | `_format_exec_approval_fallback` | 纯文本 `/approve` 回落体 |
| `tools/approval_prompt.py` | `_ask_human` | **仅 CLI header** 路径；`approval_callback` 仍传英文 |

`# [owner] approval reason display i18n (see owner/i18n/approval_reasons.py)`

## 如何补译

1. 上游新增静态 description 时，漂移测 `test_drift_static_descriptions_covered` 会红。
2. 在 `REASON_ZH` 增加「英文原文 → 简体」条目；术语不译。
3. 若是 `arbitrary program execution via …` 这类 f-string，优先扩 `_REASON_ZH_TEMPLATES`。

## 测

```bash
cd ~/.hermes/hermes-agent && uv run pytest tests/owner/test_approval_reason_i18n.py -q
```
