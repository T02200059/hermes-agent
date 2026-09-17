# 生成中退化闸门设计（§14.2：P0 三处收口 + P1 闸门已落地）

> 目标：让「thinking 与输出两个阶段的死循环」在**生成进行中**被检测、被终止，并**主动告知用户**
> 状态：**P0 + P1 已实现**（2026-09-17）。P2（切 `action: interrupt`）待 `warn_only` 一周灰度数据；
>       P3（平台侧交互卡片）未开始。
> 实现落点：`owner/owner-extensions/stream_guard/`（新插件）、
>           `owner/owner-extensions/output_guard/`（C3）、
>           `agent/turn_finalizer.py`（C1/C2）、`run_agent.py`（route B 薄 seam）
> 相关：`owner/docs/output-guard-design.md`、`owner/docs/owner改动清单.md` §14
> 事故取证：`state.db` msg 108360（2026-09-17 16:25:14，session `20260917_122148_57701e`）
> 事故样本：`owner/owner-extensions/stream_guard/samples/incident_9_17_thinking_loop.txt`
>           （30,742 字符，含用户对话内容，已 gitignore）

---

## 0 结论摘要

1. **检测能力已经够，缺的是"在流中做判断"的那一环。** 把今日事故原文喂给已实现的 v2，判定
   `verdict=degenerate`，30742 → 19474 字符。但运行期它一次都没跑到。
2. **终止能力也已经够。** 流式消费循环每个 chunk 都检查 `agent._interrupt_requested`
   （`agent/chat_completion_helpers.py:4417`，Anthropic 路径 `:4958`）。只要有人置位，**一个 chunk 内即中断**。
   今天这轮是人工 Ctrl-C 终止的（`agent.log` `Turn ended: reason=interrupted_during_api_call`），
   生成持续 4 分 16 秒。
3. **通知能力也已经够。** `agent._emit_warning()`（`run_agent.py:1107`）→ `status_callback("warn")`
   → 网关 `_status_callback_sync`（`gateway/run.py:5940`）→ 平台发送；网关侧过滤器
   （`gateway/run.py:1054`）只挡 auxiliary / compression 噪音，告警可过。
4. **缺的是一致性**：检测在「事后、整轮、被中断就跳过」，终止在「人工」，通知在「无事可通」。
   三者没有被同一个决策点串起来。本文的设计就是把它们接到**一个流中决策点**上。

---

## 0.5 实现摘要与标定结果（2026-09-17）

### 落地清单

| 项 | 文件 | 内容 |
|---|---|---|
| C1 | `agent/turn_finalizer.py` | `transform_llm_output` 去掉 `not interrupted` 门槛，载荷补 `interrupted` |
| C2 | `agent/turn_finalizer.py` | 钩子 + transcript 尾行回写**前移到 `_persist_session` 之前**（理由见 §5） |
| C3 | `agent/turn_finalizer.py` + `output_guard/__init__.py` | 载荷补 `reasoning_text`；思考通道单独扫描，只告警、不替换正文 |
| P1-a | `run_agent.py` | `_stream_hook_base_payload()` 加 `request_stop`；新增 `_request_stream_stop()`（轮次围栏 + 每轮一次 latch） |
| P1-b | `owner/owner-extensions/stream_guard/`（新） | 滑窗 + 三信号投票 + 告警 / 中止 |
| P1-c | `owner/config/patch.yaml`、`owner-extensions/plugin.yaml`、`owner-extensions/__init__.py` | 配置面、钩子声明与注册 |

### 阈值标定（真实数据，非估算）

语料：**8 条正例** = 今日事故 + 5 条逐条核实过的历史复读失控
（`msg 93635` 265,518 / `93633` 262,157 / `33260` 12,180 / `33236` 12,159 / `33222` 11,813）
+ `degenerate_9_01` 模板泄漏样本（与 `msg 107705` 同源，脚本各计一条）；
**318 条负例** = `state.db` 中全部 >2000 字符的真实 assistant 正文
（剔除上述已核实的历史失控）+ 2 条合法引用样本。

