# OpenViking 同步召回可视化卡片 — 实施设计文档

> 目标：在保留 provider 内 LLM 注入（`## OpenViking Context`）的前提下，给 OpenViking 同步召回增加用户可见反馈。  
> 约束：官方源码零改动；不复用 qdrant hook 的展开/折叠按钮；平台互斥由用户手动控制；所有失败 fail-silent 不影响 LLM。  
> 配套 patch：`owner/patches/openviking_sync_recall_patch.py`（+76abc4ded，保存 raw hits 并挂载本 patch）。  
> 实施时间戳：2026-06-20

---

## 1. 选型：运行时 post-registration patch

沿用 sync recall patch 的思路：在 `OpenVikingMemoryProvider` 已经加载到内存后，运行时替换 `initialize` / `prefetch` 两个方法。

- `initialize` 被包装为保存会话上下文（platform / chat_id / chat_type / user_id 等）。
- `prefetch` 被包装为在同步搜索返回后，把命中的 hits 异步发送为可视化卡片/文字。
- LLM 注入路径（`## OpenViking Context` markdown）完全保留在 provider 内部，不受本 patch 影响。

---

## 2. `owner/` 文件结构

```
owner/
├── patches/
│   ├── openviking_sync_recall_patch.py   # 同步 recall + advisory 提示词
│   └── openviking_recall_card_patch.py   # 可视化召回卡片（本 patch）
└── docs/
    ├── openviking-sync-recall-design.md  # 同步 recall 设计文档
    └── openviking-recall-card-design.md  # 本设计文档
```

- `owner/patches/openviking_recall_card_patch.py`
  - `build_viking_recall_card(hits, elapsed_ms)`：生成 Feishu interactive card schema 2.0（compact，无按钮）。
  - `build_viking_recall_text(hits, elapsed_ms)`：生成 markdown 纯文字摘要，长度截断到 3800 字符。
  - `_send_feishu_card_sync(...)` / `_send_qqbot_text_sync(...)`：独立 REST 发送，模块级 token 缓存。
  - `_fire_recall_display(...)`：平台分流 + feature flag 判断 + 启动 daemon thread。
  - `_wrap_initialize(...)` / `_wrap_sync_prefetch(...)`：运行时包装方法。
  - `apply_patch()` / `revert_patch()`：独立 patch 状态与还原。

- `tests/owner/patches/test_openviking_recall_card_patch.py`：覆盖卡片/文字 builder、平台路由、失败兜底、patch 还原。

---

## 3. Feature flag 与环境变量

| 环境变量 | 默认值 | 作用 |
|---|---|---|
| `OPENVIKING_RECALL_DISPLAY` | `1` | 总开关：是否发送可视化召回 |
| `OPENVIKING_RECALL_FEISHU_CARD` | `1` | Feishu 卡片分支 |
| `OPENVIKING_RECALL_QQBOT_TEXT` | `1` | QQ Bot 文字分支 |

回滚方式：

```bash
export OPENVIKING_RECALL_DISPLAY=0
# 或单独关闭某平台
export OPENVIKING_RECALL_FEISHU_CARD=0
export OPENVIKING_RECALL_QQBOT_TEXT=0
```

运行时也可调用 `owner.patches.openviking_recall_card_patch.revert_patch()` 秒级还原。

---

## 4. 数据流

```
用户消息
   │
   ▼
OpenVikingMemoryProvider.prefetch(query)  ←─ 已被 sync patch 替换为同步搜索
   │
   ├─→ 返回 markdown 注入 LLM（`## OpenViking Context`）
   │
   ├─→ 同时保存 raw hits 到 self._recall_card_hits
   │
   ▼
wrapped prefetch 读取 _recall_card_hits + _recall_card_ctx
   │
   ▼
_fire_recall_display(platform, hits, elapsed_ms)
   │
   ├─ platform == feishu → build card → daemon thread → Feishu REST
   ├─ platform == qqbot  → build text → daemon thread → QQ REST
   └─ 其他平台 → no-op
