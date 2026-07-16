"""Unit tests for owner.sync.config.SyncConfig."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from owner.sync.config import SyncConfig
from tests.owner.test_upstream_sync.conftest import build_raw_config, write_config_yaml


# ── Happy path ──────────────────────────────────────────────────────────────


def test_load_valid_config(tmp_path: Path):
    path = write_config_yaml(tmp_path)
    cfg = SyncConfig.load(path)

    assert cfg.repo_root == tmp_path
    assert cfg.owner_branch == "owner"
    assert cfg.upstream_remote == "upstream"
    assert cfg.upstream_branch == "main"
    assert cfg.d1_max_files == 20
    assert cfg.max_commits_threshold == 100
    assert cfg.high_confidence_threshold == 0.8
    assert cfg.medium_confidence_threshold == 0.5
    assert cfg.file_weight == 0.6
    assert cfg.keyword_weight == 0.4
    assert cfg.feishu_webhook == ""
    assert cfg.rollback_strategy == "reset_hard"


def test_load_tilde_expansion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """``~`` in repo.root must be expanded to the user home."""
    monkeypatch.setenv("HOME", str(tmp_path))
    raw = build_raw_config(tmp_path)
    raw["repo"]["root"] = "~/hermes-test-repo"
    path = tmp_path / "cfg.yaml"
    path.write_text(yaml.dump(raw), encoding="utf-8")

    cfg = SyncConfig.load(path)
    expected = Path(str(tmp_path)) / "hermes-test-repo"
    assert cfg.repo_root == expected.resolve()


def test_upstream_ref_property(tmp_path: Path):
    cfg = SyncConfig(build_raw_config(tmp_path))
    assert cfg.upstream_ref == "upstream/main"


def test_path_resolution_relative_to_repo_root(tmp_path: Path):
    cfg = SyncConfig(build_raw_config(tmp_path))
    assert cfg.state_file == (tmp_path / "owner/logs/upstream-sync/.sync_state.json").resolve()
    assert cfg.fingerprint_path == (tmp_path / "owner/validation/fix_fingerprints.yaml").resolve()
    assert cfg.d2_anchors_file == (tmp_path / "owner/validation/anchors.yaml").resolve()
    assert cfg.health_check_path == (tmp_path / "owner/validation/merge_health_check.py").resolve()
    assert cfg.log_dir == (tmp_path / "owner/logs/upstream-sync").resolve()
    assert cfg.venv_python == (tmp_path / ".venv/bin/python").resolve()


def test_load_accepts_string_path(tmp_path: Path):
    path = write_config_yaml(tmp_path)
    cfg = SyncConfig.load(str(path))
    assert cfg.owner_branch == "owner"


# ── Error cases ─────────────────────────────────────────────────────────────


def test_load_missing_file_raises_filenotfound(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="Config file not found"):
        SyncConfig.load(tmp_path / "nonexistent.yaml")


def test_missing_required_section_raises_valueerror(tmp_path: Path):
    raw = build_raw_config(tmp_path)
    del raw["state"]
    path = tmp_path / "cfg.yaml"
    path.write_text(yaml.dump(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="Missing required config sections"):
        SyncConfig.load(path)


def test_missing_repo_field_raises_valueerror(tmp_path: Path):
    raw = build_raw_config(tmp_path)
    del raw["repo"]["owner_branch"]
    with pytest.raises(ValueError, match="Missing required field repo.owner_branch"):
        SyncConfig(raw)


def test_empty_d3_list_raises_valueerror(tmp_path: Path):
    raw = build_raw_config(tmp_path)
    raw["classification"]["d3_heavily_intruded_files"] = []
    with pytest.raises(ValueError, match="d3_heavily_intruded_files must be a non-empty list"):
        SyncConfig(raw)


def test_empty_d5_list_raises_valueerror(tmp_path: Path):
    raw = build_raw_config(tmp_path)
    raw["classification"]["d5_dangerous_keywords"] = []
    with pytest.raises(ValueError, match="d5_dangerous_keywords must be a non-empty list"):
        SyncConfig(raw)


def test_invalid_threshold_order_raises_valueerror(tmp_path: Path):
    raw = build_raw_config(tmp_path)
    raw["fingerprint"]["medium_confidence_threshold"] = 0.9
    raw["fingerprint"]["high_confidence_threshold"] = 0.5
    with pytest.raises(ValueError, match="fingerprint thresholds must satisfy"):
        SyncConfig(raw)


def test_non_dict_yaml_raises_valueerror(tmp_path: Path):
    path = tmp_path / "cfg.yaml"
    path.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must contain a YAML mapping"):
        SyncConfig.load(path)


def test_empty_repo_root_raises_valueerror(tmp_path: Path):
    raw = build_raw_config(tmp_path)
    raw["repo"]["root"] = ""
    with pytest.raises(ValueError, match="Missing required field repo.root"):
        SyncConfig(raw)
