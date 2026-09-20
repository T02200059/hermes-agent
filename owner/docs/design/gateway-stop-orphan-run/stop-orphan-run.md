# stop-orphan-run：/stop 打在 runner 构造窗口期时会留下「孤儿轮次」

> 记录时间：2026-09-20　|　触发场景：node010 root gateway，飞书单会话
> 代码位置：`gateway/run.py::track_agent()` stale 分支（薄胶水）+ `owner/patches/stop_orphan_run.py`

## 一、现象

庭威（单一飞书 DM，routing key `agent:main:feishu:dm:oc_38253…`）在 15:24 收到：

```
⏳ 另一个 Hermes 进程正在使用此会话；正在等待其结束后再开始本轮…
⏳ 仍在等待此会话上的另一个 Hermes 进程（15 秒）…
⏳ 仍在等待此会话上的另一个 Hermes 进程（30 秒 / 45 秒）…
```

同时网关看起来是空闲的：没有在跑的话题、没有第二个 gateway 在管这个会话、租约 holder
的 PID 就是网关自己。

## 二、根因链（每步都有代码或日志实证）

| # | 事实 | 证据 |
|---|------|------|
| 1 | 15:23:47 用户发「好，操作吧」→ 网关起一轮；起轮时槽位先放 **sentinel**，真 agent 在后台线程异步构造 | `run.py:31131` `agent_holder=[None]`；`run.py:31275` `track_agent()` 注释 "We do this in a callback after the agent is created" |
| 2 | 15:23:59.556 `/stop` → 只「清槽 + bump generation」，**对 sentinel 不发中断** | `_interrupt_and_clear_session` → `if running_agent and running_agent is not _AGENT_PENDING_SENTINEL:`（`run.py:29168`）；日志 `STOP for session … — agent interrupted, session lock released` |
| 3 | 15:23:59.888 那个还在 setup 的 run 建好 agent → 取到 **durable session turn lease** 并落用户消息 | `state.db::session_turn_leases` 行 `pid=3174368:turn=20260920_111407_6ea9d634:aecb0259:platform=feishu`，`acquired_at=epoch 1789889039.888` |
| 4 | 15:23:59.914 `track_agent()` 发现 generation 不是自己的 → **只打日志就 return，跳过提升** | `Skipping stale agent promotion … generation 48 is no longer current`（`run.py:31285-31293`，由 `b7bdf32d4e` 2026-04-23 引入，Closes #11016） |
| 5 | 该 run 继续在 executor 里跑（结果后续被 `Discarding stale agent result` 丢弃），**期间一直持租约** | 15:27:21 `Discarding stale agent result … generation 50`；15:33:19 网关重启才 `killed 1 tool subprocess(es)` |
| 6 | 15:24:27 下一条消息：内存槽是空的 → `_is_session_running(key)` 为假 → 不走忙时分支 → 冷路径起新轮次 → 抢不到 session 级租约 → 每 15s 一条提示 | 15:24:28.618 `inbound message: …`（`_handle_message_with_agent` 的第一行，只有决定起新轮次才会打）；15:24:29.8 起 15s 间隔的等待提示 |

**一句话**：`/stop` 顶掉 generation 时，一个仍在异步 setup 的轮次只被「跳过登记」，没人中止它；
它继续跑并持有 session 级租约 → 后来者在内存槽里看不到它，于是起新轮次去抢租约，被挡下。

## 三、为什么算 bug（两个叠加缺陷）

1. **`/stop` 在 sentinel 窗口期不产生任何中断**（根因，早于 `b7bdf32d4e` 就存在）——
   用户按了停止，工作没停。`b7bdf32d4e` 的注释显式假设「被丢的只是结果」
   （"we'll be discarded by the stale-result check"），没有覆盖「这一轮还在跑」。
2. **孤儿轮次继续持 durable 租约**（放大器，2026-07/08 引入租约后才成立）——
   `agent/turn_facade_lease.py` 语义：TTL 300s、最长等待 1800s、`should_abort` 只看该 agent
   自己的 `_interrupt_requested`。孤儿没人中断 → 租约一直被刷新 → 整个会话被堵住。

