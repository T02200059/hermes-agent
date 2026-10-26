"""读 owner.checkpoints (patch.yaml), fail-open 返回默认值。

完全复用 owner.patch_config.load_patch_config() (60s TTL + mtime 缓存),
零新加载器。
"""

from __future__ import annotations

from typing import Any, Dict

_DEFAULTS: Dict[str, Any] = {
    "predict_enabled": True,
    "predict_llm_timeout_ms": 3000,
    "predict_cache_size": 32,
    "predict_static_threshold": 1,
}


def _load_owner_checkpoints_cfg() -> Dict[str, Any]:
    """从 patch.yaml 读 owner.checkpoints, fail-open 返回空 dict。"""
    try:
        from owner.patch_config import load_patch_config

        owner = load_patch_config()
        cp = owner.get("checkpoints", {})
        return cp if isinstance(cp, dict) else {}
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


def get_checkpoints_cfg() -> Dict[str, Any]:
    """返回合并后的 checkpoints 配置 (用户值覆盖默认值, 类型校验)。"""
    raw = _load_owner_checkpoints_cfg()
    return {
        "predict_enabled": _coerce_bool(
            raw.get("predict_enabled"), _DEFAULTS["predict_enabled"]
        ),
        "predict_llm_timeout_ms": _coerce_int(
            raw.get("predict_llm_timeout_ms"), _DEFAULTS["predict_llm_timeout_ms"]
        ),
        "predict_cache_size": _coerce_int(
            raw.get("predict_cache_size"), _DEFAULTS["predict_cache_size"]
        ),
        "predict_static_threshold": _coerce_int(
            raw.get("predict_static_threshold"),
            _DEFAULTS["predict_static_threshold"],
        ),
    }
