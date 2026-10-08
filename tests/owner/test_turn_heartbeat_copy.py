"""T2-20 A3 簇 7b-8 —— 网关「仍在工作」心跳文案（``gateway.still_working``）。

宿主 ``GatewayTurnMixin`` 不挂在 ``GatewayRunner`` 的 MRO 上（规则 ⑪），所以直接驱动
``_run_agent_notify_long_running`` 的**方法本体**，不去碰 ``GatewayRunner``。

本簇对象：宿主 ``gateway/run_turn.py`` 里的
``else f"⏳ Working — {_elapsed_mins} min{_status_detail}"`` 换成
``else t("gateway.still_working", …)``。之所以此前几轮的「同名宿主清扫」漏了它：
上游把这个嵌套闭包抽成了**改了名**的方法（我方 run.py 里仍叫 ``_notify_long_running``）。

en 值 ``"⏳ Working — {elapsed} min{status_detail}"`` 与 f-string 逐字同形
⇒ **英文零变化**（矩阵见 ``TestEnglishParityMatrix``，oracle 就是那条冻结的 f-string）；
zh 走 catalog（``⏳ 工作中 — N 分钟``）⇒ 谁把宿主改回 f-string，``zh`` 用例即全红。
"""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

import pytest

from gateway.run_turn import GatewayTurnMixin

# 冻结的 oracle：移植前宿主那行 f-string 的**同形**表达。
# 用 .format 而不是再写一条 f-string，是为了让「与上游逐字同形」这件事显式可见。
UPSTREAM_EN = "⏳ Working — {m} min{d}"
CATALOG_ZH = "⏳ 工作中 — {m} 分钟{d}"          # locales/zh.yaml::gateway.still_working


class _Clock:
    """``time.time()`` 每次 +step 秒，让 ``_elapsed_mins`` 可预测。"""

    def __init__(self, step: float = 300.0) -> None:
        self.now = 1_000.0
        self.step = step

    def time(self) -> float:
        value = self.now
        self.now += self.step
        return value


class _Adapter:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.edited: list[str] = []
        self.edit_ok = False

    async def edit_message(self, chat_id, message_id, text):
        self.edited.append(text)
        return SimpleNamespace(success=self.edit_ok, message_id=message_id)

    async def send(self, chat_id, text, metadata=None):
        self.sent.append(text)
        return SimpleNamespace(success=True, message_id=f"m{len(self.sent)}")


class _Runner(GatewayTurnMixin):
    """只装心跳方法用到的三个钩子：投递适配器 / 是否继续发 / 活动摘要。"""

    def __init__(self, adapter: _Adapter, *, emit_calls: int = 2, activity=None) -> None:
        self._adapter = adapter
        self._emit_calls = emit_calls
        self._activity = activity
        self._seen = 0

    def _delivery_adapter_for(self, source):                     # noqa: D102
        return self._adapter

    def _should_emit_long_running_notification(self, session_key, agent, exec_task):  # noqa: D102
        self._seen += 1
        return self._seen <= self._emit_calls

    def _agent_activity_summary(self, agent):                    # noqa: D102
        return self._activity


def _disp(*, mode: str = "terse", detail: bool = False, generic: str = "⚙️ Working on it"):
    return SimpleNamespace(
        _display_surface_mode=lambda *a, **k: mode,
        _generic_status_phrase=lambda kind, **k: generic,
        resolve_display_setting=lambda *a, **k: detail,
        user_config={},
        platform_key="telegram",
    )


def _turn_ctx():
    return SimpleNamespace(
        source=SimpleNamespace(platform="telegram", chat_id="c1"),
        session_key="s1",
        agent_holder=[SimpleNamespace(name="agent")],
        _status_thread_metadata=None,
        _cleanup_progress=False,
    )


async def _noop_sleep(_seconds):
    return None


def _drive(monkeypatch, *, lang: str, clock: _Clock, runner: _Runner, disp):
    """跑 1~N 轮心跳；``asyncio`` 与 ``time`` 都换成可控替身。"""
    monkeypatch.setenv("HERMES_LANGUAGE", lang)
    monkeypatch.setenv("HERMES_AGENT_NOTIFY_INTERVAL", "180")
    monkeypatch.setattr("gateway.run_turn.time", SimpleNamespace(time=clock.time))
    monkeypatch.setattr("gateway.run_turn.asyncio", SimpleNamespace(sleep=_noop_sleep))
    asyncio.run(
        runner._run_agent_notify_long_running(disp, _turn_ctx(), [None])
    )


def _heartbeat(monkeypatch, *, lang: str, activity=None, detail=False, mins=5, **kw) -> str:
    adapter = _Adapter()
    runner = _Runner(adapter, activity=activity, **kw)
    _drive(monkeypatch, lang=lang, clock=_Clock(step=mins * 60.0), runner=runner,
           disp=_disp(detail=detail))
    assert len(adapter.sent) == 1, f"期望恰好 1 次心跳发送，实得 {adapter.sent}"
    return adapter.sent[0]


