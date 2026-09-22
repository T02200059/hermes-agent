"""english_explainer 钩子：transform_llm_output 检测 + 侧路投递。

官方源码零侵入：经 owner-extensions 注册。
- 不改写原文（始终 return None，避免抢走 output_guard 的 first-wins）。
- 判定为英文回复后，后台线程调辅助模型翻译，再经网关 adapter 另发一条
  「🔤 系统提示：…」消息（飞书命中 notice 卡）。
- 顶级约束：display.language 须为中文；patch.yaml enabled 三级查找。
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Dict, Optional, Tuple

from owner.english_explainer.config import (
    display_language_is_chinese,
    load_config,
    resolve_enabled,
)
from owner.english_explainer.detect import looks_like_english_reply
from owner.english_explainer.explain import explain_sync
from owner.english_explainer.prompt import format_delivery

logger = logging.getLogger("hermes.owner.english_explainer")

_GATEWAY_REF: Any = None
_ADAPTERS: Dict[str, Any] = {}
_REF_LOCK = threading.Lock()

# session_id / gateway_session_key → (platform, chat_id)
_SESSION_ROUTES: Dict[str, Tuple[str, str]] = {}
_ROUTE_LOCK = threading.Lock()

# 去重：同一 session+正文指纹短时只解说一次
_RECENT: Dict[str, float] = {}
_RECENT_LOCK = threading.Lock()
_RECENT_TTL_S = 120.0
_RECENT_MAX = 256


def register_hooks(ctx: Any) -> None:
    ctx.register_hook("pre_gateway_dispatch", _on_pre_gateway_dispatch)
    ctx.register_hook("transform_llm_output", _on_transform_llm_output)
    logger.debug("english_explainer hooks registered")


def _on_pre_gateway_dispatch(**kwargs: Any) -> None:
    """缓存 gateway / adapters，并记下本轮 session → platform/chat_id。"""
    global _GATEWAY_REF
    gateway = kwargs.get("gateway")
    event = kwargs.get("event")
    source = kwargs.get("source")
    session_key = str(
        kwargs.get("session_key")
        or kwargs.get("gateway_session_key")
        or getattr(event, "session_key", "")
        or ""
    )
    platform = ""
    chat_id = ""
    if source is not None:
        platform = str(getattr(source, "platform", "") or "")
        chat_id = str(getattr(source, "chat_id", "") or "")
    if not platform and event is not None:
        platform = str(getattr(event, "platform", "") or "")
        chat_id = chat_id or str(getattr(event, "chat_id", "") or "")
    platform = platform.lower().replace("Platform.", "").strip()
    if hasattr(platform, "value"):
        platform = str(getattr(platform, "value", platform))

    # Normalize enum-ish strings: "Platform.FEISHU" / "feishu"
    p = str(platform or "").lower()
    if "." in p:
        p = p.split(".")[-1]
    platform = p

    if gateway is not None:
        try:
            adapters = getattr(gateway, "adapters", {}) or {}
            with _REF_LOCK:
                _GATEWAY_REF = gateway
                for key, adapter in adapters.items():
                    k = str(getattr(key, "value", key) or "").lower()
                    if k:
                        _ADAPTERS[k] = adapter
        except Exception:
            logger.debug("english_explainer cache adapters failed", exc_info=True)

    if session_key and platform and chat_id:
        with _ROUTE_LOCK:
            _SESSION_ROUTES[session_key] = (platform, chat_id)
            # 也用尾段做宽松命中
            if ":" in session_key:
                _SESSION_ROUTES[session_key.split(":")[-1]] = (platform, chat_id)


def _lookup_route(session_id: str, platform_hint: str) -> Tuple[str, str]:
    sid = str(session_id or "")
    with _ROUTE_LOCK:
        if sid in _SESSION_ROUTES:
            return _SESSION_ROUTES[sid]
        for key, val in list(_SESSION_ROUTES.items())[-32:]:
            if sid and (sid in key or key in sid):
                return val
    p = str(platform_hint or "").lower()
    if "." in p:
        p = p.split(".")[-1]
    return p, ""


def _resolve_adapter(platform: str) -> Any:
    p = str(platform or "").lower()
    with _REF_LOCK:
        if p in _ADAPTERS:
            return _ADAPTERS[p]
        # common aliases
        if p in {"lark", "feishu"}:
            return _ADAPTERS.get("feishu") or _ADAPTERS.get("lark")
        gw = _GATEWAY_REF
    if gw is None:
        return None
    adapters = getattr(gw, "adapters", {}) or {}
    try:
        from gateway.config import Platform

        enum_map = {
            "feishu": getattr(Platform, "FEISHU", None),
            "qqbot": getattr(Platform, "QQBOT", None),
            "telegram": getattr(Platform, "TELEGRAM", None),
            "discord": getattr(Platform, "DISCORD", None),
            "slack": getattr(Platform, "SLACK", None),
        }
        enum_key = enum_map.get(p)
        if enum_key is not None and enum_key in adapters:
            return adapters[enum_key]
    except Exception:
        pass
    return adapters.get(p)


def _resolve_loop(adapter: Any) -> Any:
    candidates = []
    if adapter is not None:
        candidates.append(getattr(adapter, "_loop", None))
        candidates.append(getattr(adapter, "_ws_thread_loop", None))
    with _REF_LOCK:
        gw = _GATEWAY_REF
    if gw is not None:
        candidates.append(getattr(gw, "_loop", None))
    for loop in candidates:
        if loop is None:
            continue
        try:
            if getattr(loop, "is_closed", lambda: False)():
                continue
        except Exception:
            continue
        return loop
    return None


def _should_skip_recent(session_id: str, text: str) -> bool:
    import hashlib
    import time

    digest = hashlib.sha1(f"{session_id}|{text[:800]}".encode("utf-8", "ignore")).hexdigest()
    now = time.time()
    with _RECENT_LOCK:
        # prune
        dead = [k for k, ts in _RECENT.items() if now - ts > _RECENT_TTL_S]
        for k in dead:
            _RECENT.pop(k, None)
        if digest in _RECENT:
            return True
        _RECENT[digest] = now
        if len(_RECENT) > _RECENT_MAX:
            # drop oldest
            oldest = sorted(_RECENT.items(), key=lambda x: x[1])[: len(_RECENT) - _RECENT_MAX]
            for k, _ in oldest:
                _RECENT.pop(k, None)
        return False


def _on_transform_llm_output(
    response_text: str,
    session_id: str = "",
    model: str = "",
    platform: str = "",
    reasoning_text: str = "",
    interrupted: bool = False,
    **kwargs: Any,
):
    """检测英文回复并调度侧路解说。始终返回 None（不改原文）。"""
    try:
        if interrupted:
            return None
        if not response_text or not isinstance(response_text, str):
            return None
        if not display_language_is_chinese():
            return None

        platform_l = str(platform or "").lower()
        if "." in platform_l:
            platform_l = platform_l.split(".")[-1]
        route_platform, chat_id = _lookup_route(session_id, platform_l)
        if not platform_l:
            platform_l = route_platform
        if not resolve_enabled(platform_l, chat_id or None):
            return None

        detection = looks_like_english_reply(response_text)
        if not detection:
            return None
        if _should_skip_recent(session_id, response_text):
            return None

        cfg = load_config()
        # 后台执行：避免卡住 transform_llm_output 热路径
        threading.Thread(
            target=_bg_translate_and_send,
            kwargs={
                "response_text": response_text,
                "cfg": cfg,
                "platform": platform_l,
                "chat_id": chat_id,
                "session_id": session_id,
                "detection": detection,
            },
            name="english-explainer",
            daemon=True,
        ).start()
    except Exception:
        logger.debug("english_explainer transform hook failed", exc_info=True)
    return None


def _bg_translate_and_send(
    *,
    response_text: str,
    cfg: dict,
    platform: str,
    chat_id: str,
    session_id: str,
    detection: dict,
) -> None:
    try:
        translation = explain_sync(response_text, cfg)
        body = format_delivery(translation or "")
        if not body:
            return
        adapter = _resolve_adapter(platform)
        if adapter is None or not chat_id:
            logger.debug(
                "english_explainer skip send (adapter/chat missing) "
                "platform=%s chat=%s session=%s detection=%s",
                platform,
                bool(chat_id),
                session_id,
                detection.get("reason"),
            )
            return
        loop = _resolve_loop(adapter)
        if loop is None:
            logger.debug("english_explainer no event loop for send")
            return

        async def _send() -> None:
            try:
                await adapter.send(chat_id, body)
            except Exception as exc:
                logger.debug("english_explainer send failed: %s", exc)

        fut = asyncio.run_coroutine_threadsafe(_send(), loop)
        try:
            fut.result(timeout=max(5.0, int(cfg.get("explainer_timeout_ms", 30000)) / 1000.0 + 5))
        except Exception as exc:
            logger.debug("english_explainer send wait failed: %s", exc)
    except Exception:
        logger.debug("english_explainer background failed", exc_info=True)
