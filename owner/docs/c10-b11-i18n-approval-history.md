# C10 + B11 · 护栏 i18n 与审批历史结构判定

已落地（v2）。

## C10 · `_localized` 护栏文案

- 英文原文留在 `tools/file_tools_write_guards.py` 常量（唯一真源）。
- 渲染：`owner/i18n/localized.py` → `localized(key, en_text, **kw)`：
  - `en`：直接 format 代码原文（不读 catalog，上游改词自动传导）；
  - 其他语言：`agent.i18n.t(key)`，缺键回落英文原文。
- Catalog：`locales/{en,zh}.yaml` 的 `approval.protected_file_*` / `ssh_config_*` / `gate_why_*`（en 必须与代码常量逐字一致，见漂移测）。

## B11 · 审批历史不靠英文子串

- `owner/approval/approval_history_policy.py`：层 1 status/outcome → 层 2 catalog 片段 → 层 3 英+中兜底。
- `hermes_cli/approvals_suggest.py`：`_blocked_tool_call_ids` 的 SQL 粗筛与 Python 判定共用该模块；owner 不可用时回落旧 `_BLOCK_MARKERS`。

## 测

```bash
cd ~/.hermes/hermes-agent-v2
uv run pytest tests/owner/test_file_tools_guard_text_i18n.py \
  tests/owner/test_approval_suggest_i18n_blocks.py \
  tests/hermes_cli/test_approvals_suggest.py -q
```
