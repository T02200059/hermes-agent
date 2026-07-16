"""Shared fixtures for the upstream-sync test suite.

All fixtures build hermetic, in-memory or tmp_path-based objects so no real
git repository or subprocess is ever touched.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from owner.sync.config import SyncConfig


def build_raw_config(tmp_path: Path, **overrides: Any) -> dict[str, Any]:
    """Return a valid raw config dict rooted at *tmp_path*."""
    raw: dict[str, Any] = {
        "repo": {
            "root": str(tmp_path),
            "owner_branch": "owner",
            "upstream_remote": "upstream",
            "upstream_branch": "main",
            "venv_python": ".venv/bin/python",
        },
        "cron": {
            "schedule": "0 3 * * *",
            "max_commits_threshold": 100,
        },
        "classification": {
            "d1_max_files": 20,
            "d2_anchors_file": "owner/validation/anchors.yaml",
            "d3_heavily_intruded_files": [
                "gateway/run.py",
                "agent/conversation_loop.py",
            ],
            "d5_dangerous_keywords": ["refactor", "rewrite", "remove"],
        },
        "health_check": {
            "script": "owner/validation/merge_health_check.py",
        },
        "testing": {
            "command": ".venv/bin/python -m pytest tests/owner/ -x -q",
            "timeout_seconds": 600,
        },
        "fingerprint": {
            "file": "owner/validation/fix_fingerprints.yaml",
            "high_confidence_threshold": 0.8,
            "medium_confidence_threshold": 0.5,
            "file_weight": 0.6,
            "keyword_weight": 0.4,
        },
        "notification": {
            "log_dir": "owner/logs/upstream-sync",
            "feishu_webhook": "",
        },
        "state": {
            "file": "owner/logs/upstream-sync/.sync_state.json",
        },
        "rollback": {
            "strategy": "reset_hard",
        },
    }
    raw.update(overrides)
    return raw


def write_config_yaml(tmp_path: Path, **overrides: Any) -> Path:
    """Write a valid upstream_sync.yaml into *tmp_path* and return its path."""
    raw = build_raw_config(tmp_path, **overrides)
    config_path = tmp_path / "upstream_sync.yaml"
    config_path.write_text(yaml.dump(raw, allow_unicode=True), encoding="utf-8")
    return config_path


def write_fingerprints(tmp_path: Path, fixes: list[dict[str, Any]]) -> Path:
    """Write a fix_fingerprints.yaml into the expected config location."""
    fp_dir = tmp_path / "owner" / "validation"
    fp_dir.mkdir(parents=True, exist_ok=True)
    fp_path = fp_dir / "fix_fingerprints.yaml"
    fp_path.write_text(
        yaml.dump({"fixes": fixes}, allow_unicode=True), encoding="utf-8"
    )
    return fp_path


def write_anchors(tmp_path: Path, anchors: list[dict[str, Any]]) -> Path:
    """Write an anchors.yaml into the expected config location."""
    anc_dir = tmp_path / "owner" / "validation"
    anc_dir.mkdir(parents=True, exist_ok=True)
    anc_path = anc_dir / "anchors.yaml"
    anc_path.write_text(
        yaml.dump({"anchors": anchors}, allow_unicode=True), encoding="utf-8"
    )
    return anc_path


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    """Path to a valid config file in tmp_path."""
    return write_config_yaml(tmp_path)


@pytest.fixture
def config(config_path: Path) -> SyncConfig:
    """A loaded SyncConfig rooted at tmp_path."""
    return SyncConfig.load(config_path)
