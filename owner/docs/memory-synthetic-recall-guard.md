# Memory 合成消息 Recall Guard

> 防止 memory provider 在合成系统消息(异步委托完成、后台进程通知、watch 命中、CLI→gateway handoff)触发时执行 recall/sync。

---

## 一、背景问题

Hermes 的 memory recall(通过 `MemoryManager.prefetch_all`)在每个 `run_conversation` turn 开始时**无条件触发一次**(`agent/turn_context.py:417-424`)。唯一的守卫是 `if agent._memory_manager:`——**不检查消息来源**。

但有一类消息是**系统合成**的,不是用户真实输入:

| 合成消息类型 | 触发场景 | 文本前缀 |
|---|---|---|
| 异步委托完成(批量) | `delegate_task(background=true)` 批量子代理完成 | `[ASYNC DELEGATION BATCH COMPLETE — ` |
| 异步委托完成(单个) | 单个后台子代理完成 | `[ASYNC DELEGATION COMPLETE — ` |
| 后台进程完成 | `terminal(notify_on_complete=True)` 进程退出 | `[IMPORTANT: Background process ` |
| watch pattern 命中 | `terminal(watch_patterns=...)` 命中 | `[IMPORTANT: Background process ... matched watch pattern` |
| CLI→gateway handoff | CLI 会话移交到消息平台 | `[Session was just handed off from CLI` |

这些消息通过和真实用户消息**相同的管道**重新进入对话:
- **Gateway**: `_inject_watch_notification`(`gateway/run.py:13552`)构造 `MessageEvent(internal=True)` 调 `adapter.handle_message` → `run_conversation`
- **CLI**: `drain_notifications`(`cli.py:14479`)把合成文本塞进 `_pending_input`(和键盘输入同一个队列)→ `run_conversation`

`gateway/run.py:7459` 的 `is_internal` 标记**只用于跳过 auth/hook**,dispatch 到 `agent.run_conversation` 时丢失,而 CLI 路径根本没有 internal 标记。

### 后果

合成文本(如 `[ASYNC DELEGATION COMPLETE — <goal>]`)被**原样当作用户意图**喂给 `prefetch_all`,导致:
1. **recall 相关性错误**——provider 拿系统通知文本当 query 召回
2. **浪费 provider 调用**——一次无意义的 recall round-trip
3. **污染 memory 存储**——`sync_all` 把合成消息当"用户说的话"写进去

---

## 二、解决方案

**P1:运行时 patch `MemoryManager` 方法**(遵循 `二次开发规范` §2.1)。

patch 在 `MemoryManager` 层(而非 provider 层)拦截,因为它是所有 provider 的唯一 orchestrator——`build_turn_context` 只调 manager 不直接调 provider。这样一次 patch 覆盖所有 provider(builtin + 外部),与 provider 数量无关。

### patch 的 4 个方法

| 方法 | 作用 | guard 行为 |
|---|---|---|
| `prefetch_all` | recall(读) | 合成消息 → 返回 `""`,不调底层 provider |
| `queue_prefetch_all` | 下一轮 recall 预热 | 合成消息 → 直接 return |
| `on_turn_start` | 通知 provider "新 turn" | 合成消息 → 不通知(不是真 turn) |
| `sync_all` | 写入 memory 存储 | 合成消息 → 不写入 |

### 检测逻辑

前缀匹配 4 个**协议级稳定标记**。这些标记由 `tools/process_registry.py::format_process_notification` 和 `gateway/run.py::_process_handoff` 生成,注释明确称之为 "self-contained re-injection" / "system-generated",是设计上就为了让模型识别为系统通知的标记——比 skill scaffolding 检测(已有的 `_strip_skill_scaffolding` 同类先例)还稳定。

`lstrip()` 容忍前导空白。

---

## 三、为什么选这个方案(而非其他)

| 方案 | 评价 |
|---|---|
| ❌ 改 `run_conversation` 加 `internal` 参数(P2) | 违反规范——改官方核心方法签名,需改所有 caller(gateway×2、CLI、TUI、cron、ACP、batch_runner),merge 冲突大 |
| ❌ 传 `event.internal` 标记 | gateway 的标记到不了 `run_conversation`(`_handle_message` 内部用完就丢),CLI 路径根本没有标记 |
| ❌ patch 每个 provider 的 `prefetch` | 重复 N 次,新 provider 会漏 |
| ✅ patch `MemoryManager`(本方案) | 单点覆盖所有 provider 和所有路径,不碰官方核心签名 |

`MemoryManager` 是天然 choke point:所有 recall/sync 入口都经过它。

---

## 四、文件清单

| 文件 | 类型 |
|---|---|
| `owner/patches/memory_synthetic_guard_patch.py` | 核心实现 |
| `gateway/run.py`(行 52 附近) | +4 行 apply glue(与 OpenViking patch 同构) |
| `tests/owner/patches/test_memory_synthetic_guard_patch.py` | 行为契约测试(25 项) |
| `owner/docs/memory-synthetic-recall-guard.md` | 本文档 |

---

## 五、覆盖范围

- ✅ **Gateway 路径**:所有消息平台(飞书、Telegram、Discord 等)。`apply_patch` 在 `gateway/run.py` 顶部执行,patch 类方法后全局生效
- ✅ **CLI 路径的合成消息也会经过 `MemoryManager`**(共享同一类),但**纯 CLI 模式不走 gateway 时 `apply_patch` 不会执行**——这与 OpenViking patch 的覆盖范围一致(项目实际部署以 gateway 为主)。如需 CLI 覆盖,加一个 apply 点即可(patch 幂等可复用)
- ✅ **同步委托**(`delegate_task(background=false)`):子代理 `skip_memory=True`,且不创建新父级 turn——本来就不触发父级 recall
- ✅ **上下文压缩**:调的是 `on_session_switch`(非 recall)——本来就不触发 recall

---

## 六、维护责任

**新增合成消息类型时**,需要在 `memory_synthetic_guard_patch.py` 的 `_SYNTHETIC_PREFIXES` 元组追加新前缀。前缀来自 `tools/process_registry.py::format_process_notification`(唯一的格式化入口)或 `gateway/run.py::_process_handoff`。

**误判风险**:
- 真实用户消息**不会**误判(只有命中前缀才跳过,用户不会以 `[ASYNC DELEGATION COMPLETE` 开头)
- 漏掉新的合成类型 → 该类型退化回现状(仍触发 recall),无新危害

---

## 七、回退

- `revert_patch()` 一行恢复原实现
- 或删除 `owner/patches/memory_synthetic_guard_patch.py` + 移除 `gateway/run.py` 的 4 行 glue
- 删除后官方代码字面只差 4 行注释化 try/except,完全可独立移除(规范 §2.3 可移除性)
