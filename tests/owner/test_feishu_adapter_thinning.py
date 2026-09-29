"""T2-14 guard: the adapter's own card glue lives in owner/feishu/, not inline.

背景
----
``merge-conflict`` 报告 §5.4 把 ``plugins/platforms/feishu/adapter.py`` 列为全库
第二冲突文件（33 个冲突块），并给出「新建 ``owner/feishu/profile_tag.py`` + 继续
收薄 profile 路由」的修法。动手前逐条复核，四条前提有三条不成立：

* 标签注入**已经**是单点 —— ``owner/feishu/card_sender.py`` 的
  ``_maybe_tag_interactive_payload``（``_maybe_tag_card_profile`` /
  ``_inject_profile_tag``），adapter 侧只有 ``_send_raw_message`` 里一处 5 行调用；
  新建 ``profile_tag.py`` 只是在自家两个文件之间搬代码，冲突面一字不减。
* profile 路由**已经**收拢 —— ``owner/feishu/profile_routing.py``，982 行 /
  25 个公开符号。
* §5.4 表格里的 i18n 一行不成立 —— adapter 内 0 个 ``t()``。

实测冲突面（33 块）的构成是：我们在冲突侧的 1193 行里，824 行是可执行代码，
且**大部分是「只有我们才有」的卡片胶水**，被内联塞在上游的类体里。上游一旦改动
它周边任何一行，整块变成冲突。所以真正有效的动作是把**我们自己的**代码搬走
（不删上游任何一行 → 不产生合并债），而不是把上游的正文搬出去。

本文件钉住两件让这次搬运安全的事：

1. **结构** —— 每个被搬走的方法都保住名字、保持薄。名字尤其重要：
   ``owner/feishu/auto_card.py`` 用 ``getattr(adapter, "_get_card_send_lock", None)``
   解析锁，名字丢了**不会报错**，而是静默降级成 ``contextlib.nullcontext()``。
2. **语义** —— 那个不显然的设计决定：``_dispatch_card_action`` 的兜底尾巴
   **故意留在 adapter**，因为它构造的是**适配器模块全局**的
   ``P2CardActionTriggerResponse``，而网关测试正是给那个全局打补丁的
   （``tests/gateway/test_feishu_approval_buttons.py``）。同时 ``UNHANDLED``
   哨兵不能被误当成「处理器返回了 None」。
"""

from __future__ import annotations

import ast
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict

import pytest

import plugins.platforms.feishu.adapter as feishu_adapter
from gateway.platforms.base import SendResult

ADAPTER_PATH = Path(feishu_adapter.__file__)
ADAPTER_SRC = ADAPTER_PATH.read_text(encoding="utf-8")
AUTO_CARD_PATH = ADAPTER_PATH.parents[3] / "owner" / "feishu" / "auto_card.py"

# method name -> maximum allowed body length.
#
# These are the 11 methods whose bodies moved to owner/. The bound is roughly
# 1.3x the size right after the move, so ordinary comment growth is fine while a
# re-inline (which is what produced the conflict blocks) trips the test.
# Pre-move total was 404 lines; post-move total is 212.
MOVED_METHODS: Dict[str, int] = {
    "_dispatch_card_action": 65,
    "send_card": 25,
    "send_model_picker_card": 28,
    "_handle_model_picker_action": 17,
    "send_guide_card": 21,
    "_handle_guide_card_action": 17,
    "send_queue_status_card": 37,
    "_handle_queue_card_action": 17,
    "_normalise_card_action_value": 16,
    "_get_card_send_lock": 16,
    "_send_media_guard_hint": 21,
}
TOTAL_BOUND = 260

# Distinctive strings that used to live in the adapter bodies. Their absence is
# the direct evidence that the body really moved rather than being duplicated.
MOVED_BODY_NEEDLES = (
    "[Feishu card] model_picker sent picker_id=",
    "[Feishu card] guide sent guide_id=",
    "[Feishu card] queue status sent token=",
    "media_guard: failed to surface hint to user",
    "Feishu card send failed",
)


