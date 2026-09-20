"""读 owner.approval_explainer (patch.yaml), fail-open 返回默认值。

完全复用 owner.patch_config.load_patch_config() (60s TTL + mtime 缓存),
零新加载器 —— 改 patch.yaml 不重启即生效 (与 progress_explainer.config
同构)。

enabled 三级查找 (chats.<platform>.<chat_id> → platforms.<platform> →
enabled), 写法与 owner.diff_card / progress_explainer 一致。

模型解析语义 (2026-09-20 定稿):
    provider/model 未配置或为 "auto"  →  传 None → call_llm(task=...)
    走 auxiliary auto 链 (config.yaml auxiliary.approval_explainer 有配置
    则按任务段; 否则回落主聊天模型 —— 承接 hermes 自己的配置体系)。
    显式 provider/model  →  作为 call_llm 显式参数直连 (最高优先)。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

# 落地默认值: enabled=False (不改现有行为); timeout 30s (2026-09-20 定稿,
# 与 progress_explainer 对齐)。
_DEFAULTS: Dict[str, Any] = {
    "enabled": False,
    "timeout_ms": 30000,
    "provider": "",
    "model": "",
    "description_max_chars": 500,
    "cache_ttl_seconds": 600,
    "cache_max_entries": 128,
    "platforms": {},
    "chats": {},
}

_INT_KEYS = (
    "timeout_ms",
    "description_max_chars",
    "cache_ttl_seconds",
    "cache_max_entries",
)


def _load_approval_explainer_cfg() -> Dict[str, Any]:
    """从 patch.yaml 读 owner.approval_explainer, fail-open 返回空 dict。"""
    try:
        from owner.patch_config import load_patch_config

        owner = load_patch_config()
        cfg = (owner or {}).get("approval_explainer", {})
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


def _norm_model_field(val: Any) -> str:
    """provider/model 归一: "auto" 语义 = 走 auxiliary auto 链 → 空串。"""
    s = str(val or "").strip()
    if s.lower() == "auto":
        return ""
    return s


def load_config() -> Dict[str, Any]:
    """返回合并后的配置 (用户值覆盖默认值, 类型校验, 任何异常回落默认)。"""
    raw = _load_approval_explainer_cfg()
    cfg: Dict[str, Any] = {
        "enabled": _coerce_bool(raw.get("enabled"), _DEFAULTS["enabled"])
    }
    for key in _INT_KEYS:
        cfg[key] = _coerce_int(raw.get(key), _DEFAULTS[key])
    cfg["provider"] = _norm_model_field(raw.get("provider", ""))
    cfg["model"] = _norm_model_field(raw.get("model", ""))
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


def resolve_model(cfg: Dict[str, Any]) -> "tuple[Optional[str], Optional[str]]":
    """(provider, model) 解析: 空串 → (None, None) → auxiliary auto 链。"""
    provider = str((cfg or {}).get("provider", "") or "").strip() or None
    model = str((cfg or {}).get("model", "") or "").strip() or None
    return provider, model
