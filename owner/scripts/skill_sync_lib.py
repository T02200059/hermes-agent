#!/usr/bin/env python3
"""Shared helpers for skill sync diff/apply scripts.

Provides filesystem indexing, diffing, and the "behind/ahead/mixed" verdict
logic used to decide whether a deployed skill should be overwritten from its
source-of-truth copy in the repo.
"""

from __future__ import annotations

import filecmp
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from hermes_constants import get_hermes_home

DEFAULT_SOURCE_SKILL_DIRS = ("skills", "optional-skills")
DEFAULT_SKIP_TOP = {".archive", ".hub", ".curator_backups"}


@dataclass(frozen=True)
class SkillDiff:
    """Diff result for a single source-vs-deployed skill pair."""

    missing: list[str]
    differs: list[str]
    extra: list[str]


@dataclass(frozen=True)
class SkillVerdict:
    """Aggregated verdict for one skill across all its source/deployed paths."""

    name: str
    source_paths: list[Path]
    deployed_paths: list[Path]
    missing: list[str]
    differs: list[str]
    extra: list[str]
    behind: bool


def default_repo_root() -> Path:
    """Return the repository root containing these scripts.

    ``owner/scripts/skill_sync_*.py`` -> ``owner/`` -> repo root.
    """
    return Path(__file__).resolve().parents[2]


def default_source_roots(repo_root: Path | None = None) -> list[Path]:
    """Return default source skill roots under ``repo_root``.

    Uses ``skills/`` and ``optional-skills/`` when present.
    """
    root = repo_root or default_repo_root()
    return [root / name for name in DEFAULT_SOURCE_SKILL_DIRS]


def default_deployed_root(hermes_home: Path | None = None) -> Path:
    """Return the default deployed skills directory.

    Honors an explicit ``hermes_home``; otherwise resolves via
    ``hermes_constants.get_hermes_home()``.
    """
    home = hermes_home or get_hermes_home()
    return home / "skills"


def list_files(d: Path) -> dict[str, Path]:
    """Return ``{relative posix path: absolute path}`` for every file under *d*."""
    out: dict[str, Path] = {}
    if not d.is_dir():
        return out
    for p in d.rglob("*"):
        if p.is_file():
            out[p.relative_to(d).as_posix()] = p
    return out


def index_source(source_roots: Iterable[Path]) -> dict[str, list[Path]]:
    """Map skill basename -> list of source directories containing a SKILL.md."""
    idx: dict[str, list[Path]] = {}
    for root in source_roots:
        if not root.is_dir():
            continue
        for skill_md in root.rglob("SKILL.md"):
            idx.setdefault(skill_md.parent.name, []).append(skill_md.parent)
    return idx


def index_deployed(
    deployed_root: Path,
    *,
    skip_top: Iterable[str] | None = None,
) -> dict[str, list[Path]]:
    """Map skill basename -> list of deployed directories containing a SKILL.md.

    Directories listed in ``skip_top`` are ignored.
    """
    skip = set(skip_top) if skip_top else DEFAULT_SKIP_TOP
    idx: dict[str, list[Path]] = {}
    if not deployed_root.is_dir():
        return idx
    for skill_md in deployed_root.rglob("SKILL.md"):
        sdir = skill_md.parent
        rel = sdir.relative_to(deployed_root)
        if rel.parts and rel.parts[0] in skip:
            continue
        idx.setdefault(sdir.name, []).append(sdir)
    return idx


def diff_one(src: Path, dep: Path) -> SkillDiff:
    """Compare two skill directories and return missing/differs/extra file lists."""
    sf = list_files(src)
    df = list_files(dep)
    missing = [rel for rel in sf if rel not in df]
    differs = [
        rel for rel in sf if rel in df and not filecmp.cmp(sf[rel], df[rel], shallow=False)
    ]
    extra = [rel for rel in df if rel not in sf]
    return SkillDiff(
        missing=sorted(missing),
        differs=sorted(differs),
        extra=sorted(extra),
    )


