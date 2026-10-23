# queue-steer-lifecycle：飞书 /queue 与 /steer 的生命周期

> 记录时间：2026-10-23　|　代码位置：`owner/patches/queue_cancel_patch.py`（patch）、`owner/feishu/queue_card.py`（卡片与动作）、`owner/gateway/steer_vision.py`（steer 视觉增强）
> 编排模式：**运行时 patch 注入**（不改官方 `run_agent.py` / `gateway/run.py` 的方法体，靠 `revert_patch()` 可整段撤销）

## 一、要解决的问题

上游的 busy 队列是纯文本的：用户在 agent 正在跑时再发一条消息，得到一句"已排队"，然后**就没有然后了** —— 不能取消、不能插队、看不到队列里有什么、也不知道什么时候轮到它。

owner 侧要在飞书把它做成可操作的：状态卡片 + 三个动作（取消 / 立即执行 / 转向）。

## 二、为什么用 runtime patch 而不是改源码

上游的 `_enqueue_fifo` / `_dequeue_pending_event` / `_busy_queue_command` 都在 `gateway/run.py` 这类**高频被 sync 覆盖**的文件里。直接改方法体有两个代价：

1. 每次 sync 都要重新解冲这三处（已是 `gateway/run.py` 定制最密集的区段之一）
2. 官方改了队列内部结构（比如改成 `asyncio.Queue`）会静默失效 —— `except` 一兜就成了"排队功能看起来在、卡片永远不出来"

patch 模式把定制搬进 `owner/patches/queue_cancel_patch.py`，官方文件只剩一次 `apply()` 调用。**代价是依赖内省**（按方法名取属性），所以必须做**启动时自检**：找不到 `_enqueue_fifo` 就明确打日志跳过（实测日志形如 `queue_cancel_patch: GatewayRunner._enqueue_fifo missing; skip`），而不是静默半生效。

## 三、token 传递：为什么不用 `message_id`

这是本模块**最容易写错的一处**，踩过。

飞书用 `event.message_id` 作为 `reply_to`（回复锚点）。如果把合成 token（如 `ownerq-<uuid>`）写进 `message_id`：

- ack 会失败（飞书按 message_id 找不到原消息）
- 回复锚点错乱（回复挂到不存在的消息上）

**采用的传递链**（四步，全部靠事件对象上的私有属性，不碰任何飞书字段）：

```
① register_scheduled_token(token, text=..., card_meta=...)   提交时登记
② 包装 _enqueue_fifo：按 prompt 文本匹配，盖上 event._owner_queue_token，并把 runner 绑到 adapter
③ cancel / process_now：扫 pending + overflow，找带该属性的元素
④ 包装 _dequeue_pending_event：带 token 的项开始执行时，把状态卡片 REST patch 成「已开始执行」终态
```

**为什么按文本匹配**：`_enqueue_fifo` 的签名不含调用方信息，唯一能关联的是排进去的那条 prompt 文本。这是一个**有意的妥协**，风险是"同一文本排两次"会歧义 —— 用 `_token_state` 的状态机（`scheduled` → `enqueued` → 终态）把第二次匹配挤到另一个 token 上。

## 四、状态机与 token 清理

```
scheduled ──进FIFO──> enqueued ──开始执行──> executed
    │                     ├──用户取消──> cancelled
    │                     ├──用户转向──> steered
    │                     └──立即执行──> process_now ──> executed
    └──从未进FIFO（卡片发了没点/会话结束）──> 1 小时后剪除
```

`_TOKEN_PRUNE_STATES = ("cancelled", "steered", "executed", "scheduled")`，`_TOKEN_STALE_AFTER = 3600s`。

**为什么 `enqueued` / `process_now` 不剪**：这两个状态仍在 FIFO 里，取消与转向还要靠 token 找到它。剪掉就等于"用户看着卡片说能取消，点了没反应"。

**并发**：`_token_state` 由 `_token_lock` 保护 —— cancel / enqueue / freeze **三个线程**都会碰它。

## 五、状态卡片的冻结语义

卡片发出去之后不能一直是"排队中"——用户分不清是在等还是被忘了。四个终态各自对应一张卡片：

| 终态 | 卡片 | 触发点 |
|---|---|---|
| 开始执行 | 「已开始执行」 | `_dequeue_pending_event` 包装，REST patch 原卡 |
| 已取消 | `build_queue_cancelled_card` | `_handle_cancel` |
| 立即执行 | `build_queue_process_now_card` | `_handle_process_now` |
| 已转向 | `build_queue_steered_card` | `_handle_steer` |
| 动作失败 | `*_failed_card` | 三个动作各自的失败分支 |

**失败必须有卡**：只静默 `logger.warning` 的话，用户点了取消、消息没取消、界面没变化，等于"点了没反应"。

## 六、两个非显然的附带修复

这两个都不在"队列"本身的功能描述里，但都是同一路径上被带出来的真 bug：

### 6.1 `MemoryManager._prefetch_provider` 的竞态

快速 FIFO 跟进（上一轮刚结束就接着跑下一轮）时，`queue_prefetch` 还在飞，新一轮的 recall 直接跳过 —— 表现为**紧跟其后的 queue 轮次丢 viking recall 卡片**。

修法：patch `_prefetch_provider`，让快速跟进**短暂等待**在飞的 prefetch，而不是跳过。等的是"这一轮的 recall 已完成"，不是无限等。

### 6.2 steer 模式的图片注入

`busy_input_mode=steer` 时用户发来的消息会插进当前轮次。如果这条消息带图，图片必须一并注入 —— 否则 agent 看到"这张图里的报错怎么解决"却看不到图，只能瞎猜。

`owner/gateway/steer_vision.py` 负责把 `media_urls` 转成轮次内的可见内容。**注意**：`owner/feishu/steer_card.py` 里的卡片回调走 `chat_type="p2p"` + 裸 `open_id`，与普通 bot-menu 命令路径不同，需要单独处理（见该文件注释）。

## 七、可移除性

`revert_patch()` 可整段撤销，恢复上游的原生文本队列行为：

| 删除对象 | 后果 |
|---|---|
| `owner/patches/queue_cancel_patch.py` | 队列退回纯文本 ack，无卡片、无取消/转向/立即执行 |
| `owner/feishu/queue_card.py` | 卡片构建与动作为空，patch 的卡片调用会失败并被捕获 |
| `owner/gateway/steer_vision.py` | steer 模式不再注入图片，其余不受影响 |

三者中 `queue_cancel_patch.py` 是主控，另两者是它的依赖。

## 八、已知缺口

- **文本匹配歧义**：同一文本连续排两次时，第二个 token 依赖状态机挤占，理论上仍存在极端竞态窗口
- **进程内状态**：`_token_state` 不落盘，网关重启后旧卡片上的按钮点下去会"找不到 token"（当前行为是返回失败卡，不是静默）
- **内省脆弱性**：patch 依赖上游方法名。上游重命名时会跳过生效 —— 已用启动日志显式提示，但**不会让测试变红**（这是 `tests/owner` 覆盖不到的形态，需靠运行日志发现）
