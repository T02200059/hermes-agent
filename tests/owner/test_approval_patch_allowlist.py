"""Tests for patch.yaml command_allowlist merging into approval allowlist."""

from unittest.mock import patch

import tools.approval as approval_module
from tools.approval import load_permanent_allowlist


class TestLoadPermanentAllowlistPatchMerge:
    """Verify owner.approvals.command_allowlist from patch.yaml is merged."""

    def test_patch_allowlist_merged_with_config(self, tmp_path, monkeypatch):
        """config.yaml and patch.yaml entries both end up in permanent set."""
        _saved_permanent = approval_module._permanent_approved.copy()
        approval_module._permanent_approved.clear()

        def _fake_load_config():
            return {"command_allowlist": ["config-entry"], "other": "value"}

        def _fake_load_patch():
            return {"approvals": {"command_allowlist": ["patch-entry", "tirith:raw_ip_url"]}}

        try:
            with patch("hermes_cli.config.load_config_readonly", _fake_load_config), patch(
                "owner.patch_config._load_patch_owner_config", _fake_load_patch
            ):
                patterns = load_permanent_allowlist()

            assert patterns == {"config-entry", "patch-entry", "tirith:raw_ip_url"}
            assert "config-entry" in approval_module._permanent_approved
            assert "patch-entry" in approval_module._permanent_approved
        finally:
            approval_module._permanent_approved.clear()
            approval_module._permanent_approved.update(_saved_permanent)

    def test_patch_allowlist_missing_approvals_section(self, tmp_path, monkeypatch):
        """patch.yaml without owner.approvals is fine."""
        _saved_permanent = approval_module._permanent_approved.copy()
        approval_module._permanent_approved.clear()

        def _fake_load_config():
            return {"command_allowlist": ["config-entry"]}

        def _fake_load_patch():
            return {"image_gen": {}}

        try:
            with patch("hermes_cli.config.load_config_readonly", _fake_load_config), patch(
                "owner.patch_config._load_patch_owner_config", _fake_load_patch
            ):
                patterns = load_permanent_allowlist()

            assert patterns == {"config-entry"}
        finally:
            approval_module._permanent_approved.clear()
            approval_module._permanent_approved.update(_saved_permanent)

    def test_patch_allowlist_load_failure_is_silent(self, tmp_path, monkeypatch):
        """patch.yaml loader failing does not break config.yaml allowlist."""
        _saved_permanent = approval_module._permanent_approved.copy()
        approval_module._permanent_approved.clear()

        def _fake_load_config():
            return {"command_allowlist": ["config-entry"]}

        def _broken_load_patch():
            raise RuntimeError("patch.yaml missing")

        try:
            with patch("hermes_cli.config.load_config_readonly", _fake_load_config), patch(
                "owner.patch_config._load_patch_owner_config", _broken_load_patch
            ):
                patterns = load_permanent_allowlist()

            assert patterns == {"config-entry"}
        finally:
            approval_module._permanent_approved.clear()
            approval_module._permanent_approved.update(_saved_permanent)
