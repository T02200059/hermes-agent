# C14 · output_guard + stream_guard（v2 落地）

一对退化防线：终局折叠 + 流式看门狗。

## 能力包

| 包 | 钩子 | 作用 |
|----|------|------|
| `owner/output_guard/` | `transform_llm_output` | 整轮结束后识别复读/乱码/退化/超长，折叠并附注 |
| `owner/stream_guard/` | `on_stream_delta` | 滑窗三信号（S1 阶段终止语 / S2 风格签名 / S3 官方 `is_repetition_dominated`）；命中则告警或中止 |

注册入口：`owner/owner-extensions`（`register()` + `plugin.yaml` hooks）。

## 配置（`owner/config/patch.yaml`）

- `owner.stream_guard.*`：完整版默认 `action: interrupt`；可改 `warn_only`。
- `owner.output_guard.enabled`：秒关终局折叠。

纯思考空转：需同时打开官方 `plugins.stream_reasoning_deltas`，stream_guard 才会收到 `kind=reasoning` 的 delta；output_guard 另收 `reasoning_text` 入参（正文健康时只追加告警、不替换正文）。

## 官方薄胶水

1. **`agent/stream_delivery.py`**：`_stream_hook_base_payload` 注入 `request_stop`；新增 `_request_stream_stop`（置 `_interrupt_requested` + 投递 latch）；delta/reasoning 路径尊重 latch。
2. **`agent/turn_finalizer.py`**：`apply_llm_output_transform` 转发 `interrupted` / `reasoning_text`；记录折叠后文本供幂等回放；**C1** `_persist_step` 在 interrupted 时仍折叠有正文的部分。
3. **`agent/turn_final_response.py`**：**C1** 有正文即 transform（不再被 interrupt 门槛挡掉）。
4. **`agent/turn_api_call.py`**：**C2** `handle_api_interrupt` 在 early persist 前先 transform，避免 SQLite 留下退化原文。

S3 直接复用 `agent.repetition_guard.is_repetition_dominated`，不另写复读算法。

## 本批优化（已做）

- 复用官方 repetition_guard（S3），避免双轨。
- interrupt 路径与正常路径共用 `apply_llm_output_transform`，并缓存折叠结果（`_llm_output_transform_text`），幂等调用不再把 caller 的 stale 原文交回去。
- stream stop latch 在 content/reasoning 双通道生效，减少中止后的无谓 delta 评估。
- 配置进 `patch.yaml`；代码 DEFAULTS 仍为 `warn_only`（fail-open），生产行为由 yaml `interrupt` 决定。
- 自检与测样改用合成样本，不入库真实用户事故正文。

## 自检 / 测试

```bash
cd ~/.hermes/hermes-agent-v2
python -m owner.output_guard.selfcheck
python -m owner.stream_guard.selfcheck
python -m pytest tests/owner/test_c14_guards.py -q
```

设计详述：`owner/docs/design/output-guard/output-guard.md`、`owner/docs/design/stream-guard/degenerate-stream-guard.md`。