| 信号 | 阈值 | 事故实测 | 负样本峰值 | 结论 |
|---|---|---|---|---|
| S1 阶段终止语密度 | **≥3.0/KB** | 3.17（首个命中窗口）→ 4.15 峰值 | **2.41**（恰好是一条讨论本次事故、引用了这些字样的回复） | 两侧余量最平衡 |
| S2 签名密度倍数 | **≥×8.0** | ×21.97 → ×25.88 峰值 | **×0.00**（318 条中无一条出现 `ฅ`） | 分离度极大 |
| S3 零进展 | **命中即触发** | 6/6 历史复读事故命中 | **0**（318 条中 0 命中） | 精度 100% |

**结果：8/8 正例命中、0 误伤。**

今日事故的命中点在**生成到 50%（15,360 字符）**处 —— 按该轮实测速率
（30,742 字符 / 256 秒 ≈ 120 字符/秒）折算，比人工 Ctrl-C 早约 **2 分钟**。

复现：
```bash
python owner/owner-extensions/stream_guard/selfcheck.py        # 离线自检（含事故原文回放）
.venv/bin/pytest tests/owner/test_stream_guard.py -q           # 14 项，含真实样本端到端回放
.venv/bin/pytest tests/run_agent/test_request_stream_stop.py -q # 7 项，seam 语义
```

### 三处取值依据（实测校准，非先验设定）

| 取值点 | 最终值 | 依据 |
|---|---|---|
| S1 阈值 | **3.0/KB** | 4.0/KB 只剩 4% 余量（事故首个命中窗口 3.17、负样本峰值 2.41）；3.0 两侧余量最平衡 |
| S3 地位 | **单独即可触发**（`s3_solo`） | S1/S2 对"纯复读"完全不敏感（该形态 S1=0/S2=0），若坚持 2/3 投票会整片漏掉 —— 而纯复读恰是历史事故里最常见的一类（已核实的 5 条全是） |
| S2 基线 | **静态基线** `signature_baseline_per_kb` | 静态基线在 318 条真实回复上已给出 ×0.00 vs ×21.97 的分离度；"该 profile 近 N 轮中位数"需要跨轮状态，收益不足，留作后续 |

---


| 项 | 值 | 证据 |
|----|----|------|
| 会话 / 消息 | `20260917_122148_57701e` / msg `108360` | `state.db` |
| 平台 / 模型 | cli / xy-max（provider damodel） | `agent.log` API call 行 |
| 形态 | **思考→输出阶段边界循环**：反复宣告"思考结束、现在输出"而永不输出 | 正文样本见 §1.1 |
| 长度 / 组成 | 30742 字符；风格签名 `ฅ` ×910（猫脸 ×455）；`THINKING` ×88；`END OF` ×49；`meow` ×63；`(stop)` ×9 | 统计（本文） |
| 行级结构 | 388 行 / 367 唯一行 | 统计（本文） |
| 压缩率 | 0.293（**正常区间**，v1 低信息兜底不触发） | 统计（本文） |
| 持续时长 | 约 4 分 16 秒（16:20:58 → 16:25:14） | `agent.log` |
| 终局 | `Turn ended: reason=interrupted_during_api_call ... response_len=30742` → **人工打断** | `agent.log:12205` |
| 落库 | 原文 30742 字符完整落库 | `state.db` |

### 1.1 关键形态：**词汇多样、语义空转**

事后 8% 的样本形态：

```
DONE THINKING. WRITING RESPONSE. ฅ^•ﻌ•^ฅ
(Now outputting the response.) ฅ^•ﻌ•^ฅ
[THE THINKING HAS ENDED. THE RESPONSE IS THE NEXT THING I PRODUCE.] ฅ^•ﻌ•^ฅ
(stop)(stop)(stop) ฅ^•ﻌ•^ฅ
```

前 92% 仍是有效内容（进程清单、"为什么重启 gateway 还会有别的进程"的实质回答），
只有尾部退化。**这解释了为什么所有"重复类"检测器都抓不到**：它不是复读同一句话，
而是把「终止思考」这件事本身当成了要生成的内容——**终止条件变成了循环体**。

推论（设计依据）：**对这类退化，词面重复率是错的信号；正确的是「阶段终止语密度」与「风格签名密度」。**

---

## 2 为什么漏判：三处已核实的具体原因

