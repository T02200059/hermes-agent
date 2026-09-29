"""Feishu interactive card-action branch table + action-value normalisation.

背景
----
``plugins/platforms/feishu/adapter.py`` 的 ``_dispatch_card_action`` 是一张
纯分派表：拿到 (event, action_value, loop) 后按 action_value 里的键把点击
分发给对应的卡片处理器。这张表**每一行都是本项目自己的定制**（上游没有），
却被内联在上游文件里 —— 上游只要改动它周边的任何一行，整张表就会变成冲突块。

规范 §3「官方文件只留薄胶水」的做法是把正文收到 ``owner/`` 下。本模块就是
``_dispatch_card_action`` 正文的落点。

为什么适配器侧还留了一段尾巴
----------------------------
分派表的**末尾**是「没有命中任何分支」的兜底：

    self._submit_on_loop(loop, self._handle_card_action_event(data))
    if P2CardActionTriggerResponse is None:
        return None
    return P2CardActionTriggerResponse()

这一段**故意留在 adapter.py**，因为它构造的是**适配器模块全局**的
``P2CardActionTriggerResponse`` —— 而网关侧测试是通过给它打补丁来注入假响应
的（``tests/gateway/test_feishu_approval_buttons.py`` 的
``_patch_callback_card_types`` fixture 会 ``monkeypatch.setattr(feishu_module,
"P2CardActionTriggerResponse", _FakeP2Response)``）。把尾巴搬到本模块会让那
些补丁点失效，测试会拿到真实的 lark 类。所以本模块返回 ``UNHANDLED`` 这个
哨兵值表示「继续走适配器的兜底」，而不是自己构造空响应。

（同理，本模块内部的 lark 类型走 ``_lark_card_types()`` 自己 import，与
``clarify_card.py`` / ``queue_card.py`` 的既有写法一致。）

命名
----
``dispatch_card_action`` 返回 ``UNHANDLED`` 或处理器返回值。注意处理器**可以
合法地返回 ``None``**（例如上游事件没有对应状态时），因此不能用 ``None`` 当
哨兵 —— 那会把「处理器返回 None」误判成「没有命中分支」，凭空多 submit 一次。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


class _Unhandled:
    """Sentinel: no branch matched, the adapter must run its own fallback tail."""

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "UNHANDLED"


UNHANDLED = _Unhandled()


def normalise_card_action_value(raw: Any) -> Any:
    """Accept ``action.value`` as either a dict or a JSON string.

    Feishu SDK versions differ on whether ``action.value`` is returned
    pre-parsed into a dict or left as a raw JSON string.  Without this
    normalisation every ``isinstance(action_value, dict)`` guard in
    ``dispatch_card_action`` skips and the callback silently fails,
    leaving the card stuck in a loading state.
    """
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    return {}


def dispatch_card_action(
    adapter: Any,
    *,
    event: Any,
    action_value: Dict[str, Any],
    loop: Any,
    data: Any = None,
    allow_profile_routing: bool = True,
) -> Any:
    """Dispatch a parsed card action to the right per-type handler.

    Shared by two callers:
      * the WebSocket SDK callback ``_on_card_action_trigger``
        (``allow_profile_routing=True``, ``data`` = raw lark event);
      * the sub-profile container's ``/v1/feishu/card-actions`` HTTP handler
        (``allow_profile_routing=False`` — the click was already routed here
        and the ``hermes_profile`` tag stripped).

    Returns ``UNHANDLED`` when no branch matched so the caller can run its own
    fallback (submit-as-command + empty response). Handlers may legitimately
    return ``None``, which is a resolved outcome, not a fallthrough.
    """
    hermes_action = (
        action_value.get("hermes_action") if isinstance(action_value, dict) else None
    )
    update_prompt_action = (
        action_value.get("hermes_update_prompt_action")
        if isinstance(action_value, dict)
        else None
    )

    # [owner] multi-profile routing: forward to the sub-profile that sent the card.
    # Only the WebSocket path routes (``allow_profile_routing=True``); the
    # sub-profile's own HTTP replay path skips this (``allow_profile_routing=False``)
    # so the click is handled locally instead of bouncing back to itself.
    if allow_profile_routing:
        try:
            from owner.feishu.profile_routing import try_route_card_action
        except Exception:  # pragma: no cover - fail-open when owner/ is absent
            try_route_card_action = None
        if try_route_card_action is not None:
            route_response = try_route_card_action(event, action_value)
            if route_response is not None:
                return route_response

    # [owner] model picker: dispatch picker card callbacks (see owner/feishu/model_picker.py)
    model_picker = (
        action_value.get("hermes_model_picker") if isinstance(action_value, dict) else None
    )
    if model_picker:
        return adapter._handle_model_picker_action(
            event=event, action_value=action_value, loop=loop
        )

    # [owner] clarify: route clarify card button clicks (see owner/feishu/clarify_card.py)
    clarify_id = action_value.get("clarify_id") if isinstance(action_value, dict) else None
    if clarify_id:
        return adapter._handle_clarify_card_action(
            event=event, action_value=action_value, loop=loop
        )

    # [owner] feishu guide: route guide card button clicks (see owner/feishu/steer_card.py)
    feishu_guide = (
        action_value.get("hermes_feishu_guide") if isinstance(action_value, dict) else None
    )
    if feishu_guide:
        logger.info("[Feishu] Dispatching guide card action: %s", action_value)
        return adapter._handle_guide_card_action(
            event=event, action_value=action_value, loop=loop
        )

    # [owner] queue status card: guide / process_now / cancel (see owner/feishu/queue_card.py)
    feishu_queue = (
        action_value.get("hermes_queue_card") if isinstance(action_value, dict) else None
    )
    if feishu_queue:
        logger.info("[Feishu] Dispatching queue card action: %s", action_value)
        return adapter._handle_queue_card_action(
            event=event, action_value=action_value, loop=loop
        )

    # [owner] diff cards: route expand/collapse/full actions (see owner/diff_card/feishu.py)
    diff_action = (
        (isinstance(action_value, dict) and action_value.get("expand_diff"))
        or (isinstance(action_value, dict) and action_value.get("collapse_diff"))
        or (isinstance(action_value, dict) and action_value.get("show_full_diff"))
    )
    if diff_action:
        from owner.diff_card.feishu import handle_feishu_diff_action

        return handle_feishu_diff_action(adapter, event, action_value)

    # [owner] resume: handle resume selection button click (see owner/feishu/resume_card.py)
    if hermes_action == "resume_select":
        from owner.feishu.resume_card import handle_resume_card_action

        return handle_resume_card_action(
            adapter=adapter,
            event=event,
            action_value=action_value,
            loop=loop,
        )

    # [owner] memory_approval_gate: route approval-card button clicks
    # (see owner/feishu/memory_approval.py).
    if hermes_action == "memory_approval_gate":
        from owner.feishu.memory_approval import handle_card_click

        return handle_card_click(
            adapter=adapter, event=event, action_value=action_value, loop=loop,
        )

    # [owner] skill_approval_gate: route skill approval card button clicks
    # (see owner/feishu/skill_approval_card.py).
    if hermes_action == "skill_approval_gate":
        from owner.feishu.skill_approval_card import handle_card_click

        return handle_card_click(
            adapter=adapter, event=event, action_value=action_value, loop=loop,
        )

    if hermes_action:
        return adapter._handle_approval_card_action(
            event=event, action_value=action_value, loop=loop
        )
    if update_prompt_action:
        return adapter._handle_update_prompt_card_action(
            event=event,
            action_value=action_value,
            loop=loop,
        )

    return UNHANDLED