# ---------------------------------------------------------------- en 逐字同形
class TestEnglishParityMatrix:
    """en 渲染必须与移植前那条 f-string **逐字**同形（否则英文侧就是行为变更）。

    三元组 = (``api_call_count``/``max_iterations``/``current_tool`` 摘要中的 cap 与工具,
    ``busy_ack_detail`` 闸门, 期望的 ``{status_detail}``)。迭代计数是**闸门后的**附加项，
    工具名不受闸门约束 —— 两个分支都要覆盖。
    """

    CASES = [
        # (mins, want_iter, activity, 期望 detail)
        (0, False, None, ""),
        (1, False, None, ""),
        (5, True, {"cap": 10, "tool": "web_search"}, " — iteration 3/10, web_search"),
        (59, False, {"cap": 10, "tool": "web_search"}, " — web_search"),
        (60, False, {"cap": 10, "tool": "terminal"}, " — terminal"),
        (125, True, {"cap": sys.maxsize, "tool": "web_search"}, " — iteration 3, web_search"),
        (1440, False, {"cap": 10, "tool": "delegate_task"}, " — delegate_task"),
    ]

    @pytest.mark.parametrize("mins,want_iter,activity,detail", CASES)
    def test_heartbeat_matches_upstream_fstring(self, mins, want_iter, activity, detail,
                                                monkeypatch):
        summary = None
        if activity:
            summary = {"api_call_count": 3, "max_iterations": activity["cap"],
                       "current_tool": activity["tool"]}
        text = _heartbeat(monkeypatch, lang="en", activity=summary, detail=want_iter,
                          mins=mins)
        assert text == UPSTREAM_EN.format(m=mins, d=detail)

    def test_unbounded_cap_hides_the_sentinel(self, monkeypatch):
        """``max_iterations=sys.maxsize``（无上限哨兵）不得把 19 位数字打进心跳。"""
        text = _heartbeat(
            monkeypatch, lang="en",
            activity={"api_call_count": 3, "max_iterations": sys.maxsize,
                      "current_tool": "web_search"},
            detail=True,
        )
        assert str(sys.maxsize) not in text
        assert text == UPSTREAM_EN.format(m=5, d=" — iteration 3, web_search")


# ---------------------------------------------------------------- zh 本地化
class TestZhLocalisation:

    def test_zh_uses_catalog(self, monkeypatch):
        text = _heartbeat(monkeypatch, lang="zh")
        assert text == CATALOG_ZH.format(m=5, d="")

    def test_zh_keeps_the_detail_suffix(self, monkeypatch):
        text = _heartbeat(
            monkeypatch, lang="zh",
            activity={"api_call_count": 3, "max_iterations": 10,
                      "current_tool": "web_search"},
            detail=True,
        )
        # 详情片段本身仍是英文 —— 与簇 7b-5 一致，已获用户裁决（接受英文片段）。
        assert text == CATALOG_ZH.format(m=5, d=" — iteration 3/10, web_search")

    def test_zh_is_not_the_hardcoded_fstring(self, monkeypatch):
        """把宿主改回 f-string 时，本用例（及其同类）是唯一会红的哨兵。"""
        text = _heartbeat(monkeypatch, lang="zh")
        assert "Working" not in text
        assert " min" not in text
        assert "工作中" in text and "分钟" in text

    def test_en_and_zh_differ(self, monkeypatch):
        assert _heartbeat(monkeypatch, lang="en") != _heartbeat(monkeypatch, lang="zh")


# ---------------------------------------------------------------- 分支与投递
class TestBranches:

    def test_generic_mode_uses_display_phrase(self, monkeypatch):
        adapter = _Adapter()
        runner = _Runner(adapter)
        _drive(monkeypatch, lang="zh", clock=_Clock(), runner=runner,
               disp=_disp(mode="generic", generic="⚙️ STATUS-PHRASE"))
        assert adapter.sent == ["⚙️ STATUS-PHRASE"]

    def test_off_mode_emits_nothing(self, monkeypatch):
        adapter = _Adapter()
        _drive(monkeypatch, lang="zh", clock=_Clock(), runner=_Runner(adapter),
               disp=_disp(mode="off"))
        assert adapter.sent == [] and adapter.edited == []

    def test_zero_interval_emits_nothing(self, monkeypatch):
        adapter = _Adapter()
        monkeypatch.setenv("HERMES_LANGUAGE", "zh")
        monkeypatch.setenv("HERMES_AGENT_NOTIFY_INTERVAL", "0")
        monkeypatch.setattr("gateway.run_turn.time", SimpleNamespace(time=_Clock().time))
        monkeypatch.setattr("gateway.run_turn.asyncio", SimpleNamespace(sleep=_noop_sleep))
        asyncio.run(
            _Runner(adapter)._run_agent_notify_long_running(_disp(), _turn_ctx(), [None])
        )
        assert adapter.sent == []

    def test_second_round_edits_the_same_bubble(self, monkeypatch):
        """心跳优先就地编辑同一条消息，而不是每轮刷一条新气泡。"""
        adapter = _Adapter()
        adapter.edit_ok = True
        _drive(monkeypatch, lang="zh", clock=_Clock(), runner=_Runner(adapter, emit_calls=4),
               disp=_disp())
        assert len(adapter.sent) == 1
        assert adapter.edited, "第二轮必须走 edit_message"
        # 第 1 轮 send 是 5 分钟；其后的编辑按逐轮 +5 分钟推进（同一时钟）。
        assert adapter.sent[0] == CATALOG_ZH.format(m=5, d="")
        assert [t == CATALOG_ZH.format(m=m, d="") for t, m in
                zip(adapter.edited, (10, 15))] == [True] * len(adapter.edited)
        assert all("Working" not in t for t in adapter.edited)

    def test_zh_heartbeat_carries_interim_marker(self, monkeypatch):
        """心跳属「非终局」发送，必须带 interim 标记（否则会封住流式答案）。"""
        captured = {}

        class _Meta(_Adapter):
            async def send(self, chat_id, text, metadata=None):
                captured["metadata"] = metadata
                return await super().send(chat_id, text, metadata=metadata)

        adapter = _Meta()
        _drive(monkeypatch, lang="zh", clock=_Clock(), runner=_Runner(adapter), disp=_disp())
        assert captured["metadata"] is not None
