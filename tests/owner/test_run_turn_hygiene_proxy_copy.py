"""T2-20 A3 簇 7b-9（A3 收尾）—— `gateway/run_turn.py` 剩余 13 行。

宿主 `GatewayTurnMixin` 不在 `GatewayRunner` 的 MRO 上（规则 ⑪），故全部**驱动方法本体**：

| 我方行 | 宿主方法 | 本文件覆盖 |
|---|---|---|
| 22190 / 22209 | `_hmwa_hygiene_apply_result` | 卫生压缩警告 + 辅助模型回退提示（`_hmwa_hygiene_notify` 上挂 spy 取实参） |
| 22320 | `_hmwa_first_contact_notes` | 「未设主频道」提示 + `{sethome_cmd}` 的 Slack 分支 |
| 22510 | `_hmwa_shape_agent_response` | `(empty)` 分支的新键（en 与上游 `"⚠️ " + EMPTY_RESPONSE_EXPLANATION.format(...)` 逐字同形） |
| 22851 | `_hmwa_compression_exhaustion_reset` | 自动重置尾句 |
| 23256 / 23258 / 23260 | `_format_session_info` | `ctx_source` 三个取值（等价已落位的登记对象） |
| 30042 / 30051 / 30190 / 30254 / 30293 | `_run_agent_via_proxy` | 5 条代理错误/空响应分支（注入假 aiohttp） |

en 侧一律断言与**上游字面量逐字同形**（本簇 8 处 en 逐字相同、2 处内容取上游 ⇒ 英文行为不变）；
zh 侧断言走 catalog（`≠ en`）。
"""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

import pytest

from gateway.config import Platform
from gateway.run_turn import GatewayTurnMixin

# 上游 `agent/turn_explainers.EMPTY_RESPONSE_EXPLANATION`（本树尚无该模块；A4 前向移植）
UPSTREAM_EMPTY_EXPLANATION = (
    "{model} didn't produce a reply this time, even after retries. "
    "Send `continue` to try again, or switch models with /model."
)
UPSTREAM_HISTORY_SHORTENING_FAILED = (
    "⚠️ Shortening the conversation history failed, so I kept everything as-is. "
    "Run /compress to try again or /new to start fresh. If this keeps happening, "
    "run `hermes doctor` on the host."
)


def _run(coro):
    return asyncio.run(coro)


def _source(platform=Platform.TELEGRAM, chat_id="c1", profile=""):
    return SimpleNamespace(platform=platform, chat_id=chat_id, profile=profile)


# =====================================================================================
# 卫生压缩：abort 警告（新键）与辅助模型回退提示
# =====================================================================================
class _HygieneRunner(GatewayTurnMixin):
    def __init__(self, *, aborted: bool, aux_model: str | None = None):
        self._aborted = aborted
        self._aux_model = aux_model
        self.notices: list[str] = []
        self.adapters: dict = {}
        self.cooldowns: list[tuple] = []
        self.stamps: list[tuple] = []

    async def _hmwa_hygiene_adopt_transcript(self, *a, **k):
        return (False, False, 3, 1000)          # rotated / in_place / new_count / new_tokens

    async def _hmwa_hygiene_record_failure_cooldown(self, *a, **k):
        self.cooldowns.append(a)

    def _hmwa_hygiene_stamp(self, *a, **k):
        self.stamps.append(a)

    async def _hmwa_hygiene_notify(self, source, meta, text, kind):
        self.notices.append(text)

    def _make_attempt(self):
        compressor = SimpleNamespace(
            _last_compress_aborted=self._aborted,
            _last_summary_error="provider 401 boom",
            _last_aux_model_failure_model=self._aux_model,
            _last_aux_model_failure_error="no route",
        )
        return SimpleNamespace(
            agent=SimpleNamespace(context_compressor=compressor),
            commit_fence=SimpleNamespace(is_cancelled=False),
            meta={"k": "v"},
        )


def _hygiene(monkeypatch, *, lang, aborted, aux_model=None):
    monkeypatch.setenv("HERMES_LANGUAGE", lang)
    runner = _HygieneRunner(aborted=aborted, aux_model=aux_model)
    plan = SimpleNamespace(msg_count=10, approx_tokens=5000, context_length=200000)
    hs = SimpleNamespace(hard_msg_limit=40, threshold_pct=75)
    _run(runner._hmwa_hygiene_apply_result(
        runner._make_attempt(), hs, True, [], plan,
        session_entry=SimpleNamespace(session_id="s1"), session_key="k1",
        source=_source(), _quick_key="q1", run_generation=1,
    ))
    return runner


