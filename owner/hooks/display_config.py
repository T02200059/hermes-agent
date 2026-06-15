"""Display config for message:receive hook extra_context delivery.

Controls whether hook-recalled extra_context is echoed as a chat message
to the current conversation. Configuration lives in ``owner/config/patch.yaml``
under ``owner.display_hook_message_receive``.

Hierarchy (coarse → fine): global enabled → per-platform → per-chat.
Default is all-on. Any layer explicitly set to false blocks delivery.

可移除性：删除此文件 → gateway/run.py 中的薄胶水 import 会触发
ImportError fallback，退化为全场 on。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

HOOK_EVENT = "message:receive"

# ── Sentinel regex ──────────────────────────────────────────────────────────
# Strips hook-injected extra_context (wrapped in HTML-comment sentinels)
# before persistence so the LLM sees the context but history/archive does not.
_HOOK_CTX_RE_SRC = (
    r'\n*<!-- HERMES_HOOK_CONTEXT_START -->.*?<!-- HERMES_HOOK_CONTEXT_END -->\n*'
)


def load_config() -> Dict[str, Any]:
    """Read display_hook_message_receive config from patch.yaml.

    Returns:
        dict with keys (defaults filled):
          - enabled: bool (True)
          - mode: str ("before_agent")
          - platforms: dict[platform_name, bool]
          - per_chat: dict[platform_name, dict[chat_id, bool]]

    Read failure / missing file → returns full default-on dict.
    """
    from hermes_constants import get_hermes_home

    default: Dict[str, Any] = {
        "enabled": True,
        "mode": "before_agent",
        "platforms": {},
        "per_chat": {},
    }
    try:
        patch_path = get_hermes_home() / "patch.yaml"
        if not patch_path.exists():
            return default
        import yaml as _yaml
        raw = _yaml.safe_load(patch_path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        logger.debug("display_hook_message_receive config load failed: %s", e)
        return default
    if not isinstance(raw, dict):
        return default
    owner_section = raw.get("owner")
    if not isinstance(owner_section, dict):
        return default
    cfg = owner_section.get("display_hook_message_receive")
    if not isinstance(cfg, dict):
        return default

    result: Dict[str, Any] = dict(default)
    if "enabled" in cfg:
        result["enabled"] = _truthy(cfg.get("enabled"), default=True)
    mode = cfg.get("mode")
    if isinstance(mode, str) and mode.strip():
        result["mode"] = mode.strip().lower()
    platforms = cfg.get("platforms")
    if isinstance(platforms, dict):
        result["platforms"] = {
            str(k): _truthy(v, default=True)
            for k, v in platforms.items()
        }
    per_chat = cfg.get("per_chat")
    if isinstance(per_chat, dict):
        normalized: Dict[str, Dict[str, bool]] = {}
        for plat, chat_map in per_chat.items():
            if not isinstance(chat_map, dict):
                continue
            normalized[str(plat)] = {
                str(cid): _truthy(v, default=True)
                for cid, v in chat_map.items()
            }
        result["per_chat"] = normalized
    return result


def should_deliver(
    platform: str,
    chat_id: Optional[str] = None,
) -> Tuple[bool, str]:
    """Decide whether hook recall content should be delivered to current chat.

    Returns:
        (allowed, reason) — allowed=True delivers; False ⇒ reason is a short
        human-readable explanation for debug logging.

    Decision order:
      1. global enabled = false → reject ("global disabled")
      2. per-platform = false → reject ("platform disabled")
      3. per-chat = false → reject ("chat disabled")
      4. otherwise allow
    """
    cfg = load_config()
    if not cfg.get("enabled", True):
        return False, "global disabled"
    platforms = cfg.get("platforms") or {}
    if platform in platforms and not platforms[platform]:
        return False, "platform disabled"
    if chat_id:
        per_chat = (cfg.get("per_chat") or {}).get(platform) or {}
        if chat_id in per_chat and not per_chat[chat_id]:
            return False, "chat disabled"
    return True, ""


def strip_hook_context(text: str) -> str:
    """Remove sentinel-wrapped hook context from text before persistence."""
    import re as _re
    return _re.compile(_HOOK_CTX_RE_SRC, _re.DOTALL).sub('', text)


def _truthy(value: Any, *, default: bool = True) -> bool:
    """Parse truthy value — delegates to utils.is_truthy_value when available."""
    try:
        from utils import is_truthy_value
        return is_truthy_value(value, default=default)
    except ImportError:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() not in ("0", "false", "no", "off", "")
        return bool(value) if value is not None else default
