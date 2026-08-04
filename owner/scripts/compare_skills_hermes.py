#!/usr/bin/env python3
"""Compare hermes-agent/skills (source of truth, category-nested) with the
deployed ./skills directory (flat layout, may contain a .archive area).

Answers: which deployed skills also exist in the source AND differ from it
(i.e. are out of date and need updating).

Layout assumptions:
  source:   <src>/<category>/<skill-name>/SKILL.md
  deployed: <deployed>/<skill-name>/SKILL.md   (or ./.archive/<skill-name>/...)

Usage:
  compare_skills_hermes.py [--source DIR] [--deployed DIR] [--out FILE] [--json]

Exit codes: 0 ok, 2 bad args / missing dirs.
"""

from __future__ import annotations

import argparse
import filecmp
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_SOURCE = Path("hermes-agent/skills")
DEFAULT_DEPLOYED = Path("skills")
ARCHIVE_TOPS = {".archive", ".hub", ".curator_backups"}


@dataclass
class SkillDiff:
    """Aggregated diff for one skill name across all source/deployed paths."""

    name: str
    source_paths: list[Path] = field(default_factory=list)
    deployed_paths: list[Path] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)  # in source, not deployed
    differs: list[str] = field(default_factory=list)  # in both, content differs
    extra: list[str] = field(default_factory=list)  # in deployed, not source


def list_files(root: Path) -> dict[str, Path]:
    """{relative posix path: absolute path} for every file under root.

    Symlinked directories are pruned (avoid cycles / duplicated trees).
    """
    out: dict[str, Path] = {}
    if not root.is_dir():
        return out
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames if not os.path.islink(os.path.join(dirpath, d))
        ]
        for fn in filenames:
            p = Path(dirpath) / fn
            if p.is_symlink():
                # compare symlinks by target, cheap sanity: still record the link
                pass
            out[p.relative_to(root).as_posix()] = p
    return out


def index_skills(root: Path) -> dict[str, list[tuple[Path, str]]]:
    """Map skill basename -> [(skill_dir, top_level_rel_part)] for every SKILL.md.

    ``top_level_rel_part`` is the first path component below root, e.g. the
    category in the source tree or ".archive" in the deployed tree ("" if the
    skill sits directly under root).
    """
    idx: dict[str, list[tuple[Path, str]]] = {}
    if not root.is_dir():
        return idx
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames if not os.path.islink(os.path.join(dirpath, d))
        ]
        if "SKILL.md" not in filenames:
            continue
        sdir = Path(dirpath)
        rel = sdir.relative_to(root)
        top = rel.parts[0] if rel.parts else ""
        idx.setdefault(sdir.name, []).append((sdir, top))
    return idx


def diff_one(src: Path, dep: Path) -> tuple[list[str], list[str], list[str]]:
    sf = list_files(src)
    df = list_files(dep)
    missing = [rel for rel in sf if rel not in df]
    differs = [
        rel
        for rel in sf
        if rel in df and not filecmp.cmp(sf[rel], df[rel], shallow=False)
    ]
    extra = [rel for rel in df if rel not in sf]
    return sorted(missing), sorted(differs), sorted(extra)


def aggregate(name: str, src_paths: list[Path], dep_paths: list[Path]) -> SkillDiff:
    missing: set[str] = set()
    differs: set[str] = set()
    extra: set[str] = set()
    for sp in src_paths:
        for dp in dep_paths:
            m, d, e = diff_one(sp, dp)
            missing |= set(m)
            differs |= set(d)
            extra |= set(e)
    return SkillDiff(
        name=name,
        source_paths=src_paths,
        deployed_paths=dep_paths,
        missing=sorted(missing),
        differs=sorted(differs),
        extra=sorted(extra),
    )


def line_count(path: Path) -> int:
    try:
        with path.open("r", errors="replace") as f:
            return sum(1 for _ in f)
    except Exception:
        return -1


def direction(src: Path, dep: Path, rel: str) -> str:
    s = line_count(src / rel) if (src / rel).exists() else -1
    d = line_count(dep / rel) if (dep / rel).exists() else -1
    if s < 0 or d < 0:
        return "?"
    if d < s:
        return f"behind(-{s - d})"
    if d > s:
        return f"ahead(+{d - s})"
    return "same-len-diff"