class TestHygieneCompressionNotices:

    def test_abort_notice_en_matches_upstream_copy(self, monkeypatch):
        runner = _hygiene(monkeypatch, lang="en", aborted=True)
        assert runner.notices == [UPSTREAM_HISTORY_SHORTENING_FAILED]

    def test_abort_notice_zh_is_localised(self, monkeypatch):
        runner = _hygiene(monkeypatch, lang="zh", aborted=True)
        assert len(runner.notices) == 1
        text = runner.notices[0]
        assert text != UPSTREAM_HISTORY_SHORTENING_FAILED
        assert "缩短对话历史失败" in text and "hermes doctor" in text
        # 上游这版**刻意不再回显 error**（凭据风险）—— zh 侧同样不得漏出
        assert "provider 401 boom" not in text

    def test_aux_model_fallback_notice_en_is_byte_identical(self, monkeypatch):
        runner = _hygiene(monkeypatch, lang="en", aborted=False, aux_model="small")
        assert runner.notices == [
            "ℹ️ Configured compression model `small` failed (no route). Recovered using your "
            "main model — context is intact — but you may want to check "
            "`auxiliary.compression.model` in config.yaml."
        ]

    def test_aux_model_fallback_notice_zh_is_localised(self, monkeypatch):
        runner = _hygiene(monkeypatch, lang="zh", aborted=False, aux_model="small")
        assert len(runner.notices) == 1
        assert "配置的压缩模型" in runner.notices[0]
        assert "auxiliary.compression.model" in runner.notices[0]

    def test_no_aux_failure_means_no_notice(self, monkeypatch):
        runner = _hygiene(monkeypatch, lang="zh", aborted=True, aux_model=None)
        assert len(runner.notices) == 1        # 只有 abort 那条


# =====================================================================================
# 首次联系：未设主频道提示
# =====================================================================================
class _FirstContactRunner(GatewayTurnMixin):
    def __init__(self):
        self.delivered: list[str] = []
        self.async_session_store = SimpleNamespace(
            has_any_sessions=self._has_sessions)
        self.config = SimpleNamespace(get_home_channel=lambda platform: None)

    async def _has_sessions(self):
        return True                             # 跳过「首条消息」intro 分支

    async def _deliver_platform_notice(self, source, notice):
        self.delivered.append(notice)


def _first_contact(monkeypatch, *, lang, platform):
    monkeypatch.setenv("HERMES_LANGUAGE", lang)
    monkeypatch.delenv("HERMES_HOME_TARGET_TELEGRAM", raising=False)
    monkeypatch.delenv("HERMES_HOME_TARGET_SLACK", raising=False)
    runner = _FirstContactRunner()
    _run(runner._hmwa_first_contact_notes(_source(platform), [], []))
    return runner


class TestFirstContactHomeChannelNotice:

    def test_en_matches_upstream_copy(self, monkeypatch):
        runner = _first_contact(monkeypatch, lang="en", platform=Platform.TELEGRAM)
        assert runner.delivered == [
            "📬 No home channel is set for Telegram. A home channel is where Hermes delivers "
            "cron job results and cross-platform messages.\n\nType /sethome to make this chat "
            "your home channel, or ignore to skip."
        ]

    def test_zh_is_localised(self, monkeypatch):
        runner = _first_contact(monkeypatch, lang="zh", platform=Platform.TELEGRAM)
        assert len(runner.delivered) == 1
        assert "未设置主频道" in runner.delivered[0]
        assert "No home channel" not in runner.delivered[0]

    def test_slack_gets_the_parent_command(self, monkeypatch):
        """`{sethome_cmd}` 的 Slack 分支仍生效（Slack 命令都走父级 `/hermes`）。"""
        runner = _first_contact(monkeypatch, lang="en", platform=Platform.SLACK)
        assert "/hermes sethome" in runner.delivered[0]
        zh = _first_contact(monkeypatch, lang="zh", platform=Platform.SLACK)
        assert "/hermes sethome" in zh.delivered[0]


# =====================================================================================
# `(empty)` 分支：新键承载上游共享文案
# =====================================================================================
class _ShapeRunner(GatewayTurnMixin):
    def __init__(self):
        self.async_session_store = SimpleNamespace(clear_resume_pending=self._noop)

    @staticmethod
    async def _noop(*a, **k):
        return None

    def _is_intentional_silence(self, agent_result, response):
        return False

    async def _clear_restart_failure_count(self, session_key):
        return None


async def _shape(monkeypatch, *, lang, model="claude-sonnet-4"):
    monkeypatch.setenv("HERMES_LANGUAGE", lang)
    result = {"final_response": "(empty)", "model": model, "messages": [], "api_calls": 3}
    response, _silence, _msgs = await _ShapeRunner()._hmwa_shape_agent_response(
        result, _source(), [], SimpleNamespace(session_id="s1"), "k1", "q1", 1, "s1",
        "telegram", 0.0,
    )
    return response


