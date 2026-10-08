"""T2-20 A3 簇 7b-2 —— ``gateway/run_turn.py::_hmwa_agent_error_reply`` 的错误提示。

宿主 ``GatewayTurnMixin`` 未挂到 ``GatewayRunner`` 的 MRO 上，故这里直接驱动该方法的**本体**
（规则 ⑪）：断言对象是**行为** —— 真的发了哪条提示。

本簇同时锁两类东西：
* **文案**：英文逐字等于上游（`HEAD:` 形态）的硬编码串；中文真本地化。
* **一个结构不变量**：``_STATUS_HINTS`` 的值必须是 **catalog 键**，且类体里**不得**出现 `t()`
  —— 类体在 **import 时**求值，若把 `t()` 写进去，文案与语言会被一起冻结（这是本簇刻意避开的坑，
  与 `PAIRING_RATE_LIMITED_REPLY` / `_BUSY_REJECT_I18N_KEYS` 同法）。
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from gateway.config import Platform
from gateway.run_turn import GatewayTurnMixin
from gateway.session import SessionSource

# 上游（`HEAD:`）硬编码串 —— 基线由验收脚本用 AST 抠表达式求值复核，这里按已核结果断言。
UP_401 = (
    " Your sign-in to the AI model service has expired or the API key is wrong. "
    "Use /login here, or run `{relogin}` on the host."
)
UP_402 = (
    " Your AI model service balance or quota is used up. "
    "Top it up on the service's website, or use /model to switch models."
)
UP_529 = " The AI model service is temporarily overloaded. Wait a moment, then use /retry."
UP_400 = " The AI model service rejected the request."
UP_TAIL = (
    "⚠️ Something went wrong and I couldn't finish this reply.{status_hint}\n"
    "Use /retry to try again, or /new to start a fresh conversation. "
    "Technical details are in the gateway log (`hermes logs`)."
)
UP_OVERFLOW = (
    "⚠️ This conversation has grown too long for me to read all at once. "
    "Use /compress to shorten the history, or /new to start a fresh conversation."
)
# 宿主**逐字保留**的我方三句（保我方那一类）
KEPT_RATE_LIMITED = " You are being rate-limited. Please wait a moment and try again."
KEPT_USAGE_LIMIT = " Your plan's usage limit has been reached. Please wait until it resets."


class _Err(Exception):
    def __init__(self, status_code, body=None):
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code
        self.response = _Resp(body) if body is not None else None


class _Resp:
    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body


class _Prepared:
    def __init__(self, history):
        self.history = history
        self.message_text = None      # 走不到持久化分支
        self.persistence_session_id = "s"
        self.persistence_owner = "o"


class _Runner(GatewayTurnMixin):
    """最小宿主：只提供 `_hmwa_agent_error_reply` 用到的钩子。"""

    def __init__(self, history):
        self.notices: list[str] = []
        self._history = history

    async def _hmwa_stop_typing_for_turn(self, event, source):
        return None

    async def _hmwa_close_failed_turn(self, session_id, notice):
        return None

    def _hmwa_user_transcript_entry(self, event, prepared, ts):  # pragma: no cover
        return {}

    def _hmwa_add_failed_turn_notice(self, text, notice):
        self.notices.append(text)
        return text

    def _session_state(self, session_key):
        class _S:
            class turn:  # noqa: N801
                agent = None
        return _S()

    @property
    def async_session_store(self):  # pragma: no cover
        raise AssertionError("不应走到持久化分支")


def _source():
    return SessionSource(platform=Platform.TELEGRAM, chat_id="c1", user_id="u1")


def _reply(*, lang, status_code, body=None, history=None, relogin="hermes login"):
    runner = _Runner(history if history is not None else [])
    prepared = _Prepared(runner._history)
    with patch.dict("os.environ", {"HERMES_LANGUAGE": lang}), \
         patch("agent.turn_failure_copy.relogin_command_hint", return_value=relogin):
        out = asyncio.run(
            runner._hmwa_agent_error_reply(_Err(status_code, body), None, _source(), None, "sk", prepared)
        )
    return runner, out


# ------------------------------------------------------------------ 结构不变量
class TestStatusHintsHoldKeys:

    def test_values_are_catalog_keys_not_copy(self):
        hints = GatewayTurnMixin._STATUS_HINTS
        assert set(hints) == {401, 402, 529}
        for code, val in hints.items():
            assert isinstance(val, str) and val.startswith("gateway."), (code, val)

    def test_class_body_does_not_resolve_i18n(self):
        """类体在 import 时求值 —— 类体**直接语句**里出现 `t(` 会把文案与语言一起冻结。"""
        import ast
        import inspect
        import textwrap

        from gateway import run_turn

        raw = textwrap.dedent(inspect.getsource(run_turn.GatewayTurnMixin))
        cls = ast.parse(raw).body[0]
        assert isinstance(cls, ast.ClassDef)
        direct = [n for n in cls.body if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        segs = [ast.get_source_segment(raw, n) or "" for n in direct]
        assert any("_STATUS_HINTS" in s for s in segs), "类体里应含 _STATUS_HINTS 赋值"
        for s in segs:
            assert "t(" not in s, f"类体直接语句不应解析 i18n：{s[:80]!r}"


# ------------------------------------------------------------------ 取上游新文案
class TestUpstreamRewrittenCopy:

    def test_401_uses_relogin_slot(self):
        _r, out = _reply(lang="en", status_code=401, relogin="run `hermes login`")
        assert out == UP_TAIL.format(status_hint=UP_401.format(relogin="run `hermes login`"))

    def test_401_localized(self):
        _r, out = _reply(lang="zh", status_code=401, relogin="`hermes login`")
        assert out != UP_TAIL.format(status_hint=UP_401.format(relogin="`hermes login`"))
        assert "凭据已失效" in out and "hermes login" in out

    def test_402_verbatim(self):
        _r, out = _reply(lang="en", status_code=402)
        assert out == UP_TAIL.format(status_hint=UP_402)

    def test_529_verbatim(self):
        _r, out = _reply(lang="en", status_code=529)
        assert out == UP_TAIL.format(status_hint=UP_529)

    def test_400_verbatim(self):
        _r, out = _reply(lang="en", status_code=400)
        assert out == UP_TAIL.format(status_hint=UP_400)

    def test_tail_sentence_verbatim(self):
        """收尾句本身：无 hint 时（如 500 且 history 不大）应逐字等于上游。"""
        _r, out = _reply(lang="en", status_code=500)
        assert out == UP_TAIL.format(status_hint="")

    def test_overflow_early_return_verbatim(self):
        _r, out = _reply(lang="en", status_code=400, history=list(range(60)))
        assert out == UP_OVERFLOW


# ------------------------------------------------------------------ 保我方那三句
class TestKeptCopy:

    def test_429_transient_verbatim(self):
        _r, out = _reply(lang="en", status_code=429, body={"error": {"type": "rate_limit"}})
        assert out == UP_TAIL.format(status_hint=KEPT_RATE_LIMITED)

    def test_429_plan_no_resets_verbatim(self):
        _r, out = _reply(lang="en", status_code=429, body={"error": {"type": "usage_limit_reached"}})
        assert out == UP_TAIL.format(status_hint=KEPT_USAGE_LIMIT)

    def test_429_plan_with_resets_verbatim(self):
        _r, out = _reply(
            lang="en", status_code=429,
            body={"error": {"type": "usage_limit_reached", "resets_in_seconds": 7200}},
        )
        assert out == UP_TAIL.format(
            status_hint=" Your plan's usage limit has been reached. It resets in ~2h."
        )

    def test_429_plan_resets_localized(self):
        _r, out = _reply(
            lang="zh", status_code=429,
            body={"error": {"type": "usage_limit_reached", "resets_in_seconds": 7200}},
        )
        assert "2 小时" in out


# ------------------------------------------------------------------ 横切不变量
class TestCrossCutting:

    @pytest.mark.parametrize("lang", ["en", "zh"])
    @pytest.mark.parametrize("code,body", [(401, None), (402, None), (429, None), (529, None), (400, None)])
    def test_no_leftover_placeholders(self, lang, code, body):
        _r, out = _reply(lang=lang, status_code=code, body=body)
        assert "{" not in out and "gateway." not in out

    def test_language_is_resolved_per_call(self):
        _r, en = _reply(lang="en", status_code=529)
        _r2, zh = _reply(lang="zh", status_code=529)
        assert zh != en

    def test_notice_wrapper_still_used(self):
        runner, _out = _reply(lang="en", status_code=402)
        assert len(runner.notices) == 1

    def test_overflow_skips_notice_wrapper(self):
        runner, _out = _reply(lang="en", status_code=400, history=list(range(60)))
        assert runner.notices == []


# ------------------------------------------------------------------ 控制组：单体旧键仍可用
class TestOldKeysStillServeMonolith:

    @pytest.mark.parametrize("lang", ["en", "zh"])
    def test_legacy_auth_key_renders(self, lang):
        from agent.i18n import t

        out = t("gateway.agent_error_hint_auth", lang=lang)
        assert out and "{" not in out and "gateway." not in out

    @pytest.mark.parametrize("lang", ["en", "zh"])
    def test_legacy_tail_key_renders(self, lang):
        from agent.i18n import t

        out = t("gateway.agent_error", lang=lang, status_hint=" HINT")
        assert "HINT" in out
