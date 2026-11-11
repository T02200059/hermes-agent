"""owner/gateway/lifecycle_copy：重启/上线通知附带 profile 显示名。"""

from __future__ import annotations

from pathlib import Path

from agent import i18n
from owner.gateway.lifecycle_copy import lifecycle_msg, profile_tag

ZH_RESTART = "🔄 Hermes 正在重启。当前任务会中断；重启后发任意消息，我会尽量从离开处继续。"
ZH_ONLINE = "🔄 网关已上线——Hermes 已恢复就绪。"
EN_RESTART = "🔄 Hermes is restarting. Your current task will pause; send any message after it's back and I'll try to pick up where you left off."
EN_ONLINE = "🔄 Gateway online — Hermes is back and ready."


def _set_language(monkeypatch, lang: str) -> None:
    monkeypatch.setenv("HERMES_LANGUAGE", lang)
    i18n.reset_language_cache()


def _clear_label_env(monkeypatch) -> None:
    for name in ("HERMES_LIFECYCLE_LABEL", "HERMES_PROFILE", "HERMES_PROFILE_NAME", "HERMES_OVERLAY_PATH"):
        monkeypatch.delenv(name, raising=False)
    # Isolate tests from host / well-known fleet overlay paths.
    from owner.gateway import lifecycle_copy

    monkeypatch.setattr(lifecycle_copy, "_WELL_KNOWN_OVERLAY_PATHS", ())