```

卡片/文字在 LLM 回复之前触发，因此用户会先看到「召回到了什么」，再看到模型基于这些上下文组织的答案。

---

## 5. Feishu 卡片 schema

采用 schema 2.0 compact 风格：

- 蓝色 header：标题「🧠 知识库召回」。
- body 首行：命中条数、最高 score、类型数、搜索耗时。
- 分隔线后：每条 hit 一行，包含 `type`（memory/resource）、score、截断后的 abstract。
- **无展开/折叠按钮**，避免与 qdrant hook 的卡片按钮机制纠缠。

发送方式：通过 `open.feishu.cn/open-apis/im/v1/messages` REST API，绕开 WebSocket，不抢 adapter token。

---

## 6. QQ 文字 fallback

QQ Bot 走 `msg_type=0` 纯文本：

- 第一行：标题 + 命中条数 + 最高 score + 耗时。
- 后续：每条 hit 一行 markdown 列表项。
- 总长度截断到 3800 字符，避免触发 QQ 消息长度限制。
- body 中**不带 `msg_seq`**，避免与 adapter 内部的 seq 状态冲突。

---

## 7. Token 缓存

模块级 `_TOKEN_CACHE: Dict[str, tuple[str, float]]`：

- Feishu：`tenant_access_token`，有效期 2 小时（`expire` 字段）。
- QQ：`access_token`，有效期 2 小时（`expires_in` 字段）。
- 提前 60 秒刷新，避免在 token 过期临界点请求失败。
- 缓存 key 包含 app_id 与 url，多个应用互不干扰。

---

## 8. 异常与降级

- 发送失败完全隔离，不影响 LLM 调用与主线程。
- 所有发送路径 try/except 兜底，只记录 warning log。
- token 获取失败时返回 `False`，调用方不抛异常。
- 无命中（hits 为空）时不发任何消息，避免无意义占位。
- 无 `chat_id` 时直接 return，不打 log。

---

## 9. 与 qdrant hook 的共存

本 patch 不实现与 `qdrant_memory_recall` 的自动互斥。若两者同时开启，用户可能在同一 turn 看到两张召回卡片。是否共存由用户在配置中手动控制。

---

## 10. 测试

`tests/owner/patches/test_openviking_recall_card_patch.py` 覆盖：

- `test_build_viking_recall_card`：hits → Feishu 2.0 schema；无 hits → `None`。
- `test_build_viking_recall_text`：hits → markdown 文本；超长时截断。
- `test_fire_recall_display_platform_routing`：`feishu` / `qqbot` / `cli` 平台分发。
- `test_initialize_ctx_saved`：patch 后 `provider.initialize` 保存 ctx。
- `test_sync_prefetch_triggers_card`：patch 后 prefetch 命中时触发后台发送（mock thread）。
- `test_env_flags_disabled`：开关关闭时 thread 不启动。
- `test_feishu_send_auth_failure`：token 获取失败不抛异常。
- `test_qq_send_auth_failure`：token 获取失败不抛异常。
- `test_revert_patch`：revert 后 provider 方法恢复。

---

## 11. 相关改动

- `owner/patches/openviking_sync_recall_patch.py`：
  - `_sync_prefetch` 内增加 5 行保存 raw hits 到 `self._recall_card_hits`。
  - `apply_patch()` 末尾增加 card patch 挂载（best-effort，fail-silent）。

---

## 12. Definition of Done

- [x] `owner/docs/openviking-recall-card-design.md` 已归档。
- [x] `owner/patches/openviking_recall_card_patch.py` 已实现并通过静态检查。
- [x] `tests/owner/patches/test_openviking_recall_card_patch.py` 覆盖 builder、路由、失败兜底、patch 还原。
- [x] `pytest tests/owner/patches/test_openviking_recall_card_patch.py -v` 通过。
- [x] 不破坏 `pytest tests/owner/patches/test_openviking_sync_recall_patch.py -v`。
- [x] 在 `v16改动清单.md` §11.6 追加 commit 与补充说明。