def line_count(path: Path) -> int:
    """Return the number of lines in *path*, or ``-1`` on error."""
    try:
        with path.open("r", errors="replace") as f:
            return sum(1 for _ in f)
    except Exception:
        return -1


def direction(src_lines: int, dep_lines: int) -> str:
    """Describe how the deployed file length compares to the source file."""
    if src_lines < 0 or dep_lines < 0:
        return "?"
    if dep_lines < src_lines:
        return f"behind(-{src_lines - dep_lines})"
    if dep_lines > src_lines:
        return f"ahead(+{dep_lines - src_lines})"
    return "same-len-diff"


def file_directions(
    source_paths: list[Path],
    deployed_paths: list[Path],
    differs: Iterable[str],
) -> dict[str, str]:
    """Map each differing relative path to its ``direction()`` tag."""
    sp0 = source_paths[0] if source_paths else Path()
    dp0 = deployed_paths[0] if deployed_paths else Path()
    out: dict[str, str] = {}
    for rel in differs:
        s = line_count(sp0 / rel) if (sp0 / rel).exists() else -1
        d = line_count(dp0 / rel) if (dp0 / rel).exists() else -1
        out[rel] = direction(s, d)
    return out


def is_behind(source_paths: list[Path], deployed_paths: list[Path]) -> tuple[bool, SkillDiff]:
    """Decide whether a deployed skill is behind its source copy.

    A skill is considered **behind** when:

    - any source file is missing from the deployed copy, OR
    - every content-differing file has fewer lines in the deployed copy than
      in the source copy (the conservative "source is authoritative" rule).

    Returns ``(behind, aggregated_diff)``.
    """
    missing_all: set[str] = set()
    differs_all: set[str] = set()
    extra_all: set[str] = set()

    for sp in source_paths:
        for dp in deployed_paths:
            diff = diff_one(sp, dp)
            missing_all |= set(diff.missing)
            differs_all |= set(diff.differs)
            extra_all |= set(diff.extra)

    if missing_all:
        return True, SkillDiff(
            missing=sorted(missing_all),
            differs=sorted(differs_all),
            extra=sorted(extra_all),
        )
    if not differs_all:
        return False, SkillDiff(
            missing=sorted(missing_all),
            differs=sorted(differs_all),
            extra=sorted(extra_all),
        )

    sp0 = source_paths[0]
    dp0 = deployed_paths[0]
    for rel in differs_all:
        s = line_count(sp0 / rel) if (sp0 / rel).exists() else -1
        d = line_count(dp0 / rel) if (dp0 / rel).exists() else -1
        if not (s >= 0 and d >= 0 and d < s):
            return False, SkillDiff(
                missing=sorted(missing_all),
                differs=sorted(differs_all),
                extra=sorted(extra_all),
            )

    return True, SkillDiff(
        missing=sorted(missing_all),
        differs=sorted(differs_all),
        extra=sorted(extra_all),
    )


def compare_all(
    source_roots: Iterable[Path],
    deployed_root: Path,
    *,
    skip_top: Iterable[str] | None = None,
) -> list[SkillVerdict]:
    """Compare every skill found in both source and deployed roots."""
    src_idx = index_source(source_roots)
    dep_idx = index_deployed(deployed_root, skip_top=skip_top)
    common = sorted(set(src_idx) & set(dep_idx))

    results: list[SkillVerdict] = []
    for name in common:
        sps = src_idx[name]
        dps = dep_idx[name]
        behind, diff = is_behind(sps, dps)
        results.append(
            SkillVerdict(
                name=name,
                source_paths=sps,
                deployed_paths=dps,
                missing=diff.missing,
                differs=diff.differs,
                extra=diff.extra,
                behind=behind,
            )
        )
    return results


def apply_one(source_path: Path, deployed_path: Path) -> None:
    """Copy *source_path* over *deployed_path* using ``shutil.copytree``.

    Existing files are overwritten; files only present in the deployed copy are
    left untouched.
    """
    import shutil

    shutil.copytree(source_path, deployed_path, dirs_exist_ok=True)
