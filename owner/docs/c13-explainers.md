# C13 · 统一 explainers（progress / approval / english / recap）

状态：**已落地**（含第四 kind `recap`；正文落盘审计已实现；分支 `v2` 已双推 `origin`/`gitlab`）

## 做什么

旁白共用一套基建，避免各自配 auxiliary / 各自加载器：

| kind | 行为 | 投递 |
|------|------|------|
| `progress` | 沉默期进度旁白（飞书 notice 蓝标题 **「🧭 当前进度」**，原「进度旁白」）；`stream_guard.snapshot.tripped` 时让位 | `🧭 系统提示：` → notice 卡（`template=blue`） |
| `approval` | 审批卡发出前 2–3 句事实解说；**绝不建议批/拒**；fail-open | 嵌进飞书审批卡正文；**批准/拒绝冻结卡仍保留该附录**（`body_text` 经 `_approval_state`） |
| `english` | `display.language=zh` 且终局整段英文 → 侧路中文解说；**不改原文** | `🔤 系统提示：` → notice 卡 |
| `recap` | 按需 `/recap` + **长对话闲置自动**：压平 User/Agent → **进度条文案**（做到哪了/完成度/下一步；勿列文件清单） | `📋 系统提示：` → notice 卡（标题色 `template=orange`）；**正文落 `messages`（`role=notice`）作审计，不入主会话模型历史**；watermark 只管自动门控 |

## 上下文与输入预算

- **设计前提**：辅助模型上下文 **≥ 256k**。
- **输入默认**：共用 `explainers.max_input_chars: 64000`（各 kind 可覆盖）。
- 截断策略：优先保留**尾部**（近轮对话 / 近证据）；见 `owner.explainers.common.clip_input`。
- 输出帽（已落地）：progress `max_tokens=400` / `max_output_chars=900`；approval `400` / `800`；english `450` / `1000`；recap `260` / `max_output_chars=350`（硬截断 +「…」；提示词要求 ≤220 汉字的进度文案，避免半句被砍）。**仅 `max_output_chars` 可经 yaml/registry 配置**；各 kind 的 `max_tokens` / `_MAX_TOKENS` **仍硬编码**（改码才动）。共享 `call_explainer_llm` 默认 `max_tokens=400`、`clean_output` 默认 1000。
- **recap / progress / english 落盘（2026-11-05）**：send 成功后写入 `messages`（`role=notice`，`display_kind`=kind）；渠道记 `owner_provider_name` + `display_metadata`；送模 / 导出 / TUI 一律排除 notice。helper `owner/explainers/persist.py`（`persist_notice`，fail-open）；trigger：recap `manual`/`auto`、progress `tick`、english `reply`。设计稿 `design/explainer-notice-persist/`。watermark 仍只管 recap 门控。
- **recap 文案取向（2026-11-05）**：进度/完成度/下一步；禁止文件名、表 id、测试条数等变更清单式罗列；硬帽仍 350。
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
- 飞书：`feishu_card.notice_titles` 已含该前缀 → auto-card notice；标题色 `template=orange`（橘黄；`yellow` 偏浅黄），改色只动 `owner/feishu/auto_card.py` 的 `_DEFAULT_NOTICE_RULES`。
- 成功后写入 watermark（`~/.hermes/owner/recap_watermarks/<session_id>`），避免紧接着再自动发一次。

## 长对话结束自动 recap（对齐 Grok Build）

权威来源：本机 Grok Build 1.0.62 二进制 + 上游
`crates/codegen/xai-grok-shell/src/session/helpers/session_recap.rs`：

| 常量 | 值 | 含义 |
|---|---|---|
| `MIN_TURNS_FOR_AUTO_RECAP` | **3** | 至少 3 个真实用户主回合才自动（turns 路径） |
| `RECAP_MIN_IDLE` | **180s**（`3 * 60`） | 闲置阈值；shell 从上次模型请求计，daemon 从回合结束计 |
| `MIN_ASSISTANT_CHARS_FOR_AUTO_RECAP` | **800**（owner OR） | 末条可见 assistant 回复字数 ≥ 此值也可自动；`0` 关闭 |
| watermark 文件 | `last_recap_main_turn` | 成功（或超长抑制展示）后写入；无新主回合不重复自动 |

门控失败原因（turns 路径与上游字符串一致）：`no main turns yet` / `fewer than min turns for auto recap` / `idle threshold not met` / `no new main turn since last recap`。字数 OR 未达标时复用 turns-short 原因串。

