"""T2-20 A3 簇 7b-4 —— ``gateway/run_turn.py::_hmwa_prepend_reasoning`` 的 reasoning 增强。

宿主 ``GatewayTurnMixin`` 未挂到 ``GatewayRunner`` 的 MRO 上，故直接驱动该方法**本体**（规则 ⑪）。

本簇两件事：
* **保我方**：`displayable_reasoning` 过滤（上游 0 处，是我方能力）—— 裸值守卫下，**只有空白**的
  reasoning 桩（provider 回放用的 `" "` 填充）是 truthy，会渲染出**空的 💭 框**。
* **等价已落位**：内层栅栏转义 —— 宿主用 `escape_code_fences_for_display`（无锚点 `replace`），
  7 例对抗性行为对比显示它与我们的 `escape_code_fences_for_inline_block` 一样**不会破出外层块**
  （含缩进/制表符栅栏），差异只在输出形态（`` \\`\\`\\` `` vs `'''`），故走登记而非重落。
  这里仍把「缩进栅栏也不破出」锁进用例，防止将来上游换回朴素式。

A3 期现实：宿主 `_hmwa_prepend_reasoning` 里 `from gateway.stream_consumer_fences import …` 指向的
模块**我方树里还没有**（上游拆出来的新模块，属惰性闭包、A4 前向移植才到位），故测试注入一个
转发到现有 `gateway/stream_consumer.escape_code_fences_for_display` 的替身模块。
"""

from __future__ import annotations

import re
import sys
from types import ModuleType
from unittest.mock import patch

import pytest

from gateway.config import Platform
from gateway.run_turn import GatewayTurnMixin
from gateway.session import SessionSource

BREAKABLE = re.compile(r"(?m)^[ \t]*`{3,}")


class _Runner(GatewayTurnMixin):
    def __init__(self, *, show_reasoning=True):
        self._show_reasoning = show_reasoning


def _source(platform=Platform.TELEGRAM):
    return SessionSource(platform=platform, chat_id="c1", user_id="u1")


def _fake_fences_module() -> ModuleType:
    """替身：把上游拆出的 `gateway.stream_consumer_fences` 转发到我们已有的实现。"""
    from gateway.stream_consumer import escape_code_fences_for_display

    m = ModuleType("gateway.stream_consumer_fences")
    m.escape_code_fences_for_display = escape_code_fences_for_display  # type: ignore[attr-defined]
    return m


def _prepend(reasoning, *, response="BODY", show=True, silence=False, style="code",
             platform=Platform.TELEGRAM):
    runner = _Runner(show_reasoning=show)
    agent_result: dict = {}
    if reasoning is not _MISSING:
        agent_result["last_reasoning"] = reasoning
    with patch("gateway.run._load_gateway_config", return_value={}), \
         patch("gateway.run._platform_config_key", return_value="telegram"), \
         patch("gateway.run._resolve_gateway_display_bool", return_value=show), \
         patch("gateway.display_config.resolve_display_setting_for_source", return_value=style), \
         patch.dict(sys.modules, {"gateway.stream_consumer_fences": _fake_fences_module()}):
        out = runner._hmwa_prepend_reasoning(agent_result, response, _source(platform), silence)
    return out


_MISSING = object()


# ------------------------------------------------------------------ 保我方：pad-only 不得出框
class TestPadOnlyStubSuppressed:
    """裸值守卫下 `" "` 是 truthy ⇒ 会出空框。这是本簇要保住的行为。"""

    @pytest.mark.parametrize("stub", [" ", "   ", "\n", "\t\n  ", "\u00a0"])
    def test_whitespace_only_reasoning_produces_no_box(self, stub):
        assert _prepend(stub) == "BODY"

    def test_missing_key_produces_no_box(self):
        assert _prepend(_MISSING) == "BODY"

    def test_none_produces_no_box(self):
        assert _prepend(None) == "BODY"

    def test_real_reasoning_stripped_and_shown(self):
        out = _prepend("  a real thought  ")
        assert out.startswith("💭 **Reasoning:**")
        assert "a real thought" in out and out.endswith("BODY")


# ------------------------------------------------------------------ 出框时的三种渲染
class TestRenderStyles:

    def test_default_code_block(self):
        out = _prepend("thought")
        assert out == "💭 **Reasoning:**\n```\nthought\n```\n\nBODY"

    def test_subtext_style(self):
        out = _prepend("thought", style="subtext")
        assert out.startswith("-# 💭 Reasoning")
        assert out.endswith("BODY")

    def test_blockquote_style(self):
        out = _prepend("thought", style="blockquote")
        assert out.startswith("> 💭 **Reasoning:**")
        assert out.endswith("BODY")

    def test_long_reasoning_collapsed(self):
        out = _prepend("\n".join(f"l{i}" for i in range(20)))
        assert "5 more lines" in out
        assert "l19" not in out


# ------------------------------------------------------------------ 守卫的三条负路
class TestGuards:

    def test_show_reasoning_off(self):
        assert _prepend("thought", show=False) == "BODY"

    def test_intentional_silence(self):
        assert _prepend("thought", silence=True) == "BODY"

    def test_empty_response(self):
        assert _prepend("thought", response="") == ""


# ------------------------------------------------------------------ 栅栏不破出（等价已落位的那部分）
class TestFenceNeverBreaksOut:

    @pytest.mark.parametrize("fence", ["```", "  ```", "\t```py", "`````"])
    def test_indented_and_tab_fences_are_neutralised(self, fence):
        reasoning = f"before\n{fence}\nafter"
        out = _prepend(reasoning)
        inner = out.split("```\n", 1)[1].rsplit("\n```", 1)[0]
        assert not BREAKABLE.search(inner), f"内层栅栏仍可破出：{inner!r}"

    def test_info_string_preserved_for_plain_fence(self):
        out = _prepend("```python\nx\n```")
        assert "python" in out