class TestEmptyResponseExplanation:

    def test_en_matches_upstream_concatenation(self, monkeypatch):
        text = _run(_shape(monkeypatch, lang="en"))
        assert text == "⚠️ " + UPSTREAM_EMPTY_EXPLANATION.format(model="claude-sonnet-4")

    def test_zh_is_localised(self, monkeypatch):
        text = _run(_shape(monkeypatch, lang="zh"))
        assert "本次没有产出回复" in text and "`continue`" in text
        assert "didn't produce a reply" not in text

    def test_model_fallback_is_upstreams(self, monkeypatch):
        text = _run(_shape(monkeypatch, lang="en", model=""))
        assert text == "⚠️ " + UPSTREAM_EMPTY_EXPLANATION.format(model="The model")

    def test_command_path_does_not_import_the_missing_module(self):
        """落位顺带消掉一处 A3 期悬空 import（`agent.turn_explainers` 本树没有）。"""
        import ast
        import pathlib

        src = pathlib.Path(GatewayTurnMixin.__module__.replace(".", "/") + ".py").read_text(
            encoding="utf-8")
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("agent.turn_explainers"):
                raise AssertionError(f"宿主仍在 import {node.module}（本树不存在该模块）")


# =====================================================================================
# 压缩耗尽后的自动重置尾句
# =====================================================================================
class _ResetRunner(GatewayTurnMixin):
    def __init__(self, new_entry):
        self._new_entry = new_entry
        self.synced: list[tuple] = []

        async def _reset(session_key):
            return self._new_entry

        self.async_session_store = SimpleNamespace(reset_session=_reset)

    def _evict_cached_agent(self, session_key):
        return None

    def _clear_conversation_scope(self, session_key, reason=None):
        return None

    def _sync_telegram_topic_binding(self, source, session_entry, reason=None):
        self.synced.append((session_entry, reason))


def _exhaustion(monkeypatch, *, lang, new_entry):
    monkeypatch.setenv("HERMES_LANGUAGE", lang)
    runner = _ResetRunner(new_entry)
    response, entry = _run(runner._hmwa_compression_exhaustion_reset(
        {"compression_exhausted": True}, "prior text",
        SimpleNamespace(session_id="s1"), "k1", _source(),
    ))
    return response, entry, runner


class TestCompressionExhaustionReset:

    def test_en_matches_upstream_copy(self, monkeypatch):
        response, _entry, _r = _exhaustion(monkeypatch, lang="en", new_entry=None)
        assert response == (
            "prior text\n\n🔄 Session auto-reset — the conversation exceeded the maximum "
            "context size and could not be compressed further. Your next message will start "
            "a fresh session."
        )

    def test_zh_is_localised(self, monkeypatch):
        response, _entry, _r = _exhaustion(monkeypatch, lang="zh", new_entry=None)
        assert "会话已自动重置" in response
        assert "Session auto-reset" not in response

    def test_reset_repoints_the_topic_binding(self, monkeypatch):
        new_entry = SimpleNamespace(session_id="s2")
        _response, entry, runner = _exhaustion(monkeypatch, lang="en", new_entry=new_entry)
        assert entry is new_entry
        assert runner.synced == [(new_entry, "compression-exhausted-reset")]


# =====================================================================================
# `_format_session_info` 的 ctx_source 三取值（登记为「等价已落位」）
# =====================================================================================
def _session_info(monkeypatch, *, lang, context_source):
    monkeypatch.setenv("HERMES_LANGUAGE", lang)
    import gateway.run as gw

    monkeypatch.setattr(gw, "_resolve_gateway_model_context", lambda: SimpleNamespace(
        model="m1", provider="openrouter", context_length=262144,
        context_source=context_source, base_url="",
    ))
    return GatewayTurnMixin()._format_session_info()


class TestCtxSourceIsLocalised:

    @pytest.mark.parametrize("source_word,en_word,zh_word", [
        ("config", "config", "配置"),
        ("detected", "detected", "检测"),
    ])
    def test_source_word_follows_the_catalog(self, monkeypatch, source_word, en_word, zh_word):
        assert en_word in _session_info(monkeypatch, lang="en", context_source=source_word)
        assert zh_word in _session_info(monkeypatch, lang="zh", context_source=source_word)

    def test_default_source_carries_the_config_hint(self, monkeypatch):
        en = _session_info(monkeypatch, lang="en", context_source="default")
        zh = _session_info(monkeypatch, lang="zh", context_source="default")
        assert "model.context_length" in en and "model.context_length" in zh
        assert "default — set" in en and "默认 — 在 config 中设置" in zh