**Hermes 适配（飞书无 TUI 焦点）**：把「从闲置回来」映射为「一轮正常结束后安静 `idle_seconds`」——

1. hook `on_session_end`（每轮完成）→ 调度 Timer；
2. `pre_gateway_dispatch` / `agent_loop_stopped` → 取消（用户又开口或打断）；
3. Timer 到期 → 同 `/recap` 生成 + notice 发送 → 写 watermark。

路由：`pre_gateway_dispatch` 从 **`event.source`**（官方 hook 不传顶层 platform/chat_id）写 `_SESSION_ROUTES`；缺 session_id 时 `on_session_end` 经 `session_store.lookup_by_session_id`（gateway routing）回补 chat_id。

配置（`overlay.yaml`）::

```yaml
explainers:
  recap:
    enabled: true
    auto:
      enabled: true
      min_user_turns: 3      # = Grok MIN_TURNS_FOR_AUTO_RECAP
      idle_seconds: 180      # = Grok RECAP_MIN_IDLE
      min_assistant_chars: 800  # owner OR；0=关闭
```

触发条件（idle 到期后）：有新主回合，且 **turns≥3 或 末条助手可见字数≥800**。短短答仍不触发；同一段落内不重复自动。手动 `/recap` 仍即时可用且会抬高 watermark。
- 失败 fail-open（返回短状态文案，不抛）。

## 扩展更多 kind

```python
from owner.explainers.registry import register_kind
register_kind("summary", defaults={"enabled": False, "platforms": {}})
# call_explainer_llm("summary", messages)
```

并在 `overlay.yaml` 加 `explainers.summary: { enabled: true, ... }`，包放 `owner/explainers/summary/`。新 kind 自动继承共用 `max_input_chars`（默认 64k）。

## 模块

- 共享：`owner/explainers/{common,config,llm,registry,persist,__init__}.py`（`persist.py` = notice 落盘 helper）
- kind：`owner/explainers/{progress,approval,english,recap}/`
- 胶水：`gateway/run_turn.py`（progress）、`plugins/platforms/feishu/adapter.py`（approval 嵌卡）、`owner/owner-extensions/__init__.py`（progress/english hooks + `/recap`）

## 兼容

- 仍指向旧树、顶层 `progress_explainer:` 等活键时，加载器会合成统一块（过渡期）。
- 规范约定软链应指向本 worktree 的 `owner/config/overlay.yaml`（v2 扁平、无 `owner:` 外壳）。

## 验证

```bash
cd ~/.hermes/hermes-agent          # 分支 v2
PYTHONPATH=. python -m pytest tests/owner/test_c13_explainers.py tests/owner/test_c13_notice_persist.py tests/owner/test_c11_auto_card.py -q
```

## 旁白中文门（输出语言）

共享入口 `owner/explainers/llm.py::call_explainer_llm` 在期望简体中文时：

1. 生成后用 `owner/explainers/english/detect.looks_like_non_chinese_output` 校验（内部先走 `looks_like_english_reply`，短旁白另有 latin-heavy 回落）。
2. 命中非中文 → 追加 assistant 原文 + 用户纠偏 nudge，再生成 **1** 次（temperature 仍为 0，靠 nudge 而不是盲重抽）。
3. 仍非中文：日志 warning，**fail-open** 返回最后一次文本（与其它 explainer 软失败一致）。

适用范围：`english` / `recap` 默认强制中文旁白；`progress` / `approval` 跟随 `display.language`（可用 kind cfg `require_chinese` 覆盖）。**不**改写 english explainer 的英文源正文。

## progress fact_line（旁白正文下一行）

- 尾缀经官方 `format_iteration_progress`（`display.iteration_progress.*`，随 `display.language`；zh=`第 {n}/{max} 轮迭代`）。
- 有 `current_tool` 时前缀走 `format_running_tool`（复用官方 `display.verb.*` / `get_tool_verb`，与 `display.friendly_tool_labels` 同源；zh 如 terminal→`正在运行命令`；未知工具回退 `gateway.busy.running_tool`）；无工具时前缀走活动戳对照表（精确 + 正则模板；裸 tool id 亦映射 verb；未命中 fail-open 原文；en UI 透传句子、仍映射裸 tool id）。
- `_hard_facts.iteration` / `max_iterations` 为数值对，供 prompt「迭代 N/M」展示。

