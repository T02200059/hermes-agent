"""T2-20 A3 簇 7b-1 —— ``gateway/run_turn.py::_run_background_task_inner`` 的后台任务文案。

宿主 ``GatewayTurnMixin`` **未挂到** ``GatewayRunner`` 的 MRO 上（单体里还有一份同名实现继续
对外服务），所以这里直接驱动 mixin 的**方法本体**：断言对象是**行为**（真的发了哪条消息），
不是源码文本。

英文侧必须与上游硬编码文案**逐字相同**；中文侧必须真本地化。上游在 BASE 之后**换掉了两处**
失败文案（凭据缺失 / 未完成即失败），并把 no-response 那处改成复用 ``header`` 变量 —— 故本簇
既有「取上游新文案（新键）」也有「保我方（就地换 ``t()``）」，两类都要锁住。
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from gateway.config import Platform
from gateway.run_turn import GatewayTurnMixin
from gateway.session import SessionSource

EN_NO_CREDS = (
    "❌ The background task couldn't start because no AI model sign-in is configured. "
    "Use /login, or run `hermes setup` on the host."
)
EN_HEADER = '✅ Background task complete\nPrompt: "{preview}"\n\n'
EN_FAILED = (
    '❌ Your background task "{preview}" failed before finishing. '
    "Send /bg again to retry, or /agents to see what is still running."
)


class _FakeAdapter:
    def __init__(self):
        self.sent: list[str] = []
        self.warned: list[str] = []

    async def send(self, *args, **kwargs):
        text = args[1] if len(args) > 1 else kwargs.get("content", "")
        self.sent.append(text)

    async def emit_warning(self, chat_id, text, **kwargs):
        self.warned.append(text)

    def extract_media(self, response):
        return [], response

    def extract_images(self, response):
        return [], response


class _Runner(GatewayTurnMixin):
    """最小宿主：只提供 ``_run_background_task_inner`` 会用到的那几处钩子。"""

    def __init__(self, adapter, *, runtime_kwargs, final_response, error, raise_in_agent):
        self._adapter = adapter
        self._runtime_kwargs = runtime_kwargs
        self._final_response = final_response
        self._error = error
        self._raise_in_agent = raise_in_agent
        self._provider_routing: dict = {}
        self._session_db = None

    # ---- 依赖钩子 ----
    def _delivery_adapter_for(self, source):
        return self._adapter

    def _thread_metadata_for_source(self, source, event_message_id=None):
        return {}

    def _resolve_session_agent_runtime(self, *, source=None, user_config=None, session_key=None):
        return "test-model", dict(self._runtime_kwargs)

    def _resolve_turn_toolsets(self, user_config, source, platform_key):
        return [], []

    def _resolve_session_reasoning_config(self, *, source=None, model=None):
        return None

    def _resolve_session_service_tier(self, *, source=None):
        return None

    def _resolve_turn_agent_config(self, prompt, model, runtime_kwargs):
        return {"model": model, "runtime": dict(runtime_kwargs)}

    def _session_key_for_source(self, source):
        return "sess-key"

    def _refresh_fallback_model(self):
        return None

    def _cleanup_agent_resources(self, agent):
        return None

    async def _enrich_message_with_vision(self, prompt, image_paths):  # pragma: no cover
        return prompt

    async def _run_in_executor_with_context(self, fn):
        return fn()


class _StubAgent:
    def __init__(self, runner, **kwargs):
        self._runner = runner

    def run_conversation(self, user_message=None, task_id=None):
        if self._runner._raise_in_agent:
            raise RuntimeError("boom")
        out: dict = {"final_response": self._runner._final_response, "messages": []}
        if self._runner._error is not None:
            out["error"] = self._runner._error
        return out


def _source():
    return SessionSource(platform=Platform.TELEGRAM, chat_id="c1", user_id="u1")


def _drive(*, lang: str, runtime_kwargs=None, final_response="", error=None,
           raise_in_agent=False):
    adapter = _FakeAdapter()
    runner = _Runner(
        adapter,
        runtime_kwargs={"api_key": "k"} if runtime_kwargs is None else runtime_kwargs,
        final_response=final_response, error=error, raise_in_agent=raise_in_agent,
    )
    import run_agent

    with patch.dict("os.environ", {"HERMES_LANGUAGE": lang}), \
         patch.object(run_agent, "AIAgent", lambda **kw: _StubAgent(runner, **kw)), \
         patch("gateway.run._load_gateway_config", return_value={}), \
         patch("gateway.run._platform_config_key", return_value="telegram"), \
         patch("gateway.run._current_max_iterations", return_value=5), \
         patch("gateway.run._checkpoint_agent_kwargs", return_value={}):
        asyncio.run(runner._run_background_task_inner("do the thing", _source(), "task-42"))
    return adapter


# ------------------------------------------------------------------ 凭据缺失（取上游新文案）
class TestNoCredentials:

    def test_english_verbatim(self):
        a = _drive(lang="en", runtime_kwargs={})
        assert a.sent == [EN_NO_CREDS]

    def test_localized(self):
        a = _drive(lang="zh", runtime_kwargs={})
        assert a.sent and a.sent[0] != EN_NO_CREDS
        assert "后台任务无法启动" in a.sent[0]
        assert "hermes setup" in a.sent[0]

    def test_no_leftover_placeholders(self):
        for lang in ("en", "zh"):
            a = _drive(lang=lang, runtime_kwargs={})
            assert "{" not in a.sent[0] and "gateway." not in a.sent[0]


# ------------------------------------------------------------------ 完成通知（header 片段键）
class TestCompleteNotice:

    def test_english_verbatim_with_text(self):
        a = _drive(lang="en", final_response="hello there")
        assert a.sent == [EN_HEADER.format(preview="do the thing") + "hello there"]

    def test_english_verbatim_no_response(self):
        a = _drive(lang="en", final_response="")
        assert a.sent == [EN_HEADER.format(preview="do the thing") + "(No response generated)"]

    def test_header_localized(self):
        a = _drive(lang="zh", final_response="你好")
        assert a.sent == ["✅ 后台任务完成\n提示：\"do the thing\"\n\n你好"]

    def test_no_response_localized(self):
        a = _drive(lang="zh", final_response="")
        assert a.sent == ["✅ 后台任务完成\n提示：\"do the thing\"\n\n（未生成响应）"]

    def test_error_prefix_folded_into_body(self):
        a = _drive(lang="en", final_response="", error="kaboom")
        assert a.sent == [EN_HEADER.format(preview="do the thing") + "Error: kaboom"]

    def test_error_prefix_localized(self):
        a = _drive(lang="zh", final_response="", error="kaboom")
        assert a.sent == ["✅ 后台任务完成\n提示：\"do the thing\"\n\n错误：kaboom"]


# ------------------------------------------------------------------ 失败通知（取上游新文案）
class TestFailureNotice:

    def test_english_verbatim(self):
        a = _drive(lang="en", raise_in_agent=True)
        assert a.warned == [EN_FAILED.format(preview="do the thing")]

    def test_localized(self):
        a = _drive(lang="zh", raise_in_agent=True)
        assert a.warned and a.warned[0] != EN_FAILED.format(preview="do the thing")
        assert "未完成即失败" in a.warned[0]

    def test_task_id_is_not_leaked(self):
        """上游新文案刻意不暴露 task_id（`_bg_prompt_preview` 的 docstring 明写
        "the task id means nothing to the user"）——换码不得把它带回来。"""
        for lang in ("en", "zh"):
            a = _drive(lang=lang, raise_in_agent=True)
            assert "task-42" not in a.warned[0]

    def test_no_leftover_placeholders(self):
        for lang in ("en", "zh"):
            a = _drive(lang=lang, raise_in_agent=True)
            assert "{" not in a.warned[0] and "gateway." not in a.warned[0]


# ------------------------------------------------------------------ 控制组：单体旧键仍可用
class TestOldKeysStillServeMonolith:

    @pytest.mark.parametrize("lang", ["en", "zh"])
    def test_legacy_failed_key_renders(self, lang):
        from agent.i18n import t

        out = t("gateway.background_task_failed", lang=lang, task_id="T1", error="E1")
        assert "T1" in out and "E1" in out

    @pytest.mark.parametrize("lang", ["en", "zh"])
    def test_legacy_composite_key_renders(self, lang):
        from agent.i18n import t

        out = t("gateway.background_task_complete", lang=lang, preview="P", response="R")
        assert "P" in out and "R" in out