def _bare_adapter() -> Any:
    """A FeishuAdapter with no __init__, so only the attribute under test is needed."""
    return object.__new__(feishu_adapter.FeishuAdapter)


# ===========================================================================
# 1. Structure
# ===========================================================================


@pytest.mark.parametrize("name", sorted(MOVED_METHODS))
def test_moved_method_still_exists_on_the_adapter(name: str) -> None:
    assert hasattr(feishu_adapter.FeishuAdapter, name), (
        f"{name} disappeared from FeishuAdapter. Some call sites resolve these "
        "defensively (getattr(..., None) / hasattr) and would degrade silently "
        "instead of failing loudly."
    )


def _method_sizes() -> Dict[str, int]:
    sizes: Dict[str, int] = {}
    for node in ast.walk(ast.parse(ADAPTER_SRC)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in MOVED_METHODS:
            sizes[node.name] = node.end_lineno - node.lineno + 1
    return sizes


def test_every_moved_method_is_present_and_thin() -> None:
    sizes = _method_sizes()
    assert set(sizes) == set(MOVED_METHODS), f"missing: {set(MOVED_METHODS) - set(sizes)}"
    grew = {n: s for n, s in sizes.items() if s > MOVED_METHODS[n]}
    assert not grew, f"body grew back inline (bound in MOVED_METHODS): {grew}"


def test_moved_methods_total_stays_small() -> None:
    total = sum(_method_sizes().values())
    assert total <= TOTAL_BOUND, (
        f"the 11 moved methods total {total} lines (bound {TOTAL_BOUND}). "
        "Pre-move total was 404 — this is drifting back toward inline."
    )


@pytest.mark.parametrize("needle", MOVED_BODY_NEEDLES)
def test_moved_bodies_no_longer_live_in_the_adapter(needle: str) -> None:
    assert needle not in ADAPTER_SRC, (
        f"{needle!r} is still in adapter.py — the body was copied rather than moved"
    )


def test_auto_card_still_resolves_the_lock_defensively() -> None:
    """Documents *why* `_get_card_send_lock` must keep its name.

    owner/feishu/auto_card.py looks it up with a default and silently falls back
    to nullcontext(). If either side of this contract changes, the coupling is no
    longer obvious from the adapter alone — so assert it.
    """
    src = AUTO_CARD_PATH.read_text(encoding="utf-8")
    assert 'getattr(adapter, "_get_card_send_lock", None)' in src
    assert hasattr(feishu_adapter.FeishuAdapter, "_get_card_send_lock")


# ===========================================================================
# 2. Semantics — the deliberately-kept fall-through tail
# ===========================================================================


def _record_submissions(monkeypatch, adapter: Any) -> list:
    submitted: list = []

    def _fake_submit(loop: Any, coro: Any) -> bool:
        # The real _submit_on_loop hands the coroutine to the adapter loop; here
        # we only assert that it was handed over, so close it to avoid an
        # "never awaited" warning.
        submitted.append(coro)
        coro.close()
        return True

    monkeypatch.setattr(adapter, "_submit_on_loop", _fake_submit)

    async def _noop(_data: Any) -> None:
        return None

    monkeypatch.setattr(adapter, "_handle_card_action_event", _noop)
    return submitted


def test_fallthrough_builds_the_response_from_the_adapter_module_global(monkeypatch) -> None:
    """The tail must keep reading adapter.P2CardActionTriggerResponse.

    tests/gateway/test_feishu_approval_buttons.py patches exactly that global
    (``_patch_callback_card_types``); if the tail moved into owner/ it would read
    its own module's binding and those patch points would go dead.
    """

    class _FakeResponse:
        pass

    monkeypatch.setattr(feishu_adapter, "P2CardActionTriggerResponse", _FakeResponse)
    adapter = _bare_adapter()
    submitted = _record_submissions(monkeypatch, adapter)

    response = adapter._dispatch_card_action(
        object(), {}, object(), data=None, allow_profile_routing=False
    )

    assert isinstance(response, _FakeResponse)
    assert len(submitted) == 1, "unrecognised actions must still be submitted as commands"


def test_handler_returning_none_is_not_treated_as_unhandled(monkeypatch) -> None:
    """`None` from a handler is a resolved outcome, not a fallthrough.

    The owner-side dispatcher returns a dedicated UNHANDLED sentinel for
    "no branch matched" precisely so this cannot be confused. If it ever used
    `None` as the sentinel, every resolved-but-empty click would additionally
    submit a synthetic command event.
    """
    adapter = _bare_adapter()
    monkeypatch.setattr(adapter, "_handle_approval_card_action", lambda **kw: None)
    submitted = _record_submissions(monkeypatch, adapter)

    response = adapter._dispatch_card_action(
        object(),
        {"hermes_action": "approve_once"},
        object(),
        data=None,
        allow_profile_routing=False,
    )

    assert response is None
    assert submitted == [], "None from a handler must not re-enter the fallback tail"


def test_profile_routing_short_circuits_before_any_local_branch(monkeypatch) -> None:
    sentinel = object()
    monkeypatch.setattr(
        "owner.feishu.profile_routing.try_route_card_action",
        lambda event, value: sentinel,
    )
    adapter = _bare_adapter()
    local: list = []
    monkeypatch.setattr(
        adapter, "_handle_approval_card_action", lambda **kw: local.append("local")
    )

    response = adapter._dispatch_card_action(
        object(),
        {"hermes_action": "approve_once"},
        object(),
        data=None,
        allow_profile_routing=True,
    )

    assert response is sentinel
    assert local == [], "a routed click must never run the local handler"


def test_allow_profile_routing_false_skips_routing(monkeypatch) -> None:
    def _boom(event: Any, value: Any) -> Any:
        raise AssertionError("routing must be skipped on the HTTP replay path")

    monkeypatch.setattr("owner.feishu.profile_routing.try_route_card_action", _boom)
    adapter = _bare_adapter()
    monkeypatch.setattr(adapter, "_handle_approval_card_action", lambda **kw: "local")

    assert (
        adapter._dispatch_card_action(
            object(),
            {"hermes_action": "approve_once"},
            object(),
            data=None,
            allow_profile_routing=False,
        )
        == "local"
    )


# ===========================================================================
# 3. Semantics — the moved helpers
# ===========================================================================


@pytest.mark.parametrize(
    "raw,expected",
    [
        ({"a": 1}, {"a": 1}),
        ('{"a": 1}', {"a": 1}),
        # JSON that parses but is NOT a dict must still collapse to {}: the
        # dispatcher's isinstance(action_value, dict) guards rely on it.
        ("[1, 2]", {}),
        ('"plain"', {}),
        ("42", {}),
        ("not json", {}),
        ("", {}),
        (None, {}),
        ([1, 2], {}),
    ],
)
def test_normalise_card_action_value(raw: Any, expected: Any) -> None:
    assert feishu_adapter.FeishuAdapter._normalise_card_action_value(raw) == expected


@pytest.mark.asyncio
async def test_send_card_reports_send_failure(monkeypatch) -> None:
    adapter = _bare_adapter()

    async def _raw(**kw: Any) -> Any:
        return SimpleNamespace(success=lambda: False)

    monkeypatch.setattr(adapter, "_send_raw_message", _raw)
    monkeypatch.setattr(
        adapter,
        "_finalize_send_result",
        lambda response, msg, chat_id=None: SendResult(success=False, error="card send failed"),
    )

    result = await adapter.send_card(chat_id="oc_x", card={"a": 1})

    assert result.success is False
    assert result.error == "card send failed"


@pytest.mark.asyncio
async def test_send_card_surfaces_send_success(monkeypatch) -> None:
    adapter = _bare_adapter()

    async def _raw(**kw: Any) -> Any:
        return SimpleNamespace(success=lambda: True)

    monkeypatch.setattr(adapter, "_send_raw_message", _raw)
    monkeypatch.setattr(
        adapter,
        "_finalize_send_result",
        lambda response, msg, chat_id=None: SendResult(success=True, message_id="om_1"),
    )

    result = await adapter.send_card(chat_id="oc_x", card={"a": 1})

    assert result.success is True
    assert result.message_id == "om_1"


@pytest.mark.asyncio
async def test_send_card_fails_open_when_send_raw_raises(monkeypatch) -> None:
    adapter = _bare_adapter()

    async def _boom(**kw: Any) -> Any:
        raise RuntimeError("transport down")

    monkeypatch.setattr(adapter, "_send_raw_message", _boom)

    result = await adapter.send_card(chat_id="oc_x", card={"a": 1})

    assert result.success is False
    assert "transport down" in (result.error or "")


@pytest.mark.asyncio
async def test_get_card_send_lock_is_per_chat_and_lru_bounded() -> None:
    adapter = _bare_adapter()
    adapter.CHAT_LOCK_MAX_SIZE = 2
    adapter._card_send_locks = OrderedDict()

    first = adapter._get_card_send_lock("oc_1")
    assert adapter._get_card_send_lock("oc_1") is first, "same chat must reuse its lock"

    adapter._get_card_send_lock("oc_2")
    adapter._get_card_send_lock("oc_3")

    assert len(adapter._card_send_locks) <= 2
    assert "oc_1" not in adapter._card_send_locks, "oldest entry must be evicted"


@pytest.mark.asyncio
async def test_send_model_picker_card_records_state_before_sending(monkeypatch) -> None:
    from owner.feishu import model_picker

    adapter = _bare_adapter()
    adapter._model_picker_state = {}
    monkeypatch.setattr(model_picker, "build_provider_card", lambda pid, provs: {"pid": pid})

    seen: Dict[str, Any] = {}

    async def _send_card(*, chat_id: str, card: Any, metadata: Any = None) -> SendResult:
        seen["state_at_send"] = dict(adapter._model_picker_state)
        seen["card"] = card
        return SendResult(success=True, message_id="om_1")

    monkeypatch.setattr(adapter, "send_card", _send_card)

    await adapter.send_model_picker_card(chat_id="oc_x", providers=[], source=None)

    assert seen["state_at_send"], "picker state must be written before the card goes out"
    assert len(adapter._model_picker_state) == 1
    assert seen["card"]["pid"] in adapter._model_picker_state


@pytest.mark.asyncio
async def test_send_guide_card_records_source(monkeypatch) -> None:
    from owner.feishu import steer_card

    adapter = _bare_adapter()
    adapter._guide_card_state = {}
    monkeypatch.setattr(steer_card, "build_guide_card", lambda gid: {"gid": gid})

    async def _send_card(*, chat_id: str, card: Any, metadata: Any = None) -> SendResult:
        return SendResult(success=True, message_id="om_2")

    monkeypatch.setattr(adapter, "send_card", _send_card)

    await adapter.send_guide_card(chat_id="oc_x", source="queue")

    assert list(adapter._guide_card_state.values()) == [{"source": "queue"}]


@pytest.mark.asyncio
async def test_send_queue_status_card_returns_the_send_result(monkeypatch) -> None:
    from owner.feishu import queue_card

    adapter = _bare_adapter()
    monkeypatch.setattr(queue_card, "build_queue_status_card", lambda *a, **k: {"card": 1})
    sentinel = SendResult(success=True, message_id="om_q")

    async def _send_card(*, chat_id: str, card: Any, metadata: Any = None) -> SendResult:
        return sentinel

    monkeypatch.setattr(adapter, "send_card", _send_card)

    result = await adapter.send_queue_status_card(
        chat_id="oc_x", user_input="hi", user_name="Bob", queue_token="tok12345678"
    )

    assert result is sentinel


@pytest.mark.asyncio
async def test_media_guard_hint_is_best_effort(monkeypatch) -> None:
    adapter = _bare_adapter()
    calls: list = []

    async def _send(**kw: Any) -> None:
        calls.append(kw)
        raise RuntimeError("dm down")

    monkeypatch.setattr(adapter, "send", _send)

    # must not propagate: a failed hint send may not mask the original upload failure
    await adapter._send_media_guard_hint("oc_x", "⚠️ too big", None, None)
    assert len(calls) == 1

    calls.clear()
    await adapter._send_media_guard_hint("oc_x", None, None, None)
    assert calls == [], "no hint text -> nothing to send"
