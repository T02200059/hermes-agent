"""语义审计配置读取。

优先读用户 config.yaml 的 ``semantic_audit`` / ``auxiliary.semantic_audit``，
缺省使用本模块内置默认值。不改 hermes_cli/config.py DEFAULT_CONFIG
（官方文件零侵入；用户可按设计文档自行加配置）。
"""

from __future__ import annotations

from typing import Any, Dict

_DEFAULTS: Dict[str, Any] = {
    "enabled": False,  # 默认关闭；用户在 config.yaml 显式 semantic_audit.enabled: true 开启
    "max_strikes": 2,
    "cron_enforce": True,
    "respect_yolo": False,  # yolo 不关闭语义审计
}

_AUX_DEFAULTS: Dict[str, Any] = {
    "provider": "auto",
    "model": "auto",
    "timeout": 5,
}


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


def _coerce_int(val: Any, default: int, minimum: int = 1) -> int:
    try:
        n = int(val)
    except (TypeError, ValueError):
        return default
    return max(minimum, n)


def _coerce_float(val: Any, default: float, minimum: float = 0.5) -> float:
    try:
        n = float(val)
    except (TypeError, ValueError):
        return default
    return max(minimum, n)


def _load_user_config() -> Dict[str, Any]:
    try:
        from hermes_cli.config import load_config_readonly

        cfg = load_config_readonly()
        return cfg if isinstance(cfg, dict) else {}
    except Exception:
        try:
            from hermes_cli.config import load_config

            cfg = load_config()
            return cfg if isinstance(cfg, dict) else {}
        except Exception:
            return {}


def get_semantic_audit_cfg() -> Dict[str, Any]:
    """合并 semantic_audit + auxiliary.semantic_audit 配置。"""
    raw = _load_user_config()
    sa = raw.get("semantic_audit") if isinstance(raw.get("semantic_audit"), dict) else {}
    aux_root = raw.get("auxiliary") if isinstance(raw.get("auxiliary"), dict) else {}
    aux = (
        aux_root.get("semantic_audit")
        if isinstance(aux_root.get("semantic_audit"), dict)
        else {}
    )

    return {
        "enabled": _coerce_bool(sa.get("enabled"), _DEFAULTS["enabled"]),
        "max_strikes": _coerce_int(
            sa.get("max_strikes"), _DEFAULTS["max_strikes"], minimum=1
        ),
        "cron_enforce": _coerce_bool(
            sa.get("cron_enforce"), _DEFAULTS["cron_enforce"]
        ),
        "respect_yolo": _coerce_bool(
            sa.get("respect_yolo"), _DEFAULTS["respect_yolo"]
        ),
        "provider": str(aux.get("provider") or _AUX_DEFAULTS["provider"]),
        "model": str(aux.get("model") or _AUX_DEFAULTS["model"]),
        "timeout": _coerce_float(
            aux.get("timeout"), float(_AUX_DEFAULTS["timeout"]), minimum=0.5
        ),
    }
