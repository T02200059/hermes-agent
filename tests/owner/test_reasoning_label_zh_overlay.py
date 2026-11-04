"""Owner locale overlay: zh 「💭 推理」→「💭 想法」 for thinking display labels."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

# Source of truth tracked in-repo; runtime is ~/.hermes/locales -> this file.
_OVERLAY = (
    Path(__file__).resolve().parents[2]
    / "owner"
    / "config"
    / "locales"
    / "zh.yaml"
)


@pytest.fixture()
def zh_home(tmp_path, monkeypatch):
    home = tmp_path / "hermes-home"
    locales = home / "locales"
    locales.mkdir(parents=True)
    (locales / "zh.yaml").write_text(_OVERLAY.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_LANGUAGE", "zh")
    from agent.i18n import reset_language_cache

    reset_language_cache()
    yield home
    reset_language_cache()


def test_overlay_file_only_touches_reasoning_display_labels():
    data = yaml.safe_load(_OVERLAY.read_text(encoding="utf-8"))
    reasoning = data["gateway"]["reasoning"]
    assert set(reasoning) == {
        "quote_label_discord",
        "quote_label_md",
        "block",
    }
    assert reasoning["quote_label_discord"] == "-# 💭 想法"
    assert reasoning["quote_label_md"] == "> 💭 **想法：**"
    assert reasoning["block"].startswith("💭 **想法：**")


def test_overlay_wins_for_thinking_display_labels(zh_home):
    from agent.i18n import t

    assert t("gateway.reasoning.quote_label_discord") == "-# 💭 想法"
    assert t("gateway.reasoning.quote_label_md") == "> 💭 **想法：**"
    rendered = t("gateway.reasoning.block", reasoning="think", response="hi")
    assert rendered.startswith("💭 **想法：**")
    assert "think" in rendered and rendered.endswith("hi")
    # Config wording stays bundled 「推理」
    status = t(
        "gateway.reasoning.status",
        level="medium",
        scope="会话",
        display="开",
    )
    assert "推理设置" in status
