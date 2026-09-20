"""Per-turn 进度状态跟踪 (线程安全)。

回调在工具线程写、tick 在事件循环读 —— 只共享锁保护的标量与短列表,
不读 agent.messages (设计稿 §13)。分支判定按设计稿 §5.3:

    current_tool 非空 或 最近 60s 内有 tool started  → tool
    30s 内有 kind="reasoning" 增量                   → reasoning
    30s 内有 kind="text" 增量                        → text
    无 chunk 且无工具活动 > stall_seconds            → stall

digest_hash 对"事实"哈希 (分支/当前工具/累计字符/思考尾摘录/事件序列),
刻意不含时间戳: 事实不变 → 同 hash (§5.2 去重), 事实变化 → hash 变化,
文案随事实自然更新 (§5.4 允许每 min_interval 重发)。
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import deque
from typing import Any, Dict, Optional

_EVENTS_MAXLEN = 64
_DEFAULT_TAIL_CHARS = 1500
_DEFAULT_STALL_SECONDS = 120
_TOOL_RECENT_SECONDS = 60
_STREAM_RECENT_SECONDS = 30
_STARTED_PHASES = frozenset({"started", "start"})
_ENDED_PHASES = frozenset({"completed", "complete", "error", "failed", "done", "end"})


def _now() -> float:
    return time.time()


class ProgressTracker:
    """一轮 turn 的证据累计器。构造时读一次配置, delta 路径只计数与切片。"""

    def __init__(
        self,
        turn_started_at: float,
        user_message: str = "",
        cfg: Optional[Dict[str, Any]] = None,
    ) -> None:
        cfg = cfg if isinstance(cfg, dict) else {}
        self.turn_started_at = float(turn_started_at)
        self.user_message = user_message or ""
        # 配置只在构造时读一次 (设计稿 §4 性能纪律: 禁止在 delta 里读配置)
        try:
            self._tail_limit = max(0, int(cfg.get("reasoning_tail_chars", _DEFAULT_TAIL_CHARS)))
        except (TypeError, ValueError):
            self._tail_limit = _DEFAULT_TAIL_CHARS
        try:
            self._stall_seconds = max(1, int(cfg.get("stall_seconds", _DEFAULT_STALL_SECONDS)))
        except (TypeError, ValueError):
            self._stall_seconds = _DEFAULT_STALL_SECONDS

        self._lock = threading.Lock()
        self._events: "deque" = deque(maxlen=_EVENTS_MAXLEN)
        self._reasoning_chars = 0
        self._text_chars = 0
        self._last_reasoning_ts: Optional[float] = None
        self._last_text_ts: Optional[float] = None
        self._reasoning_tail = ""
        # silence 计时起点 = turn 开始时间 (设计稿 §5.2)
        self._last_content_ts = float(turn_started_at)
        self._current_tool: Optional[str] = None
        self._current_tool_started_ts: Optional[float] = None
        self._last_tool_started_ts: Optional[float] = None
        self._explainer_count = 0
        self._last_explainer_ts: Optional[float] = None

    # ---- 写路径 (工具线程 / 流回调线程) ----

    def record_tool_event(self, event: Dict[str, Any]) -> None:
        """工具事件打点: started / completed 等。容错: 非法输入静默丢弃。"""
        try:
            ev: Dict[str, Any] = dict(event) if isinstance(event, dict) else {"raw": str(event)}
        except Exception:
            return
        ts = ev.get("ts")
        if not isinstance(ts, (int, float)):
            ts = _now()
            ev["ts"] = ts
        phase = str(ev.get("phase") or ev.get("type") or "").lower()
        name = ev.get("name") or ev.get("tool") or ev.get("tool_name")
        with self._lock:
            self._events.append(ev)
            if phase in _STARTED_PHASES:
                self._last_tool_started_ts = float(ts)
                if name:
                    self._current_tool = str(name)
                    self._current_tool_started_ts = float(ts)
            elif phase in _ENDED_PHASES:
                self._current_tool = None
                self._current_tool_started_ts = None

    def record_stream_delta(self, kind: str, delta: str, ts: float) -> None:
        """流增量统计: 累计字符 + 最近活动 ts; reasoning 另存尾部摘录。"""
        if not delta:
            return
        try:
            ts = float(ts)
        except (TypeError, ValueError):
            ts = _now()
        k = str(kind or "").lower()
        with self._lock:
            if k == "reasoning":
                self._reasoning_chars += len(delta)
                self._last_reasoning_ts = ts
                if self._tail_limit > 0:
                    self._reasoning_tail = (self._reasoning_tail + delta)[
                        -self._tail_limit :
                    ]
                else:
                    self._reasoning_tail = ""
            elif k == "text":
                self._text_chars += len(delta)
                self._last_text_ts = ts
            # 其它 kind 忽略: 设计稿只定义 text / reasoning 两种

    def record_content_emitted(self) -> None:
        """用户可见内容 (interim 散文等) 已出现 → 重置静默计时 (§5.1)。"""
        with self._lock:
            self._last_content_ts = _now()

    def record_explainer_sent(self) -> None:
        """本模块自己发的系统提示也计入可见内容, 否则刚发完就再次触发 (§5.1)。"""
        with self._lock:
            self._explainer_count += 1
            now = _now()
            self._last_explainer_ts = now
            self._last_content_ts = now

    # ---- 读路径 (tick / 事件循环线程) ----

    def state(self) -> Dict[str, Any]:
        """一致性快照: 静默秒数 / 停滞检测 / 分支 / 流统计 / digest_hash。"""
        now = _now()
        with self._lock:
            silence = max(0.0, now - self._last_content_ts)

            tool_recent = self._current_tool is not None or (
                self._last_tool_started_ts is not None
                and (now - self._last_tool_started_ts) <= _TOOL_RECENT_SECONDS
            )
            reasoning_recent = self._last_reasoning_ts is not None and (
                now - self._last_reasoning_ts
            ) <= _STREAM_RECENT_SECONDS
            text_recent = self._last_text_ts is not None and (
                now - self._last_text_ts
            ) <= _STREAM_RECENT_SECONDS

            if tool_recent:
                branch = "tool"
            elif reasoning_recent:
                branch = "reasoning"
            elif text_recent:
                branch = "text"
            elif silence >= self._stall_seconds:
                branch = "stall"
            else:
                # 灰区: 无近期 chunk/工具活动但未到 stall 阈值, 归入 text
                # (tick 只在 silence >= silence_seconds 后才真正触发)
                branch = "text"

            # 停滞检测: 无 chunk 且无工具活动 > stall_seconds (§5.3 停滞型)
            candidates = [
                self._last_reasoning_ts,
                self._last_text_ts,
                self._last_tool_started_ts,
                self.turn_started_at,
            ]
            last_activity = max(t for t in candidates if t is not None)
            stalled = (now - last_activity) > self._stall_seconds

            snapshot: Dict[str, Any] = {
                "now": now,
                "turn_started_at": self.turn_started_at,
                "user_message": self.user_message,
                "silence_seconds_since_last_content": silence,
                "stalled": stalled,
                "stall_seconds": self._stall_seconds,
                "branch": branch,
                "current_tool": self._current_tool,
                "current_tool_started_ts": self._current_tool_started_ts,
                "last_tool_started_ts": self._last_tool_started_ts,
                "stream": {
                    "reasoning_chars_total": self._reasoning_chars,
                    "text_chars_total": self._text_chars,
                    "last_reasoning_ts": self._last_reasoning_ts,
                    "last_text_ts": self._last_text_ts,
                    "reasoning_tail": self._reasoning_tail,
                    "reasoning_tail_chars_limit": self._tail_limit,
                },
                "events": [dict(ev) for ev in self._events],
                "explainer_count": self._explainer_count,
                "last_explainer_ts": self._last_explainer_ts,
            }

        # 锁外计算: 对事实哈希, 不含时间戳 → 事实不变即同 hash (§5.2/§5.4)
        snapshot["digest_hash"] = _digest_hash(snapshot)
        return snapshot


def _digest_hash(snapshot: Dict[str, Any]) -> str:
    basis = {
        "branch": snapshot["branch"],
        "current_tool": snapshot["current_tool"],
        "reasoning_chars_total": snapshot["stream"]["reasoning_chars_total"],
        "text_chars_total": snapshot["stream"]["text_chars_total"],
        "reasoning_tail": snapshot["stream"]["reasoning_tail"],
        "events": [
            (str(ev.get("phase") or ev.get("type") or ""), str(ev.get("name") or ""))
            for ev in snapshot["events"]
        ],
    }
    blob = json.dumps(basis, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]
