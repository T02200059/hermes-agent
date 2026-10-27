"""B17 飞书半边：clarify 真超时后打断 agent，并补发一句提示。

官方半边（清理路径返回 CLARIFY_STOP_SENTINEL / CANCELLED）已在 upstream。
本模块只覆盖飞书：用户无应答超时（``[user did not respond within Nm]``）时
补发超时提示，并改返回 CANCELLED，使 clarify 工具 outcome 为 ``cancelled``
（停转），而不是 ``timed_out``（模型可能自行拍板继续）。
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

_TIMEOUT_PREFIX = "[user did not respond"

_NOTICE = {
    "zh": "⏳ 未在 {minutes} 分钟内收到回复，已停止当前操作。需要的话再发消息给我。",
    "en": (
        "⏳ No response received within {minutes} minutes; "
        "the current operation has stopped. Send me a message if you need anything."
    ),
}


def _platform_value(ctx: Any) -> str:
    source = getattr(ctx, "source", None)
    platform = getattr(source, "platform", None)
    if platform is None:
        return ""
    return str(getattr(platform, "value", platform) or "")


def is_feishu_inactivity_timeout(
    *, platform: str, answered: bool, response: Any,
) -> bool:
    if answered:
        return False
    if str(platform or "") != "feishu":
        return False
    return isinstance(response, str) and response.startswith(_TIMEOUT_PREFIX)


def timeout_notice_text(timeout_seconds: float, *, lang: str | None = None) -> str:
    try:
        minutes = max(0, int(float(timeout_seconds) / 60))
    except (TypeError, ValueError):
        minutes = 0
    if not lang:
        try:
            from owner.explainers.common import display_language

            lang = display_language()
        except Exception:
            lang = "zh"
    lang = str(lang or "zh").strip().lower() or "zh"
    try:
        from agent.i18n import t

        text = t("gateway.clarify_timeout_notice", lang=lang, minutes=minutes)
        if text and "clarify_timeout_notice" not in text:
            return text
    except Exception:
        pass
    # Prefer exact / prefix match (en / zh-*), else zh fallback.
    template = _NOTICE.get(lang)
    if template is None:
        if lang.startswith("zh"):
            template = _NOTICE["zh"]
        elif lang.startswith("en"):
            template = _NOTICE["en"]
        else:
            template = _NOTICE["zh"]
    return template.format(minutes=minutes)


def apply_feishu_timeout_stop(
    runner: Any,
    *,
    response: Any,
    answered: bool,
    clarify_mod: Any,
) -> Optional[tuple[str, bool]]:
    """飞书真超时：调度用户提示并返回 ``(CANCELLED, False)``；否则 ``None``。"""
    ctx = getattr(runner, "_ctx", None)
    if ctx is None:
        return None
    platform = _platform_value(ctx)
    if not is_feishu_inactivity_timeout(
        platform=platform, answered=answered, response=response,
    ):
        return None

    try:
        timeout = float(clarify_mod.get_clarify_timeout())
    except Exception:
        timeout = 3600.0

    notice = timeout_notice_text(timeout)  # lang via display_language()
    adapter = getattr(ctx, "_status_adapter", None)
    chat_id = getattr(ctx, "_status_chat_id", None)
    schedule = getattr(runner, "_schedule", None)
    if adapter is not None and chat_id and callable(schedule):
        try:
            schedule(
                adapter.send(
                    chat_id,
                    notice,
                    metadata=getattr(ctx, "_status_thread_metadata", None),
                ),
                "clarify timeout notice scheduling error",
            )
        except Exception:
            logger.debug("B17 clarify timeout notice failed", exc_info=True)

    stop = getattr(clarify_mod, "CANCELLED", None)
    if not stop:
        from tools.clarify_tool import CLARIFY_STOP_SENTINEL

        stop = CLARIFY_STOP_SENTINEL
    return str(stop), False
