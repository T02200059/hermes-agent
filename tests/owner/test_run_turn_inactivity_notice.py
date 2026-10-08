"""T2-20 A3 簇 7b-5 —— ``run_turn.py`` 的 inactivity 警告 + 超时诊断。

宿主 ``GatewayTurnMixin`` 未挂到 ``GatewayRunner`` 的 MRO 上，故直接驱动两个方法**本体**（规则 ⑪）。

两类裁定：
* **取上游文案**：`_run_agent_inactivity_warning` 的整句被上游换过（指引 `/stop` + `/new`、并说明会
  放弃任务），且发送 API 改成 `emit_warning(..., logical_platform=)` ⇒ 走**新键**。
* **header/tail 保我方 + 迭代渲染取上游**：`_run_agent_timeout_result` 的 header 与 tail 与我方
  `gateway.agent_timeout` 模板逐字相同；差异只在迭代渲染 —— 上游用 `format_iteration_progress`
  隐藏 `sys.maxsize` 无界哨兵（#102806），我方 BASE 版会打印 `iteration 3/9223372036854775807`。
  这里既断言**无界时只印 `iteration N`**（防止将来回退成裸 `{n}/{m}`），也断言文案逐字。
"""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from gateway.config import Platform
from gateway.run_turn import GatewayTurnMixin
from gateway.session import SessionSource

# 宿主（= 上游）硬编码英文 —— 由验收脚本用 AST 从 `HEAD:` 抠表达式复核
UP_WARNING = (
    "⚠️ I seem to be stuck (no activity for {elapsed} min). If nothing happens in the next "
    "{remaining} min I'll give up on this task. You can keep waiting, send /stop to cancel it, "
    "or /new to start a fresh conversation."
)
HEADER = "⏱️ Agent inactive for {timeout_mins} min — no tool calls or API responses."
TOOL_DETAIL = ("The agent appears stuck on tool `{cur_tool}` ({secs_since}s since last activity, "
               "{iter_progress}).")
ACT_DETAIL = ("Last activity: {last_desc} ({secs_since}s ago, {iter_progress}). "
              "The agent may have been waiting on an API response.")
TAIL = ("To increase the limit, set agent.gateway_timeout in config.yaml (value in seconds, 0 "
        "= no limit) and restart the gateway.\nTry again, or use /reset to start fresh.")


class _Adapter:
    def __init__(self):
        self.warned: list[str] = []

    async def emit_warning(self, chat_id, text, **kwargs):
        self.warned.append(text)


class _Runner(GatewayTurnMixin):
    def __init__(self, adapter=None, activity=None):
        self._adapter = adapter
        self._activity = activity or {}

    def _delivery_adapter_for(self, source):
        return self._adapter

    def _agent_activity_summary(self, agent):
        return dict(self._activity)


def _source():
    return SessionSource(platform=Platform.TELEGRAM, chat_id="c1", user_id="u1")


def _warning(*, lang, agent_warning=300, agent_timeout=1800):
    adapter = _Adapter()
    runner = _Runner(adapter)
    worker = SimpleNamespace(agent_warning=agent_warning, agent_timeout=agent_timeout)
    with patch.dict("os.environ", {"HERMES_LANGUAGE": lang}), \
         patch("gateway.run._interim_metadata", return_value={}):
        asyncio.run(runner._run_agent_inactivity_warning(worker, _source(), {}))
    return adapter


_MISSING = object()


def _timeout(*, lang, cur_tool="bash", secs_ago=12.4, last_desc="thinking", iter_n=3,
             iter_max=10, agent_timeout=1800):
    runner = _Runner(activity={
        "last_activity_desc": last_desc, "seconds_since_activity": secs_ago,
        "current_tool": cur_tool, "api_call_count": iter_n, "max_iterations": iter_max,
    })
    ctx = SimpleNamespace(
        session_key="sk", agent_holder=[object()], result_holder=[{"messages": [1, 2]}],
        tools_holder=[["t1"]],
    )
    worker = SimpleNamespace(agent_timeout=agent_timeout)
    with patch.dict("os.environ", {"HERMES_LANGUAGE": lang}), \
         patch("gateway.run._INTERRUPT_REASON_TIMEOUT", "timeout", create=True), \
         patch("gateway.run._INTERRUPT_TOOL_REASON_TIMEOUT", "tool", create=True), \
         patch("gateway.run.request_hard_interrupt", lambda *a, **k: None, create=True), \
         patch("gateway.run_turn.request_hard_interrupt", lambda *a, **k: None, create=True):
        out = runner._run_agent_timeout_result(worker, ctx)
    return out


