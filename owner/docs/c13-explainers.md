# C13 · 统一 explainers（progress / approval / english）

状态：**已落地**（本地 commit；未要求前不 push）

## 做什么

三套旁白共用一套基建，避免各自配 auxiliary / 各自加载器：

| kind | 行为 | 投递 |
|------|------|------|
| `progress` | 沉默期进度旁白；`stream_guard.snapshot.tripped` 时让位 | `🧭 系统提示：` → notice 卡 |
| `approval` | 审批卡发出前 2–3 句事实解说；**绝不建议批/拒**；fail-open | 嵌进飞书审批卡正文 |
| `english` | `display.language=zh` 且终局整段英文 → 侧路中文解说；**不改原文** | `🔤 系统提示：` → notice 卡 |

## 配置（`owner/config/patch.yaml` → `~/.hermes/patch.yaml`）

```yaml
explainers:
  provider: auto          # 共用；可被 kind 覆盖
  model: auto
  timeout_ms: 30000
  progress:
    enabled: true         # 代码默认 false；本机对齐旧树 true
    silence_seconds: 60
    platforms: { feishu: true }
  approval:
    enabled: true
    cache_ttl_seconds: 600
    platforms: { feishu: true }
  english:
    enabled: true
    platforms: { feishu: true }
```

取模优先级：**kind provider/model → 共用 → `config.yaml` `auxiliary.<task>` → 主模型**。  
`call_llm(task=)` 长名保留：`progress_explainer` / `approval_explainer` / `english_explainer`。

三级启用：`chats.<platform>.<chat_id>` → `platforms.<platform>` → `enabled`。

## 扩展第四种 kind

```python
from owner.explainers.registry import register_kind
register_kind("summary", defaults={"enabled": False, "platforms": {}})
# 然后 call_explainer_llm("summary", messages)
```

并在 `patch.yaml` 加 `explainers.summary: { enabled: true, ... }`，包放 `owner/explainers/summary/`。

## 模块

- 共享：`owner/explainers/{common,config,llm,registry,__init__}.py`
- kind：`owner/explainers/{progress,approval,english}/`
- 胶水：`gateway/run_turn.py`（progress install/stop）、`plugins/platforms/feishu/adapter.py`（approval 嵌卡）、`owner/owner-extensions/__init__.py`（progress delta + english hooks）

## 兼容

- 仍指向旧树、顶层 `progress_explainer:` 等活键时，加载器会合成统一块（过渡期）。
- 规范约定软链应指向本 worktree 的 `owner/config/patch.yaml`（v2 扁平、无 `owner:` 外壳）。

## 验证

```bash
cd ~/.hermes/hermes-agent-v2
PYTHONPATH=. python -m pytest tests/owner/test_c13_explainers.py -q
```
