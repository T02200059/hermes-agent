"""Security tests for owner/approval/skill_script_approval.py."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from owner.approval import skill_script_approval as ssa


@pytest.fixture(autouse=True)
def _reset_session_state():
    ssa.reset_session_skills_viewed()
    ssa.invalidate_skill_scripts_cache()
    yield
    ssa.reset_session_skills_viewed()
    ssa.invalidate_skill_scripts_cache()


def test_extract_script_filenames_nested_bash_c():
    cmd = 'bash -c "python3 run_task.py && echo done"'
    assert ssa.extract_script_filenames(cmd) == ["run_task.py"]


def test_extract_script_filenames_ignores_interpreters():
    assert ssa.extract_script_filenames("python3 helper.py") == ["helper.py"]


def test_auto_approve_requires_viewed_skill(tmp_path, monkeypatch):
    skills_root = tmp_path / "skills" / "devops" / "deploy-skill"
    skills_root.mkdir(parents=True)
    script = skills_root / "deploy.sh"
    script.write_text("#!/bin/bash\necho deploy\n", encoding="utf-8")

    patch_yaml = tmp_path / "patch.yaml"
    patch_yaml.write_text(
        json.dumps(
            {
                "owner": {
                    "approvals": {
                        "skill_script_allowlist": [
                            {"skill": "deploy-skill", "paths": [], "extensions": [".sh"]}
                        ]
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    # Not viewed yet — must not auto-approve
    assert ssa.is_skill_script_allowed("bash deploy.sh") is None

    ssa.track_session_skill_view("deploy-skill")
    assert ssa.is_skill_script_allowed("bash deploy.sh") == "deploy-skill"


def test_auto_approve_rejects_unlisted_script_name(tmp_path, monkeypatch):
    skills_root = tmp_path / "skills" / "devops" / "deploy-skill"
    skills_root.mkdir(parents=True)
    (skills_root / "deploy.sh").write_text("#!/bin/bash\n", encoding="utf-8")

    patch_yaml = tmp_path / "patch.yaml"
    patch_yaml.write_text(
        json.dumps(
            {
                "owner": {
                    "approvals": {
                        "skill_script_allowlist": [
                            {"skill": "deploy-skill", "paths": [], "extensions": [".sh"]}
                        ]
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    ssa.track_session_skill_view("deploy-skill")

    # Filename not present in scanned allowlist
    assert ssa.is_skill_script_allowed("bash unknown.sh") is None


def test_same_filename_different_skill_requires_viewed_match(tmp_path, monkeypatch):
    for skill in ("skill-a", "skill-b"):
        root = tmp_path / "skills" / "cat" / skill
        root.mkdir(parents=True)
        (root / "run.py").write_text("print('x')\n", encoding="utf-8")

    patch_yaml = tmp_path / "patch.yaml"
    patch_yaml.write_text(
        json.dumps(
            {
                "owner": {
                    "approvals": {
                        "skill_script_allowlist": [
                            {"skill": "skill-a", "paths": [], "extensions": [".py"]},
                            {"skill": "skill-b", "paths": [], "extensions": [".py"]},
                        ]
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    ssa.track_session_skill_view("skill-a")
    # run.py exists in both skills; only skill-a was viewed
    assert ssa.is_skill_script_allowed("python3 run.py") == "skill-a"

    ssa.reset_session_skills_viewed()
    ssa.track_session_skill_view("skill-b")
    assert ssa.is_skill_script_allowed("python3 run.py") == "skill-b"


def test_reset_session_clears_viewed_set():
    ssa.track_session_skill_view("foo")
    assert "foo" in ssa.get_session_skills_viewed()
    ssa.reset_session_skills_viewed()
    assert ssa.get_session_skills_viewed() == set()


def test_cross_session_isolation_uses_contextvar(tmp_path, monkeypatch):
    """CR-01: a skill viewed in session A must NOT auto-approve in session B.

    Concurrent gateway sessions run in different executor threads/tasks,
    each with its own ``_approval_session_key`` ContextVar. The per-session
    viewed-skills dict must isolate them — viewing a skill in one session
    must never leak to another session.
    """
    import contextvars

    skills_root = tmp_path / "skills" / "devops" / "deploy-skill"
    skills_root.mkdir(parents=True)
    (skills_root / "deploy.sh").write_text("#!/bin/bash\necho deploy\n", encoding="utf-8")

    patch_yaml = tmp_path / "patch.yaml"
    patch_yaml.write_text(
        json.dumps(
            {
                "owner": {
                    "approvals": {
                        "skill_script_allowlist": [
                            {"skill": "deploy-skill", "paths": [], "extensions": [".sh"]}
                        ]
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    from tools.approval import (
        set_current_session_key,
        reset_current_session_key,
    )

    ssa.invalidate_skill_scripts_cache()

    # Session A views the skill and runs a script — must auto-approve.
    token_a = set_current_session_key("session-A")
    try:
        ssa.track_session_skill_view("deploy-skill")
        assert ssa.is_skill_script_allowed("bash deploy.sh") == "deploy-skill"
    finally:
        reset_current_session_key(token_a)

    # Session B starts fresh in the same process. It has NOT viewed the
    # skill, so the same script invocation must NOT auto-approve.
    token_b = set_current_session_key("session-B")
    try:
        assert ssa.is_skill_script_allowed("bash deploy.sh") is None
    finally:
        reset_current_session_key(token_b)

    # Switching back to session A still works (its state is preserved).
    token_a2 = set_current_session_key("session-A")
    try:
        assert ssa.is_skill_script_allowed("bash deploy.sh") == "deploy-skill"
    finally:
        reset_current_session_key(token_a2)

    # Clearing session A's state must not touch session B.
    ssa.reset_session_skills_viewed("session-A")
    token_a3 = set_current_session_key("session-A")
    try:
        assert ssa.is_skill_script_allowed("bash deploy.sh") is None
    finally:
        reset_current_session_key(token_a3)
    token_b2 = set_current_session_key("session-B")
    try:
        # Session B is still empty (was never viewed) — still no auto-approve.
        assert ssa.is_skill_script_allowed("bash deploy.sh") is None
    finally:
        reset_current_session_key(token_b2)


# ---------------------------------------------------------------------------
# Integration: guard functions in tools/approval.py now respect the bypass
# (both the unified check_all_command_guards used by terminal, and the
# legacy check_dangerous_command). This verifies the owner-v16 migration
# wiring is complete.
# ---------------------------------------------------------------------------

def test_skill_script_bypass_in_check_all_command_guards(tmp_path, monkeypatch):
    """Skill scripts from a viewed skill must short-circuit check_all_command_guards
    (the live path) before tirith/dangerous collection or user prompts.
    """
    from unittest.mock import patch

    skills_root = tmp_path / "skills" / "devops" / "deploy-skill"
    skills_root.mkdir(parents=True)
    (skills_root / "deploy.sh").write_text("#!/bin/bash\necho ok\n", encoding="utf-8")

    patch_yaml = tmp_path / "patch.yaml"
    patch_yaml.write_text(
        json.dumps(
            {
                "owner": {
                    "approvals": {
                        "skill_script_allowlist": [
                            {"skill": "deploy-skill", "paths": [], "extensions": [".sh"]}
                        ]
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    ssa.track_session_skill_view("deploy-skill")

    from tools.approval import check_all_command_guards, check_dangerous_command

    # A command that would normally be treated as dangerous (to prove early bypass)
    cmd = "bash deploy.sh"

    # Patch the expensive/approval-triggering steps so we can assert they were not reached
    with patch("tools.approval.detect_dangerous_command") as mock_detect, \
         patch("tools.approval._get_approval_mode", return_value="normal"):
        result_all = check_all_command_guards(cmd, "local")
        assert result_all["approved"] is True
        assert result_all.get("message") is None
        # The bypass must have short-circuited before any dangerous detection
        mock_detect.assert_not_called()

    # Also exercise the legacy path (still has the bypass for compat)
    with patch("tools.approval.detect_dangerous_command") as mock_detect2:
        result_legacy = check_dangerous_command(cmd, "local")
        assert result_legacy["approved"] is True
        mock_detect2.assert_not_called()


def test_skill_script_bypass_skips_tirith_and_prompts(tmp_path, monkeypatch):
    """Even when tirith would block/warn, a viewed skill script is auto-approved."""
    from unittest.mock import patch

    skills_root = tmp_path / "skills" / "sre" / "sre-king"
    skills_root.mkdir(parents=True)
    (skills_root / "inspect.sh").write_text("#!/bin/bash\ncurl http://10.0.0.1\n", encoding="utf-8")

    patch_yaml = tmp_path / "patch.yaml"
    patch_yaml.write_text(
        json.dumps(
            {
                "owner": {
                    "approvals": {
                        "skill_script_allowlist": [
                            {"skill": "sre-king", "paths": [], "extensions": [".sh"]}
                        ]
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    ssa.track_session_skill_view("sre-king")

    from tools.approval import check_all_command_guards

    cmd = "bash inspect.sh"

    # Force tirith to "block" — the skill bypass must still win (early return before warnings)
    fake_tirith_block = {"action": "block", "findings": [{"severity": "high", "title": "raw IP", "rule_id": "raw_ip_url"}], "summary": "raw IP"}
    with patch("tools.approval._get_approval_mode", return_value="normal"), \
         patch("tools.tirith_security.check_command_security", return_value=fake_tirith_block, create=True):
        result = check_all_command_guards(cmd, "local")
        assert result["approved"] is True
        # No pending status, no description from tirith
        assert result.get("status") is None
        assert "tirith" not in str(result)