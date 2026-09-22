# 出站剥 DeepSeek BOS/EOS 泄漏

> 状态：已实现  
> 对应清单：§7.27

## 背景

上游（常见于 DeepSeek 词表链路）偶发把 `<｜begin▁of▁sentence｜>` / `<｜end▁of▁sentence｜>` decode 成可见正文。本机开启 `interim_assistant_messages` 时，中间轮旁白也会进飞书。

## 决策

- **只剥 BOS/EOS 字面量**；奇怪 JSON tool 参数另案。
- **不按 provider / model 门控**：字形序列足够特异；按 damodel 门控需要在出站链路补传 provider，胶水变厚，不符合「干净简洁」。
- **出站两处**：`_sanitize_gateway_final_response`（终局）+ `run_agent` interim 两条发送前路径。

## 模块

`owner/outbound_special_token_scrub.py` → `scrub_outbound_text`

## 验证

`tests/owner/test_outbound_special_token_scrub.py`；生效需网关重启。