def render_markdown(
    need_update: list[SkillDiff],
    archived: list[SkillDiff],
    in_sync: list[str],
    deployed_only: list[str],
    source_only: list[str],
    stats: dict,
) -> str:
    lines: list[str] = []
    lines.append("# Skill 同步对比报告")
    lines.append("")
    lines.append(
        f"- 生成时间: {__import__('datetime').datetime.now().isoformat(timespec='seconds')}"
    )
    lines.append(f"- 源码根目录: `{stats['source_root']}`")
    lines.append(f"- 工作目录: `{stats['deployed_root']}`")
    lines.append("")
    lines.append("## 统计")
    lines.append("")
    lines.append(
        f"| 指标 | 数量 |\n|---|---|\n"
        f"| 源码 skills | {stats['source_count']} |\n"
        f"| 工作目录 skills (含归档) | {stats['deployed_total']} |\n"
        f"| 工作目录主部署 (非归档) | {stats['deployed_main']} |\n"
        f"| 同名共有 | {stats['common']} |\n"
        f"| **需要更新 (不一致)** | **{stats['need_update']}** |\n"
        f"| 已一致 | {stats['in_sync']} |\n"
        f"| 工作目录独有 (源码无) | {stats['deployed_only']} |\n"
        f"| 源码独有 (工作目录无) | {stats['source_only']} |\n"
        f"| 归档区同名副本 (参考) | {stats['archived']} |\n"
    )
    lines.append("")

    lines.append("## 需要更新（工作目录与源码不一致）")
    lines.append("")
    if not need_update:
        lines.append("_无_")
    for v in need_update:
        lines.append(f"### {v.name}")
        lines.append("")
        for sp in v.source_paths:
            lines.append(f"- 源码: `{sp}`")
        for dp in v.deployed_paths:
            lines.append(f"- 工作目录: `{dp}`")
        if v.missing:
            lines.append(f"- 缺失 (源码有、工作目录无): {len(v.missing)} 个文件")
            for rel in v.missing:
                lines.append(f"  - `{rel}`")
        if v.differs:
            lines.append(f"- 内容不同: {len(v.differs)} 个文件")
            for rel in v.differs:
                sp0, dp0 = v.source_paths[0], v.deployed_paths[0]
                lines.append(
                    f"  - `{rel}`  [{direction(sp0, dp0, rel)}]"
                    f" (源码 {line_count(sp0 / rel)} 行 | 工作目录 {line_count(dp0 / rel)} 行)"
                )
        if v.extra:
            lines.append(f"- 工作目录多出 (源码无): {len(v.extra)} 个文件")
            for rel in v.extra[:10]:
                lines.append(f"  - `{rel}`")
            if len(v.extra) > 10:
                lines.append(f"  - ... 共 {len(v.extra)} 个")
        lines.append("")

    lines.append("## 归档区同名副本（仅供参考，不计入主结果）")
    lines.append("")
    if not archived:
        lines.append("_无_")
    for v in archived:
        status = "一致" if not (v.missing or v.differs) else "不一致"
        lines.append(f"- `{v.name}` ({status})")
        for dp in v.deployed_paths:
            lines.append(f"  - `{dp}`")

    lines.append("## 已一致（无需更新）")
    lines.append("")
    lines.append(", ".join(in_sync) if in_sync else "_无_")
    lines.append("")

    lines.append("## 工作目录独有（源码中没有，非缺失项）")
    lines.append("")
    lines.append(", ".join(sorted(deployed_only)) if deployed_only else "_无_")
    lines.append("")

    lines.append("## 源码独有（工作目录中缺失，需要补充）")
    lines.append("")
    lines.append(", ".join(sorted(source_only)) if source_only else "_无_")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--deployed", type=Path, default=DEFAULT_DEPLOYED)
    parser.add_argument("--out", type=Path, help="Write the markdown report to FILE.")
    parser.add_argument("--json", action="store_true", help="Emit JSON to stdout.")
    args = parser.parse_args(argv)

    source_root: Path = args.source.resolve()
    deployed_root: Path = args.deployed.resolve()
    for p in (source_root, deployed_root):
        if not p.is_dir():
            print(f"error: directory does not exist: {p}", file=sys.stderr)
            return 2

    src_idx = index_skills(source_root)
    dep_all = index_skills(deployed_root)  # every deployed skill incl. .archive

    # split deployed into main (non-archived) vs archived copies
    dep_main: dict[str, list[Path]] = {}
    dep_arch: dict[str, list[Path]] = {}
    for name, entries in dep_all.items():
        for sdir, top in entries:
            (dep_arch if top in ARCHIVE_TOPS else dep_main).setdefault(name, []).append(sdir)

    src_paths_of = {name: [p for p, _ in entries] for name, entries in src_idx.items()}

    common_main = sorted(set(src_paths_of) & set(dep_main))
    need_update: list[SkillDiff] = []
    in_sync: list[str] = []
    for name in common_main:
        v = aggregate(name, src_paths_of[name], dep_main[name])
        if v.missing or v.differs:
            need_update.append(v)
        else:
            in_sync.append(name)

    archived: list[SkillDiff] = []
    for name in sorted(set(src_paths_of) & set(dep_arch)):
        v = aggregate(name, src_paths_of[name], dep_arch[name])
        archived.append(v)

    deployed_only = sorted(set(dep_main) - set(src_paths_of))
    source_only = sorted(set(src_paths_of) - set(dep_all))

    stats = {
        "source_root": str(source_root),
        "deployed_root": str(deployed_root),
        "source_count": len(src_paths_of),
        "deployed_total": len(dep_all),
        "deployed_main": len(dep_main),
        "common": len(common_main),
        "need_update": len(need_update),
        "in_sync": len(in_sync),
        "deployed_only": len(deployed_only),
        "source_only": len(source_only),
        "archived": len(archived),
    }

    # ---- console summary ----
    print("=" * 70)
    print(f"source:   {source_root}  ({stats['source_count']} skills)")
    print(f"deployed: {deployed_root}  ({stats['deployed_main']} main + {len(dep_arch)} archived dirs)")
    print(f"common:   {stats['common']} | need update: {stats['need_update']} | in sync: {stats['in_sync']}")
    print(f"deployed-only: {stats['deployed_only']} | source-only: {stats['source_only']} | archived copies: {stats['archived']}")
    print("=" * 70)
    if need_update:
        print("\n[NEED UPDATE]")
        for v in need_update:
            detail = []
            if v.missing:
                detail.append(f"missing {len(v.missing)}")
            if v.differs:
                detail.append(f"differs {len(v.differs)}")
            if v.extra:
                detail.append(f"extra {len(v.extra)}")
            print(f"  ■ {v.name}  ({', '.join(detail)})")
            for dp in v.deployed_paths:
                print(f"      -> {dp}")
            for rel in v.missing:
                print(f"         - MISSING {rel}")
            for rel in v.differs:
                sp0, dp0 = v.source_paths[0], v.deployed_paths[0]
                print(f"         ~ {rel}  [{direction(sp0, dp0, rel)}]")
    if in_sync:
        print(f"\n[IN SYNC] {', '.join(in_sync)}")
    if deployed_only:
        print(f"\n[DEPLOYED ONLY] {', '.join(deployed_only)}")
    if source_only:
        print(f"\n[SOURCE ONLY] {', '.join(source_only)}")
    if archived:
        for v in archived:
            tag = "in-sync" if not (v.missing or v.differs) else "OUTDATED"
            print(f"\n[ARCHIVED {tag}] {v.name}")

    if args.out:
        report = render_markdown(
            need_update, archived, in_sync, deployed_only, source_only, stats
        )
        args.out.write_text(report, encoding="utf-8")
        print(f"\nreport written to {args.out.resolve()}")

    if args.json:
        payload = {
            "stats": stats,
            "need_update": [
                {
                    "name": v.name,
                    "source": [str(p) for p in v.source_paths],
                    "deployed": [str(p) for p in v.deployed_paths],
                    "missing": v.missing,
                    "differs": v.differs,
                    "extra": v.extra,
                }
                for v in need_update
            ],
            "in_sync": in_sync,
            "deployed_only": deployed_only,
            "source_only": source_only,
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
