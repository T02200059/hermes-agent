"""Strike 逻辑、PASS/BLOCK/HALT 决策、线程安全会话状态。

- 第 1 次 BLOCK → 警告（仍 BLOCK）
- 第 2 次 BLOCK → 升级为 HALT（max_strikes 默认 2）
- Hardline 直接 HALT，不走 strike 计数
- key = session_id or id(agent)；turn_id 变化时重置；TTL 30min 防泄漏
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

_TTL_SECONDS = 30 * 60  # 30 min


@dataclass
class _SessionStrike:
    strikes: int = 0
    turn_id: Any = None
    last_seen: float = field(default_factory=time.time)


_lock = threading.Lock()
_states: Dict[str, _SessionStrike] = {}


def session_key(agent: Any) -> str:
    sid = getattr(agent, "session_id", None)
    if sid:
        return str(sid)
    return f"agent:{id(agent)}"


def turn_id_of(agent: Any) -> Any:
    for attr in ("_current_turn_id", "_user_turn_count", "_turn_count"):
        val = getattr(agent, attr, None)
        if val is not None:
            return val
    return None


def _purge_expired(now: float) -> None:
    dead = [k for k, st in _states.items() if now - st.last_seen > _TTL_SECONDS]
    for k in dead:
        del _states[k]


def _get_state(agent: Any) -> _SessionStrike:
    key = session_key(agent)
    now = time.time()
    _purge_expired(now)
    st = _states.get(key)
    if st is None:
        st = _SessionStrike(turn_id=turn_id_of(agent), last_seen=now)
        _states[key] = st
        return st
    st.last_seen = now
    tid = turn_id_of(agent)
    if tid is not None and st.turn_id is not None and tid != st.turn_id:
        st.strikes = 0
        st.turn_id = tid
    elif st.turn_id is None and tid is not None:
        st.turn_id = tid
    return st


def get_strikes(agent: Any) -> int:
    with _lock:
        return _get_state(agent).strikes


def record_block(agent: Any) -> int:
    """Increment strike count; return new count."""
    with _lock:
        st = _get_state(agent)
        st.strikes += 1
        return st.strikes


def reset_strikes(agent: Any) -> None:
    with _lock:
        st = _get_state(agent)
        st.strikes = 0


def clear_session(agent: Any) -> None:
    with _lock:
        _states.pop(session_key(agent), None)


def clear_all() -> None:
    """Test helper."""
    with _lock:
        _states.clear()


def merge_batch_decision(verdicts: Dict[str, str]) -> str:
    """Aggregate per-call verdicts into batch decision.

    - any HALT → HALT (whole batch stops)
    - else any BLOCK → BLOCK (filter blocked, rest continue)
    - else PASS
    """
    vals = {(v or "PASS").upper() for v in verdicts.values()}
    if "HALT" in vals:
        return "HALT"
    if "BLOCK" in vals:
        return "BLOCK"
    return "PASS"


def should_skip_for_yolo(cfg: Dict[str, Any]) -> bool:
    """Only skip audit when respect_yolo=True AND yolo is active."""
    if not cfg.get("respect_yolo"):
        return False
    try:
        from tools.approval import (
            _YOLO_MODE_FROZEN,
            is_current_session_yolo_enabled,
        )

        return bool(_YOLO_MODE_FROZEN or is_current_session_yolo_enabled())
    except Exception:
        return False


def is_cron_session(agent: Any) -> bool:
    platform = str(getattr(agent, "platform", "") or "").lower()
    return platform == "cron"