| # | 原因 | 证据 | 性质 |
|---|------|------|------|
| 1 | 钩子被 `not interrupted` 跳过 | `agent/turn_finalizer.py:624` `if final_response and not interrupted:` | **结构性**：失控生成的典型结局就是被打断，钩子恰好在此失效 |
| 2 | 进程内插件代码陈旧 | 该轮由 12:21 启动的 agent 进程执行；v2 的 commit 在 14:17。v1 对该文本判 `ok`（`top_count=0`、`comp_ratio=0.293`、`ffd=0`） | 运维性：改仓内文件对**已启动**的 agent 进程无效（与 `max_tokens` 同一类） |
| 3 | transcript 回写落在落库之后 | `_persist_session` 在 `agent/turn_finalizer.py:477`（**唯一一次**），钩子在 `:624` | 结构性：v2 的回写只改内存；且 `_db_persisted` 标记（`agent/context_compressor.py:394`）会让后续 flush 跳过该行 |

第 3 条的实证：全库检索 `[output-guard]` 共 17 行，**没有任何一行是护栏替换后的落库文本**，
全部是会话正文里对护栏的讨论。即 §14.1 文档中「落库与下一轮上下文拿到干净文本」的表述，
就 `state.db` 而言当前不成立（下一轮上下文经 `agent._session_messages` 拿到的是干净文本，
跨进程 / 重启 / 任何读库路径拿到的仍是原文）。

---

## 3 现有防线盘点：全是「事后」或「空闲」型

| 防线 | 落点 | 触发时机 | 对今日事故 |
|------|------|----------|------------|
| `output_guard` v1/v2 | `transform_llm_output`（`turn_finalizer.py:624`） | **整轮生成结束之后**，且要求 `not interrupted` | ✗ 未触发（原因 1/2） |
| `_thinking_exhausted` | `conversation_loop.py:4079` | `finish_reason=length` 的续写边界 | ✗ 未到该边界（生成被人工打断） |
| `is_repetition_dominated` | `conversation_loop.py:4133` + `agent/repetition_guard.py:43` | 同上（续写边界） | ✗ 同上；且词面重复率对本形态无效 |
| `TurnLivenessWatchdog` | `agent/turn_liveness.py:159`（默认 600s / 轮询 15s） | **空闲**超时 | ✗ **永不触发**：流式每 chunk 都 `_touch_activity("receiving stream response")`（`chat_completion_helpers.py:4396`），活动时钟始终新鲜 |
| `max_tokens`（配置兜底） | `config.yaml:4`（128000 → 16000，今日已同步 13 份 config） | API 层硬截断 | △ 只压总量，不终止退化；且此刻正被打断，续写路径都不走 |

**结论**：四道防线里没有一道能在"持续吐 token 的循环"中做判断。
`TurnLivenessWatchdog` 是最接近的一块积木，但它回答的是"**还有没有动静**"，
而退化循环回答的是"**动静很大，但零进展**"。缺的是 **progress**（质量）看门狗，不是 **liveness**（活性）看门狗。

---

## 4 v3 设计：流中退化闸门

### 4.1 三段式

```
         ┌────────────── 流中决策点（每个 chunk 后）──────────────┐
delta ──▶│  ① 滑窗信号  →  ② 阈值投票  →  ③ 终止 + 通知          │──▶ 下一 chunk 检测到
         └───────────────────────────────────────────────────────┘   _interrupt_requested → break
```

- **① 检测**：`on_stream_delta` 观察钩子（`kind="reasoning" | "text"`），O(1)/delta 累加，每 N 字符或每 ~1s 才做一次窗口判定（摊销成本，不拖慢 token 路径）
- **② 判定**：三信号 2/3 投票（沿用 v1/v2 的多信号防误伤哲学）
- **③ 动作**：`agent.interrupt(require_generation=…)` + `agent._emit_warning(...)`（一次事故一条）

### 4.2 检测信号（用今日样本回放定标）

