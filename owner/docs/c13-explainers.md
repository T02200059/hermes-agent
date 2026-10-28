# C13 · 统一 explainers（progress / approval / english / recap）

状态：**已落地**（含第四 kind `recap`；本地 commit；未要求前不 push）

## 做什么

旁白共用一套基建，避免各自配 auxiliary / 各自加载器：

| kind | 行为 | 投递 |
|------|------|------|
| `progress` | 沉默期进度旁白；`stream_guard.snapshot.tripped` 时让位 | `🧭 系统提示：` → notice 卡 |
| `approval` | 审批卡发出前 2–3 句事实解说；**绝不建议批/拒**；fail-open | 嵌进飞书审批卡正文 |
| `english` | `display.language=zh` 且终局整段英文 → 侧路中文解说；**不改原文** | `🔤 系统提示：` → notice 卡 |
| `recap` | 按需 `/recap` + **长对话闲置自动**：压平 User/Agent → 一句/小段回顾 | `📋 系统提示：` → notice 卡；**不写主会话模型历史** |

## 上下文与输入预算

- **设计前提**：辅助模型上下文 **≥ 256k**。
- **输入默认**：共用 `explainers.max_input_chars: 64000`（各 kind 可覆盖）。
- 截断策略：优先保留**尾部**（近轮对话 / 近证据）；见 `owner.explainers.common.clip_input`。
- 输出帽（已落地）：progress `max_tokens=400` / `max_output_chars=900`；approval `400` / `800`；english `450` / `1000`；recap `260` / `max_output_chars=350`（约二三百汉字）。**仅 `max_output_chars` 可经 yaml/registry 配置**；各 kind 的 `max_tokens` / `_MAX_TOKENS` **仍硬编码**（改码才动）。共享 `call_explainer_llm` 默认 `max_tokens=400`、`clean_output` 默认 1000。
- **告警前缀 = notice 匹配键**：如默认 `💡 [stream-guard]` 须与 `overlay.yaml` → `feishu_card.notice_titles` 以及 `owner/feishu/auto_card.py` 内置表字面一致；改前缀要三处同步，否则旁白/告警不会升格为 notice 卡。`💡 [output-guard]` 有用户可见串，但**不在** `notice_titles`（多半内嵌正文末尾，不单独发卡）。

## 配置（`owner/config/overlay.yaml` → `~/.hermes/overlay.yaml`）

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
    max_output_chars: 350
    platforms: { feishu: true }
```

取模优先级：**kind provider/model → 共用 → `auxiliary.<task>` → 主模型**。  
`call_llm(task=)` 长名：`progress_explainer` / `approval_explainer` / `english_explainer` / `recap_explainer`。

三级启用：`chats.<platform>.<chat_id>` → `platforms.<platform>` → `enabled`。

## `/recap`

- 注册：`owner/owner-extensions` → `register_command("recap", …)`
- 路径：`SessionDB` 读当前 `session_id` transcript → `flatten_messages` → `call_explainer_llm("recap", …)` → `📋 系统提示：…`
- 飞书：`feishu_card.notice_titles` 已含该前缀 → auto-card notice。
- 成功后写入 watermark（`~/.hermes/owner/recap_watermarks/<session_id>`），避免紧接着再自动发一次。

## 长对话结束自动 recap（对齐 Grok Build）

权威来源：本机 Grok Build 1.0.62 二进制 + 上游
`crates/codegen/xai-grok-shell/src/session/helpers/session_recap.rs`：

| 常量 | 值 | 含义 |
|---|---|---|
| `MIN_TURNS_FOR_AUTO_RECAP` | **3** | 至少 3 个真实用户主回合才自动 |
| `RECAP_MIN_IDLE` | **180s**（`3 * 60`） | 闲置阈值；shell 从上次模型请求计，daemon 从回合结束计 |
| watermark 文件 | `last_recap_main_turn` | 成功（或超长抑制展示）后写入；无新主回合不重复自动 |

门控失败原因（与上游字符串一致）：`no main turns yet` / `fewer than min turns for auto recap` / `idle threshold not met` / `no new main turn since last recap`。

**Hermes 适配（飞书无 TUI 焦点）**：把「从闲置回来」映射为「一轮正常结束后安静 `idle_seconds`」——

1. hook `on_session_end`（每轮完成）→ 调度 Timer；
2. `pre_gateway_dispatch` / `agent_loop_stopped` → 取消（用户又开口或打断）；
3. Timer 到期 → 同 `/recap` 生成 + notice 发送 → 写 watermark。

配置（`overlay.yaml`）::

```yaml
explainers:
  recap:
    enabled: true
    auto:
      enabled: true
      min_user_turns: 3   # = Grok MIN_TURNS_FOR_AUTO_RECAP
      idle_seconds: 180   # = Grok RECAP_MIN_IDLE
```

短会话（<3 用户回合）不触发；同一段落内不重复自动。手动 `/recap` 仍即时可用且会抬高 watermark。
- 失败 fail-open（返回短状态文案，不抛）。

## 扩展更多 kind

```python
from owner.explainers.registry import register_kind
register_kind("summary", defaults={"enabled": False, "platforms": {}})
# call_explainer_llm("summary", messages)
```

并在 `overlay.yaml` 加 `explainers.summary: { enabled: true, ... }`，包放 `owner/explainers/summary/`。新 kind 自动继承共用 `max_input_chars`（默认 64k）。

## 模块

- 共享：`owner/explainers/{common,config,llm,registry,__init__}.py`
- kind：`owner/explainers/{progress,approval,english,recap}/`
- 胶水：`gateway/run_turn.py`（progress）、`plugins/platforms/feishu/adapter.py`（approval 嵌卡）、`owner/owner-extensions/__init__.py`（progress/english hooks + `/recap`）

## 兼容

- 仍指向旧树、顶层 `progress_explainer:` 等活键时，加载器会合成统一块（过渡期）。
- 规范约定软链应指向本 worktree 的 `owner/config/overlay.yaml`（v2 扁平、无 `owner:` 外壳）。

## 验证

```bash
cd ~/.hermes/hermes-agent-v2
PYTHONPATH=. python -m pytest tests/owner/test_c13_explainers.py -q
```
