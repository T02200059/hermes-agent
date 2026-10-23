"""C01: disable permanent (Always) approval via config.owner.approvals."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def hermes_home(tmp_path, monkeypatch):
    home = tmp_path / "hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    from owner import patch_config as pc
    from hermes_cli import config as cfg_mod

    pc.invalidate_owner_config_cache()
    cfg_mod._LOAD_CONFIG_CACHE.clear()
    yield home
    pc.invalidate_owner_config_cache()
    cfg_mod._LOAD_CONFIG_CACHE.clear()


def _write_patch(home: Path, allow_permanent: bool, allowlist=None):
    allowlist = allowlist if allowlist is not None else []
    lines = ["approvals:", f"  allow_permanent: {'true' if allow_permanent else 'false'}", "  command_allowlist:"]
    if not allowlist:
        lines.append("    []")
    else:
        for item in allowlist:
            lines.append(f"    - {item}")
    (home / "patch.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (home / "config.yaml").write_text("model:\n  default: test\n", encoding="utf-8")


def test_gate_allow_permanent_defaults_false(hermes_home: Path):
    _write_patch(hermes_home, allow_permanent=False)
    from owner.patch_config import invalidate_owner_config_cache
    from hermes_cli import config as cfg_mod
    from owner.approval.permanent_policy import gate_allow_permanent, get_allow_permanent

    invalidate_owner_config_cache()
    cfg_mod._LOAD_CONFIG_CACHE.clear()
    assert get_allow_permanent() is False
    assert gate_allow_permanent(True) is False
    assert gate_allow_permanent(False) is False


def test_gate_allow_permanent_opt_in(hermes_home: Path):
    _write_patch(hermes_home, allow_permanent=True)
    from owner.patch_config import invalidate_owner_config_cache
    from hermes_cli import config as cfg_mod
    from owner.approval.permanent_policy import gate_allow_permanent, get_allow_permanent

    invalidate_owner_config_cache()
    cfg_mod._LOAD_CONFIG_CACHE.clear()
    assert get_allow_permanent() is True
    assert gate_allow_permanent(True) is True


def test_sanitize_always_degrades_to_session(hermes_home: Path):
    _write_patch(hermes_home, allow_permanent=False)
    from owner.patch_config import invalidate_owner_config_cache
    from hermes_cli import config as cfg_mod
    from owner.approval.permanent_policy import sanitize_permanent_choice

    invalidate_owner_config_cache()
    cfg_mod._LOAD_CONFIG_CACHE.clear()
    assert sanitize_permanent_choice("always") == "session"
    assert sanitize_permanent_choice("once") == "once"
    assert sanitize_permanent_choice("session") == "session"


def test_merge_owner_command_allowlist(hermes_home: Path):
    _write_patch(hermes_home, allow_permanent=False, allowlist=["git status", "ls *"])
    (hermes_home / "config.yaml").write_text(
        "model:\n  default: test\ncommand_allowlist:\n  - echo hi\n",
        encoding="utf-8",
    )
    from owner.patch_config import invalidate_owner_config_cache
    from hermes_cli import config as cfg_mod
    from tools.approval import _read_permanent_allowlist

    invalidate_owner_config_cache()
    cfg_mod._LOAD_CONFIG_CACHE.clear()
    patterns = _read_permanent_allowlist()
    assert "echo hi" in patterns
    assert "git status" in patterns
    assert "ls *" in patterns


def test_base_exec_approval_actions_hide_always_when_gated():
    """Feishu/QQ build buttons from ExecApprovalPrompt.actions — no Always when flag False."""
    from types import SimpleNamespace

    from gateway.platforms.base import BasePlatformAdapter

    stub = SimpleNamespace(
        _EA_ACTION_LABELS={"once": "o", "session": "s", "always": "a", "deny": "d"},
        _EA_ACTION_STYLES=BasePlatformAdapter._EA_ACTION_STYLES,
    )
    actions = BasePlatformAdapter._exec_approval_actions(
        stub, allow_permanent=False, allow_session=True, smart_denied=False
    )
    choices = [c for _, c, _ in actions]
    assert "always" not in choices
    assert "once" in choices
    assert "session" in choices
    assert "deny" in choices

    actions_on = BasePlatformAdapter._exec_approval_actions(
        stub, allow_permanent=True, allow_session=True, smart_denied=False
    )
    assert "always" in [c for _, c, _ in actions_on]


def test_qq_keyboard_hides_always_when_not_allowed():
    from plugins.platforms.qqbot.keyboards import build_approval_keyboard

    kb = build_approval_keyboard("sess:1", allow_permanent=False)
    # Flatten button labels / ids
    blob = str(kb)
    assert "allow-always" not in blob
    assert "allow-once" in blob
