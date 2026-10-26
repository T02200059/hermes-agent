"""C13 unified explainers: config / registry / detect / fail-open / glue contracts."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def test_builtins_registered():
    from owner.explainers.registry import known_kinds, task_name_for

    kinds = set(known_kinds())
    assert {"progress", "approval", "english"} <= kinds
    assert task_name_for("progress") == "progress_explainer"
    assert task_name_for("approval") == "approval_explainer"
    assert task_name_for("english") == "english_explainer"


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