**上游状态（2026-09-20 核对）**：`upstream/main @ 9573f44ca5` 仍未修——
`_run_agent_track_agent`（`gateway/run_turn.py:3233-3247`）照样 skip+return；
`_interrupt_running_turn`（`gateway/run_agent_cache.py:449-450/496`）照样对 sentinel 跳过中断，
且注释写着 "the pending-sentinel /stop has no in-flight work"；`agent/` 下 0 处 `run_generation`
引用（run 自身无法感知过时）。本修复是本地补丁，后续可提 upstream。

## 四、方案

**官方源码 5 行薄胶水 + owner/ 全部逻辑**（符合 `owner/docs/二次开发规范.md` P2 最小侵入）：

```python
# gateway/run.py::track_agent() 的 stale 分支，return 之前
# [owner] stop-orphan-run: 这个 run 被跳过提升，但它的执行线程已经在跑并持有
# session turn lease → 补一次硬中断，否则它会挡住该会话的后续消息。
# 实现见 owner/patches/stop_orphan_run.py（fail-open）。
try:
    from owner.patches.stop_orphan_run import cancel_stale_run
    cancel_stale_run(self, session_key, run_generation, agent_holder[0])
except Exception:
    pass
```

`owner/patches/stop_orphan_run.py::cancel_stale_run()` 做三件事：
判开关（`patch.yaml → owner.gateway_stop_orphan.enabled`，缺省 true）→ 去重
（同一 `(session_key, run_generation)` 只补发一次）→ 调
`agent.interrupt_compat.request_hard_interrupt(agent, "Stop requested (stale run cancelled)")`
（与 `/stop` 同一条 API）。孤儿在下一个检查点退出 → 轮次 finally 释放租约 → 会话恢复可用。

### 为什么不用 P1（零源码改动）

判「这个 run 是不是孤儿」需要同时拿到 **generation 已过期**和 **agent 对象**，
而这两者在 `track_agent()` 里都是闭包局部量（`run_generation` / `agent_holder`），外部拿不到。
退而求其次的「/stop 时按 session_key 打标记、轮次入口消费」会误伤紧随其后发来的正常消息
（用户在 `/stop` 后立刻再发一条是常见操作），因此选择在唯一的精确位置做 5 行委托。

## 五、边界与残留风险

- **微秒级窗口**：若 `/stop` 恰好落在「currency 检查通过 → 写入槽位」之间（`run.py:31285` ↔ `31294`），
  该 run 会被正常提升进槽位；此时它没被中断（stop 当时看到的还是 sentinel），但它**在槽位里**，
  后续消息会走忙时分支排队，不会出现「冷路径 + 抢租约」的错配。属于另一类症状（停止不彻底），本补丁不覆盖。
- **长时间 tool call**：硬中断在下一次检查点生效；若孤儿正卡在超长 tool call 里，
  租约仍会被多占一会儿（与 `/stop` 对正常 running agent 的限制一致）。
- **不影响正常路径**：只在 stale 分支触发；`cancel_stale_run` 全函数 fail-open，
  任何异常都吞掉，绝不影响 gateway 主流程。

## 六、验证

- 定向单测：`tests/owner/patches/test_stop_orphan_run.py` 11 passed
  （硬中断/legacy ABI/去重/槽位守卫/无 agent/无 interrupt API/开关关闭/默认开启/probe 抛错/契约接线）
- 回归：`tests/owner/patches/` + `tests/owner/test_contract_entrypoints.py` → 102 passed
  （1 failed 为既有失败 `test_cron_run_job_sets_cron_contextvar_on_real_agent_path`，
  已用 `git stash` 复现确认与本次改动无关）
- 契约测试 `test_gateway_glue_is_wired` 断言 5 行胶水在 `gateway/run.py` 中存在，
  merge 丢失时立即红。

## 七、回滚

删除 `gateway/run.py::track_agent()` stale 分支里的 5 行 `[owner]` 委托即完全回滚
（本补丁不是 monkey-patch）；或用 `patch.yaml` 的 `owner.gateway_stop_orphan.enabled: false` 秒级关闭。