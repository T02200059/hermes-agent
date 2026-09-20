"""[owner] stop-orphan-run: cancel runs whose slot promotion was skipped after /stop|/new.

问题（node010 2026-09-20 实测，详见 owner/docs/design/gateway-stop-orphan-run/）
---------------------------------------------------------------------------
`/stop` 打在「agent 还在后台线程里构造（槽位处于 sentinel）」这个窗口期时：

1. `_interrupt_and_clear_session` 只在槽位里是**真 agent** 时才发中断
   （`if running_agent and running_agent is not _AGENT_PENDING_SENTINEL:`），
   对 sentinel 只做「清槽 + bump generation」；
2. `track_agent()` 随后发现 generation 不是自己的 → **只打一行日志就 return**，
   跳过提升（`Skipping stale agent promotion …`）；
3. 被跳过的那个 run 并没有被中止：它继续在 executor 里跑 `run_conversation`，
   而且在轮次开头就已经拿到了 **durable session turn lease**
   （`state.db::session_turn_leases`，TTL 300s，等待队列最长 1800s）。

最终形态是「孤儿轮次」：**在跑、持租约、但不在内存槽里**。后果：
- 内存槽空 → 后续消息被判定为「会话不忙」→ 走冷路径起新轮次；
- 新轮次在 run_agent 里抢不到 session 级租约 → 排队，每 15s 一条
  「⏳ 仍在等待此会话上的另一个 Hermes 进程（N 秒）…」，最长 30 分钟。

本模块做的事
------------
在 `gateway/run.py::track_agent()` 的 stale 分支里，对那个「已被跳过提升」的
agent 补一次硬中断（与 `/stop` 同一条 API：`agent.interrupt_compat.request_hard_interrupt`）。
孤儿轮次会在下一个检查点退出 → 轮次 finally 释放租约 → 会话立刻恢复可用；
它的结果本来就会被 `Discarding stale agent result` 丢弃，所以不产生额外副作用。

编排方式（符合 owner/docs/二次开发规范.md）
------------------------------------------
- 官方源码只加 5 行薄胶水（`# [owner]` 标记 + 委托），不重排任何既有行；
- 全部逻辑在本文件（upstream 不会碰）；
- 不是 monkey-patch：删掉那段胶水即完全回滚（`revert_patch()` 仅为约定占位）。

行为开关
--------
`~/.hermes/patch.yaml` → `owner.gateway_stop_orphan.enabled`（缺省 `true`）。
只有「等了 N 次仍未提升」的极端场景才需要关掉它（见 `max_defer`）。

为什么不能靠 P1（零源码改动）
----------------------------
判「这个 run 是不是孤儿」需要同时拿到 **generation 已过期** 和 **agent 对象**，
而这两样在 `track_agent()` 里都是闭包局部量（`run_generation` / `agent_holder`），
外部拿不到；用 session_key 打标记再在轮次入口消费，会误伤紧随其后发来的正常消息
（用户在 /stop 后立刻再发一条是常见操作）。因此选择在唯一的精确位置做 5 行委托。
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# 与 /stop 的 _INTERRUPT_REASON_STOP（"Stop requested"）区分开，便于日志归因：
# 这条中断由 owner 的 stop-orphan-run 补发，不是用户当场那次 /stop。
_CANCEL_REASON = "Stop requested (stale run cancelled)"

_DEFAULTS: Dict[str, Any] = {
    "enabled": True,
    # 同一个 (session_key, run_generation) 只补发一次中断。
    "dedupe_ttl_seconds": 3600.0,
    "dedupe_max_entries": 256,
}

# (session_key, run_generation) -> 最近一次补发中断的时间戳
_cancelled: Dict[Tuple[str, Optional[int]], float] = {}


def _config() -> Dict[str, Any]:
    """读取 ``owner.gateway_stop_orphan``（缺省全开；任何异常都回落默认值）。"""
    cfg = dict(_DEFAULTS)
    try:
        from owner.patch_config import _load_patch_owner_config

        section = (_load_patch_owner_config() or {}).get("gateway_stop_orphan") or {}
        if isinstance(section, dict):
            cfg.update({k: v for k, v in section.items() if k in _DEFAULTS})
    except Exception:
        logger.debug("stop_orphan_run: patch.yaml read failed, using defaults", exc_info=True)
    return cfg


def _prune(now: float, ttl: float, max_entries: int) -> None:
    stale = [key for key, ts in _cancelled.items() if now - ts > ttl]
    for key in stale:
        _cancelled.pop(key, None)
    while len(_cancelled) > max_entries:
        oldest = min(_cancelled.items(), key=lambda item: item[1])[0]
        _cancelled.pop(oldest, None)


def _is_current_slot_agent(gateway: Any, session_key: str, agent: Any) -> bool:
    """槽位里现在登记的就是这个 agent → 走官方 /stop 路径即可，无需补发。"""
    try:
        state = gateway._peek_session_state(session_key)
    except Exception:
        return False
    if state is None:
        return False
    return getattr(getattr(state, "turn", None), "agent", None) is agent


def cancel_stale_run(
    gateway: Any,
    session_key: str,
    run_generation: Optional[int],
    agent: Any,
) -> bool:
    """对「被跳过提升」的轮次补一次硬中断。返回是否真的发出了中断。

    只做三件事：判开关 → 去重 → 调 `request_hard_interrupt`。
    fail-open：任何异常都吞掉并返回 False，绝不影响 gateway 主流程。
    """
    try:
        if agent is None:
            return False
        cfg = _config()
        if not cfg.get("enabled", True):
            return False
        if not session_key:
            return False
        if _is_current_slot_agent(gateway, session_key, agent):
            # 已经提升进槽位（说明 /stop 的实时中断路径能管到它），不重复中断。
            return False

        now = time.time()
        key = (session_key, run_generation)
        ttl = float(cfg.get("dedupe_ttl_seconds", _DEFAULTS["dedupe_ttl_seconds"]))
        max_entries = int(cfg.get("dedupe_max_entries", _DEFAULTS["dedupe_max_entries"]))
        _prune(now, ttl, max_entries)
        if key in _cancelled:
            return False
        _cancelled[key] = now

        from agent.interrupt_compat import request_hard_interrupt

        sent = bool(request_hard_interrupt(agent, _CANCEL_REASON))
        if sent:
            logger.info(
                "[owner] stop-orphan-run: cancelled stale run for %s (generation %s) — "
                "it skipped slot promotion after /stop|/new but kept running and holding "
                "the session turn lease",
                session_key,
                run_generation,
            )
        else:
            logger.warning(
                "[owner] stop-orphan-run: agent for %s (generation %s) exposes no interrupt API; "
                "stale run may keep holding the session turn lease",
                session_key,
                run_generation,
            )
        return sent
    except Exception:
        logger.debug("[owner] stop-orphan-run: cancel failed", exc_info=True)
        return False


def revert_patch() -> None:
    """本 patch 由官方文件的 [owner] 薄胶水显式调用，没有 monkey-patch 需要撤销。

    回滚 = 删除 `gateway/run.py::track_agent()` stale 分支里的 5 行委托；
    测试用此函数清空去重表，保证用例之间互不污染。
    """
    _cancelled.clear()


def _reset_state_for_tests() -> None:
    _cancelled.clear()