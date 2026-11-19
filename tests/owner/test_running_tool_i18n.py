"""[owner] owner/i18n/running_tool — migration guard for format_running_tool.

Body moved from agent/display.py (commit a6e7e672) to
owner/i18n/running_tool.py; agent/display.py keeps a thin delegate and
gateway/run_busy.py + gateway/run_turn.py call it unchanged. These tests pin
the pre-migration output through every entry point (zh 「正在…」, non-zh verb
as-is, unknown/labels-off fallback to ``gateway.busy.running_tool``).
"""

from __future__ import annotations

import pytest


def _set_lang(monkeypatch: pytest.MonkeyPatch, lang: str) -> None:
    from agent import i18n

    monkeypatch.setenv("HERMES_LANGUAGE", lang)
    i18n.reset_language_cache()


def _entry_points():
    from agent import display
    from owner.i18n import running_tool
    from owner.explainers.progress import activity_i18n

    return {
        "agent.display (thin delegate)": display.format_running_tool,
        "owner.i18n.running_tool (impl)": running_tool.format_running_tool,
        "activity_i18n (C13 delegate)": activity_i18n.format_running_tool,
    }


@pytest.mark.parametrize("label", list(_entry_points().keys()))
def test_zh_known_tool_is_zhengzai_verb(monkeypatch, label):
    _set_lang(monkeypatch, "zh")
    monkeypatch.setattr("agent.display._friendly_tool_labels", True)
    fmt = _entry_points()[label]
    assert fmt("terminal") == "正在运行命令"
    assert fmt("web_search") == "正在搜索网页"


@pytest.mark.parametrize("label", list(_entry_points().keys()))
def test_zh_unknown_tool_falls_back_to_busy_key(monkeypatch, label):
    _set_lang(monkeypatch, "zh")
    monkeypatch.setattr("agent.display._friendly_tool_labels", True)
    assert _entry_points()[label]("not_a_real_tool_xyz") == "正在运行：not_a_real_tool_xyz"


@pytest.mark.parametrize("label", list(_entry_points().keys()))
def test_en_known_tool_returns_progressive_verb(monkeypatch, label):
    _set_lang(monkeypatch, "en")
    monkeypatch.setattr("agent.display._friendly_tool_labels", True)
    assert _entry_points()[label]("terminal") == "Running"


@pytest.mark.parametrize("label", list(_entry_points().keys()))
def test_en_unknown_tool_falls_back_to_busy_key(monkeypatch, label):
    _set_lang(monkeypatch, "en")
    monkeypatch.setattr("agent.display._friendly_tool_labels", True)
    assert _entry_points()[label]("not_a_real_tool_xyz") == "running: not_a_real_tool_xyz"


@pytest.mark.parametrize("label", list(_entry_points().keys()))
def test_labels_off_falls_back_to_busy_key_even_for_known_tool(monkeypatch, label):
    _set_lang(monkeypatch, "zh")
    monkeypatch.setattr("agent.display._friendly_tool_labels", False)
    assert _entry_points()[label]("terminal") == "正在运行：terminal"


@pytest.mark.parametrize("label", list(_entry_points().keys()))
def test_blank_tool_name_returns_empty_string(monkeypatch, label):
    _set_lang(monkeypatch, "zh")
    fmt = _entry_points()[label]
    assert fmt(None) == ""
    assert fmt("") == ""
    assert fmt("   ") == ""


def test_owner_i18n_package_exports_impl(monkeypatch):
    import owner.i18n as pkg
    from owner.i18n.running_tool import format_running_tool

    assert pkg.format_running_tool is format_running_tool
