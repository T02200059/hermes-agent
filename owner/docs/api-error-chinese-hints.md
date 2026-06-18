# LLM API 错误中文提示

> 最后更新：2026-06-18

## 背景

Hermes 在 LLM API 请求失败（429/500/400 等）时，面向用户的报错文案全是英文硬编码。对于中文用户不够友好，因此增加按 HTTP 状态码 + FailoverReason 映射的中文提示。

## 设计原则

遵循 [`owner/docs/二次开发规范.md`](./二次开发规范.md)：

- **核心逻辑放在 `owner/`**：`owner/api_error_hints.py` 维护状态码到中文提示的映射。
- **官方源码最小改动**：`agent/conversation_loop.py` 只在最终用户输出点加 `# [owner]` 标记的薄胶水调用。
- **可移除性**：删除 `owner/api_error_hints.py` 及相关胶水调用后，官方功能完全不受影响。
- **语言感知**：仅在 `display.language` / `HERMES_LANGUAGE` 为中文时追加提示，英文环境保持原样。

## 文件改动

| 文件 | 类型 | 说明 |
|---|---|---|
| `owner/api_error_hints.py` | 新增 | 中文提示映射 + 语言判断 |
| `tests/owner/test_api_error_hints.py` | 新增 | 单元测试 |
| `agent/conversation_loop.py` | 修改 | 3 处终端输出点追加 `# [owner]` 胶水调用 |
| `owner/docs/api-error-chinese-hints.md` | 新增 | 本文档 |
| `owner/docs/原有改动清单.md` | 修改 | 登记本次定制 |

## 映射表

| HTTP 状态 / FailoverReason | 中文提示 |
|---|---|
| 429 / `rate_limit` | 请求过于频繁，请稍后再试，或配置 fallback 提供商自动切换。 |
| 500 / 502 / `server_error` | 模型服务端异常，请稍后重试或切换到其他模型/提供商。 |
| 503 / 529 / `overloaded` | 模型服务商当前负载过高，请稍后重试。 |
| 504 / 524 / `timeout` | 上游响应超时，请稍后重试。 |
| 400 / `format_error` | 请求被服务端拒绝（400），可能是参数、内容安全或上下文过长，请尝试 /new 或换模型。 |
| `billing` | 账户余额或额度不足，请检查提供商账单或配置 fallback 自动切换。 |

## 集成点

`agent/conversation_loop.py` 中的三处最终输出：

1. **Invalid response 重试耗尽**（~1330）：空/异常响应且 fallback 不可用。
2. **Non-retryable client error**（~3193）：400 等不可重试客户端错误且 fallback 不可用。
3. **Max retries exhausted**（~3325）：常规 API 异常重试耗尽且 fallback 不可用。

每处调用：

```python
# [owner] append Chinese hint for terminal API errors
_zh_hint = _get_api_error_hint(status_code, reason)
if _zh_hint:
    agent._emit_status(f"💡 {_zh_hint}")
```

并在返回的 `error` / `final_response` 中追加同一提示，确保 CLI、TUI、Gateway 都能收到。

## 测试

```bash
source .venv/bin/activate
pytest tests/owner/test_api_error_hints.py -v
```

## sync fork 注意事项

- `agent/conversation_loop.py` 的改动是薄胶水，冲突风险低；sync 时只需保留 `# [owner]` 标记处的几行调用。
- 若上游重命名了 `classified.reason` 或调整了终端返回结构，需同步更新 `_get_api_error_hint` 的参数传递。
