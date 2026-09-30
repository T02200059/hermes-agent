"""Split-module notifications keep their copy in ``locales`` (T2-20 A3).

``gateway/run_notifications.py`` is one of upstream's split modules, and it is the
landing site for the notification copy the owner tree had i18n-ised inside the
monolith. Three things must hold once ``GatewayRunner`` is bound to the module:

* the non-concise background-process lanes render a **localized tail** — #54266
  replaced the old bracketed ``[Background process …]`` wrapper with "concise header
  + fenced tail", so the tail, not the retired wrapper, is what carries the copy;
* the update flow's failure notice lives in the catalog, not in the module-level
  ``_UPDATE_FAILED_NOTICE`` constant upstream used (both its call sites resolve the
  key at call time, so a language switch mid-process is honoured);
* restart / online lifecycle copy resolves through ``owner.gateway.lifecycle_copy``
  so the ``{profile_tag}`` injection (改动清单 §7.14) keeps working from the module.

The tests exercise the mixin directly: ``GatewayRunner`` only inherits it after the
split cutover, so a runner-level test would pass against the monolith's own copy.
"""
from types import SimpleNamespace

import pytest

from agent.i18n import t
from gateway.run_notifications import GatewayNotificationsMixin

# Upstream's copy for the failed-update notice; the catalog key must render to it
# verbatim in English (the owner customisation is i18n, not wording).
UPSTREAM_FAILED_NOTICE = (
    "❌ Hermes update failed; the previous version is still running. Run `hermes update` on the "
    "host to see the full error, or try /update again later."
)


class _Notifier(GatewayNotificationsMixin):
    """Bare mixin instance: only the formatters and the lifecycle helper are used."""


def _runner() -> _Notifier:
    return object.__new__(_Notifier)


def _session(*, out: str = "", cmd: str = "pytest -q", exit_code: int = 0):
    return SimpleNamespace(output_buffer=out, command=cmd, exit_code=exit_code, started_at=None)


# ------------------------------------------------------------------ bg process: final lane


def test_bg_final_tail_is_localized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HERMES_LANGUAGE", "zh")
    msg = _runner()._format_process_final_message("proc_1", _session(out="boom", exit_code=1), "all")
    assert "最终输出" in msg
    assert "Final output:" not in msg
    assert t("gateway.bg_process_final_body", output="boom").strip() in msg


def test_bg_final_tail_matches_split_structure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HERMES_LANGUAGE", "en")
    msg = _runner()._format_process_final_message("proc_1", _session(out="boom", exit_code=1), "all")
    assert msg.endswith("Final output:\n```\nboom\n```")
    # the retired bracket wrapper must not come back
    assert "[Background process" not in msg


def test_bg_final_without_output_has_no_tail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HERMES_LANGUAGE", "zh")
    msg = _runner()._format_process_final_message("proc_1", _session(out=""), "result")
    assert "最终输出" not in msg
    assert "```" not in msg


# ------------------------------------------------------------------ bg process: running lane


def test_bg_running_header_and_tail_are_localized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HERMES_LANGUAGE", "zh")
    msg = _runner()._format_process_running_message(_session(out="tick"))
    assert msg.startswith(t("gateway.bg_process_running_header"))
    assert "最新输出" in msg
    assert "Recent output:" not in msg


def test_bg_running_without_output_is_header_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HERMES_LANGUAGE", "en")
    msg = _runner()._format_process_running_message(_session(out=""))
    assert msg == t("gateway.bg_process_running_header") + " — `pytest -q`"


# ------------------------------------------------------------------ update flow copy


def test_update_failed_notice_is_in_the_catalog() -> None:
    assert t("gateway.update.failed_notice", lang="en") == UPSTREAM_FAILED_NOTICE
    assert t("gateway.update.failed_notice", lang="zh") != UPSTREAM_FAILED_NOTICE


def test_update_module_no_longer_hardcodes_the_notice() -> None:
    import gateway.run_notifications as mod

    assert not hasattr(mod, "_UPDATE_FAILED_NOTICE")
    src = read_module_source()
    assert "❌ Hermes update failed;" not in src
    assert 't("gateway.update.failed_notice")' in src


def test_update_with_output_keeps_the_tail_label() -> None:
    en = t("gateway.update.failed_with_output", lang="en", output="X")
    assert en.startswith(UPSTREAM_FAILED_NOTICE)
    assert en.endswith("Last lines:\n```\nX\n```")
    zh = t("gateway.update.failed_with_output", lang="zh", output="X")
    assert "最后几行" in zh
    assert t("gateway.update.finished_with_output", lang="en", output="X") == (
        "✅ Hermes update finished successfully.\n\n```\nX\n```"
    )


def test_update_needs_input_keeps_the_prompt_shape() -> None:
    got = t("gateway.update.needs_input", lang="en", prompt="P", default_hint=" (default: d)",
            command_prefix="/")
    assert got.startswith("⚕ **Update needs your input:**")
    assert "`/approve`" in got and "`/deny`" in got


# ------------------------------------------------------------------ lifecycle copy


def test_lifecycle_copy_resolves_from_the_owner_module() -> None:
    import gateway.run_notifications as mod

    assert mod._gateway_lifecycle_msg.__module__ == "owner.gateway.lifecycle_copy"
    assert mod._gateway_lifecycle_msg("gateway.online") == t("gateway.online", profile_tag=t_profile_tag())


def test_restart_and_online_keep_owner_wording() -> None:
    src = read_module_source()
    assert "♻ Gateway restarted successfully" not in src
    assert "♻️ Gateway online" not in src
    assert '_gateway_lifecycle_msg("gateway.restart_success")' in src
    assert '_gateway_lifecycle_msg("gateway.online")' in src


# ------------------------------------------------------------------ helpers


def t_profile_tag() -> str:
    from owner.gateway.lifecycle_copy import profile_tag

    return profile_tag()


def read_module_source() -> str:
    from gateway.run_notifications import __file__ as f

    with open(f, encoding="utf-8") as fh:
        return fh.read()
