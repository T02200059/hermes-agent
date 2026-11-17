"""展示层翻译：自动恢复等诊断提示（英文原文保留为源/匹配键）。"""

from __future__ import annotations

from typing import Any, Iterator

import pytest

from agent import i18n
from agent.turn_recovery_autorecover import ladder_notice
from gateway.config import Platform
from gateway.run import _prepare_gateway_status_message
from owner.explainers.progress.activity_i18n import localize_activity_desc
from owner.i18n.diagnostic_notices import translate_diagnostic_notice


@pytest.fixture
def use_language(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    def _set(lang: str) -> None:
        monkeypatch.setenv("HERMES_LANGUAGE", lang)
        i18n.reset_language_cache()
        assert i18n.get_language() == lang

    yield _set
    i18n.reset_language_cache()


USER_LADDER = (
    "⏳ Provider temporarily unavailable — retrying automatically in 17s "
    "(cycle 1/5); send /stop to cancel"
)

USER_LADDER_ZH = (
    "⏳ 供应商暂时不可用 — 将在 17 秒后自动重试（第 1/5 轮）；发送 /stop 可取消"
)


def test_user_ladder_zh_keeps_params_and_stop(use_language):
    use_language("zh")
    zh = translate_diagnostic_notice(USER_LADDER)
    assert zh == USER_LADDER_ZH
    assert "17" in zh
    assert "1/5" in zh
    assert "/stop" in zh
    assert "Provider temporarily unavailable" not in zh


def test_ladder_notice_builder_zh(use_language):
    """官方拼装函数仍出英文；展示层按平台 hint 翻译并保留参数。"""
    use_language("zh")

    class _Agent:
        def __init__(self, platform: str):
            self.platform = platform

    feishu = ladder_notice(_Agent("feishu"), wait_s=17, cycle=1, total=5)
    assert feishu == USER_LADDER
    assert translate_diagnostic_notice(feishu) == USER_LADDER_ZH

    cli = ladder_notice(_Agent("cli"), wait_s=30, cycle=2, total=5)
    zh = translate_diagnostic_notice(cli)
    assert "30" in zh and "2/5" in zh
    assert "Esc" in zh
    assert zh == "⏳ 供应商暂时不可用 — 将在 30 秒后自动重试（第 2/5 轮）；按 Esc 可停止"

    api = ladder_notice(_Agent("api_server"), wait_s=15, cycle=1, total=5)
    zh = translate_diagnostic_notice(api)
    assert "15" in zh
    assert zh.endswith("；取消请求即可停止")

    cron = ladder_notice(_Agent("cron"), wait_s=15, cycle=3, total=5)
    zh = translate_diagnostic_notice(cron)
    assert zh == "⏳ 供应商暂时不可用 — 将在 15 秒后自动重试（第 3/5 轮）"
    assert "；" not in zh


def test_gave_up_zh(use_language):
    use_language("zh")
    en = "⏳ Automatic recovery gave up after 5 cycles — the provider is still unavailable."
    zh = translate_diagnostic_notice(en)
    assert zh == "⏳ 自动恢复已在 5 轮后放弃 — 供应商仍不可用。"
    assert "5" in zh


def test_en_passthrough(use_language):
    use_language("en")
    assert translate_diagnostic_notice(USER_LADDER) == USER_LADDER
    assert translate_diagnostic_notice(
        "⏳ Automatic recovery gave up after 5 cycles — the provider is still unavailable."
    ).startswith("⏳ Automatic recovery")


def test_unknown_and_empty_fail_open(use_language):
    use_language("zh")
    unknown = "⏳ Something completely new — not in the table"
    assert translate_diagnostic_notice(unknown) == unknown
    assert translate_diagnostic_notice("") == ""
    assert translate_diagnostic_notice(None) == ""


def test_related_durable_notices_keep_commands_and_params(use_language):
    use_language("zh")
    zh = translate_diagnostic_notice(
        "❌ The model provider didn't answer after all retries. "
        "Send /retry, or switch models with /model."
    )
    assert "/retry" in zh and "/model" in zh
    assert "Send /retry" not in zh

    zh = translate_diagnostic_notice(
        "⚠️ Tool guardrail halted terminal: dangerous_rm"
    )
    assert "terminal" in zh and "dangerous_rm" in zh

    zh = translate_diagnostic_notice(
        "❌ Billing or credits exhausted — quota exceeded for sk-test"
    )
    assert "quota exceeded for sk-test" in zh
    assert zh.startswith("❌ 额度或账单已耗尽")


def test_prepare_feishu_translates_zh_not_raw_surfaces(use_language):
    use_language("zh")
    assert _prepare_gateway_status_message(Platform.FEISHU, "lifecycle", USER_LADDER) == USER_LADDER_ZH
    # Programmatic / local surfaces keep the English diagnostic verbatim.
    assert _prepare_gateway_status_message("local", "lifecycle", USER_LADDER) == USER_LADDER
    assert _prepare_gateway_status_message(Platform.API_SERVER, "lifecycle", USER_LADDER) == USER_LADDER


def test_prepare_feishu_en_keeps_english(use_language):
    use_language("en")
    assert _prepare_gateway_status_message(Platform.FEISHU, "lifecycle", USER_LADDER) == USER_LADDER


def test_activity_stamp_reuses_translator(monkeypatch):
    monkeypatch.setattr(
        "owner.explainers.progress.activity_i18n.display_language_is_chinese",
        lambda: True,
    )
    assert localize_activity_desc(USER_LADDER) == USER_LADDER_ZH
    assert localize_activity_desc("auto-recovery wait (1/5)") == "自动恢复等待（1/5）"


def test_official_english_source_unchanged():
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "agent" / "turn_recovery_autorecover.py"
    text = src.read_text(encoding="utf-8")
    assert "⏳ Provider temporarily unavailable — retrying automatically in" in text
    assert "send /stop to cancel" in text
    assert "{wait_s:.0f}s (cycle {cycle}/{total})" in text
