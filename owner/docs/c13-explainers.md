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
- **recap 超预算混合兜底（2026-11-17）**：仅当可见 User/Agent 正文超过当前 `max_input_chars`（默认 64k）、即将/已经尾部截断时启用。prompt 带上同一 compression 链最近一条 `display_kind=recap` 作为被省略前半段的说明，再加上截断后的近期原文；找不到旧回顾则仍走纯尾部截断。不沿 session_reset 链，不用 watermark 正文，进度卡不算回顾。flatten 仍跳过 notice，避免回顾套回顾。超预算路径上每 3 次混合后做 1 次不依赖旧回顾的纯尾部校准。不到预算时行为不变。自动回顾的 180 秒闲置与触发门槛不改。设计稿 `design/recap-hybrid-fallback/hybrid.md`；测 `tests/owner/test_c13_recap_hybrid.py`。
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
    pause_while_awaiting_user: true   # clarify/审批等待期不旁白
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

## 长对话自动 recap（长耗时或长结束消息）

自动回顾只覆盖「本轮 agent turn 时间过长」或「end 消息过长」，**不是**等待用户下一条输入。回合结束后不再空等。

| 门槛 | 默认 | 含义 |
|---|---|---|
| `min_turn_seconds` | **180** | 本轮耗时：触发本轮的那条用户消息时间 → `on_session_end`。`0` 关闭耗时路径 |
| `min_assistant_chars` | **800** | 末条可见 assistant 回复字数 ≥ 此值也可自动；`0` 关闭 |
| watermark 文件 | `last_recap_main_turn` | 成功后写入；无新主回合不重复自动 |

门控失败原因：`no main turns yet` / `no new main turn since last recap` / `turn duration and end message below auto recap thresholds`。拿不到可靠本轮起点时跳过耗时路径（打日志），只走「消息过长」这条 OR，不会再空等 180 秒充数。

流程：

1. `pre_gateway_dispatch` 记住本轮用户消息到达时间，并缓存路由（从 **`event.source`** 读 platform/chat_id；官方 hook 不传顶层字段）。
2. hook `on_session_end`（正常完成的一轮）立刻判定并生成，同 `/recap` notice，写 watermark。不再调度结束后的 Timer。
3. 被打断 / 失败 / `completed=False` 的回合跳过。`agent_loop_stopped` 可能先于 `on_session_end` 到达，会留下标记；仅在结束标志含糊时据此跳过，并在本次结束时清掉，以免污染下一轮。

缺 session_id 时 `on_session_end` 经 `session_store.lookup_by_session_id`（gateway routing）回补 chat_id。

配置（`overlay.yaml`）::

```yaml
explainers:
  recap:
    enabled: true
    auto:
      enabled: true
      min_turn_seconds: 180     # 本轮耗时门槛；0=关闭耗时路径
      # idle_seconds: 180       # 旧键，仅作 min_turn_seconds 的回退，不再表示「结束后空等」
      min_assistant_chars: 800  # 结束消息过长；0=关闭
```

现网若只配了旧键 `idle_seconds: 180`，会被读成耗时门槛，不必改 overlay。`min_user_turns` 仍可解析，但**不再**单独触发自动回顾。

触发条件（回合结束立刻判断）：有新主回合，且 **本轮耗时≥180 秒或末条助手可见字数≥800**。短耗时且短结束消息不自动出卡。手动 `/recap` 仍即时可用，不走这两个自动门槛，成功后会抬高 watermark。
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
PYTHONPATH=. python -m pytest tests/owner/test_c13_explainers.py tests/owner/test_c13_notice_persist.py tests/owner/test_c13_recap_auto.py tests/owner/test_c11_auto_card.py -q
```

## 旁白中文门（输出语言）

共享入口 `owner/explainers/llm.py::call_explainer_llm` 在期望简体中文时：

1. 生成后用 `owner/explainers/english/detect.looks_like_non_chinese_output` 校验（内部先走 `looks_like_english_reply`，短旁白另有 latin-heavy 回落）。
2. 命中非中文 → 追加 assistant 原文 + 用户纠偏 nudge，再生成 **1** 次（temperature 仍为 0，靠 nudge 而不是盲重抽）。
3. 仍非中文：日志 warning，**fail-open** 返回最后一次文本（与其它 explainer 软失败一致）。

适用范围：`english` / `recap` 默认强制中文旁白；`progress` / `approval` 跟随 `display.language`（可用 kind cfg `require_chinese` 覆盖）。**不**改写 english explainer 的英文源正文。

## progress 用户输入门（clarify / approval）等待期不旁白

`clarify` 与审批卡都会让 agent 线程阻塞在「等用户回答」上：turn 没结束、executor 没 done，但也没有工具完成事件和流增量。这正是沉默期旁白的触发条件——若不处理，提问卡发出约 60s 后就开始出「🧭 当前进度」，每 `min_interval_seconds` 一条、最多 `max_per_turn` 条（默认 120s / 5 条），底栏还会因为 `current_tool=clarify` 显示「正在提问 — 第 N/M 轮迭代」：用户在思考怎么回答，bot 在旁边反复催促。默认 `clarify_timeout=3600`，一次提问足以把整轮配额刷满。

判定不看进度事件，直接查两个模块级注册表（`dispatcher.user_gate_pending`）：

| 门 | 探针 | 返回 |
|---|---|---|
| 提问 | `tools.clarify_gateway.has_pending(session_key)` | `clarify` |
| 审批 | `tools.approval.has_blocking_approval(session_key)` | `approval` |

用注册表而非事件回放，是因为 `mute_notification_reply` 会把 `tool_progress_callback` 置 `None`，包装器随之失效、`tool.started/completed` 不再进 tracker；而注册表始终如实反映「agent 线程正卡在一个等回答的门上」。探针是两次字典查询，可每 tick 调用，失败 fail-open。

行为：

- 等待期间 tick 整段跳过——不发旁白，**也不消耗** `max_per_turn`（早退在计数之前）。
- 静默计时冻结（`tracker.note_awaiting_user(True)`），避免等 10 分钟后把 `silence` 累到 stall，用户一回答就补发一条「疑似停滞」。
- 门消失（用户点了按钮/回了文字/超时退出）时静默计时重新起算，所以「刚回答完立刻被插嘴」不会发生。
- 多问题 clarify 逐题发卡，中间间隙极短；门在间隙变空也只会重置计时，不会误发。
- `explainers.progress.pause_while_awaiting_user: false` 可关闭该行为（回到纯沉默期计时）。

## progress fact_line（旁白正文下一行）

- 尾缀经官方 `format_iteration_progress`（`display.iteration_progress.*`，随 `display.language`；zh=`第 {n}/{max} 轮迭代`）。
- 有 `current_tool` 时前缀走 `format_running_tool`（复用官方 `display.verb.*` / `get_tool_verb`，与 `display.friendly_tool_labels` 同源；zh 如 terminal→`正在运行命令`；未知工具回退 `gateway.busy.running_tool`）；无工具时前缀走活动戳对照表（精确 + 正则模板；裸 tool id 亦映射 verb；未命中 fail-open 原文；en UI 透传句子、仍映射裸 tool id）。
- `_hard_facts.iteration` / `max_iterations` 为数值对，供 prompt「迭代 N/M」展示。

