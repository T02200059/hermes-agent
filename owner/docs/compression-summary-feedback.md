# 上下文压缩摘要反馈

> 遵循 `owner/docs/二次开发规范.md` 的最小侵入原则。

## 目标

在上下文压缩完成后，向用户发送一条简短的中文状态摘要（平台无关 fallback），并在飞书等支持交互卡片的平台上渲染为普通卡片。

## 数据流

```text
ContextCompressor.compress()
  │
  ▼
[owner] set_last_summary(id(compressor), raw_summary)
  │
  ▼
conversation_compression.compress_context()
  │
  ▼
[owner] emit_compression_summary(agent, before, after, before_tokens, after_tokens)
  │
  ▼
agent._emit_status(text)  ──▶  gateway/platforms/feishu.py::send()
                                  │
                                  ▼
                          [owner] send_compression_summary() (薄委托)
                                  │
                                  ▼
                          owner/feishu/compression_summary_card.py
                                  │
                                  ▼
                          Feishu interactive card (plain, no fold)
```

## 文件职责

| 文件 | 职责 | 是否官方源码 |
|------|------|--------------|
| `owner/compression_summary_feedback.py` | 解析结构化 summary、生成中文摘要、存储/读取每个 compressor 实例的 summary、提供 `emit_compression_summary()` | owner |
| `owner/feishu/compression_summary_card.py` | 构建非折叠 Schema 2.0 卡片；提供 `try_send_compression_summary()` 完成前缀检测与发送 | owner |
| `agent/context_compressor.py` | 仅新增 `[owner]` 标记的一行胶水：summary 生成后调用 `set_last_summary(id(self), summary)` | 官方（最小改动） |
| `agent/conversation_compression.py` | 仅新增 `[owner]` 标记的 3 行胶水：压缩完成后调用 `emit_compression_summary(...)` | 官方（最小改动） |
| `gateway/platforms/feishu.py` | 仅保留 `[owner]` 标记的薄委托 `send_compression_summary()` | 官方（最小改动） |

## 设计决策

1. **状态外置**：`ContextCompressor` 不保存 `_last_summary_for_display`。owner 模块通过 `id(compressor)` 作为 key 维护外部字典，避免修改上游类定义。
2. **平台无关 fallback**：`emit_compression_summary()` 只调用 `agent._emit_status()` 发送文本。飞书 adapter 在 `send()` 中检测文本前缀并转换为卡片。
3. **不折叠卡片**：摘要文本本身已很简短，使用普通卡片（header + markdown body）即可，避免 fold/expand 的交互复杂度。
4. **前缀匹配**：同时支持中文 `🗜️ 上下文已压缩` 和英文 `🗜️ Context compressed`，防止未来 locale 切换导致卡片路径静默失效。

## sync fork 注意事项

- `agent/context_compressor.py` 和 `agent/conversation_compression.py` 只有少量带 `[owner]` 标记的胶水行，sync 时优先保留官方改动，再重新应用 `[owner]` 胶水。
- 所有核心逻辑位于 `owner/` 下，不会与上游产生交叉修改。
- 删除 `owner/compression_summary_feedback.py`、`owner/feishu/compression_summary_card.py` 和本文档后，官方代码仍可正常运行（只是不再发送压缩摘要卡片）。
