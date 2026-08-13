# output_guard 设计文档

> 功能：LLM 输出复读 / 乱码 / 超长检测与折叠
> 状态：v1 已实现（2026-08-13），owner-extensions 插件，零官方侵入
> 相关：owner/owner-extensions/output_guard/、owner/docs/owner改动清单.md §14

---

## 1. 背景与问题

2026-08-12 `ark-agent-plan-deepseek-v4-flash`（provider damodel）在 git 推送确认场景
陷入**复读死循环**：单次生成 12 万~14.6 万 token，最终单条输出 **265,518 字符**
（「确认就推。默认不推 upstream。需要就说一声。」反复数百遍）直接刷给用户。

**根因链**（三铁证，见 2026-08-12 会话）：

1. 模型级输出退化（复读是生成行为，非 Hermes bug）
2. 未设输出上限：Hermes 只在配置了上限时才传 `max_tokens`，不传则落到 damodel
   渠道自身的超大默认值 → 退化循环能一口气跑 14 万 token
3. 复读输出喂回下一轮上下文，`in` 从 124K 涨到 271K，**自我强化**

**已做的第一道防线**：`config.yaml → model.max_tokens: 16000`（API 层硬截断）。
复读最多膨胀到 ~1.6 万 token 即被截断，不再出 26 万字符。但用户仍会收到
「半截复读」的截断尾巴。

**output_guard 定位**：第二道防线。在响应**发送给用户之前**（`transform_llm_output`）
识别退化输出并修正，让用户看到的是干净信息而非刷屏。

## 2. 架构决策

| 项 | 决策 | 理由 |
|----|------|------|
| 落点 | owner-extensions 插件，注册 `transform_llm_output` 钩子 | 二次开发规范 P0：能 hook 实现绝不动源码；`transform_llm_output` 是在非流式响应发送前的最后一环（`agent/turn_finalizer.py:556`，返回非空字符串即替换最终响应；gateway 端 `response_transformed` 保证发送最终版） |
| 检测时机 | 一次性（事后），非流式 | 飞书为非流式整条发送（`adapter._send_raw_message`），钩子在发送前触发，折叠必然生效 |
| 不做什么（v1） | 不 interrupt、不自动重试、不流式掐断 | interrupt 需核心桥接且 `_interrupt_requested` 跨轮 reset 语义未确认；重试增加 LLM 调用；流式掐断收益已被 max_tokens 削弱 |
| fail-safe | 钩子内任何异常 → 返回 None（原样） | turm_finalizer 本身 try/except 包裹，但模块内仍防御性 catch，绝不破坏主流程 |

## 3. 检测算法（O(n)，纯 stdlib）

| 信号 | 实现 | 正常值 | 异常值 |
|------|------|--------|--------|
| **句子级 top-1 重复率**（主） | 按 `。！？!?；;` + 换行切句；归一化（剥空白/标点）后计数 | top 句占比 < 10% | 事故样本 > 95% |
| **独有句占比** | `唯一句数 / 总句数` | > 0.8 | < 0.5 |
| **zlib 压缩率**（低信息兜底） | `len(zlib.compress(text)) / len(text)` | 0.3 ~ 0.5 | < 0.15 |
| **U+FFFD 乱码占比** | `text.count("\ufffd") / len(text)` | ~0 | > 0.5% |
| **长度** | `len(text)` | 100 ~ 5000 字符 | > 50000 |

### 判定（多信号防误伤，v1 阈值）

```
len(text) < 3000                       → 不判（正常回复 100~2000 token）
fffd_ratio > 0.005                     → mojibake（优先）
top_count >= 5 AND top_ratio >= 0.25   → repeat
top_count >= 5 AND unique_ratio < 0.50 → low_info
comp_ratio < 0.15 AND sentence_count >= 10 → comp_belt（兜底）
chars > 50000                          → too_long（截断）
```

单个信号不触发：长报告有重复词组但 top 句占比到不了 25%；代码/表格是结构重复
不是句子重复；短回复不判。

## 4. 处理策略

| verdict | 动作 | 附加 |
|---------|------|------|
| repeat / low_info / comp_belt | **段落级去重**（`\n\n` 切段，归一化后首现保留），重组文本 | 末尾追加 `⚠️ [output-guard]` 标注：top 句、重复次数、占比、压缩率、原始长度 → 折叠后长度、模型 |
| mojibake | 同样段落去重 | 标注 U+FFFD 占比 |
| too_long | 截断前 50000 字符 | 标注原始长度 |

折叠后追加标注：用户看到完整信息（每个不同段落都在）+ 明确说明发生了什么。

## 5. 文件

```
owner/owner-extensions/output_guard/__init__.py   检测 + 折叠 + register_hooks
owner/owner-extensions/plugin.yaml                hooks 列表 + transform_llm_output
owner/owner-extensions/__init__.py                register() 聚合注册 output_guard
owner/docs/output-guard-design.md                 本文档
owner/docs/owner改动清单.md                       §14 + 附录 A 索引
```

无官方文件改动（`agent/`、`gateway/`、`hermes_cli/` 均未触碰）。

## 6. 验证

策略单测（可直接运行）：

```bash
cd /Users/yangtb/.hermes/hermes-agent && python3 - <<'EOF'
from owner.owner_extensions.output_guard import analyze, _fold_paragraphs, _on_transform_llm_output

# 1) 复读样本（模拟事故形态）
repeat_text = ("要推 origin + gitlab 吗？需要就说一声。确认就推。默认不推 upstream。需要就说一声。确认就推。默认不推 upstream。\n\n" * 100)
sig = analyze(repeat_text)
assert sig["verdict"] == "repeat", sig["verdict"]
assert sig["top_count"] >= 100
out = _on_transform_llm_output(repeat_text, session_id="t", model="test", platform="feishu")
assert out is not None and "[output-guard]" in out
assert len(out) < len(repeat_text) / 10

# 2) 正常长输出（不应误伤）
import random
normal = "\n\n".join(f"第 {i} 段：这是包含一些重复用词但内容不同的长报告段落。" + "正常句子。" * 3 for i in range(200))
sig2 = analyze(normal)
assert sig2["verdict"] == "ok", (sig2["verdict"], sig2)
assert _on_transform_llm_output(normal, model="test") is None

# 3) 乱码样本
moji = ("正常内容。锟斤拷锟斤拷" + "\ufffd" * 100 + "。继续正常。" * 50)
sig3 = analyze(moji)
assert sig3["verdict"] == "mojibake", sig3["verdict"]

# 4) 短回复不判
sig4 = analyze("已标完成。")
assert sig4["verdict"] == "ok"

print("output_guard 策略验证全部通过 ✓")
EOF
```

## 7. 后续（P2，未实现）

- **stop 下一轮**：检测到复读后 `agent.interrupt()`，阻断上下文回灌强化（事故放大器
  是轮间 in 124K→271K）。需 2 处核心小改：turn_finalizer 钩子 context 传 agent、
  识别插件返回的 stop 标志。实现前必须确认 `_interrupt_requested` 的跨轮 reset 语义，
  否则会误伤下一轮正常对话。
- **自动重试**：退化时换 temperature / 换模型重生成一次。
- **流式掐断**：chunk 级检测，生成中取消（收益已被 max_tokens 削弱，优先级最低）。
- **阈值调优**：上线后按真实误报/漏报调整 `_TOP_REPEAT_MIN_RATIO` 等。