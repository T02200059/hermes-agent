"""progress_explainer — 沉默期进度旁白 dispatcher（owner 模块，官方源码零侵入）。

设计稿：owner/docs/design/silent-progress-narration/progress-explainer.md

接线（全部走 owner 既有通道，gateway/run.py 零改动）：
  1. ``on_stream_delta`` 观察者 → owner-extensions 聚合器（plugin.yaml 声明
     + owner/owner-extensions/__init__.py 调 ``progress_explainer.register_hooks``，
     与 stream_guard 完全同模式）。
  2. 工具事件 → 包装 ``agent.tool_progress_callback`` / ``tool_gen_callback``
     （原回调先执行、后打点、异常吞——观察者绝不影响 token 路径）。
  3. 可见内容 → 包装 ``agent.interim_assistant_callback``（重置静默计时）。
  4. tick 任务 → 网关侧安装（见 gateway/run.py 心跳任务创建点旁的 [owner] 行）。

性能纪律（设计稿 §4）：配置只在安装时读一次（patch.yaml 60s TTL 由
load_patch_config 内部保证）；delta 路径只做计数与切片，不读文件。
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .config import load_config, resolve_enabled
from .tracker import ProgressTracker

logger = logging.getLogger("hermes.owner.progress_explainer")

# ---- 模块级观察者表：session_id|turn_id → ProgressTracker ----
_TRACKERS: Dict[str, ProgressTracker] = {}
_TRACKERS_LOCK = threading.Lock()

# 已经在 owner-extensions 聚合器里注册过 on_stream_delta 的标记
_HOOKS_REGISTERED: Dict[str, bool] = {}

_LAST_DIGEST_HASH_ATTR = "_pe_last_digest_hash"


def register_hooks(ctx: Any) -> None:
    """owner-extensions 聚合器入口（同 stream_guard 模式）。

    注册 on_stream_delta 观察者。任何异常吞掉——观察者绝不影响 token 路径。
    """
    try:
        ctx.register_hook("on_stream_delta", _observe_stream_delta)
        logger.debug("progress_explainer: on_stream_delta hook registered")
    except Exception:
        logger.debug("progress_explainer: hook registration failed", exc_info=True)


def _observe_stream_delta(
    delta: str = "",
    *,
    kind: str = "text",
    session_id: str = "",
    turn_id: str = "",
    **kwargs: Any,
) -> None:
    """on_stream_delta 回调体（在 dispatcher 线程上运行，永不抛）。"""
    try:
        tracker = _tracker_for(session_id, turn_id)
        if tracker is not None:
            tracker.record_stream_delta(kind, delta, time.time())
    except Exception:
        logger.debug("progress_explainer observe failed", exc_info=True)


def _tracker_for(session_id: str, turn_id: str) -> Optional[ProgressTracker]:
    key = f"{session_id}|{turn_id}"
    with _TRACKERS_LOCK:
        return _TRACKERS.get(key)


def _register_tracker(session_id: str, turn_id: str, tracker: ProgressTracker) -> None:
    key = f"{session_id}|{turn_id}"
    with _TRACKERS_LOCK:
        _TRACKERS[key] = tracker


def _rekey_tracker(old_key: str, new_key: str) -> None:
    """[owner] tracker 重键（agent 延迟到 spin-up 后才解出 → key 变化）。

    旧 key（占位 identity）下收到的流增量已累计在同一个 tracker 对象里，
    重键只是让模块级表能按新 key 命中——迁移引用，不换对象、不丢计数。
    新 key 与旧 key 相同（identity 未变）或旧 key 不存在 → 无操作。
    """
    if not old_key or not new_key or old_key == new_key:
        return
    with _TRACKERS_LOCK:
        # 新 key 已被别的 tracker 占用（理论上不可能：同 turn 只有一个）→ 保留现有，丢弃重键
        if new_key in _TRACKERS:
            return
        t = _TRACKERS.pop(old_key, None)
        if t is not None:
            _TRACKERS[new_key] = t


def _unregister_tracker(session_id: str, turn_id: str) -> Optional[ProgressTracker]:
    key = f"{session_id}|{turn_id}"
    with _TRACKERS_LOCK:
        return _TRACKERS.pop(key, None)


# ---------------------------------------------------------------------------
# stream_guard 让位（设计稿 §8）
# ---------------------------------------------------------------------------

_STREAM_GUARD_SNAPSHOT = None


def _stream_guard_snapshot_fn() -> Optional[Callable]:
    """拿到 stream_guard.snapshot()（只在第一次调用时 import，成功后缓存）。

    snapshot() 是设计稿 §8 要求 stream_guard 新增的公开只读函数。若上游
    尚未实现（AttributeError），返回 None —— 本模块照常工作，不让位判定
    缺席阻塞功能。
    """
    global _STREAM_GUARD_SNAPSHOT
    if _STREAM_GUARD_SNAPSHOT is None:
        try:
            # owner-extensions 目录名不可 import（tests/owner/test_stream_guard.py
            # 同样用 importlib 按路径加载），按文件路径加载一次并缓存模块。
            import importlib.util as _ilu

            _path = (
                Path(__file__).resolve().parents[2]
                / "owner"
                / "owner-extensions"
                / "stream_guard"
                / "__init__.py"
            )
            _spec = _ilu.spec_from_file_location("owner_stream_guard_for_pe", _path)
            if _spec is not None and _spec.loader is not None:
                _mod = _ilu.module_from_spec(_spec)
                _spec.loader.exec_module(_mod)
                fn = getattr(_mod, "snapshot", None)
                _STREAM_GUARD_SNAPSHOT = fn if callable(fn) else False
            else:
                _STREAM_GUARD_SNAPSHOT = False
        except Exception:
            _STREAM_GUARD_SNAPSHOT = False
    return _STREAM_GUARD_SNAPSHOT or None


def _stream_guard_tripped(session_id: str, turn_id: str) -> bool:
    fn = _stream_guard_snapshot_fn()
    if fn is None:
        return False
    try:
        snap = fn(session_id, turn_id)
        return bool(snap and snap.get("tripped"))
    except Exception:
        return False


# ---------------------------------------------------------------------------
# ProgressExplainer：一个网关 turn 的运行时
# ---------------------------------------------------------------------------


class ProgressExplainer:
    """一个网关 turn 的 progress_explainer 运行时。

    install() 之后：
      - agent 三个回调被包装（tool_progress / tool_gen / interim_assistant）；
      - on_stream_delta 经模块级表喂 tracker；
      - tick 任务每 tick_seconds 醒一次，按设计稿 §5.2 决策树判定。
    stop() 时：tick 任务取消、回调还原、tracker 注销。
    """

    def __init__(
        self,
        runner: Any,
        agent: Any = None,
        source: Any = None,
        session_key: Optional[str] = None,
        turn_ctx: Any = None,
        executor_ref: Optional[Callable[[], Any]] = None,
        agent_holder: Optional[Any] = None,
    ) -> None:
        self._runner = runner
        self._agent = agent
        self._source = source
        self._session_key = session_key
        self._turn_ctx = turn_ctx
        self._executor_ref = executor_ref
        # [owner] 方案①惰性解 agent：安装点在 agent_holder=[None] 初始化后、
        # executor 线程创建 agent 之前同步执行（run.py 31131→31496→31623），
        # 此刻读 agent 必为 None。改为持引用（list 容器或 callable），
        # tick / 回调包装都延迟到首次解出非 None 再消费——对齐网关
        # executor_ref=lambda: _executor_task 的既有惯例。
        # agent_holder 可传：list 容器（[agent]）或 callable（返回 agent）。
        self._agent_holder = agent_holder if agent_holder is not None else ([agent] if agent is not None else None)
        # 性能纪律：配置只在安装时读一次（§4），tick 循环里只读缓存值
        self._cfg = load_config()
        self._platform = str(getattr(source, "platform", "") or "") if source is not None else ""
        self._chat_id = str(getattr(source, "chat_id", "") or "") if source is not None else ""
        # identity 占位：agent 未解出前 tracker 先按 session_key 注册（唯一、
        # 非 None —— 安装点已保证 session_key 可用），agent 解出后重键到
        # "session_id|turn_id"（与 on_stream_delta payload 的 key 一致）。
        self._session_id = str(session_key or "")
        self._turn_id = ""
        self._identity_resolved = False
        # 回调包装的幂等锚：同一 agent 实例只包一次（agent=None 阶段不包）
        self._wrapped_agent_id: Optional[int] = None
        self._tracker = ProgressTracker(
            turn_started_at=time.time(),
            user_message=str(getattr(turn_ctx, "message", "") or ""),
            cfg=self._cfg,
        )
        self._orig_tool_progress_cb = getattr(agent, "tool_progress_callback", None)
        self._orig_tool_gen_cb = getattr(agent, "tool_gen_callback", None)
        self._orig_interim_cb = getattr(agent, "interim_assistant_callback", None)
        self._tick_task: Optional[asyncio.Task] = None
        self._stopped = False
        self._sending = False
        self._send_done_cb: Optional[Callable[[bool], None]] = None
        # 已发出 digest_hash（§5.4 去重）
        self._last_digest_hash: Optional[str] = None

    # ---- 安装 ----

    def _resolve_agent(self) -> Any:
        """惰性解 agent（方案①）：优先 agent_holder（list 容器或 callable），
        回落构造期传入的静态 agent。任何异常 → None。"""
        try:
            holder = self._agent_holder
            if holder is not None:
                if callable(holder) and not isinstance(holder, list):
                    return holder()
                return holder[0] if isinstance(holder, list) and holder else None
        except Exception:
            return None
        return self._agent

    def _sync_identity_and_callbacks(self) -> None:
        """tick 每轮调用：agent 解出后做一次重键 + 回调包装（幂等）。

        重键：tracker 从占位 key（session_key）迁到真 key（session_id|turn_id），
        与 on_stream_delta payload 对齐——此前按占位 key 收到的流增量已累计
        在同一 tracker 里，重键不丢数据。
        回调包装：同一 agent 实例（id 锚定）只包一次，包装前先存原回调。
        """
        agent = self._resolve_agent()
        if agent is None:
            return
        if self._identity_resolved and self._wrapped_agent_id == id(agent):
            return

        if not self._identity_resolved:
            new_sid = str(getattr(agent, "session_id", "") or "") or self._session_id
            new_tid = str(getattr(agent, "_current_turn_id", None) or "")
            _rekey_tracker(f"{self._session_id}|{self._turn_id}", f"{new_sid}|{new_tid}")
            self._session_id, self._turn_id = new_sid, new_tid
            self._identity_resolved = True

        # 回调包装（幂等：换 agent 实例才重包）
        if self._wrapped_agent_id == id(agent):
            return
        tracker = self._tracker
        orig_tool_progress = getattr(agent, "tool_progress_callback", None)

        def _tool_progress_cb(event_type: str, *args, **kwargs) -> None:
            if orig_tool_progress is not None:
                try:
                    orig_tool_progress(event_type, *args, **kwargs)
                except Exception:
                    logger.debug("pe: orig tool_progress error", exc_info=True)
            try:
                tracker.record_tool_event(
                    ProgressExplainer._event_from_cb(event_type, args, kwargs)
                )
            except Exception:
                logger.debug("pe: record tool event failed", exc_info=True)

        agent.tool_progress_callback = _tool_progress_cb

        orig_tool_gen = getattr(agent, "tool_gen_callback", None)

        def _tool_gen_cb(tool_name: str) -> None:
            if orig_tool_gen is not None:
                try:
                    orig_tool_gen(tool_name)
                except Exception:
                    pass
            try:
                tracker.record_tool_event(
                    {"phase": "tool_gen", "name": str(tool_name or ""), "ts": time.time()}
                )
            except Exception:
                pass

        agent.tool_gen_callback = _tool_gen_cb

        orig_interim = getattr(agent, "interim_assistant_callback", None)

        def _interim_cb(text: Any, *args, **kwargs) -> None:
            if orig_interim is not None:
                try:
                    orig_interim(text, *args, **kwargs)
                except Exception:
                    pass
            try:
                tracker.record_content_emitted()
            except Exception:
                pass

        agent.interim_assistant_callback = _interim_cb
        self._wrapped_agent_id = id(agent)

    def install(self) -> "ProgressExplainer":
        tracker = self._tracker
        # on_stream_delta 观察者（模块级表，先按占位 identity 注册）
        _register_tracker(self._session_id, self._turn_id, tracker)

        tick_seconds = self._tick_seconds()
        self._tick_task = asyncio.create_task(self._tick_loop())
        logger.debug(
            "progress_explainer installed (platform=%s chat=%s tick=%ss lazy-agent=%s)",
            self._platform,
            self._chat_id,
            tick_seconds,
            self._agent_holder is not None,
        )
        return self

    def _tick_seconds(self) -> float:
        try:
            v = int(self._cfg.get("tick_seconds", 5))
            return max(1, v)
        except (TypeError, ValueError):
            return 5.0

    @staticmethod
    def _event_from_cb(event_type: str, args: tuple, kwargs: dict) -> Dict[str, Any]:
        """tool_executor 回调签名 → tracker 事件 dict。

        started: cb("tool.started", function_name, preview, display_args)
        completed: cb("tool.completed", name, None, None,
                      duration=, is_error=, result=)
        """
        ev: Dict[str, Any] = {
            # phase 归一化：tool_executor 回调传 "tool.started"/"tool.completed"，
            # tracker 只认 "started"/"completed"（_STARTED_PHASES）
            "phase": str(event_type or "").split(".")[-1],
            "ts": time.time(),
        }
        # wrapper 收到 cb(event_type, *args)：args[0]=name, args[1]=preview, args[2]=display_args
        if len(args) > 0 and args[0] is not None:
            ev["name"] = str(args[0])
        if len(args) > 1 and args[1] is not None:
            ev["preview"] = str(args[1])
        if len(args) > 2 and args[2] is not None:
            ev["args_preview"] = str(args[2])
        if "duration" in kwargs:
            ev["duration"] = kwargs["duration"]
        if "is_error" in kwargs:
            ev["is_error"] = bool(kwargs["is_error"])
        if "result" in kwargs:
            ev["result"] = str(kwargs["result"])
        return ev

    # ---- tick 循环（§5.2 决策树） ----

    async def _tick_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self._tick_seconds())
                if self._stopped:
                    return
                try:
                    await self._tick_once()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.debug("progress_explainer tick error", exc_info=True)
        except asyncio.CancelledError:
            return

    async def _tick_once(self) -> None:
        if self._sending:
            return
        # 惰性同步：agent 解出后重键 tracker + 包装回调（幂等，一次生效）
        self._sync_identity_and_callbacks()
        cfg = self._cfg
        if not bool(cfg.get("enabled", False)):
            return
        if self._resolve_agent() is None:
            return  # agent 尚未 spin-up：无活动可报，静默等下一轮
        if not self._run_still_current():
            return
        state = self._tracker.state()
        if state["silence_seconds_since_last_content"] < float(
            cfg.get("silence_seconds", 60)
        ):
            return
        last_ts = state.get("last_explainer_ts")
        if last_ts is not None:
            if (time.time() - float(last_ts)) < float(cfg.get("min_interval_seconds", 120)):
                return
        if state["explainer_count"] >= int(cfg.get("max_per_turn", 5)):
            return
        # §8 让位：stream_guard tripped → 静默让位
        if _stream_guard_tripped(self._session_id, self._turn_id):
            return
        # §5.4 去重：digest 相同且非停滞分支 → 不发
        if (
            self._last_digest_hash is not None
            and state["branch"] != "stall"
            and state["digest_hash"] == self._last_digest_hash
        ):
            return

        adapter = self._adapter()
        if adapter is None:
            return

        from .digest import build_digest
        from .explain import explain as _explain
        from .prompt import PREFIX

        tracker_state = dict(state)
        tracker_state["digest"] = build_digest(state, cfg)
        activity = self._activity_summary()
        tracker_state["hard_facts"] = self._hard_facts(state, activity)

        from agent.i18n import get_language

        self._sending = True
        try:
            text = await _explain(
                state=tracker_state,
                cfg=cfg,
                user_message=self._tracker.user_message,
                language=get_language(),
            )
        finally:
            self._sending = False
        if not text:
            return  # 辅助模型失败 → 静默丢弃（§9），下个 tick 自然重试

        fact_line = self._fact_line(activity)
        body = f"{PREFIX}{text}" + (f"\n{fact_line}" if fact_line else "")

        # 发送前重验 run 存活（§13）
        if not self._run_still_current():
            return
        try:
            res = await adapter.send(self._chat_id, body)
        except Exception as exc:
            logger.debug("progress_explainer send failed: %s", exc)
            return
        if not (res and getattr(res, "success", False)):
            return
        self._last_digest_hash = state["digest_hash"]
        self._tracker.record_explainer_sent()
        # cleanup_progress：登记 message id，随成功收尾清理（§6）
        msg_id = getattr(res, "message_id", None)
        if msg_id and bool(self._cfg.get("cleanup_progress", False)):
            cleanup_ids = getattr(self._turn_ctx, "_cleanup_msg_ids", None)
            if cleanup_ids is not None and hasattr(cleanup_ids, "append"):
                try:
                    cleanup_ids.append(str(msg_id))
                except Exception:
                    pass

    # ---- 辅助方法 ----

    def _run_still_current(self) -> bool:
        """抄 _should_emit_long_running_notification 判法（gateway/run.py:12047）。

        agent is None / executor done / session slot 被换 → 不再发。
        [owner] 方案①：agent 经 _resolve_agent() 惰性解——executor 线程
        spin-up 完成前 holder 为空，此时 run 必然 current（判定只会在
        tick 已解出 agent 后给出「不再 current」的结论）。
        """
        agent = self._resolve_agent() or self._agent
        if agent is None:
            return False
        try:
            exec_ref = self._executor_ref() if callable(self._executor_ref) else self._executor_ref
        except Exception:
            exec_ref = None
        if exec_ref is not None and getattr(exec_ref, "done", lambda: False)():
            return False
        if self._session_key:
            try:
                hb_state = self._runner._peek_session_state(self._session_key)
                current_agent = (
                    getattr(hb_state.turn, "agent", None) if hb_state and hb_state.turn else None
                )
                if current_agent is not agent:
                    return False
            except Exception:
                pass
        return True

    def _adapter(self):
        try:
            return self._runner._adapter_for_source(self._source)
        except Exception:
            return None

    def _activity_summary(self) -> Dict[str, Any]:
        try:
            agent = self._resolve_agent() or self._agent
            a = agent.get_activity_summary()
            return a if isinstance(a, dict) else {}
        except Exception:
            return {}

    def _hard_facts(self, state: dict, activity: dict) -> Dict[str, Any]:
        facts: Dict[str, Any] = {
            "elapsed_seconds": int(
                max(0.0, state.get("now", 0) - state.get("turn_started_at", 0))
            ),
            "branch": state.get("branch", ""),
        }
        if activity.get("current_tool"):
            facts["current_tool"] = str(activity["current_tool"])
        elif activity.get("last_activity_desc"):
            facts["current_tool"] = str(activity["last_activity_desc"])
        if "api_call_count" in activity:
            facts["iteration"] = (
                f"{activity['api_call_count']}/{activity.get('max_iterations', '?')}"
            )
        try:
            from hermes_cli.config import load_config as _load_user_config

            _agent_cfg = _load_user_config().get("agent", {}) or {}
            facts["gateway_timeout_s"] = int(_agent_cfg.get("gateway_timeout", 1800))
            facts["watchdog_timeout_s"] = 600
            facts["suggested_action"] = "/stop"
        except Exception:
            pass
        return facts

    def _fact_line(self, activity: dict) -> str:
        parts = []
        if activity.get("current_tool"):
            parts.append(str(activity["current_tool"]))
        elif activity.get("last_activity_desc"):
            parts.append(str(activity["last_activity_desc"]))
        if "api_call_count" in activity:
            parts.append(
                f"iteration {activity['api_call_count']}/{activity.get('max_iterations', '?')}"
            )
        if not parts:
            return ""
        return " — ".join(str(p) for p in parts if p)

    # ---- 停止 ----

    def stop(self) -> None:
        self._stopped = True
        task = self._tick_task
        if task is not None and not task.done():
            task.cancel()
        agent = self._resolve_agent() or self._agent
        if agent is not None:
            try:
                if getattr(agent, "tool_progress_callback", None) is not None:
                    agent.tool_progress_callback = self._orig_tool_progress_cb
                agent.tool_gen_callback = self._orig_tool_gen_cb
                agent.interim_assistant_callback = self._orig_interim_cb
            except Exception:
                pass
        _unregister_tracker(self._session_id, self._turn_id)

    @property
    def tracker(self) -> ProgressTracker:
        return self._tracker


# ---------------------------------------------------------------------------
# 安装 / 停止入口（网关侧调用）
# ---------------------------------------------------------------------------


def install_progress_explainer(
    runner: Any,
    agent: Any = None,
    source: Any = None,
    session_key: Optional[str] = None,
    turn_ctx: Any = None,
    executor_ref: Optional[Callable[[], Any]] = None,
    agent_holder: Optional[Any] = None,
) -> Optional[ProgressExplainer]:
    """网关侧安装入口（fail-open：任何异常 → None，不影响主流程）。

    在 gateway/run.py 心跳任务创建点附近调用（设计稿 §3/§10）。enabled=false
    或平台/chat 未启用时返回 None，零开销。

    [owner] 方案①（2026-09-20 修正）：安装点早于 agent spin-up（run.py
    31496 在 31131 agent_holder=[None] 之后、31623 executor 创建之前），
    此刻 agent 必为 None——传 agent_holder（list 容器或 callable）做惰性
    解出，tick 首轮解出 agent 后重键 tracker 并包装回调。旧的「同步读
    agent_holder[0] 传值」写法会因 None 直接 return None，tick 循环
    从未启动（上线首日 0 旁白的事故根因）。agent=None + 无 holder →
    返回 None（兼容旧行为：确实没有 agent 可观察）。
    """
    try:
        platform = str(getattr(source, "platform", "") or "")
        chat_id = str(getattr(source, "chat_id", "") or "")
        if not resolve_enabled(platform, chat_id):
            return None
        if agent is None and agent_holder is None:
            return None
        if not session_key:
            return None
        inst = ProgressExplainer(
            runner=runner,
            agent=agent,
            source=source,
            session_key=session_key,
            turn_ctx=turn_ctx,
            executor_ref=executor_ref,
            agent_holder=agent_holder,
        )
        return inst.install()
    except Exception:
        logger.debug("progress_explainer install failed", exc_info=True)
        return None


def stop(explainer: Optional[ProgressExplainer]) -> None:
    """停止并清理（fail-open）。网关 finally 块调用。"""
    try:
        if explainer is not None:
            explainer.stop()
    except Exception:
        logger.debug("progress_explainer stop failed", exc_info=True)
