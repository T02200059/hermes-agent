# explainer-notice-persist — recap / 进度旁白落盘到 messages

状态：**设计稿**（本轮不改生产代码、不迁库、不重启）  
关联：C13 explainers；清单占位见 `owner/docs/owner改动清单-todo.md` C13 条  
规范对照：`owner/docs/二次开发规范.md` §2.1 P0/P1、§2.2.2 设计目录

## 1. 目标

把 **recap 正文**与 **进度旁白（progress）**写入与对话同一张表 `messages`，要求：

| 要求 | 做法 |
|------|------|
| 同表、少字段 | **零 ALTER**：复用现有列；不新增表、不扩官方 SCHEMA 字面 |
| 标明种类 | `display_kind ∈ {recap, progress}`（跟 C13 kind / 仓库惯例；进度旁白 = `progress`） |
| 标明生成渠道 | 与主会话模型可不同：见 §3.2 |
| 不污染主上下文 | 新 `role=notice` + 读路径排除（§5） |
| watermark 关系 | 文件水位仍管「自动是否再发」；DB 行是正文审计（§6） |

**本轮范围**：仅 `recap` + `progress`。`english` / `approval` 同形可扩，**不在本轮必做**。

## 2. 现状（探查摘要）

- `state.db.messages` 已有：`role`、`content`、`display_kind`、`display_metadata`、`owner_provider_name`、`platform_message_id`、token 四列、`timestamp`、`active` 等。
- **无**通用 `metadata` 列；旁路 JSON 用 `display_metadata`。
- 现网 `display_kind` 已见：`steer` / `internal_notification` / `hidden` 等。
- `role` 现网：`user` / `assistant` / `tool` / `session_meta` / `system`。`role` 为自由 TEXT，**无 CHECK**，新枚举无需 DDL。
- C13 今日：生成后只飞书 `adapter.send`；**正文不落盘**；recap 仅 `~/.hermes/owner/recap_watermarks/<session_id>` 记用户回合数。
- 归因：当前 `_INSERT_MESSAGE_SQL` **只写** `owner_provider_name`（且 `_message_row_params` 仅在 `role=="assistant"` 时绑定）。live 库上的 `messages.model` / `messages.provider` 是**历史残留列**，近期 INSERT **不再写入**（近行多为 NULL）——**落盘渠道不要依赖这两列**。
- 模型上下文：`session_meta` 在 resume model_history 被显式丢掉；TUI `_HISTORY_ROLES={user,assistant,tool,system}`；recap `flatten_messages` 只认 user/assistant。

## 3. 选定方案（零 ALTER）

### 3.1 行形态

| 列 | 值 | 说明 |
|----|----|------|
| `session_id` | 当前会话 tip id | 与对话同行 |
| `role` | **`notice`** | 新枚举；不进 `_HISTORY_ROLES`；flatten 自然跳过 |
| `display_kind` | **`recap`** 或 **`progress`** | 种类主键；查询：`WHERE role='notice' AND display_kind=?` |
| `content` | **投递正文（含 PREFIX）** | 与飞书 notice 一致：`📋 系统提示：…` / `🧭 系统提示：…`；审计「用户看到了什么」 |
| `timestamp` | 发送成功时刻 | `time.time()` |
| `active` | `1` | 可查；不参与 compaction 摘要对象（见 §5） |
| `platform_message_id` | 飞书 `message_id`（有则写） | 已有列；progress 已从 `send` 结果取过 |
| `owner_provider_name` | 解析后的渠道 slug（尽力） | 见 §3.2；若标准 `append_message` 因 role≠assistant 写 NULL，则 owner 写入后 **UPDATE** 补齐，或走 owner 专用 INSERT 助手 |
| `display_metadata` | JSON（§3.3） | 种类冗余、trigger、resolved model、task 名等 |
| 其余 | NULL / 默认 | 不碰 tool_* / reasoning_* |

**不采用**：

- 新表 / 新列（违背「同表、少字段」与规范「勿改官方 SCHEMA 字面」）。
- `role=assistant` + 仅靠 `display_kind`：`display_kind` 出站会剥掉，但 **content 仍进模型**，污染主上下文。
- 复用 `session_meta`：语义是会话书签/空壳，导出与 display 一律跳过，且不宜塞长正文。
- 依赖 live 残留列 `messages.model`/`provider` 作为唯一渠道来源。

