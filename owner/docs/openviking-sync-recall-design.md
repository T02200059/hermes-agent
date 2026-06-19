# OpenViking memory provider 同步化 + advisory 提示词改写 — 实施设计文档

> 目标：解决 `prefetch()` 延迟一轮导致 recall 串台，以及 `build_memory_context_block` 措辞过强导致 LLM 强行引用的问题。  
> 约束：官方源码 `plugins/memory/openviking/__init__.py` 与 `agent/memory_manager.py` 不能改字面定义，全部改动通过 `owner/` 运行时 post-registration patch 注入。  
> 实施时间戳：2026-06-19

---

## 1. 选型：路径 A（纯 owner/ post-registration patch）

沿用第一轮方案结论：运行时替换 `OpenVikingMemoryProvider.prefetch` / `queue_prefetch` / `agent.memory_manager.build_memory_context_block` 三个方法。

- 风险最低：只替换行为，不持有原实现细节。
- 与 `owner/docs/二次开发规范.md` 一致：post-registration patch、高内聚、可移除、可追踪。
- 秒级回滚：环境变量 feature flag + `revert_patch()`。

---

## 2. `owner/` 文件结构

```
owner/
├── patches/
│   └── openviking_sync_recall_patch.py   # patch 注册器与实现
└── docs/
    └── openviking-sync-recall-design.md  # 本设计文档
```

- `owner/patches/openviking_sync_recall_patch.py`
  - `_sync_prefetch(self, query, *, session_id="")`：同步 `httpx.post /api/v1/search/find`，解析 `memories/resources` 各 top 3，返回 markdown bullet。
  - `_noop_queue_prefetch(self, query, *, session_id="")`：原 `queue_prefetch` 替换为空操作（同步化后不再依赖后台线程与 `_prefetch_result`）。
  - `_build_advisory_memory_context_block(raw_context)`：替换 `MemoryManager.build_memory_context_block`，使用 advisory 融合版措辞。
  - `apply_patch(force_sync=None, advisory_tone=None)` / `revert_patch()`：运行时注入与还原。
  - 环境变量：`OPENVIKING_SYNC_RECALL` / `OPENVIKING_ADVISORY_MEMORY` / `OPENVIKING_SEARCH_TIMEOUT`。

- `tests/owner/patches/test_openviking_sync_recall_patch.py`：owner 定制单测。

---

## 3. Feature flag 与环境变量

| 环境变量 | 默认值 | 作用 |
|---|---|---|
| `OPENVIKING_SYNC_RECALL` | `1` | `1`：启用同步 recall；`0`：不替换 prefetch/queue_prefetch |
| `OPENVIKING_ADVISORY_MEMORY` | `1` | `1`：启用 advisory 提示词；`0`：不替换 build_memory_context_block |
| `OPENVIKING_SEARCH_TIMEOUT` | `10` | 同步搜索超时（秒） |

回滚方式：

```bash
export OPENVIKING_SYNC_RECALL=0
export OPENVIKING_ADVISORY_MEMORY=0
```

重启 hermes-agent 即可恢复官方行为；运行时也可调用 `revert_patch()`。

---

## 4. 宝哥拍板决策（与第一轮方案的偏差）

### 决策 1：timeout 固定 10s

- `OPENVIKING_SEARCH_TIMEOUT` 默认值 **10**。
- 不在代码里写软上限/硬上限两套值，只有一个 10s timeout。
- 实现：`_get_httpx().post(..., timeout=10.0)`。

### 决策 2：advisory 措辞融合版

最终文案：

```
<memory-context>
[System note: The following is recalled memory context, NOT new user input.
It may help inform the response, but use it only when relevant to the user's
current message — treat as helpful hints, not authoritative facts.]
...
</memory-context>
```

保留要素：

- `<memory-context>` 标签
- `[System note: ...]` 前缀
- `NOT new user input`
- `may help inform`
- `only when relevant`
- `helpful hints, not authoritative facts`

删除旧措辞：

- `Treat as authoritative reference data`
- `this is the agent's persistent memory`
- `should inform all responses`

### 决策 3：完全同步，砍掉预热逻辑

- 完全砍掉 `queue_prefetch` 的预热逻辑。
- `prefetch` 同步调用搜索，**不**消费上轮 `_prefetch_result`。
- `queue_prefetch` 替换为 noop（保留方法以维持 ABC 兼容）。
- 不实现缓存层、不实现 staleness check —— 后续如需要再单独设计。

### 决策 4：方案先归档到 `owner/docs`

本文件即归档位置：`owner/docs/openviking-sync-recall-design.md`。  
写代码前已完成归档，后续实现保持与本方案一致。

---

## 5. 异常与降级

- 同步搜索包完整 `try/except`：连接失败、timeout、HTTP 错误、JSON 解析错误均返回空字符串。
- 异常时打印 `warning` 日志，不中断 LLM 调用。
- timeout 使用 `httpx.TimeoutException` 与通用 `Exception` 兜底。

---

## 6. 运行时挂载

```python
from owner.patches.openviking_sync_recall_patch import apply_patch
apply_patch()
```

该调用可放在 owner 启动入口或官方启动流程的最薄委托点；`owner/patches/` 本身不修改任何官方文件字面定义。

---

## 7. Definition of Done

- [x] `owner/docs/openviking-sync-recall-design.md` 已归档。
- [x] `owner/patches/openviking_sync_recall_patch.py` 存在且通过静态检查。
- [x] `tests/owner/patches/test_openviking_sync_recall_patch.py` 覆盖默认开关、显式关闭、幂等性、同步搜索成功/超时、advisory 措辞。
- [x] `pytest tests/owner/patches/test_openviking_sync_recall_patch.py -v` 通过。
- [ ] 在 `v16改动清单.md` 中新增记录（待宝哥 review 后统一添加）。
