"""bg-review 线程的 memory_propose 静默自动批准（隔离 key 方案）。

bg-review 是后台自我改进流程，其 memory_propose 不应触发用户审批卡片，也
**绝不能**与并发的主 session 共享审批队列 / notify 回调槽。

关键设计：把当前 bg-review 线程的 approval session-key ContextVar **重绑**到一个
隔离的 ``<parent>#bg-review`` key，并在该隔离 key 下注册 auto-approve 回调。

为什么必须重绑而不是直接用父 key：
``owner/memory/gateway._memory_notify_cbs`` 是 *每个 session_key 单槽* 的 dict，
``unregister_memory_notify`` 还带 ``clear_memory_proposal`` 副作用。如果 bg-review
直接在父 key K 上注册，并发场景（bg-review 还在跑、用户又发了下一轮）会：
  - 覆盖主 session 当前轮的用户卡片回调 —— bg-review 提案弹给用户，或用户的真实
    提案被静默自动批准（未经确认写入长期记忆）；
  - bg-review 结束清理时 ``unregister_memory_notify(K)`` 把主 session 正在等待的
    真实提案一并 deny，或 pop 后让后续提案无回调挂到超时。
重绑到 ``K#bg-review`` 后，review agent 在本线程里调用的每一次 memory_propose
（``_get_session_key()`` 读的就是重绑后的 ContextVar）都落到隔离队列，主 session
的 K 槽与队列完全不被触碰。

用法（在 agent/background_review.py 的 _run_review_in_thread 里）::

    from owner.memory.bg_review_auto_approve import (
        setup_bg_review_memory_auto_approve,
    )
    _bg_cleanup = setup_bg_review_memory_auto_approve()
    try:
        # ... run review agent ...
    finally:
        _bg_cleanup()

See: owner/docs/二次开发规范.md §2.1 P0；owner/docs/v16改动清单.md §4.5。
"""
from __future__ import annotations

import logging
from typing import Callable

logger = logging.getLogger(__name__)

# Suffix appended to the parent session key to form the isolated bg-review key.
_BG_REVIEW_SUFFIX = "#bg-review"


def _derive_bg_review_key(parent_key: str) -> str:
    """Derive the isolated bg-review session key from a parent key.

    - Empty/falsy parent → ``default`` base (CLI single-process has no real
      session key but bg-review proposals still need a deterministic bucket).
    - Idempotent: a key that already carries the suffix is returned unchanged,
      so re-deriving (e.g. nested bg-review, or a key read back after rebind)
      never double-appends.
    """
    base = parent_key or "default"
    if base.endswith(_BG_REVIEW_SUFFIX):
        return base
    return f"{base}{_BG_REVIEW_SUFFIX}"


def setup_bg_review_memory_auto_approve() -> Callable[[], None]:
    """Rebind to an isolated bg-review session key and auto-approve its proposals.

    Returns a cleanup callable that unregisters the isolated callback, clears
    the isolated queue, and restores the prior session-key ContextVar. The
    cleanup is idempotent and exception-safe.
    """
    from tools.approval import (
        get_current_session_key,
        set_current_session_key,
        reset_current_session_key,
    )
    from owner.memory.gateway import (
        register_memory_notify,
        unregister_memory_notify,
        resolve_memory_approval,
    )

    # Isolated key — never the live parent key. Rebinding the ContextVar means
    # every memory_propose the review agent makes in THIS thread reads bg_key
    # via _get_session_key() and routes into the isolated queue, not into the
    # parent's queue/notify slot.
    parent_key = get_current_session_key(default="")
    bg_key = _derive_bg_review_key(parent_key)
    token = set_current_session_key(bg_key)

    def _auto_approve(entry) -> None:
        """Silently approve memory_propose from the bg-review thread."""
        try:
            resolved = resolve_memory_approval(bg_key, "approve")
            if resolved:
                logger.debug(
                    "bg-review auto-approved memory proposal for %s", bg_key,
                )
        except Exception:
            logger.debug(
                "bg-review auto-approve failed for %s", bg_key, exc_info=True,
            )

    register_memory_notify(bg_key, _auto_approve)

    _cleaned = {"done": False}

    def _cleanup() -> None:
        # Idempotent: a second call (e.g. defensive double-cleanup) is a no-op.
        # Only ever touches the isolated bg_key — the parent session's queue,
        # notify slot, and ContextVar are restored untouched.
        if _cleaned["done"]:
            return
        _cleaned["done"] = True
        try:
            unregister_memory_notify(bg_key)
        except Exception:
            pass
        try:
            reset_current_session_key(token)
        except Exception:
            pass

    return _cleanup