### 3.2 模型渠道（可与主模型不同）

C13 取模链：`explainers.<kind>.provider|model` → 共用 `explainers.*` → `auxiliary.<kind>_explainer` → 主模型。

落盘时记 **实际用于生成的渠道**，优先顺序：

1. `call_llm(..., route_info={})` 回填的 resolved provider/model（若调用点能拿到）；
2. 否则 `resolve_explainer_call(kind)` 的配置意图值（可能仍是 `auto`/空 → 记 `null` + `task`）；
3. `display_metadata.task` 固定为 `recap_explainer` / `progress_explainer`。

持久化位置：

| 位置 | 字段 | 用途 |
|------|------|------|
| 列 `owner_provider_name` | 渠道 slug（如 `damodel`） | 与 C02 归因列对齐，便于 SQL `GROUP BY` |
| `display_metadata.provider` | 同上或更细 | 冗余备份；role≠assistant 时仍可读 |
| `display_metadata.model` | 具体模型 id | **主存放处**（表列不可靠） |
| `display_metadata.task` | `*_explainer` | 辅助任务名 |

### 3.3 `display_metadata` 约定

```json
{
  "explainer_kind": "recap",
  "trigger": "manual",
  "provider": "damodel",
  "model": "deepseek-v4-flash",
  "task": "recap_explainer",
  "user_turns": 12,
  "digest_hash": null
}
```

| 键 | 适用 | 说明 |
|----|------|------|
| `explainer_kind` | 两者 | 与 `display_kind` 同值（冗余，防 display_kind 被 UI 改写时仍可辨） |
| `trigger` | recap: `manual`\|`auto`；progress: `tick` | |
| `provider` / `model` / `task` | 两者 | 见 §3.2 |
| `user_turns` | recap | 写入时的主用户回合数（与 watermark 同口径） |
| `digest_hash` | progress | 可选；与 dispatcher 去重同源 |

`platform_message_id` 列优先；若 adapter 只把 id 放在别处，可再镜像 `display_metadata.feishu_message_id`（P1）。

### 3.4 示例行

**手动 /recap：**

```
role=notice
display_kind=recap
content=📋 系统提示：已把周报「解读要点」做成混合方案……下一步接剩余表与回归。
owner_provider_name=damodel
platform_message_id=om_xxx
display_metadata={"explainer_kind":"recap","trigger":"manual","provider":"damodel","model":"xy-pro","task":"recap_explainer","user_turns":17}
```

**沉默期进度旁白：**

```
role=notice
display_kind=progress
content=🧭 系统提示：正在跑契约测试，表注入校验还没完。
owner_provider_name=damodel
display_metadata={"explainer_kind":"progress","trigger":"tick","provider":"damodel","model":"deepseek-flash","task":"progress_explainer","digest_hash":"…"}
```

查询：

```sql
SELECT timestamp, display_kind, owner_provider_name,
       json_extract(display_metadata,'$.model') AS model,
       content
FROM messages
WHERE session_id = ? AND role = 'notice' AND display_kind IN ('recap','progress')
ORDER BY id;
```

## 4. 写入点（实现落点 · 下轮）

