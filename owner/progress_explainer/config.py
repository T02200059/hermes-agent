"""读 owner.progress_explainer (patch.yaml), fail-open 返回默认值。

完全复用 owner.patch_config.load_patch_config() (60s TTL + mtime 缓存),
零新加载器 —— 改 patch.yaml 不重启即生效。

enabled 三级查找 (设计稿 §7, 与 owner.diff_card 的写法一致):
    chats.<platform>.<chat_id>  →  platforms.<platform>  →  enabled
"""

from __future__ import annotations

from typing import Any, Dict

_DEFAULTS: Dict[str, Any] = {
    # 总开关默认 false: 落地时不改变现有行为 (设计稿 §7)
    "enabled": False,
    "silence_seconds": 60,
    "stall_seconds": 120,
    "min_interval_seconds": 120,
    "max_per_turn": 5,
    "tick_seconds": 5,
    "events_in_digest": 8,
    "chars_per_event": 200,
    "reasoning_tail_chars": 1500,
    "explainer_timeout_ms": 15000,
    "platforms": {},
    "chats": {},
}

_INT_KEYS = (
    "silence_seconds",
    "stall_seconds",
    "min_interval_seconds",
    "max_per_turn",
    "tick_seconds",
    "events_in_digest",
    "chars_per_event",
    "reasoning_tail_chars",
    "explainer_timeout_ms",
)


def _load_progress_explainer_cfg() -> Dict[str, Any]:
    """从 patch.yaml 读 owner.progress_explainer, fail-open 返回空 dict。"""
    try:
        from owner.patch_config import load_patch_config

        owner = load_patch_config()
        cfg = (owner or {}).get("progress_explainer", {})
        return cfg if isinstance(cfg, dict) else {}
    except Exception:
        return {}


def _coerce_bool(val: Any, default: bool) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        low = val.strip().lower()
        if low in {"true", "yes", "1", "on"}:
            return True
        if low in {"false", "no", "0", "off"}:
            return False
        return default
    if isinstance(val, int):
        return val != 0
    return default


def _coerce_int(val: Any, default: int, minimum: int = 0) -> int:
    try:
        n = int(val)
    except (TypeError, ValueError):
        return default
    return max(minimum, n)


def load_config() -> Dict[str, Any]:
    """返回合并后的配置 (用户值覆盖默认值, 类型校验, 任何异常回落默认)。"""
    raw = _load_progress_explainer_cfg()
    cfg: Dict[str, Any] = {
        "enabled": _coerce_bool(raw.get("enabled"), _DEFAULTS["enabled"])
    }
    for key in _INT_KEYS:
        # tick_seconds 至少 1s, 避免 0/负值把 tick 任务变成忙循环
        minimum = 1 if key == "tick_seconds" else 0
        cfg[key] = _coerce_int(raw.get(key), _DEFAULTS[key], minimum)
    platforms = raw.get("platforms")
    cfg["platforms"] = platforms if isinstance(platforms, dict) else {}
    chats = raw.get("chats")
    cfg["chats"] = chats if isinstance(chats, dict) else {}
    return cfg


def resolve_enabled(platform: str = "", chat_id: Any = None) -> bool:
    """三级查找: chats.<platform>.<chat_id> → platforms.<platform> → enabled。

    chat_id 做 str 归一 (yaml 里 int/str key 混写也能命中)。
    """
    cfg = load_config()
    p = str(platform or "")
    fallback = cfg["enabled"]

    per_chat = cfg["chats"].get(p)
    if isinstance(per_chat, dict) and chat_id is not None:
        key = str(chat_id)
        if key in per_chat:
            return _coerce_bool(per_chat[key], fallback)

    per_platform = cfg["platforms"]
    if p in per_platform:
        return _coerce_bool(per_platform[p], fallback)

    return fallback