| 信号 | 定义 | 正常值 | 今日事故 | 分离度 |
|------|------|--------|----------|--------|
| **S1 阶段终止语密度** | 窗口内命中 `END OF THINKING` / `DONE THINKING` / `STOP THINKING` / `response follows` / `WRITING RESPONSE` / `思考结束` / `停止思考` / `以下为最终回答` / `(stop)` / `(done)` / `(end)` 的**次数 / KB** | ~0 | 高（`THINKING`×88 + `END OF`×49 / 30.7KB） | 极大 |
| **S2 风格签名密度**（相对基线） | 会话/画像签名 token（如 `ฅ`）的密度 / KB，与该 profile 近 N 轮中位数比较 | 中位 3.1；长文（>2KB）全部 0.5–1.0 | **29.6** | **~30×** |
| **S3 零进展窗口** | 连续 W 字符内：无工具调用、无终止语之外的"新增内容"，且 `is_repetition_dominated(tail)` 或内容词唯一率骤降 | — | 尾部命中 | 中 |

- S2 需按 profile 配置签名 token 列表（`owner/config/` 可承载），**只用密度异常**，不做二值判定——签名本身是风格特征（全库 147 条正常回复都带它）。
- S3 复用 `agent/repetition_guard.py:is_repetition_dominated` 与 v2 的 `_block_score`，不重写。
- 门槛建议：`min_stream_chars=1200`（短回复不判）、`grace_seconds=20`（首 token 后给 20s，避免打断正常长思考）、任一窗口投票 2/3 命中即触发。

### 4.3 终止：两条落地路线

**路线 A — 零核心源码改动（纯 owner 内可完成）**

利用已存在的 owner 先例 `owner/approval/skill_manage_gate.py:298 _resolve_running_agent()`：
`pre_gateway_dispatch` 钩子缓存网关引用 → `gw._running_agents[session_key]` 取活体 agent → 校验
`agent.session_id` / `_current_turn_id` 与观察到的 `(session_id, turn_id)` 一致 → `agent.interrupt(require_generation=…)`。

- 优点：全部落在 `owner/`，符合二次开发规范 P0/P1
- 代价：依赖 `_running_agents` 这一内部结构（已在 owner 内使用，但属私有契约）；CLI 直连会话（无网关）路径需要另找 agent 引用

**路线 B — 极小核心薄 seam（推荐）**

让流式观察钩子具备"请求停止"的回传通道，约 15 行：

```python
# run_agent.py:7385 _stream_hook_base_payload() 增加：
"request_stop": self._request_stream_stop,   # 插件侧调用即置位

def _request_stream_stop(self, reason: str = "", *, turn_id: str = "") -> bool:
    """[owner] 流中闸门：插件判定退化 → 请求中断本轮。
    仅当 turn_id 与本轮一致时生效（一次性 latch，防跨轮误伤）。"""
    if turn_id and turn_id != (getattr(self, "_current_turn_id", "") or ""):
        return False
    if getattr(self, "_stream_stop_latched_turn", None) == turn_id:
        return False
    self._stream_stop_latched_turn = turn_id
    self._stream_stop_reason = reason
    self._interrupt_requested = True          # 既有每 chunk 检查点即生效
    return True
```

- 优点：不碰 `_running_agents` 私有结构；CLI / 网关两条路径统一；`interrupt()` 的 generation claim
  竞态保护（`run_agent.py:3511`，`_turn_liveness_activity_generation` 校验）可原样复用
- 面：`run_agent.py` 单函数 + 一个新方法，`[owner]` 标注，符合"薄胶水（最好只有 import + 1~3 行委托）"上限

### 4.4 通知用户

复用 `agent._emit_warning()`（`run_agent.py:1107`）——已被 `TurnLivenessWatchdog` 验证可直达用户：

```
agent._emit_warning()
  → _vprint(force=True)                # CLI 立即可见
  → status_callback("warn", msg)
    → gateway/run.py:5940 _status_callback_sync
      → gateway/run.py:1054 _prepare_gateway_status_message   # 只挡 auxiliary/compression 噪音
        → adapter.send(...)                                   # 飞书/Discord/Telegram 一条独立消息
```

建议文案（信息量优先，且明确"已终止 + 已保留有效前缀 + 建议下一步"）：

```
⚠️ 检测到生成退化（思考/输出阶段边界循环），已中止本轮生成。
   判定：阶段终止语密度 X/KB、风格签名密度 Y/KB（基线 Z）；已生成 N 字符，保留前 M 字符。
   原文未落库；如需完整重试，回复"继续"或换模型。
```