全部 **owner/**，官方 SCHEMA 字面不动。

| 步骤 | 位置 | 行为 |
|------|------|------|
| 共享 helper | 新 `owner/explainers/persist.py`（名可微调） | `persist_notice(session_id, kind, body, *, provider, model, task, trigger, platform_message_id, extra_meta) -> row_id\|None`；fail-open；永不抛穿旁白路径 |
| recap 手动 | `owner/explainers/recap/command.py` | 生成成功且将返回 body **之后**、watermark 前后均可；建议 **send/返回成功口径** 与 auto 一致后再写 |
| recap 自动 | `owner/explainers/recap/auto.py` `_send_notice` 成功后 | 与 `save_recap_watermark` 同成功闸；先发后写或写失败只打 debug |
| progress | `owner/explainers/progress/dispatcher.py` 在 `adapter.send` success 后 | 已有 `message_id`；`cleanup_progress` 若删飞书消息，**DB 行默认保留**（审计）；若需联删列为 P2 |
| 取模 | `call_explainer_llm` / 调用方 | 尽量把 resolved route 传进 persist（可扩返回值或 out-param；保持「失败仍 None」契约） |

写入 API 偏好：

1. `SessionDB.append_message(session_id, role="notice", content=..., display_kind=..., display_metadata=..., platform_message_id=...)`；
2. 若 `owner_provider_name` 因 role 门被置 NULL → helper 内短 `UPDATE messages SET owner_provider_name=? WHERE id=?`（owner 侧，不改官方 `_message_row_params` 字面；若必须改门控，标 `# [owner]` 并登清单——优先 UPDATE 以免碰官方）。

**P0**：helper + recap manual/auto + progress send 成功钩。  
**P1**：`route_info` 实渠道路；english 同形；导出会话可选渲染 notice。  
**P2**：progress 飞书 cleanup 联删 DB；FTS 噪音（notice 进 messages_fts）若烦可再滤。

## 5. 读出 / 不注入主上下文

| 路径 | 策略 |
|------|------|
| 主模型请求 | `role=notice` ∉ 常规对话角色；实现时在 **model restore**（`get_messages_as_conversation` / resume `model_history`）加 `role != 'notice'`（与 `session_meta` 同级）。若只改 owner 薄补丁：runtime patch 过滤函数，或确认现有 sanitize 丢弃未知 role 后补测。**必须有单测：notice 行不得出现在送模 messages。** |
| recap flatten | 已只认 user/assistant → 自然忽略 notice（防「回顾里套回顾」） |
| TUI / `_HISTORY_ROLES` | 默认不展示；需要「会话内回顾列表」时再按 `display_kind` 特制表面 |
| FTS 搜索 | 触发器会索引 content；可接受。若要排除：P2 搜条件加 `role != 'notice'` |
| compaction | notice 不应充当 user turn；compressor 已跳过多数 `display_kind` user 行——补测 notice 不被当成用户意图 |

## 6. 与 watermark 关系

| 机制 | 职责 |
|------|------|
| `owner/recap_watermarks/<sid>` | **门控**：`last_recap_main_turn`；无新用户主回合不自动再发 |
| `messages` notice 行 | **正文审计**：可查历史 recap/旁白全文与渠道 |

成功路径建议顺序：`生成 → 发送成功 → persist_notice → save_recap_watermark`（auto）；手动 `/recap`：`生成 → （网关投递）→ persist → note_manual_recap`。  
persist 失败 **不**回滚 watermark（避免刷屏）；watermark 失败不删已写 notice。

## 7. 风险

| 风险 | 缓解 |
|------|------|
| notice 误入主上下文 | 单测 + model_history 显式过滤；禁止用 assistant role |
| `owner_provider_name` 写不进 | UPDATE 补列或 metadata 双写 model/provider |
| 官方以后占用 `role=notice` | 低概率；若冲突改 `explainer_notice` 并迁移 display_kind 查询 |
| FTS / 导出噪音 | 默认接受；导出过滤 P1 |
| progress 频繁写放大 DB | 已有 silence/digest 门；行短（≤900 字级） |
| 与 tip `c3da56ebf1` 文案改动 | 正交；落盘存最终投递串即可 |

## 8. 非目标

- 不改 recap 提示词 / 350 硬帽（已在 tip `c3da56ebf1`）。
- 不迁 watermark 进 DB（文件方案与 Grok Build 对齐，继续保留）。
- 本轮不实现、不迁库、不重启 gateway。
- 不强制 english/approval 落盘。

## 9. 待拍板（开放点）

1. **会话导出 / TUI 是否展示 `role=notice` 行？** 设计默认：**否**（仅 SQL / 后续专用查询；飞书侧用户已看过）。若要「在桌面历史里重看回顾」，再加 display 投影例外。
2. **`english` 旁白是否同一 helper 一并落盘？** 默认本轮不做；接口可预留 `display_kind=english`。

## 10. 验收（实现轮）

- [ ] 手动 `/recap` 成功后 `messages` 有 `role=notice, display_kind=recap` 且 content 含 PREFIX
- [ ] auto recap 发送成功后同上，`trigger=auto`，watermark 仍更新
- [ ] progress send 成功后有 `display_kind=progress`
- [ ] `display_metadata.model`（或等价）可区分于会话主模型
- [ ] 送模 transcript / flatten **不含** notice
- [ ] 无 DDL；官方 `hermes_state_common` CREATE 字面无改（除非仅清单登记的必要薄门控）