def _home_with_meta(tmp_path: Path, monkeypatch, **meta: str) -> Path:
    lines = []
    for key, value in meta.items():
        lines.append(f"{key}: {value}")
    (tmp_path / "profile.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    return tmp_path


def test_profile_tag_empty_for_default(monkeypatch, tmp_path):
    _clear_label_env(monkeypatch)
    monkeypatch.setenv("HERMES_PROFILE", "default")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    assert profile_tag() == ""


def test_profile_tag_empty_for_custom_home(monkeypatch, tmp_path):
    """非标准 HERMES_HOME 推断为 custom，不加标签，避免测试/临时目录误伤官方文案。"""
    _clear_label_env(monkeypatch)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    assert profile_tag() == ""


def test_profile_tag_named_profile_id(monkeypatch, tmp_path):
    _clear_label_env(monkeypatch)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_PROFILE", "yangtb")
    assert profile_tag() == " [yangtb]"


def test_profile_tag_prefers_display_name(monkeypatch, tmp_path):
    _clear_label_env(monkeypatch)
    _home_with_meta(tmp_path, monkeypatch, display_name="杨天宝", description="杨天宝的 AI 助手")
    monkeypatch.setenv("HERMES_PROFILE", "yangtb")
    assert profile_tag() == " [杨天宝]"


def test_profile_tag_falls_back_to_description(monkeypatch, tmp_path):
    _clear_label_env(monkeypatch)
    _home_with_meta(tmp_path, monkeypatch, description="杨天宝的 AI 助手")
    monkeypatch.setenv("HERMES_PROFILE", "yangtb")
    assert profile_tag() == " [杨天宝的 AI 助手]"


def test_profile_tag_prefers_overlay_display_name_over_description(monkeypatch, tmp_path):
    _clear_label_env(monkeypatch)
    _home_with_meta(tmp_path, monkeypatch, description="杨天宝的 AI 助手")
    (tmp_path / "overlay.yaml").write_text(
        "fleet_profiles:\n  yangtb:\n    display_name: 杨天宝\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_PROFILE", "yangtb")
    assert profile_tag() == " [杨天宝]"


def test_profile_tag_prefers_overlay_over_profile_display_name(monkeypatch, tmp_path):
    """集中管理人卡 display_name 优先于 profile.yaml 的同名字段。"""
    _clear_label_env(monkeypatch)
    _home_with_meta(tmp_path, monkeypatch, display_name="档案显示名", description="杨天宝的 AI 助手")
    (tmp_path / "overlay.yaml").write_text(
        "fleet_profiles:\n  yangtb:\n    display_name: 杨天宝\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_PROFILE", "yangtb")
    assert profile_tag() == " [杨天宝]"


def test_profile_tag_overlay_path_env(monkeypatch, tmp_path):
    _clear_label_env(monkeypatch)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    overlay = tmp_path / "elsewhere" / "overlay.yaml"
    overlay.parent.mkdir()
    overlay.write_text("fleet_profiles:\n  sunqf:\n    display_name: 孙起飞\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_PROFILE", "sunqf")
    monkeypatch.setenv("HERMES_OVERLAY_PATH", str(overlay))
    assert profile_tag() == " [孙起飞]"


def test_profile_tag_well_known_overlay_path(monkeypatch, tmp_path):
    """容器内 $HERMES_HOME/overlay.yaml 不是舰队 overlay 时，走约定挂载路径。"""
    from owner.gateway import lifecycle_copy

    _clear_label_env(monkeypatch)
    _home_with_meta(tmp_path, monkeypatch, description="杨天宝的 AI 助手")
    well_known = tmp_path / "etc-hermes" / "overlay.yaml"
    well_known.parent.mkdir()
    well_known.write_text(
        "fleet_profiles:\n  yangtb:\n    display_name: 杨天宝\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(lifecycle_copy, "_WELL_KNOWN_OVERLAY_PATHS", (well_known,))
    monkeypatch.setenv("HERMES_PROFILE", "yangtb")
    assert profile_tag() == " [杨天宝]"


def test_profile_tag_prefers_lifecycle_label(monkeypatch, tmp_path):
    _clear_label_env(monkeypatch)
    _home_with_meta(tmp_path, monkeypatch, display_name="杨天宝")
    monkeypatch.setenv("HERMES_PROFILE", "yangtb")
    monkeypatch.setenv("HERMES_LIFECYCLE_LABEL", "孙起飞的 AI 助手")
    assert profile_tag() == " [孙起飞的 AI 助手]"


def test_profile_tag_blank_lifecycle_label_falls_through(monkeypatch, tmp_path):
    _clear_label_env(monkeypatch)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_PROFILE", "sunqf")
    monkeypatch.setenv("HERMES_LIFECYCLE_LABEL", "   ")
    assert profile_tag() == " [sunqf]"


def test_zh_restart_and_online_include_chinese_name(monkeypatch, tmp_path):
    _clear_label_env(monkeypatch)
    _home_with_meta(tmp_path, monkeypatch, display_name="杨天宝")
    monkeypatch.setenv("HERMES_PROFILE", "yangtb")
    _set_language(monkeypatch, "zh")
    try:
        assert lifecycle_msg("gateway.shutdown.notice_restart") == (
            "🔄 Hermes [杨天宝] 正在重启。当前任务会中断；重启后发任意消息，我会尽量从离开处继续。"
        )
        assert lifecycle_msg("gateway.startup.online") == (
            "🔄 网关 [杨天宝]已上线——Hermes 已恢复就绪。"
        )
    finally:
        monkeypatch.delenv("HERMES_LANGUAGE", raising=False)
        i18n.reset_language_cache()


def test_zh_messages_match_original_when_untagged(monkeypatch, tmp_path):
    _clear_label_env(monkeypatch)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_PROFILE", "default")
    _set_language(monkeypatch, "zh")
    try:
        assert lifecycle_msg("gateway.shutdown.notice_restart") == ZH_RESTART
        assert lifecycle_msg("gateway.startup.online") == ZH_ONLINE
    finally:
        monkeypatch.delenv("HERMES_LANGUAGE", raising=False)
        i18n.reset_language_cache()


def test_en_restart_and_online_include_tag(monkeypatch, tmp_path):
    _clear_label_env(monkeypatch)
    _home_with_meta(tmp_path, monkeypatch, display_name="杨天宝")
    monkeypatch.setenv("HERMES_PROFILE", "yangtb")
    _set_language(monkeypatch, "en")
    try:
        assert lifecycle_msg("gateway.shutdown.notice_restart") == (
            "🔄 Hermes [杨天宝] is restarting. Your current task will pause; "
            "send any message after it's back and I'll try to pick up where you left off."
        )
        assert lifecycle_msg("gateway.startup.online") == (
            "🔄 Gateway [杨天宝] online — Hermes is back and ready."
        )
    finally:
        monkeypatch.delenv("HERMES_LANGUAGE", raising=False)
        i18n.reset_language_cache()


def test_en_messages_match_original_when_untagged(monkeypatch, tmp_path):
    _clear_label_env(monkeypatch)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _set_language(monkeypatch, "en")
    try:
        assert lifecycle_msg("gateway.shutdown.notice_restart") == EN_RESTART
        assert lifecycle_msg("gateway.startup.online") == EN_ONLINE
    finally:
        monkeypatch.delenv("HERMES_LANGUAGE", raising=False)
        i18n.reset_language_cache()
