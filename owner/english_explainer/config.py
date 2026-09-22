"""读 owner.english_explainer (patch.yaml)，fail-open 返回默认值。

完全复用 owner.patch_config.load_patch_config()（60s TTL + mtime 缓存），
改 patch.yaml 不重启即生效。enabled 三级查找同 progress_explainer。
"""

from __future__ import annotations

from typing import Any, Dict

_DEFAULTS: Dict[str, Any] = {
    # 总开关默认 false：落地不改变现有行为
    "enabled": False,
    "explainer_timeout_ms": 30000,
    # 空 / auto → auxiliary auto 链（call_llm task=english_explainer）
    "provider": "",
    "model": "",
    "platforms": {},
    "chats": {},
    # 触发后侧路投递；失败不改原文
    "max_source_chars": 4000,
    "max_output_chars": 1200,
}


def _load_raw() -> Dict[str, Any]:
    try:
        from owner.patch_config import load_patch_config

        owner = load_patch_config()
        cfg = (owner or {}).get("english_explainer", {})
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
    raw = _load_raw()
    cfg: Dict[str, Any] = {
        "enabled": _coerce_bool(raw.get("enabled"), _DEFAULTS["enabled"]),
        "explainer_timeout_ms": _coerce_int(
            raw.get("explainer_timeout_ms"), _DEFAULTS["explainer_timeout_ms"], 1
        ),
        "max_source_chars": _coerce_int(
            raw.get("max_source_chars"), _DEFAULTS["max_source_chars"], 200
        ),
        "max_output_chars": _coerce_int(
            raw.get("max_output_chars"), _DEFAULTS["max_output_chars"], 100
        ),
    }
    for key in ("provider", "model"):
        val = str(raw.get(key, "") or "").strip()
        if val.lower() == "auto":
            val = ""
        cfg[key] = val
    platforms = raw.get("platforms")
    cfg["platforms"] = platforms if isinstance(platforms, dict) else {}
    chats = raw.get("chats")
    cfg["chats"] = chats if isinstance(chats, dict) else {}
    return cfg


def resolve_enabled(platform: str = "", chat_id: Any = None) -> bool:
    """三级查找: chats.<platform>.<chat_id> → platforms.<platform> → enabled。"""
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


def display_language_is_chinese() -> bool:
    """顶级约束：仅 display.language 为中文时功能才可能生效。"""
    try:
        from agent.i18n import get_language

        return str(get_language() or "").strip().lower().startswith("zh")
    except Exception:
        return False
