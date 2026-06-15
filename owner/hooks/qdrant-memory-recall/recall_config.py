"""Configuration and environment loading for qdrant-memory-recall hook."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import yaml
from dotenv import dotenv_values

DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "top_k": 3,
    "score_threshold": 0.5,
    "per_collection_k": 3,
    "body_max_chars": 300,
    "min_query_length": 5,
    "embed_model": "text-embedding-v4",
    "embed_timeout_sec": 3,
    "embed_max_retries": 2,
    "collections": ["cases", "entities", "events", "patterns", "preferences"],
    "per_collection_timeout_sec": 2,
    "total_timeout_sec": 10,
    "include_score": True,
    "include_source_collection": True,
    "extra_context_header": (
        "# Retrieved Memory (qdrant 语义召回, top-K 按 cosine 相似度排序)\n\n"
        "以下是从知识库中语义检索到的相关条目，score 为相似度（0-1，越高越相关）：\n"
    ),
    "log_on_empty_recall": False,
}


def _log_dir() -> Path:
    from hermes_constants import get_hermes_home

    return get_hermes_home() / "logs"


_LOG_DIR = _log_dir()
_LOG_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("qdrant-memory-recall")
if not logger.handlers:
    _h = logging.FileHandler(_LOG_DIR / "qdrant-memory-recall.log", encoding="utf-8")
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)

_env_cache: dict | None = None
_bot_menu_cache: set[str] | None = None
_bot_menu_cache_time: float = 0.0
_BOT_MENU_CACHE_TTL: float = 60.0


def load_config() -> dict[str, Any]:
    """Read owner.hooks.qdrant_memory_recall from patch.yaml; fail-open to defaults."""
    try:
        from hermes_constants import get_hermes_home

        patch_path = get_hermes_home() / "patch.yaml"
        if not patch_path.exists():
            return dict(DEFAULTS)
        with patch_path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        cfg = (
            data.get("owner", {})
            .get("hooks", {})
            .get("qdrant_memory_recall", {})
        )
        merged = dict(DEFAULTS)
        merged.update(cfg or {})
        return merged
    except Exception as e:
        logger.warning(f"config load failed, using defaults: {e}")
        return dict(DEFAULTS)


def get_env() -> dict:
    """Read DAMODEL/QDRANT credentials from ~/.hermes/.env."""
    global _env_cache
    if _env_cache is not None:
        return _env_cache
    try:
        from hermes_constants import get_hermes_home

        env = dotenv_values(get_hermes_home() / ".env")
        _env_cache = {
            "DAMODEL_BASE_URL": (env.get("DAMODEL_BASE_URL") or "").rstrip("/"),
            "DAMODEL_API_KEY": env.get("DAMODEL_API_KEY") or "",
            "QDRANT_URL": (env.get("QDRANT_URL") or "").rstrip("/"),
            "QDRANT_KEY": env.get("QDRANT_KEY") or "",
        }
    except Exception as e:
        logger.error(f".env load failed: {e}")
        _env_cache = {
            "DAMODEL_BASE_URL": "",
            "DAMODEL_API_KEY": "",
            "QDRANT_URL": "",
            "QDRANT_KEY": "",
        }
    return _env_cache


def load_bot_menu_commands() -> set[str]:
    """Return bot menu command strings to skip (not user queries)."""
    global _bot_menu_cache, _bot_menu_cache_time
    now = time.monotonic()
    if _bot_menu_cache is not None and (now - _bot_menu_cache_time) < _BOT_MENU_CACHE_TTL:
        return _bot_menu_cache
    try:
        from hermes_constants import get_hermes_home

        patch_path = get_hermes_home() / "patch.yaml"
        if not patch_path.exists():
            _bot_menu_cache = set()
            _bot_menu_cache_time = now
            return _bot_menu_cache
        with patch_path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        bot_menu = (
            data.get("owner", {})
            .get("feishu", {})
            .get("bot_menu", {})
        )
        _bot_menu_cache = set(bot_menu.values()) if isinstance(bot_menu, dict) else set()
        _bot_menu_cache_time = now
    except Exception as e:
        logger.warning(f"bot_menu load failed: {e}")
        _bot_menu_cache = set()
        _bot_menu_cache_time = now
    return _bot_menu_cache