# ------------------------------------------------------------------ A. inactivity 警告
class TestInactivityWarning:

    def test_english_verbatim(self):
        a = _warning(lang="en", agent_warning=300, agent_timeout=1800)
        assert a.warned == [UP_WARNING.format(elapsed=5, remaining=25)]

    def test_floor_of_one_minute(self):
        a = _warning(lang="en", agent_warning=30, agent_timeout=60)
        assert a.warned == [UP_WARNING.format(elapsed=1, remaining=1)]

    def test_localized(self):
        a = _warning(lang="zh")
        assert a.warned and a.warned[0] != UP_WARNING.format(elapsed=5, remaining=25)
        assert "我似乎卡住了" in a.warned[0] and "/stop" in a.warned[0]

    def test_no_leftover_placeholders(self):
        for lang in ("en", "zh"):
            a = _warning(lang=lang)
            assert "{" not in a.warned[0] and "gateway." not in a.warned[0]

    def test_no_adapter_is_noop(self):
        runner = _Runner(None)
        worker = SimpleNamespace(agent_warning=300, agent_timeout=1800)
        with patch("gateway.run._interim_metadata", return_value={}):
            asyncio.run(runner._run_agent_inactivity_warning(worker, _source(), {}))


# ------------------------------------------------------------------ B. 超时诊断
class TestTimeoutResult:

    def test_tool_branch_verbatim(self):
        out = _timeout(lang="en", cur_tool="bash", secs_ago=12.4, iter_n=3, iter_max=10)
        detail = TOOL_DETAIL.format(cur_tool="bash", secs_since=12, iter_progress="iteration 3/10")
        assert out["final_response"] == "\n".join(
            [HEADER.format(timeout_mins=30), detail, TAIL])

    def test_activity_branch_verbatim(self):
        out = _timeout(lang="en", cur_tool=None, last_desc="thinking", secs_ago=12.4,
                       iter_n=3, iter_max=10)
        detail = ACT_DETAIL.format(last_desc="thinking", secs_since=12,
                                   iter_progress="iteration 3/10")
        assert out["final_response"] == "\n".join(
            [HEADER.format(timeout_mins=30), detail, TAIL])

    def test_unbounded_iteration_hides_the_sentinel(self):
        """上游按 #102806 修的：`max_iterations` 为 `sys.maxsize` 时只印 `iteration N`。"""
        out = _timeout(lang="en", iter_n=3, iter_max=sys.maxsize)
        assert "iteration 3)" in out["final_response"], out["final_response"]
        assert str(sys.maxsize) not in out["final_response"]

    def test_localized(self):
        out = _timeout(lang="zh", cur_tool="bash")
        assert "代理已不活跃" in out["final_response"]
        assert "卡在工具" in out["final_response"]

    def test_metadata_preserved(self):
        out = _timeout(lang="en")
        assert out["failed"] is True
        assert out["api_calls"] == 3
        assert out["history_offset"] == 0
        assert out["messages"] == [1, 2]
        assert out["tools"] == ["t1"]

    def test_no_leftover_placeholders(self):
        for lang in ("en", "zh"):
            for cur_tool in ("bash", None):
                out = _timeout(lang=lang, cur_tool=cur_tool)
                assert "{" not in out["final_response"]
                # 键路径泄漏的判据要具体：正句里本来就有 "restart the gateway."
                assert "gateway.agent_timeout" not in out["final_response"]
                assert "gateway.no_activity" not in out["final_response"]

    @pytest.mark.parametrize("secs,expect", [(12.4, 12), (12.6, 13), (0.4, 0)])
    def test_seconds_rounding_matches_format_spec(self, secs, expect):
        """我方用 `round()`、宿主的 f-string 用 `:.0f` —— 两者须一致（银行家舍入）。"""
        out = _timeout(lang="en", secs_ago=secs, cur_tool="x")
        assert f"({expect}s since last activity" in out["final_response"]


# ------------------------------------------------------------------ 控制组：单体旧键仍在
class TestOldKeysStillServeMonolith:

    @pytest.mark.parametrize("lang", ["en", "zh"])
    def test_legacy_keys_render(self, lang):
        from agent.i18n import t

        out = t("gateway.no_activity_warning", lang=lang, elapsed=1, remaining=2)
        assert ("No activity for 1 min" in out) or ("1 分钟" in out), out
        assert t("gateway.agent_timeout_detail_tool", lang=lang, cur_tool="c", secs_since=1,
                 iter_n=1, iter_max=2)