去重：仿 `TurnLivenessWatchdog._surface_stalled` 的 `_last_surfaced_generation`
（`agent/turn_liveness.py:289`）——**一次事故只推一条**，重复抑制到下一轮。

### 4.5 配置面（已实现）

实际位置是 **`owner/config/patch.yaml` → `owner.stream_guard`**（软链接到 `~/.hermes/patch.yaml`），
经 `owner/patch_config.py:load_patch_config()` 读取（mtime + 60s TTL 缓存，插件内再叠 5s 缓存）：

```yaml
owner:
  stream_guard:
    enabled: true
    action: warn_only          # warn_only（灰度）| interrupt
    min_stream_chars: 1200     # 累计低于此值不判
    grace_seconds: 20          # 首个 delta 后 N 秒内不判
    window_chars: 4096         # 信号评估窗口（尾部 N 字符）
    eval_interval_chars: 512   # 每积累 N 新字符才评估一次
    vote_threshold: 2          # S1/S2 需命中几项（S3 例外，见 s3_solo）
    s3_solo: true              # S3 命中即触发
    marker_rate_per_kb: 3.0    # S1
    signature_rate_multiple: 8.0     # S2 相对基线倍数
    signature_baseline_per_kb: 1.0   # S2 基线
    signature_tokens: ["ฅ"]     # S2 签名 token（按 profile 配置；空 = 关闭 S2）
    max_actions_per_turn: 1
```

**reasoning 通道的前置条件**：正文 delta 走 `_fire_stream_delta`，恒转发；
思考 delta 走 `_fire_reasoning_delta`，**仅在 `plugins.stream_reasoning_deltas: true` 时**
才转发到插件。因此：

- 今日事故（退化全在 `content`）**不依赖**该开关，开箱即可拦；
- 要覆盖"纯思考空转"形态，需在 `config.yaml` 打开 `plugins.stream_reasoning_deltas: true`。
  该开关的每-delta 插件开销尚未实测（队列 1024、drop-oldest），列入 §7 遗留区。

### 4.6 接口（已实现）

```python
# owner/owner-extensions/stream_guard/__init__.py
DEFAULTS: dict                       # 上表全部键的默认值
config() -> dict                     # 带 5s TTL 缓存的配置读取（fail-open）

def evaluate_window(buf: str, cfg: dict) -> dict:
    """纯函数：对窗口文本做三信号判定，便于离线回放与自检。
    返回 {"window_chars","kb","s1_marker_rate","s2_signature_multiple",
          "s3_no_progress","votes","trip"}"""

def observe(delta="", *, kind="text", session_id="", turn_id="", iteration=0,
            model="", provider="", surface="", request_stop=None, **kwargs) -> None:
    """on_stream_delta 回调体。在 dispatcher 线程上运行；异常全部吞掉。"""

def register_hooks(ctx) -> None:      # ctx.register_hook("on_stream_delta", observe)
def reset_state() -> None             # 清空窗口/动作表（测试用）

# run_agent.py（route B 薄 seam）
def _request_stream_stop(self, reason: str = "", *, turn_id: str = "") -> bool:
    """轮次围栏（跨轮观测不得误伤）+ 每轮一次 latch（按 turn_id）
    + 已有中断时不抢 latch → 置位 _interrupt_requested。"""
```

`observe` 的入参即 `_stream_hook_base_payload()` 的键；`request_stop` 是新增的
唯一回传通道。`stream_guard` 经 `request_stop.__self__` 取回 agent 句柄，
再用 `agent._emit_warning()` 通知用户 —— 载荷里**没有** agent，这是唯一回溯路径，
且只在绑定方法名为 `_request_stream_stop` 时才认（`_resolve_agent()`），否则安静降级。

### 4.7 分阶段落地（当前状态）

| 阶段 | 内容 | 规模 | 状态 |
|------|------|------|------|
| **P0** | v2 的三处收口（§5 C1/C2/C3） | 3 处、约 30 行 | **已完成** |
| **P1** | 路线 B 的 `request_stop` seam + `stream_guard` 插件 | 约 380 行（含自检） | **已完成**，`action: warn_only` 灰度中 |
| **P2** | `action: interrupt` 开闸（+ 视需要开 `stream_reasoning_deltas`） | 配置 | 待 P1 灰度数据 |
| **P3** | 平台侧交互（飞书卡片"重试/换模型"按钮） | 中 | 未开始 |

