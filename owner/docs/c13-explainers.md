# C13 · 统一 explainers（progress / approval / english / recap）

状态：**已落地**（含第四 kind `recap`；本地 commit；未要求前不 push）

## 做什么

旁白共用一套基建，避免各自配 auxiliary / 各自加载器：

| kind | 行为 | 投递 |
|------|------|------|
| `progress` | 沉默期进度旁白；`stream_guard.snapshot.tripped` 时让位 | `🧭 系统提示：` → notice 卡 |
| `approval` | 审批卡发出前 2–3 句事实解说；**绝不建议批/拒**；fail-open | 嵌进飞书审批卡正文 |
| `english` | `display.language=zh` 且终局整段英文 → 侧路中文解说；**不改原文** | `🔤 系统提示：` → notice 卡 |
| `recap` | 按需 `/recap`：压平 User/Agent 对话 → 一句/小段回顾（主体语气） | `📋 系统提示：` → notice 卡；**不写主会话模型历史** |

## 上下文与输入预算

- **设计前提**：辅助模型上下文 **≥ 256k**。
- **输入默认**：共用 `explainers.max_input_chars: 64000`（各 kind 可覆盖）。
- 截断策略：优先保留**尾部**（近轮对话 / 近证据）；见 `owner.explainers.common.clip_input`。
- 输出帽仍按 kind 小限（如 recap `max_output_chars`、progress/approval/english 的 `max_output_chars`）。

## 配置（`owner/config/patch.yaml` → `~/.hermes/patch.yaml`）

```yaml
explainers:
  provider: auto
  model: auto
  timeout_ms: 30000
  max_input_chars: 64000
  progress:
    enabled: true
    silence_seconds: 60
    platforms: { feishu: true }
  approval:
    enabled: true
    cache_ttl_seconds: 600
    platforms: { feishu: true }
  english:
    enabled: true
    platforms: { feishu: true }
  recap:
    enabled: true
    max_output_chars: 500
    platforms: { feishu: true }
```

取模优先级：**kind provider/model → 共用 → `auxiliary.<task>` → 主模型**。  
`call_llm(task=)` 长名：`progress_explainer` / `approval_explainer` / `english_explainer` / `recap_explainer`。

三级启用：`chats.<platform>.<chat_id>` → `platforms.<platform>` → `enabled`。

## `/recap`

- 注册：`owner/owner-extensions` → `register_command("recap", …)`
- 路径：`SessionDB` 读当前 `session_id` transcript → `flatten_messages` → `call_explainer_llm("recap", …)` → `📋 系统提示：…`
- 飞书：`feishu_card.notice_titles` 已含该前缀 → auto-card notice。
- 失败 fail-open（返回短状态文案，不抛）。

## 扩展更多 kind

```python
from owner.explainers.registry import register_kind
register_kind("summary", defaults={"enabled": False, "platforms": {}})
# call_explainer_llm("summary", messages)
```

并在 `patch.yaml` 加 `explainers.summary: { enabled: true, ... }`，包放 `owner/explainers/summary/`。新 kind 自动继承共用 `max_input_chars`（默认 64k）。

## 模块

- 共享：`owner/explainers/{common,config,llm,registry,__init__}.py`
- kind：`owner/explainers/{progress,approval,english,recap}/`
- 胶水：`gateway/run_turn.py`（progress）、`plugins/platforms/feishu/adapter.py`（approval 嵌卡）、`owner/owner-extensions/__init__.py`（progress/english hooks + `/recap`）

## 兼容

- 仍指向旧树、顶层 `progress_explainer:` 等活键时，加载器会合成统一块（过渡期）。
- 规范约定软链应指向本 worktree 的 `owner/config/patch.yaml`（v2 扁平、无 `owner:` 外壳）。

## 验证

```bash
cd ~/.hermes/hermes-agent-v2
PYTHONPATH=. python -m pytest tests/owner/test_c13_explainers.py -q
```
