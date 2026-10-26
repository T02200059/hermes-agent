# C04 · 飞书审批卡底座 + 中文名缓存 + inbound 身份

## 背景

飞书审批卡（CallBack 冻结、失败路径、open_id→中文名、inbound/cron 身份）原在官方 adapter 内联过深，sync 冲突大；官方仅有进程内 `_sender_name_cache`（短 TTL、过期破坏性 pop），无 disk-backed user_store、无失败冻结卡、无 inbound/cron session 身份块。

## 方案（已落地）

### 1. 审批卡（§3.1）

- `owner/feishu/approval.py`：`build_resolved_card` / `build_failed_card` / `handle_approval_card_action` / metadata pre-warm
- 发送仍走官方 `ExecApprovalPrompt` + `_send_exec_approval_prompt`（**C01** `gate_allow_permanent` 已禁用永久按钮时不展示 Always）
- 失败路径（unauthorized / already_handled / chat_mismatch / missing_id / submit_failed）返回**冻结错误卡**，不再 `card=None`
- adapter 薄委托：`_handle_approval_card_action` / `_build_resolved_approval_card` + send 前 `pre_warm_sender_from_metadata`

### 2. user_store / 中文名（§3.1）

- `owner/feishu/user_store.py` + `user_cache.py` + `sender_name_helpers.py`
- TTL **24h**；过期只从 hot map 驱逐，**不**清 `_users.display_name`（soft TTL，避免卡面泄漏 `ou_xxx`）
- adapter `_user_store` 属性惰性创建；创建时把既有 `_sender_name_cache` 条目 migrate 进 store，再把属性指到 `store.name_ttl_cache`

### 3. inbound / cron 身份（§3.2–3.3）

- `owner/feishu/inbound_context.py` + `owner/gateway/inbound_context.py`
- Feishu 入站追加 `[Inbound context]`（open_id / chat_id / user_name 经 sanitize / session_id）
- Cron 在 user prompt 追加 `[Cron context] session_id: …`（不改 system prompt）

### 4. 多平台审批签名（§3.4）

- `gateway/run_turn_runner.py` 在 `send_exec_approval` metadata 写入 `sender_open_id` / `sender_is_bot`
- 不改官方 `send_exec_approval` 签名；QQ/飞书经 `ExecApprovalPrompt.metadata` 吸收

## 侵入

| 位置 | 类型 |
|------|------|
| `plugins/platforms/feishu/adapter.py` | 薄胶水（委托 + TTL + store + pre-warm） |
| `gateway/run_inbound.py` | 一处 append inbound |
| `gateway/run_turn_runner.py` | metadata 填 sender |
| `cron/scheduler.py` | Cron context 追加 |
| `locales/{zh,en}.yaml` | fail_* / operator_fallback 文案 |

## 测

`tests/owner/test_c04_feishu_base.py`；官方 `tests/gateway/test_feishu_approval_buttons.py` 期望已对齐冻结卡与 soft TTL。

## 范围外（后续）

C10 显示 i18n、C11 auto-card/early-typing、C13 explainer、C05 多 profile。（C09 skill 门已另见 `design/skill-approval/`）