灰度判读方式：`agent.log` 里 `stream_guard trip ...` 行已带完整 `signals` dict，
一周后按 `action=warn_only` 的命中数与内容抽样核算误伤率，再决定是否开 `interrupt`。

---

## 5 三个收口（C1/C2/C3，已实现）

| # | 问题 | 实现 | 落点 |
|---|------|------|------|
| **C1** | 钩子门槛 `if final_response and not interrupted` —— **今日事故的直接逃生口**：失控生成的典型结局就是被打断，护栏恰在此失效 | 门槛改为 `if final_response:`；载荷补 `interrupted=bool(interrupted)`，让插件知道本轮是被打断收场的；退化文案据此追加"（本轮生成已被中止。）" | `agent/turn_finalizer.py` |
| **C2** | 钩子与 transcript 回写在 `_persist_session` **之后**，护栏替换只改内存 | **把「钩子调用 + 尾行回写」整块前移到 `_persist_session` 之前**（紧接 transcript 闭合块、micro-compaction 之前） | `agent/turn_finalizer.py` |
| **C3** | 钩子看不到 reasoning 通道 | 载荷补 `reasoning_text`（`extract_last_turn_reasoning(messages)`）；`output_guard` 新增 `_scan_reasoning()`，正文健康而思考退化时**只追加告警、不替换正文** | `agent/turn_finalizer.py` + `owner/owner-extensions/output_guard/__init__.py` |

### C2 为什么是"前移"而不是"回写"

"回写时清除 `_db_persisted` 标记然后重跑一次 flush"这条路经代码核实**走不通**：
`_flush_messages_to_session_db` 是 **append-only** 的（`run_agent.py:2339` 文档串明确写了），
而 `agent/transcript_repair.py:56-95` 对已带 `_row_id` 的行只在**内容为空**时原地 UPDATE，
内容非空则"adopt canonical content without overwrite"、既不覆盖也不插入。也就是说：对一条
已经落库的非空行，弹标记 + 重跑 flush **什么也不会发生**。只有把钩子移到落库之前，
落库才真正拿到干净文本。

- 该块仍保留"弹标记 + 失效 `_db_flush_scan_prefix`"，用于**mid-turn flush 已写入空行**的情形
  （复用 `_fill_assistant_tail_content` 的既有手法，此时 repair 会原地 UPDATE）。
- 残余缺口：若该行在 mid-turn 就已按**非空**写入，append-only 的 flush 无法改写它，
  state.db 仍是原文。此情形由 `output_guard` 自身的 `logger.warning`（含 `chars=A→B`）留痕，
  列入 §7。

### C1/C2 的回归测试

`tests/agent/test_turn_finalizer_transform_transcript_sync.py` 新增两项：

- `test_transform_hook_runs_before_persist` —— 断言 `_persist_session` 收到的尾行内容
  已是替换后文本、且不再带 `_db_persisted` 标记；
- `test_transform_hook_runs_on_interrupted_turn` —— 断言 `interrupted=True` 的轮次钩子照常触发，
  且载荷带 `interrupted=True` 与 `reasoning_text`。

---

## 6 测试与验收（结果）

**离线回放（已执行）**

| # | 用例 | 期望 | 结果 |
|---|---|---|---|
| 1 | 今日事故原文（msg 108360，30,742 字符） | `trip=True`，命中点早于尾部退化起点 | ✅ 50%（15,360 字符）命中 |
| 2 | 5 条历史复读失控（265,518 / 262,157 / 12,180 / 12,159 / 11,813） | 命中 | ✅ 5/5，首个窗口即命中（S3） |
| 3 | `degenerate_9_01` 模板泄漏样本 | 命中 | ✅（S3） |
| 4 | 318 条真实长回复 + 2 条合法引用样本 | **零误伤** | ✅ 0 |
| 5 | 合法引用 / 模板化长报告（`output_guard/selfcheck.py`） | 不回归 | ✅ 全部通过 |

**自动化（已执行）**