# =====================================================================================
# `_run_agent_via_proxy` 的五条分支
# =====================================================================================
class _Stream:
    def __init__(self, chunks):
        self._chunks = chunks

    def iter_any(self):
        async def _gen():
            for c in self._chunks:
                yield c
        return _gen()


class _Resp:
    def __init__(self, *, status=200, body="", chunks=(), raise_on_enter=None):
        self.status = status
        self._body = body
        self.content = _Stream(chunks)
        self._raise = raise_on_enter

    async def __aenter__(self):
        if self._raise is not None:
            raise self._raise
        return self

    async def __aexit__(self, *exc):
        return False

    async def text(self):
        return self._body


class _Session:
    def __init__(self, resp):
        self._resp = resp

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def post(self, url, json=None, headers=None):
        return self._resp


def _install_fake_aiohttp(monkeypatch, resp):
    mod = SimpleNamespace(
        ClientSession=lambda timeout=None: _Session(resp),
        ClientTimeout=lambda **kw: None,
    )
    monkeypatch.setitem(sys.modules, "aiohttp", mod)


class _ProxyRunner(GatewayTurnMixin):
    def __init__(self, *, proxy_url="http://proxy.local"):
        self._proxy_url = proxy_url

    def _run_still_current_fn(self, session_key, run_generation):
        return lambda: True

    def _thread_metadata_for_source(self, source, event_message_id):
        return None

    def _get_proxy_url(self):
        return self._proxy_url

    def _delivery_adapter_for(self, source):
        return None


async def _proxy(monkeypatch, *, lang, resp=None, proxy_url="http://proxy.local"):
    monkeypatch.setenv("HERMES_LANGUAGE", lang)
    if resp is not None:
        _install_fake_aiohttp(monkeypatch, resp)
    return await _ProxyRunner(proxy_url=proxy_url)._run_agent_via_proxy(
        "hi", "", [], _source(), "s1", session_key="k1", run_generation=1,
        scheduled_heartbeat=True,
    )


class TestRunAgentViaProxyErrors:

    def test_aiohttp_missing_en(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "aiohttp", None)
        out = _run(_proxy(monkeypatch, lang="en"))
        assert out == {"final_response": "⚠️ Proxy mode requires aiohttp. Install with: "
                                         "pip install aiohttp", "messages": [], "api_calls": 0,
                       "tools": []}

    def test_aiohttp_missing_zh(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "aiohttp", None)
        out = _run(_proxy(monkeypatch, lang="zh"))
        assert "代理模式需要 aiohttp" in out["final_response"]

    def test_url_not_configured_en(self, monkeypatch):
        out = _run(_proxy(monkeypatch, lang="en", proxy_url=None))
        assert out["final_response"] == (
            "⚠️ Proxy URL not configured (GATEWAY_PROXY_URL or gateway.proxy_url)")

    def test_url_not_configured_zh(self, monkeypatch):
        out = _run(_proxy(monkeypatch, lang="zh", proxy_url=None))
        assert "未配置代理 URL" in out["final_response"]

    def test_http_error_branch(self, monkeypatch):
        en = _run(_proxy(monkeypatch, lang="en",
                         resp=_Resp(status=502, body="upstream down")))
        assert en["final_response"] == "⚠️ Proxy error (502): upstream down"
        zh = _run(_proxy(monkeypatch, lang="zh",
                         resp=_Resp(status=502, body="upstream down")))
        assert zh["final_response"] == "⚠️ 代理错误（502）：upstream down"

    def test_connection_error_branch(self, monkeypatch):
        boom = ConnectionResetError("proxy fell over")
        en = _run(_proxy(monkeypatch, lang="en",
                         resp=_Resp(raise_on_enter=boom)))
        assert en["final_response"] == "⚠️ Proxy connection error: proxy fell over"
        zh = _run(_proxy(monkeypatch, lang="zh",
                         resp=_Resp(raise_on_enter=ConnectionResetError("proxy fell over"))))
        assert "代理连接错误" in zh["final_response"]

    def test_empty_stream_falls_back_to_no_response_copy(self, monkeypatch):
        chunks = (b'data: {"choices":[{"delta":{}}]}\n', b"data: [DONE]\n")
        en = _run(_proxy(monkeypatch, lang="en", resp=_Resp(chunks=chunks)))
        assert en["final_response"] == "(No response from remote agent)"
        zh = _run(_proxy(monkeypatch, lang="zh", resp=_Resp(chunks=chunks)))
        assert zh["final_response"] == "（远程代理无响应）"

    def test_streamed_content_still_wins(self, monkeypatch):
        chunks = (b'data: {"choices":[{"delta":{"content":"hello"}}]}\n', b"data: [DONE]\n")
        en = _run(_proxy(monkeypatch, lang="en", resp=_Resp(chunks=chunks)))
        assert en["final_response"] == "hello"
