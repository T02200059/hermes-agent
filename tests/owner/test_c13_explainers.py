"""C13 unified explainers: config / registry / detect / fail-open / glue contracts."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def test_builtins_registered():
    from owner.explainers.registry import known_kinds, task_name_for

    kinds = set(known_kinds())
    assert {"progress", "approval", "english", "recap"} <= kinds
    assert task_name_for("progress") == "progress_explainer"
    assert task_name_for("approval") == "approval_explainer"
    assert task_name_for("english") == "english_explainer"
    assert task_name_for("recap") == "recap_explainer"


def test_register_kind_extension():
    from owner.explainers.registry import get_kind, register_kind, task_name_for

    register_kind("summary", defaults={"enabled": False, "platforms": {}})
    assert get_kind("summary") is not None
    assert task_name_for("summary") == "summary_explainer"


def test_resolve_model_kind_over_shared():
    from owner.explainers import config as cfg_mod

    with patch.object(
        cfg_mod,
        "_raw_explainers",
        return_value={
            "provider": "shared-p",
            "model": "shared-m",
            "timeout_ms": 30000,
            "approval": {"enabled": True, "provider": "kind-p", "model": "kind-m"},
        },
    ):
        cfg = cfg_mod.load_kind_config("approval")
        assert cfg["provider"] == "kind-p"
        assert cfg["model"] == "kind-m"
        p, m = cfg_mod.resolve_model(cfg)
        assert p == "kind-p" and m == "kind-m"


def test_resolve_model_auto_becomes_none():
    from owner.explainers import config as cfg_mod

    with patch.object(
        cfg_mod,
        "_raw_explainers",
        return_value={"provider": "auto", "model": "auto", "progress": {"enabled": False}},
    ):
        cfg = cfg_mod.load_kind_config("progress")
        p, m = cfg_mod.resolve_model(cfg)
        assert p is None and m is None


def test_enabled_three_level():
    from owner.explainers import config as cfg_mod

    with patch.object(
        cfg_mod,
        "_raw_explainers",
        return_value={
            "english": {
                "enabled": False,
                "platforms": {"feishu": True},
                "chats": {"feishu": {"chat-a": False}},
            }
        },
    ):
        assert cfg_mod.resolve_enabled("english", "feishu", "chat-a") is False
        assert cfg_mod.resolve_enabled("english", "feishu", "chat-b") is True
        assert cfg_mod.resolve_enabled("english", "telegram", "x") is False


def test_english_detect_positive_and_negative():
    from owner.explainers.english.detect import looks_like_english_reply

    en = (
        "The deployment finished successfully and the service is now healthy. "
        "You should check the logs if anything looks wrong."
    )
    assert looks_like_english_reply(en) is not None
    zh = "部署已经完成，服务现在是健康的。如果有问题请看日志。"
    assert looks_like_english_reply(zh) is None
    mixed = "用 `kubectl apply -f deploy.yaml` 部署到 prod namespace。"
    assert looks_like_english_reply(mixed) is None



def test_non_chinese_output_detects_short_and_long():
    from owner.explainers.english.detect import looks_like_non_chinese_output

    en_long = (
        "The deployment finished successfully and the service is now healthy. "
        "You should check the logs if anything looks wrong."
    )
    assert looks_like_non_chinese_output(en_long) is not None
    en_short = "Still checking the deployment logs carefully now."
    assert looks_like_non_chinese_output(en_short) is not None
    zh = "正在核对部署日志，稍等片刻。"
    assert looks_like_non_chinese_output(zh) is None
    mixed = "用 `kubectl apply -f deploy.yaml` 部署到 prod namespace。"
    assert looks_like_non_chinese_output(mixed) is None


def test_call_explainer_llm_retries_once_on_english(monkeypatch):
    from owner.explainers import llm as llm_mod

    en = (
        "The deployment finished successfully and the service is now healthy. "
        "You should check the logs if anything looks wrong."
    )
    zh = "部署已经完成，服务现在是健康的。"
    calls = {"n": 0}

    class _Msg:
        def __init__(self, content):
            self.content = content

    class _Choice:
        def __init__(self, content):
            self.message = _Msg(content)

    class _Resp:
        def __init__(self, content):
            self.choices = [_Choice(content)]

    def fake_call_llm(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return _Resp(en)
        return _Resp(zh)

    import agent.auxiliary_client as ac

    monkeypatch.setattr(ac, "call_llm", fake_call_llm)
    monkeypatch.setattr(
        llm_mod,
        "_should_enforce_chinese",
        lambda kind, cfg: True,
    )
    out = llm_mod.call_explainer_llm(
        "progress",
        [{"role": "system", "content": "x"}, {"role": "user", "content": "y"}],
    )
    assert out == zh
    assert calls["n"] == 2


def test_call_explainer_llm_fail_open_keeps_english_after_retry(monkeypatch):
    from owner.explainers import llm as llm_mod

    en = (
        "The deployment finished successfully and the service is now healthy. "
        "You should check the logs if anything looks wrong."
    )
    calls = {"n": 0}

    class _Msg:
        def __init__(self, content):
            self.content = content

    class _Choice:
        def __init__(self, content):
            self.message = _Msg(content)

    class _Resp:
        def __init__(self, content):
            self.choices = [_Choice(content)]

    def fake_call_llm(**kwargs):
        calls["n"] += 1
        return _Resp(en)

    import agent.auxiliary_client as ac

    monkeypatch.setattr(ac, "call_llm", fake_call_llm)
    monkeypatch.setattr(llm_mod, "_should_enforce_chinese", lambda kind, cfg: True)
    out = llm_mod.call_explainer_llm(
        "english",
        [{"role": "user", "content": "translate"}],
    )
    assert out == en
    assert calls["n"] == 2


def test_english_prefix_and_format_delivery():
    from owner.explainers.english.prompt import PREFIX, format_delivery

    assert PREFIX == "🔤 系统提示："
    assert format_delivery("你好").startswith(PREFIX)


def test_progress_prefix_aligned_with_notice():
    from owner.explainers.progress.prompt import PREFIX

    assert PREFIX == "🧭 系统提示："


def test_approval_never_advises_in_system_prompt():
    from owner.explainers.approval.prompt import build_messages

    msgs = build_messages("rm -rf /tmp/x", "destructive", "zh")
    system = msgs[0]["content"]
    assert "NEVER" in system and "approve" in system.lower()


def test_approval_format_appendix():
    from owner.explainers.approval import format_card_appendix

    assert "命令说明" in format_card_appendix("删临时目录", language="zh")
    assert format_card_appendix("") == ""


def test_approval_fail_open_empty_command():
    from owner.explainers.approval import maybe_explain_command

    with patch("owner.explainers.approval.resolve_enabled", return_value=True):
        assert maybe_explain_command("") is None


def test_call_explainer_llm_fail_open(monkeypatch):
    from owner.explainers import llm as llm_mod

    def boom(**kwargs):
        raise RuntimeError("no net")

    monkeypatch.setattr("agent.auxiliary_client.call_llm", boom, raising=False)
    # Also patch import path used inside
    import agent.auxiliary_client as ac

    monkeypatch.setattr(ac, "call_llm", boom)
    assert llm_mod.call_explainer_llm("approval", [{"role": "user", "content": "x"}]) is None


def test_english_hook_does_not_rewrite_body():
    from owner.explainers.english.hook import maybe_explain_english_reply

    with patch("owner.explainers.english.hook.display_language_is_chinese", return_value=True), patch(
        "owner.explainers.english.hook.resolve_enabled", return_value=False
    ):
        assert maybe_explain_english_reply("The service is healthy now.") is None


def test_stream_guard_yield_helper_fail_open():
    from owner.explainers.progress import dispatcher as d

    with patch.dict("sys.modules", {"owner.stream_guard": MagicMock(snapshot=MagicMock(side_effect=RuntimeError))}):
        # re-import path uses from owner.stream_guard import snapshot inside fn
        assert d._stream_guard_tripped("s", "t") is False


def test_clean_output_strips_quotes():
    from owner.explainers.llm import clean_output

    assert clean_output('"hello"') == "hello"
    assert clean_output("") is None


def test_legacy_flat_keys_synthesize_unified_block():
    from owner.explainers import config as cfg_mod

    with patch.object(
        cfg_mod,
        "_patch_root",
        return_value={
            "progress_explainer": {"enabled": True, "provider": "auto", "model": "auto"},
            "approval_explainer": {"enabled": True, "timeout_ms": 15000},
        },
    ):
        raw = cfg_mod._raw_explainers()
        assert "progress" in raw and raw["progress"]["enabled"] is True
        assert raw["approval"]["timeout_ms"] == 15000
        cfg = cfg_mod.load_kind_config("approval")
        assert cfg["timeout_ms"] == 15000


def test_shared_max_input_chars_default_64k():
    from owner.explainers import config as cfg_mod
    from owner.explainers.common import DEFAULT_MAX_INPUT_CHARS

    assert DEFAULT_MAX_INPUT_CHARS == 64000
    with patch.object(cfg_mod, "_raw_explainers", return_value={}):
        shared = cfg_mod.load_shared()
        assert shared["max_input_chars"] == 64000
        for kind in ("progress", "approval", "english", "recap"):
            cfg = cfg_mod.load_kind_config(kind)
            assert cfg["max_input_chars"] == 64000


def test_max_input_chars_kind_overrides_shared():
    from owner.explainers import config as cfg_mod

    with patch.object(
        cfg_mod,
        "_raw_explainers",
        return_value={
            "max_input_chars": 64000,
            "recap": {"enabled": True, "max_input_chars": 12000},
        },
    ):
        assert cfg_mod.load_kind_config("recap")["max_input_chars"] == 12000
        assert cfg_mod.load_kind_config("english")["max_input_chars"] == 64000


def test_clip_input_prefers_tail_within_budget():
    from owner.explainers.common import clip_input

    s = "HEAD" + ("x" * 100) + "TAIL"
    out = clip_input(s, 40)
    assert len(out) <= 40
    assert out.endswith("TAIL")
    assert "省略" in out or out == s[-40:]


def test_recap_flatten_user_agent_only():
    from owner.explainers.recap.flatten import flatten_messages

    msgs = [
        {"role": "system", "content": "ignore me"},
        {"role": "user", "content": "请改 C13"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "1"}]},
        {"role": "tool", "content": "ok"},
        {"role": "assistant", "content": "已落地 recap"},
    ]
    flat = flatten_messages(msgs, max_input_chars=64000)
    assert "User: 请改 C13" in flat
    assert "Agent: 已落地 recap" in flat
    assert "ignore me" not in flat
    assert "tool" not in flat.lower() or "User:" in flat


def test_recap_flatten_clips_to_budget():
    from owner.explainers.recap.flatten import flatten_messages

    msgs = [{"role": "user", "content": "A" * 5000}, {"role": "assistant", "content": "B" * 5000}]
    flat = flatten_messages(msgs, max_input_chars=800)
    assert len(flat) <= 800
    assert "B" in flat  # tail retained


def test_recap_prefix_and_format_delivery():
    from owner.explainers.recap.prompt import PREFIX, format_delivery

    assert PREFIX == "📋 系统提示："
    assert format_delivery("你问了 X，我们改了 Y。").startswith(PREFIX)


def test_recap_explain_fail_open_empty(monkeypatch):
    from owner.explainers.recap.explain import explain_from_messages

    assert explain_from_messages([]) is None
    assert explain_from_messages([{"role": "system", "content": "x"}]) is None


def test_recap_command_disabled():
    from owner.explainers.recap.command import handle_recap_command
    import asyncio

    with patch("owner.explainers.recap.command.resolve_enabled", return_value=False):
        out = asyncio.run(handle_recap_command("", session_id="s1", platform="feishu"))
    assert "未启用" in out

def test_explainer_output_caps_defaults():
    """Chinese-friendly output caps; recap stays short (~二三百汉字)."""
    import importlib
    import inspect

    from owner.explainers import llm as llm_mod
    from owner.explainers.registry import get_kind

    progress_explain = importlib.import_module("owner.explainers.progress.explain")
    approval_explain = importlib.import_module("owner.explainers.approval.explain")
    english_explain = importlib.import_module("owner.explainers.english.explain")
    recap_explain = importlib.import_module("owner.explainers.recap.explain")

    assert progress_explain._MAX_TOKENS == 400
    assert progress_explain._MAX_OUTPUT_CHARS == 900
    assert approval_explain._MAX_TOKENS == 400
    assert approval_explain._MAX_OUTPUT_CHARS == 800
    assert english_explain._MAX_TOKENS == 450
    assert english_explain._MAX_OUTPUT_CHARS == 1000
    assert recap_explain._MAX_TOKENS == 260
    assert get_kind("recap").defaults["max_output_chars"] == 350
    assert llm_mod._MAX_OUTPUT_CHARS_DEFAULT == 1000
    sig = inspect.signature(llm_mod.call_explainer_llm)
    assert sig.parameters["max_tokens"].default == 400


def _progress_explainer_stub():
    """Bypass __init__ (overlay/tracker); only exercise pure helpers."""
    from owner.explainers.progress.dispatcher import ProgressExplainer

    return ProgressExplainer.__new__(ProgressExplainer)


def _set_lang(monkeypatch, lang: str) -> None:
    from agent import i18n

    monkeypatch.setenv("HERMES_LANGUAGE", lang)
    i18n.reset_language_cache()


def test_progress_fact_line_zh_uses_i18n(monkeypatch):
    _set_lang(monkeypatch, "zh")
    pe = _progress_explainer_stub()
    line = pe._fact_line(
        {"current_tool": "patch", "api_call_count": 15, "max_iterations": 120}
    )
    assert line == "正在运行：patch — 第 15/120 轮迭代"
    line2 = pe._fact_line(
        {
            "last_activity_desc": "receiving stream response",
            "api_call_count": 12,
            "max_iterations": 120,
        }
    )
    assert line2 == "正在接收流式响应 — 第 12/120 轮迭代"
    assert "iteration " not in line and "iteration " not in line2


def test_progress_fact_line_en_uses_i18n(monkeypatch):
    _set_lang(monkeypatch, "en")
    pe = _progress_explainer_stub()
    line = pe._fact_line(
        {"current_tool": "patch", "api_call_count": 15, "max_iterations": 120}
    )
    assert line == "running: patch — iteration 15/120"
    # 英文 UI：活动戳保持原文
    line2 = pe._fact_line(
        {
            "last_activity_desc": "receiving stream response",
            "api_call_count": 12,
            "max_iterations": 120,
        }
    )
    assert line2 == "receiving stream response — iteration 12/120"


def test_localize_activity_desc_exact_and_templates(monkeypatch):
    from owner.explainers.progress.activity_i18n import (
        localize_activity_desc,
        mapped_exact_count,
        mapped_template_count,
    )

    _set_lang(monkeypatch, "zh")
    assert localize_activity_desc("receiving stream response") == "正在接收流式响应"
    assert localize_activity_desc(
        "waiting for stream response (12s, no chunks yet)"
    ) == "正在等待流式响应（12 秒，尚无数据块）"
    assert localize_activity_desc(
        "waiting for stream response (90s, first_chunk)"
    ) == "正在等待流式响应（90 秒，等待首块）"
    assert localize_activity_desc("starting API call #3") == "开始第 3 次 API 调用"
    assert localize_activity_desc("executing tool: terminal") == "正在执行工具：terminal"
    assert localize_activity_desc(
        "tool completed: patch (1.5s)"
    ) == "工具已完成：patch（1.5 秒）"
    assert localize_activity_desc(
        "tool completed: patch (1.5s) (error)"
    ) == "工具已完成：patch（1.5 秒）（出错）"
    assert localize_activity_desc(
        "error retry backoff (2/5), 40s remaining"
    ) == "错误重试退避（2/5），剩余 40 秒"
    assert localize_activity_desc(
        "⏳ waiting on gpt-test — 12s waiting for the first stream chunk"
    ) == "⏳ 正在等待 gpt-test — 已等待首个数据块 12 秒"
    assert localize_activity_desc(
        "⏳ still waiting on gpt-test — stream open; 80s without stream output "
        "(auto-reconnect: stream stale watchdog in 10s)"
    ) == (
        "⏳ 仍在等待 gpt-test — 流已打开；80 秒无流输出"
        "（自动重连：流过期 看门狗将在 10 秒后触发）"
    )
    # 未命中 fail-open
    assert localize_activity_desc("totally unknown stamp xyz") == "totally unknown stamp xyz"
    assert mapped_exact_count() >= 20
    assert mapped_template_count() >= 20


def test_localize_activity_desc_en_passthrough(monkeypatch):
    from owner.explainers.progress.activity_i18n import localize_activity_desc

    _set_lang(monkeypatch, "en")
    assert localize_activity_desc("receiving stream response") == "receiving stream response"
    assert (
        localize_activity_desc("waiting for stream response (12s, no chunks yet)")
        == "waiting for stream response (12s, no chunks yet)"
    )
    # force_chinese 覆盖 display.language
    assert (
        localize_activity_desc("receiving stream response", force_chinese=True)
        == "正在接收流式响应"
    )


def test_progress_hard_facts_numeric_iteration_for_prompt(monkeypatch):
    _set_lang(monkeypatch, "zh")
    pe = _progress_explainer_stub()
    facts = pe._hard_facts(
        {"now": 100.0, "turn_started_at": 40.0, "branch": "tool"},
        {"current_tool": "patch", "api_call_count": 15, "max_iterations": 120},
    )
    assert facts["iteration"] == 15
    assert facts["max_iterations"] == 120
    assert facts["elapsed_s"] == 60
    assert facts["elapsed_seconds"] == 60
    from owner.explainers.progress.prompt import _format_hard_facts

    rendered = _format_hard_facts(facts)
    assert "迭代 15/120" in rendered
    assert "已耗时 60s" in rendered
    assert "当前工具: patch" in rendered
