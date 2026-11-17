"""展示层翻译：定时任务出错投递文案（英文原文保留为源/匹配键）。"""

from __future__ import annotations

from typing import Any, Iterator

import pytest

from agent import i18n
from cron.scheduler import (
    _failure_streak_nudge,
    _summarize_cron_failure_for_delivery,
)
from cron.scheduler_failure_copy import (
    blocked_config_notice,
    generic_failure_notice,
    inactivity_notice,
    provider_failure_notice,
    script_timeout_notice,
)
from owner.i18n.cron_notices import translate_cron_delivery


@pytest.fixture
def use_language(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    def _set(lang: str) -> None:
        monkeypatch.setenv("HERMES_LANGUAGE", lang)
        i18n.reset_language_cache()
        assert i18n.get_language() == lang

    yield _set
    i18n.reset_language_cache()


JOB = {"name": "Morning brief", "id": "ab12cd34"}


def _no_chain(monkeypatch):
    from cron import scheduler

    monkeypatch.setattr(scheduler, "load_config", dict)
    monkeypatch.setattr(scheduler, "get_fallback_chain", lambda cfg: [])


def test_script_timeout_zh_keeps_name_id_path_and_commands(use_language):
    use_language("zh")
    en = script_timeout_notice("Morning brief", "ab12cd34")
    zh = translate_cron_delivery(en)
    assert zh.startswith("💡 定时任务「Morning brief」失败：其脚本超时")
    assert "未调用模型" in zh
    assert "`hermes cron runs ab12cd34`" in zh
    assert "`hermes cron run ab12cd34`" in zh
    assert "cron/output/ab12cd34/" in zh
    assert "its script timed out" not in zh
    assert "💡 Cron 'Morning brief' failed" not in zh


def test_inactivity_and_generic_and_blocked(use_language, tmp_path, monkeypatch):
    use_language("zh")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))

    stalled = translate_cron_delivery(inactivity_notice("Morning brief", "ab12cd34"))
    assert stalled.startswith("💡 定时任务「Morning brief」失败：任务停滞")
    assert "`hermes cron runs ab12cd34`" in stalled
    assert "`hermes cron run ab12cd34`" in stalled
    assert "the job stalled" not in stalled

    generic = translate_cron_delivery(
        generic_failure_notice("Morning brief", "ab12cd34", "RuntimeError: boom")
    )
    assert "RuntimeError: boom" in generic
    assert "`hermes cron runs ab12cd34`" in generic
    assert "`hermes cron edit ab12cd34`" in generic
    assert "`hermes cron pause ab12cd34`" in generic
    assert "See the full run" not in generic

    blocked = translate_cron_delivery(
        blocked_config_notice("Morning brief", "provider credential missing: no key")
    )
    assert blocked.startswith("⛔ 定时任务「Morning brief」未运行")
    assert "provider credential missing: no key" in blocked
    assert "`hermes cron doctor`" in blocked
    assert "Nothing was charged" not in blocked
    assert "did not run" not in blocked


def test_blocked_known_preflight_reason_is_translated(use_language):
    use_language("zh")
    reason = (
        "delivery platform 'slack' has no gateway credentials configured "
        "(not connected). Configure it via `hermes setup` or change the "
        "job's `deliver` target."
    )
    zh = translate_cron_delivery(blocked_config_notice("Morning brief", reason))
    assert "投递平台「slack」未配置网关凭证（未连接）" in zh
    assert "`hermes setup`" in zh
    assert "`deliver`" in zh
    assert "has no gateway credentials" not in zh


def test_provider_timeout_and_auth_keep_commands(use_language, monkeypatch):
    use_language("zh")
    _no_chain(monkeypatch)

    timeout = _summarize_cron_failure_for_delivery(
        JOB, "ReadTimeout: HTTPSConnectionPool timed out"
    )
    zh = translate_cron_delivery(timeout)
    assert "AI 模型服务未及时响应" in zh
    assert "未配置备用供应商" in zh
    assert "`hermes fallback add`" in zh
    assert "`cron.model`" in zh and "`cron.model_provider`" in zh
    assert "`hermes cron run ab12cd34`" in zh
    assert "`hermes cron runs ab12cd34`" in zh
    assert "the AI model service did not respond" not in zh
    # Official English source remains the translator key.
    assert "💡 Cron 'Morning brief' failed:" in timeout

    auth = _summarize_cron_failure_for_delivery(JOB, "Error code: 401 - Unauthorized")
    zh = translate_cron_delivery(auth)
    assert "AI 模型服务拒绝了登录" in zh
    assert "/login" in zh
    assert "`hermes cron edit ab12cd34 --provider <name>`" in zh
    assert "`hermes cron run ab12cd34`" in zh
    assert "Sign in again" not in zh


