"""Configuration loader for the upstream sync pipeline.

Reads ``owner/config/upstream_sync.yaml`` (schema defined in architecture doc
section 3.1), expands ``~`` paths, validates required fields and exposes every
configuration value as a read-only attribute.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


class SyncConfig:
    """Immutable view over the upstream_sync.yaml configuration file.

    All path attributes are resolved to absolute :class:`pathlib.Path`
    instances rooted at ``repo.root`` (after ``~`` expansion).
    """

    # Required top-level sections that must be present in the YAML file.
    _REQUIRED_SECTIONS: tuple[str, ...] = (
        "repo",
        "cron",
        "classification",
        "health_check",
        "testing",
        "fingerprint",
        "notification",
        "state",
        "rollback",
    )

    def __init__(self, raw: dict[str, Any]) -> None:
        """Construct a config from a parsed YAML mapping.

        This is normally called via :meth:`load`; callers may use it directly
        in tests.

        Args:
            raw: Parsed YAML mapping.

        Raises:
            ValueError: If a required section or field is missing.
        """
        self._raw: dict[str, Any] = raw
        self._validate()

        repo = raw["repo"]
        repo_root = Path(os.path.expanduser(repo["root"])).resolve()

        self.repo_root: Path = repo_root
        self.owner_branch: str = repo["owner_branch"]
        self.upstream_remote: str = repo["upstream_remote"]
        self.upstream_branch: str = repo["upstream_branch"]
        self.venv_python: Path = (repo_root / repo["venv_python"]).resolve()

        cron = raw["cron"]
        self.cron_schedule: str = cron["schedule"]
        self.max_commits_threshold: int = int(cron["max_commits_threshold"])

        cls_cfg = raw["classification"]
        self.d1_max_files: int = int(cls_cfg["d1_max_files"])
        self.d2_anchors_file: Path = (repo_root / cls_cfg["d2_anchors_file"]).resolve()
        self.d3_heavily_intruded_files: list[str] = list(
            cls_cfg["d3_heavily_intruded_files"]
        )
        self.d5_dangerous_keywords: list[str] = list(
            cls_cfg["d5_dangerous_keywords"]
        )

        hc = raw["health_check"]
        self.health_check_script: str = hc["script"]
        self.health_check_path: Path = (repo_root / hc["script"]).resolve()

        testing = raw["testing"]
        self.test_command: str = testing["command"]
        self.testing_timeout: int = int(testing["timeout_seconds"])

        fp = raw["fingerprint"]
        self.fingerprint_file: str = fp["file"]
        self.fingerprint_path: Path = (repo_root / fp["file"]).resolve()
        self.high_confidence_threshold: float = float(fp["high_confidence_threshold"])
        self.medium_confidence_threshold: float = float(
            fp["medium_confidence_threshold"]
        )
        self.file_weight: float = float(fp["file_weight"])
        self.keyword_weight: float = float(fp["keyword_weight"])

        notif = raw["notification"]
        self.log_dir: Path = (repo_root / notif["log_dir"]).resolve()
        self.feishu_webhook: str = str(notif.get("feishu_webhook", "") or "")

        state = raw["state"]
        self.state_file: Path = (repo_root / state["file"]).resolve()

        rollback = raw["rollback"]
        self.rollback_strategy: str = rollback["strategy"]

        # Optional kanban section (K0 manual-review tickets). Missing/empty = disabled.
        kanban = raw.get("kanban") or {}
        self.kanban_enabled: bool = bool(kanban.get("enabled", False))
        self.kanban_create_on: list[str] = list(
            kanban.get("create_on") or ["MANUAL_REVIEW"]
        )
        self.kanban_tenant: str = str(kanban.get("tenant") or "owner-upstream-sync")
        ws = str(kanban.get("workspace") or "~/.hermes/kanban/workspaces/owner-upstream-sync")
        self.kanban_workspace: Path = Path(os.path.expanduser(ws)).resolve()
        self.kanban_assignee: str = str(kanban.get("assignee") or "")
        self.kanban_initial_status: str = str(kanban.get("initial_status") or "blocked")
        self.kanban_priority: int = int(kanban.get("priority") or 20)
        self.kanban_created_by: str = str(kanban.get("created_by") or "upstream-sync")
        self.kanban_hermes_bin: str = str(kanban.get("hermes_bin") or "hermes")
        self.kanban_max_runtime: str = str(kanban.get("max_runtime") or "")
        self.kanban_timeout_seconds: int = int(kanban.get("timeout_seconds") or 120)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    @classmethod
    def load(cls, path: Path | str) -> "SyncConfig":
        """Load a :class:`SyncConfig` from a YAML file.

        Args:
            path: Path to ``upstream_sync.yaml``. ``~`` is expanded.

        Returns:
            Parsed and validated :class:`SyncConfig`.

        Raises:
            FileNotFoundError: If the config file does not exist.
            ValueError: If required sections/fields are missing or invalid.
        """
        config_path = Path(os.path.expanduser(str(path)))
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")
        with config_path.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
        if not isinstance(raw, dict):
            raise ValueError(
                f"Config file {config_path} must contain a YAML mapping at the top level."
            )
        return cls(raw)

    @property
    def upstream_ref(self) -> str:
        """Full upstream reference, e.g. ``upstream/main``."""
        return f"{self.upstream_remote}/{self.upstream_branch}"

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------
    def _validate(self) -> None:
        """Ensure all required sections and critical fields are present.

        Raises:
            ValueError: With a descriptive message listing missing fields.
        """
        missing_sections = [
            section
            for section in self._REQUIRED_SECTIONS
            if section not in self._raw
        ]
        if missing_sections:
            raise ValueError(
                f"Missing required config sections: {', '.join(missing_sections)}"
            )

        # repo.* required fields
        repo = self._raw["repo"]
        for field_name in ("root", "owner_branch", "upstream_remote",
                           "upstream_branch", "venv_python"):
            if not repo.get(field_name):
                raise ValueError(f"Missing required field repo.{field_name}")

        # classification critical lists must be non-empty
        cls_cfg = self._raw["classification"]
        if not cls_cfg.get("d3_heavily_intruded_files"):
            raise ValueError(
                "classification.d3_heavily_intruded_files must be a non-empty list"
            )
        if not cls_cfg.get("d5_dangerous_keywords"):
            raise ValueError(
                "classification.d5_dangerous_keywords must be a non-empty list"
            )

        # fingerprint thresholds sanity
        fp = self._raw["fingerprint"]
        if not (0.0 <= float(fp["medium_confidence_threshold"])
                <= float(fp["high_confidence_threshold"]) <= 1.0):
            raise ValueError(
                "fingerprint thresholds must satisfy "
                "0 <= medium <= high <= 1"
            )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"SyncConfig(repo_root={self.repo_root!r}, "
            f"upstream_ref={self.upstream_ref!r}, "
            f"max_commits_threshold={self.max_commits_threshold})"
        )
