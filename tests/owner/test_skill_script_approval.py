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