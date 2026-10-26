# C09 · skill 脚本自动审批 + skill_manage 飞书审批门

## 背景

源 §3.6 / §3.11。依赖已齐：**C04** 审批卡/name cache、**C01** `gate_allow_permanent`。

## 方案（已落地）

### 1. skill 脚本自动审批（§3.6）

- `owner/approval/skill_script_approval.py`
- 本会话经 `skill_view` 看过的 skill，其 `approvals.skill_script_allowlist` 脚本可跳过危险命令提示
- 五道门：viewed 空 / 引号外复合符 / 引号内元字符 / 全脚本匹配 / `detect_dangerous_command`（CR-01 会话隔离、CR-02/CR-006 fail-closed）
- 胶水（`# [owner] C09`）：
  - `tools/skills_tool.py` `_skill_view_with_bump` → `track_session_skill_view`
  - `tools/approval.py` `clear_session` → `reset_session_skills_viewed`
  - `check_dangerous_command` / `check_all_command_guards`：floors 之后、yolo 之前

### 2. skill_manage 飞书审批门（§3.11）

- `owner/approval/skill_manage_gate.py` + `owner/owner-extensions/skill_manage_bridge/`
- `owner/feishu/skill_approval_card.py`（自建卡，发往 `approval_home_chat_id`）
- Hook：`pre_tool_call`（`run_gate`）+ `pre_gateway_dispatch`（cache gateway）
- 仅飞书/Lark + `skill_manage` 写动作 + profile 白名单 + `allow_skills`；YOLO 不绕过
- 等待默认 24h：`tools.approval_context._get_approval_timeout` ContextVar 覆盖
- 门开启时压制 `_spawn_background_review(review_skills=…)`（转发 `focus`/`explicit`）
- 卡片点击：adapter `_on_card_action_trigger` 薄分支 → `handle_card_click` → `resolve_gateway_approval`
- 发卡走 `owner.feishu.card_sender.send_card`（无 REST 旁路）

### 3. 配置

| 文件 | 段 |
|------|----|
| `owner/config/patch.yaml` | `approvals.skill_script_allowlist` |
| `owner/config/patch_feishu_profile.yaml` | `feishu.skill_approval`（`enabled` 默认 false） |

运行时 `~/.hermes/patch_feishu_profile.yaml` 若仍软链旧树，以旧树活配置为准；仓内文件为 v2 自包含模板。

## 测

- `tests/owner/test_skill_script_approval.py`
- `tests/owner/test_skill_manage_gate.py`

## 可移除性

删 `owner/approval/skill_*`、`owner/feishu/skill_approval_card.py`、`skill_manage_bridge/` 与三处官方薄胶水后，官方审批/skill_view 行为恢复（import fail-open）。
