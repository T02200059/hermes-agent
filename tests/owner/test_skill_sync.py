"""Tests for owner/scripts/skill_sync_lib.py and the sync CLI scripts."""

from __future__ import annotations

from pathlib import Path

import pytest

from owner.scripts.skill_sync_lib import (
    SkillDiff,
    apply_one,
    compare_all,
    default_deployed_root,
    default_repo_root,
    default_source_roots,
    diff_one,
    direction,
    index_deployed,
    index_source,
    is_behind,
    line_count,
    list_files,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class TestPathDefaults:
    """Default paths must be inferred without hard-coding host paths."""

    def test_default_repo_root_is_repo(self):
        root = default_repo_root()
        assert (root / "run_agent.py").is_file()
        assert (root / "owner" / "scripts" / "skill_sync_lib.py").is_file()

    def test_default_source_roots_under_repo(self):
        roots = default_source_roots()
        assert all(r.parent == default_repo_root() for r in roots)
        assert {r.name for r in roots} == {"skills", "optional-skills"}

    def test_default_deployed_root_uses_hermes_home(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        assert default_deployed_root() == tmp_path / "skills"


class TestListFiles:
    def test_lists_files_recursively(self, tmp_path):
        _write(tmp_path / "a.txt", "a")
        _write(tmp_path / "sub" / "b.txt", "b")
        files = list_files(tmp_path)
        assert set(files.keys()) == {"a.txt", "sub/b.txt"}
        assert files["a.txt"].is_absolute()

    def test_returns_empty_for_missing_dir(self, tmp_path):
        assert list_files(tmp_path / "nope") == {}


class TestIndexSource:
    def test_indexes_by_skill_name(self, tmp_path):
        _write(tmp_path / "skills" / "foo" / "SKILL.md", "foo")
        _write(tmp_path / "optional-skills" / "bar" / "SKILL.md", "bar")
        idx = index_source([tmp_path / "skills", tmp_path / "optional-skills"])
        assert set(idx.keys()) == {"foo", "bar"}
        assert idx["foo"][0].name == "foo"

    def test_skips_missing_roots(self, tmp_path):
        assert index_source([tmp_path / "missing"]) == {}


class TestIndexDeployed:
    def test_skips_metadata_top_dirs(self, tmp_path):
        _write(tmp_path / "foo" / "SKILL.md", "foo")
        _write(tmp_path / ".archive" / "old" / "SKILL.md", "old")
        _write(tmp_path / ".hub" / "hub" / "SKILL.md", "hub")
        idx = index_deployed(tmp_path)
        assert set(idx.keys()) == {"foo"}

    def test_returns_empty_for_missing_dir(self, tmp_path):
        assert index_deployed(tmp_path / "nope") == {}


class TestDiffOne:
    def test_detects_missing_differs_extra(self, tmp_path):
        src = tmp_path / "src"
        dep = tmp_path / "dep"
        _write(src / "SKILL.md", "skill")
        _write(src / "keep.txt", "keep")
        _write(dep / "SKILL.md", "changed")
        _write(dep / "extra.txt", "extra")

        diff = diff_one(src, dep)
        assert diff.missing == ["keep.txt"]
        assert diff.differs == ["SKILL.md"]
        assert diff.extra == ["extra.txt"]


class TestLineCountAndDirection:
    def test_line_count(self, tmp_path):
        path = tmp_path / "f.txt"
        _write(path, "line1\nline2\n")
        assert line_count(path) == 2

    def test_direction(self):
        assert direction(10, 5) == "behind(-5)"
        assert direction(5, 10) == "ahead(+5)"
        assert direction(5, 5) == "same-len-diff"
        assert direction(-1, 5) == "?"


class TestIsBehind:
    def test_missing_files_mean_behind(self, tmp_path):
        src = tmp_path / "src"
        dep = tmp_path / "dep"
        _write(src / "SKILL.md", "skill")
        _write(src / "missing.txt", "x")
        _write(dep / "SKILL.md", "skill")

        behind, diff = is_behind([src], [dep])
        assert behind is True
        assert diff.missing == ["missing.txt"]

    def test_differs_with_fewer_deployed_lines_mean_behind(self, tmp_path):
        src = tmp_path / "src"
        dep = tmp_path / "dep"
        _write(src / "SKILL.md", "a\nb\nc\n")
        _write(dep / "SKILL.md", "a\n")

        behind, diff = is_behind([src], [dep])
        assert behind is True
        assert diff.differs == ["SKILL.md"]

    def test_differs_with_more_deployed_lines_not_behind(self, tmp_path):
        src = tmp_path / "src"
        dep = tmp_path / "dep"
        _write(src / "SKILL.md", "a\n")
        _write(dep / "SKILL.md", "a\nb\nc\n")

        behind, diff = is_behind([src], [dep])
        assert behind is False

    def test_in_sync_not_behind(self, tmp_path):
        src = tmp_path / "src"
        dep = tmp_path / "dep"
        _write(src / "SKILL.md", "skill")
        _write(dep / "SKILL.md", "skill")

        behind, diff = is_behind([src], [dep])
        assert behind is False
        assert diff == SkillDiff(missing=[], differs=[], extra=[])


class TestCompareAll:
    def test_returns_only_common_skills(self, tmp_path):
        src_root = tmp_path / "src"
        dep_root = tmp_path / "dep"
        _write(src_root / "common" / "SKILL.md", "common")
        _write(src_root / "source_only" / "SKILL.md", "source")
        _write(dep_root / "common" / "SKILL.md", "common")
        _write(dep_root / "deploy_only" / "SKILL.md", "deploy")

        results = compare_all([src_root], dep_root)
        assert len(results) == 1
        assert results[0].name == "common"


class TestApplyOne:
    def test_copies_and_overwrites(self, tmp_path):
        src = tmp_path / "src"
        dep = tmp_path / "dep"
        _write(src / "SKILL.md", "new")
        _write(src / "new_file.txt", "new file")
        _write(dep / "SKILL.md", "old")
        _write(dep / "extra.txt", "should remain")

        apply_one(src, dep)

        assert (dep / "SKILL.md").read_text(encoding="utf-8") == "new"
        assert (dep / "new_file.txt").read_text(encoding="utf-8") == "new file"
        assert (dep / "extra.txt").read_text(encoding="utf-8") == "should remain"


class TestDiffCLI:
    def test_diff_json_output(self, tmp_path, capsys):
        src_root = tmp_path / "src"
        dep_root = tmp_path / "dep"
        _write(src_root / "behind" / "SKILL.md", "a\nb\n")
        _write(dep_root / "behind" / "SKILL.md", "a\n")

        from owner.scripts.skill_sync_diff import main

        code = main(
            [
                "--source",
                str(src_root),
                "--deployed",
                str(dep_root),
                "--json",
            ]
        )
        captured = capsys.readouterr()
        assert code == 0
        assert '"behind": true' in captured.out
        assert "behind" in captured.out

    def test_diff_reports_invalid_deployed_root(self, capsys):
        from owner.scripts.skill_sync_diff import main

        code = main(["--deployed", "/nonexistent/path"])
        assert code == 2
        assert "deployed root does not exist" in capsys.readouterr().err


class TestApplyCLI:
    def test_apply_dry_run_does_not_copy(self, tmp_path, capsys):
        src_root = tmp_path / "src"
        dep_root = tmp_path / "dep"
        _write(src_root / "behind" / "SKILL.md", "a\nb\n")
        _write(dep_root / "behind" / "SKILL.md", "a\n")

        from owner.scripts.skill_sync_apply import main

        code = main(
            [
                "--source",
                str(src_root),
                "--deployed",
                str(dep_root),
            ]
        )
        captured = capsys.readouterr()
        assert code == 0
        assert "DRY-RUN" in captured.out
        assert (dep_root / "behind" / "SKILL.md").read_text(encoding="utf-8") == "a\n"

    def test_apply_with_yes_copies(self, tmp_path, capsys):
        src_root = tmp_path / "src"
        dep_root = tmp_path / "dep"
        _write(src_root / "behind" / "SKILL.md", "a\nb\n")
        _write(dep_root / "behind" / "SKILL.md", "a\n")

        from owner.scripts.skill_sync_apply import main

        code = main(
            [
                "--source",
                str(src_root),
                "--deployed",
                str(dep_root),
                "--apply",
                "--yes",
            ]
        )
        captured = capsys.readouterr()
        assert code == 0
        assert "Synced 1 skill" in captured.out
        assert (dep_root / "behind" / "SKILL.md").read_text(encoding="utf-8") == "a\nb\n"
