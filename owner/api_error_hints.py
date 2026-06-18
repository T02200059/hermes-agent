"""Chinese hints for common LLM API HTTP errors.

Loaded by ``agent/conversation_loop.py`` when surfacing terminal API errors to
users.  Returns ``None`` when the active language is not Chinese or when no hint
is defined, so callers can skip appending anything.

可移除性：删除此文件后，agent 不再追加中文 API 错误提示，其余功能不受影响。
"""

from __future__ import annotations

from typing import Optional

from agent.i18n import get_language


def get_api_error_hint(
    status_code: Optional[int] = None,
    reason: Optional[str] = None,
) -> Optional[str]:
    """Return a short Chinese user-facing hint for common API errors.

    Parameters
    ----------
    status_code
        HTTP status code from the failed API call, if available.
    reason
        ``FailoverReason`` value (e.g. ``"rate_limit"``, ``"billing"``) from
        ``agent.error_classifier``, if available.

    Returns
    -------
    A Chinese hint string when the active display language is Chinese and a
    matching hint exists; otherwise ``None``.
    """
    if not get_language().startswith("zh"):
        return None

    if status_code == 429 or reason == "rate_limit":
        return "请求过于频繁，请稍后再试，或配置 fallback 提供商自动切换。"
    if status_code in (500, 502) or reason == "server_error":
        return "模型服务端异常，请稍后重试或切换到其他模型/提供商。"
    if status_code in (503, 529) or reason == "overloaded":
        return "模型服务商当前负载过高，请稍后重试。"
    if status_code in (504, 524) or reason == "timeout":
        return "上游响应超时，请稍后重试。"
    if status_code == 400 or reason == "format_error":
        return "请求被服务端拒绝（400），可能是参数、内容安全或上下文过长，请尝试 /new 或换模型。"
    if reason == "billing":
        return "账户余额或额度不足，请检查提供商账单或配置 fallback 自动切换。"

    return None