def test_provider_billing_and_rate_limit(use_language, monkeypatch):
    use_language("zh")
    _no_chain(monkeypatch)
    billing = translate_cron_delivery(
        provider_failure_notice(
            "Morning brief",
            "ab12cd34",
            "billing",
            backup_provider_phrase="unused.",
        )
    )
    assert "账户用量或额度已达上限" in billing
    assert "`hermes cron edit ab12cd34 --provider <name>`" in billing
    assert "Top up or wait" not in billing

    rate = _summarize_cron_failure_for_delivery(
        JOB, "Nous Portal rate limit active until 15:00"
    )
    zh = translate_cron_delivery(rate)
    assert "速率限制" in zh
    assert "15:00" not in zh or "15:00" in rate  # gloss does not interpolate the until-time
    assert "rate-limited" not in zh


def test_nudge_hold_and_skew_suffixes(use_language, monkeypatch):
    use_language("zh")
    body = script_timeout_notice("Morning brief", "ab12cd34")
    nudge = _failure_streak_nudge(
        {"name": "Morning brief", "id": "ab12cd34", "schedule": {"kind": "cron"}, "failure_streak": 2}
    )
    # Threshold default is 3, failure_streak+1 == 3.
    assert "failed 3 runs" in nudge
    hold = (
        "\nThe provider's usage window is closed for about 6.0h. This job is held "
        "through 2026-11-17 20:00 CST and resumes at the first safe "
        "opportunity afterwards; no further alerts are sent while the provider is unavailable."
    )
    skew = (
        " Likely cause: the gateway is running stale code (booted "
        "on abc1234, disk is at def5678) — run `hermes gateway restart` to fix it."
    )
    zh = translate_cron_delivery(body + nudge + hold + skew)
    assert "其脚本超时" in zh
    assert "已连续失败 3 次" in zh
    assert "`hermes cron pause Morning brief`" in zh or "`hermes cron pause ab12cd34`" in zh
    assert "大约关闭 6.0 小时" in zh
    assert "2026-11-17 20:00 CST" in zh
    assert "启动时为 abc1234" in zh and "磁盘上为 def5678" in zh
    assert "`hermes gateway restart`" in zh
    assert "worth a review" not in zh
    assert "usage window is closed" not in zh
    assert "stale code" not in zh


def test_watchdog_monitor_and_autopause(use_language):
    use_language("zh")
    watchdog = (
        "💡 Cron watchdog 'disk check' script failed\n\n"
        "Script execution failed: exit 2\n\n"
        "Time: 2026-11-17 14:00:00"
    )
    zh = translate_cron_delivery(watchdog)
    assert zh.startswith("💡 定时任务看门狗「disk check」的脚本失败")
    assert "脚本执行失败：exit 2" in zh
    assert "时间：2026-11-17 14:00:00" in zh
    assert "script failed" not in zh

    monitor = (
        "💡 Cron monitor 'inbox' source failed\n\n"
        "connection refused\n\n"
        "Time: 2026-11-17 14:00:00"
    )
    zh = translate_cron_delivery(monitor)
    assert zh.startswith("💡 定时任务监视器「inbox」的数据源失败")
    assert "connection refused" in zh
    assert "时间：2026-11-17 14:00:00" in zh

    paused = (
        "💡 Cron job 'empty' was auto-paused\n\n"
        "no_agent=True requires a script — with no agent and no script "
        "there is nothing for the job to run."
    )
    zh = translate_cron_delivery(paused)
    assert zh.startswith("💡 定时任务「empty」已被自动暂停")
    assert "no_agent=True 需要提供脚本" in zh
    assert "was auto-paused" not in zh


def test_wrap_header_and_inner_failure(use_language):
    use_language("zh")
    inner = script_timeout_notice("Morning brief", "ab12cd34")
    wrapped = (
        "Cronjob Response: Morning brief\n"
        "(job_id: ab12cd34)\n"
        "-------------\n\n"
        f"{inner}\n\n"
        'To stop or manage this job, send me a new message (e.g. "stop reminder Morning brief").'
    )
    zh = translate_cron_delivery(wrapped)
    assert zh.startswith("定时任务回复：Morning brief")
    assert "（任务 ID：ab12cd34）" in zh
    assert "要停止或管理此任务" in zh
    assert "停止提醒 Morning brief" in zh
    assert "其脚本超时" in zh
    assert "`hermes cron run ab12cd34`" in zh
    assert "Cronjob Response:" not in zh
    assert "To stop or manage this job" not in zh