- `tests/owner/test_stream_guard.py` —— 14 项全通过（含事故原文端到端回放、
  grace/min_chars/warn_only/latch/跨轮重挂/异常吞掉/外部绑定方法不误认 agent）
- `tests/run_agent/test_request_stream_stop.py` —— 7 项全通过（载荷暴露、轮次围栏、latch、已有中断不抢）
- `tests/agent/test_turn_finalizer_transform_transcript_sync.py` —— 4 项全通过（含新增 2 项）
- `owner/owner-extensions/stream_guard/selfcheck.py` + `output_guard/selfcheck.py` —— 均通过

**在线（待做）**

- `action: warn_only` 一周：记录 `stream_guard trip` 行的 `signals` 分布与误伤数
- 验收标准：真阳性 ≥ 1（复现今日形态）；误伤率 0；每次事故恰好 1 条用户通知；
  `request_stop` 后下一轮正常对话不受影响（latch 按 turn 重挂，已由单测覆盖）
- P2 开 `interrupt` 前，必须先确认灰度期**零误伤**；「用户 Ctrl-C 与闸门中断的区分」
  由 `_stream_stop_reason` + `_stream_stop_latched_turn` 两个字段保证，
  但 `_turn_exit_reason` 目前对两者**同样**记为 `interrupted_during_api_call`
  （列 §7）

**必须覆盖的边界（已覆盖 / 待补）**

- ✅ 闸门中断与用户 Ctrl-C 的区分（`_request_stream_stop` 在已有中断时拒绝抢 latch）
- ✅ 同一 turn 内多次命中 → 只动作一次（latch）
- ✅ 跨轮迟到观测不误伤下一轮（turn-id 围栏）
- ✅ 载荷缺 `request_stop`（旧核心）时不崩、不误动作
- ⬜ 中断发生在工具执行期（`_interrupt_requested` 也会终止长命令）—— 需在线观察

---

## 7 遗留问题与未知区

| 项 | 状态 |
|----|------|
| `_turn_exit_reason` 对"闸门中断"与"用户 Ctrl-C"同样记为 `interrupted_during_api_call` | **未区分**。`_stream_stop_reason` / `_stream_stop_latched_turn` 已落 agent，但未接进 `_turn_exit_reason`。要做精确归因需再动 finalizer 一处（列 P2 前置） |
| mid-turn 已按**非空**落库的尾行无法被 append-only flush 改写（C2 残余缺口） | **已知**，由 `output_guard` 的 `logger.warning`（`chars=A→B`）留痕 |
| C3 思考通道的**真实**收益 | **未验证**：今日事故 `reasoning_content` 为 NULL，C3 是为 thinking-heavy provider 补盲，样本尚未出现 |
| `plugins.stream_reasoning_deltas: true` 的每-delta 插件开销（队列 1024，drop-oldest） | 未实测；开启前需压测 |
| `request_stop` 在生成**已结束**但队列仍有积压 delta 时的行为 | 由 turn-id 围栏 + latch 覆盖，但"同一 turn 内 API call 已返回、下一个 iteration 尚未开始"的窗口未单独验证 |
| `interrupt()` 对"流式已输出内容"的截断语义（用户已看到的部分如何收尾） | 未验证；`_request_stream_stop` 走 `_interrupt_requested`，与 Ctrl-C 同一路径，故沿用既有语义 |
| CLI 直连会话下 `_emit_warning` 与流式输出的交错观感 | 未验证 |
| 风格签名（`ฅ`）来源未定位（SOUL.md / profile 全库均无该字符） | 未确认；不影响 S2 的"密度异常"用法，但换 profile 时须重配 `signature_tokens` |
| S1 终止语词表对多语言 / 其他模型的覆盖率 | 仅覆盖今日形态 + 常见英文宣告词；需按 profile 扩充 |
| S2 改用"该 profile 近 N 轮中位数"动态基线 | 未做（静态基线已足够）；留作后续 |
| `owner-extensions` 目录名含连字符，单测需以 `spec_from_file_location` + 手动注册 `sys.modules` 加载 | 已在 `tests/owner/test_stream_guard.py` 落地；`@dataclass` 必须在注册 `sys.modules` 之后才能 exec |
