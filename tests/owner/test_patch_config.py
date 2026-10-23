"""C01: owner patch.yaml loader + config.owner overlay."""

from __future__ import annotations

import time
from pathlib import Path

import pytest


@pytest.fixture()
def hermes_home(tmp_path, monkeypatch):
    home = tmp_path / "hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    # Reset loader caches between tests
    from owner import patch_config as pc

    pc.invalidate_owner_config_cache()
    pc.invalidate_patch_feishu_profile_config_cache()
    yield home
    pc.invalidate_owner_config_cache()
    pc.invalidate_patch_feishu_profile_config_cache()


def test_load_owner_config_no_shell(hermes_home: Path):
    """File first-level keys ARE the sections — no owner:/patch: wrapper."""
    (hermes_home / "patch.yaml").write_text(
        "approvals:\n  allow_permanent: false\n  command_allowlist: []\n"
        "feishu_card:\n  auto_card_threshold: 57\n",
        encoding="utf-8",
    )
    from owner.patch_config import load_owner_config

    cfg = load_owner_config(force=True)
    assert "owner" not in cfg  # no shell peeled / no shell expected
    assert cfg["approvals"]["allow_permanent"] is False
    assert cfg["feishu_card"]["auto_card_threshold"] == 57


def test_apply_owner_overlay_hangs_under_config_owner(hermes_home: Path):
    (hermes_home / "patch.yaml").write_text(
        "approvals:\n  allow_permanent: false\n",
        encoding="utf-8",
    )
    from owner.patch_config import apply_owner_overlay, invalidate_owner_config_cache

    invalidate_owner_config_cache()
    config = {"model": {"default": "x"}, "owner": {"legacy": 1}}
    apply_owner_overlay(config)
    assert config["owner"]["approvals"]["allow_permanent"] is False
    # patch section keys replace; unrelated leftover keys from config.yaml owner kept if not in patch
    assert config["owner"]["legacy"] == 1


def test_load_config_exposes_config_owner(hermes_home: Path, monkeypatch):
    (hermes_home / "patch.yaml").write_text(
        "approvals:\n  allow_permanent: false\n  command_allowlist: []\n",
        encoding="utf-8",
    )
    (hermes_home / "config.yaml").write_text("model:\n  default: test-model\n", encoding="utf-8")
    from owner.patch_config import invalidate_owner_config_cache
    from hermes_cli import config as cfg_mod

    invalidate_owner_config_cache()
    # Clear config cache for this home
    cfg_mod._LOAD_CONFIG_CACHE.clear()
    loaded = cfg_mod.load_config()
    assert loaded["owner"]["approvals"]["allow_permanent"] is False
    assert loaded["owner"]["approvals"]["command_allowlist"] == []


def test_missing_patch_yaml_fail_open(hermes_home: Path):
    from owner.patch_config import apply_owner_overlay, load_owner_config, invalidate_owner_config_cache

    invalidate_owner_config_cache()
    assert load_owner_config(force=True) == {}
    config = {}
    apply_owner_overlay(config)
    assert config["owner"] == {}


def test_mtime_cache_refresh(hermes_home: Path):
    path = hermes_home / "patch.yaml"
    path.write_text("approvals:\n  allow_permanent: false\n", encoding="utf-8")
    from owner.patch_config import load_owner_config, invalidate_owner_config_cache

    invalidate_owner_config_cache()
    assert load_owner_config()["approvals"]["allow_permanent"] is False
    time.sleep(0.05)
    path.write_text("approvals:\n  allow_permanent: true\n", encoding="utf-8")
    # mtime change should invalidate even within TTL
    assert load_owner_config()["approvals"]["allow_permanent"] is True