def test_success_body_untouched_but_wrap_translated(use_language):
    use_language("zh")
    wrapped = (
        "Cronjob Response: Morning brief\n"
        "(job_id: ab12cd34)\n"
        "-------------\n\n"
        "Nightly report looks fine.\n\n"
        'To stop or manage this job, send me a new message (e.g. "stop reminder Morning brief").'
    )
    zh = translate_cron_delivery(wrapped)
    assert "Nightly report looks fine." in zh
    assert zh.startswith("定时任务回复：Morning brief")
    assert "Cronjob Response:" not in zh


def test_en_passthrough_and_unknown_fail_open(use_language):
    use_language("en")
    en = script_timeout_notice("Morning brief", "ab12cd34")
    assert translate_cron_delivery(en) == en
    use_language("zh")
    unknown = "💡 Cron 'Morning brief' invented a brand new failure shape."
    assert translate_cron_delivery(unknown) == unknown
    assert translate_cron_delivery("") == ""
    assert translate_cron_delivery(None) == ""


def test_official_english_source_unchanged():
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "cron" / "scheduler_failure_copy.py"
    text = src.read_text(encoding="utf-8")
    assert "💡 Cron '{job_name}' failed:" in text
    assert "its script timed out. No model was invoked." in text
    assert "the job stalled — it stopped doing anything for too long" in text
    assert "⛔ Cron '{job_name}' did not run:" in text
    assert "See the full run with `hermes cron runs {job_id}`" in text
    assert "Run log: `hermes cron runs {job_id}`." in text


def test_deliver_result_hook_translates_for_zh(use_language, monkeypatch):
    """Glue in _deliver_result rewrites the wrapped payload before send."""
    use_language("zh")
    from types import SimpleNamespace

    from cron import scheduler_delivery as delivery

    sent: list[str] = []

    job = {"id": "ab12cd34", "name": "Morning brief", "deliver": "feishu"}
    monkeypatch.setattr(delivery, "_resolve_delivery_targets", lambda job, for_failure=False: [
        {"platform": "feishu", "chat_id": "oc_test", "thread_id": None}
    ])
    monkeypatch.setattr(delivery, "_unresolved_delivery_outcome", lambda *a, **k: None)
    monkeypatch.setattr(delivery, "_cron_delivery_notify_enabled", lambda cfg: True)
    monkeypatch.setattr(delivery, "_cron_mirror_delivery_enabled", lambda job, cfg: False)
    monkeypatch.setattr(delivery, "_redact_cron_payload", lambda text, _label: text)
    monkeypatch.setattr(delivery, "_record_delivery_verification", lambda *a, **k: None)
    monkeypatch.setattr(
        "gateway.config.load_gateway_config",
        lambda: SimpleNamespace(),
    )
    monkeypatch.setattr(
        delivery,
        "_prepare_target_delivery",
        lambda *a, **k: SimpleNamespace(live_adapter_ready=True, platform="feishu"),
    )

    def _live(t, cleaned_delivery_content, media_files, **kwargs):
        sent.append(cleaned_delivery_content)
        return True

    monkeypatch.setattr(delivery, "_deliver_via_live_adapter", _live)
    monkeypatch.setattr("gateway.platforms.base.BasePlatformAdapter.extract_media", lambda text: ([], text))
    monkeypatch.setattr(
        "gateway.platforms.base.BasePlatformAdapter.filter_media_delivery_paths",
        lambda files: files,
    )
    monkeypatch.setattr("gateway.media_policy.apply_media_policy_env", lambda cfg: None)
    monkeypatch.setattr("gateway.warning_notifications.warning_notifications_enabled", lambda *a, **k: True)
    monkeypatch.setattr(delivery._sched, "load_config", lambda: {"cron": {"wrap_response": True}})

    err = delivery._deliver_result(
        job, script_timeout_notice("Morning brief", "ab12cd34"), adapters={"feishu": object()}, loop=object()
    )
    assert err is None
    assert sent, "expected a live-adapter send"
    payload = sent[0]
    assert payload.startswith("定时任务回复：Morning brief")
    assert "其脚本超时" in payload
    assert "`hermes cron run ab12cd34`" in payload
    assert "Cronjob Response:" not in payload
