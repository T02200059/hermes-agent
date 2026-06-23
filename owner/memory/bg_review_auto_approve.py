"""bg-review 线程的 memory_propose 静默自动批准。

bg-review 是后台自我改进流程，其 memory_propose 不应触发用户审批卡片。
注册一个自动 approve 的 notify 回调，彻底避免与并发 session 的审批串台。

用法（在 agent/background_review.py 的 _run_review_in_thread 里）::

    from owner.memory.bg_review_auto_approve import (
        setup_bg_review_memory_auto_approve,
    )
    _bg_cleanup = setup_bg_review_memory_auto_approve()
    try:
        # ... run review agent ...
    finally:
        _bg_cleanup()

See: owner/docs/二次开发规范.md §2.1 P0 — hook/plugin 优先。
"""
from __future__ import annotations

import logging
from typing import Callable

logger = logging.getLogger(__name__)


def setup_bg_review_memory_auto_approve() -> Callable[[], None]:
    """Register a per-session auto-approve callback for memory proposals.

    Returns a cleanup callable that unregisters the callback.
    If no session key is available (CLI single-process), returns a no-op.
    """
    from tools.approval import get_current_session_key
    from owner.memory.gateway import (
        register_memory_notify,
        unregister_memory_notify,
        resolve_memory_approval,
    )

    session_key = get_current_session_key(default="")
    if not session_key:
        return lambda: None

    def _auto_approve(entry) -> None:
        """Silently approve memory_propose from bg-review thread."""
        try:
            resolved = resolve_memory_approval(session_key, "approve")
            if resolved:
                logger.debug(
                    "bg-review auto-approved memory proposal for session %s",
                    session_key,
                )
        except Exception:
            logger.debug(
                "bg-review auto-approve failed for session %s",
                session_key,
                exc_info=True,
            )

    register_memory_notify(session_key, _auto_approve)

    def _cleanup() -> None:
        try:
            unregister_memory_notify(session_key)
        except Exception:
            pass

    return _cleanup
