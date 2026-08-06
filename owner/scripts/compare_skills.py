#!/usr/bin/env python3
"""对比 hermes-agent 源码目录 skills/ 与用户真实 skills 目录的整体差异。

用法:
    python3 compare_skills.py [--src DIR] [--usr DIR] [--verbose]

默认:
    --src ~/.hermes/hermes-agent/skills   (源码仓库自带)
    --usr ~/.hermes/skills                (真实加载目录)

输出分四段:
    [A] 仅源码有 (bundled 但未出现在用户目录)
    [B] 仅用户目录有 (自装/第三方/自建)
    [C] 两边都有且内容一致
    [D] 两边都有但内容不同 (列出差异文件)
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

SKIP_DIRS = {".archive", ".hub", ".curator_backups", ".merge-backup-20260715", "node_modules", ".git"}


def discover_skills(root: Path) -> dict[str, list[Path]]:
    """找 root 下所有含 SKILL.md 的目录 (深度<=3, 跳过隐藏/无关目录)。
    返回 {叶子目录名: [路径, ...]} (同名多份时保留全部)。"""
    found: dict[str, list[Path]] = {}
    if not root.is_dir():
        return found
    for skill_md in sorted(root.rglob("SKILL.md")):
        rel = skill_md.relative_to(root)
        if len(rel.parts) > 3:  # skills/<category>/<name>/SKILL.md 最多 3 段
            continue
        if any(p.startswith(".") or p in SKIP_DIRS for p in rel.parts):
            continue
        d = skill_md.parent
        found.setdefault(d.name, []).append(d)
    return found


def file_hashes(d: Path) -> dict[str, str]:
    """目录内所有文件的相对路径 -> sha256 (跳过隐藏文件/目录)。"""
    out: dict[str, str] = {}
    for f in sorted(d.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(d)
        if any(p.startswith(".") or p in SKIP_DIRS for p in rel.parts):
            continue
        out[str(rel)] = hashlib.sha256(f.read_bytes()).hexdigest()
    return out


def diff_dirs(a: Path, b: Path) -> tuple[list[str], list[str], list[str]]:
    """返回 (仅a有, 仅b有, 内容不同) 的相对路径列表。"""
    ha, hb = file_hashes(a), file_hashes(b)
    only_a = sorted(set(ha) - set(hb))
    only_b = sorted(set(hb) - set(ha))
    changed = sorted(k for k in set(ha) & set(hb) if ha[k] != hb[k])
    return only_a, only_b, changed


def rel_of(p: Path, root: Path) -> str:
    try:
        return str(p.relative_to(root))
    except ValueError:
        return str(p)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", default="~/.hermes/hermes-agent/skills")
    ap.add_argument("--usr", default="~/.hermes/skills")
    ap.add_argument("--verbose", action="store_true", help="一致段也列出路径")
    args = ap.parse_args()

    src_root = Path(args.src).expanduser()
    usr_root = Path(args.usr).expanduser()
    src = discover_skills(src_root)
    usr = discover_skills(usr_root)

    only_src = sorted(set(src) - set(usr))
    only_usr = sorted(set(usr) - set(src))
    both = sorted(set(src) & set(usr))

    same, differ = [], []
    for name in both:
        # 同名多份时两两比, 任一对一致算一致
        pairs = [(a, b) for a in src[name] for b in usr[name]]
        best = None
        for a, b in pairs:
            d = diff_dirs(a, b)
            if not any(d):
                best = None
                break
            if best is None or sum(map(len, d)) < sum(map(len, best[2])):
                best = (a, b, d)
        if best is None:
            same.append(name)
        else:
            differ.append((name, best))

    w = sys.stdout.write
    w(f"源码目录: {src_root}  ({sum(len(v) for v in src.values())} 个 skill)\n")
    w(f"用户目录: {usr_root}  ({sum(len(v) for v in usr.values())} 个 skill)\n")
    w(f"同名: {len(both)} | 仅源码: {len(only_src)} | 仅用户: {len(only_usr)}\n\n")

    w(f"[A] 仅源码有 ({len(only_src)})\n")
    for n in only_src:
        for p in src[n]:
            w(f"  {rel_of(p, src_root)}\n")
    w("\n")

    w(f"[B] 仅用户目录有 ({len(only_usr)})\n")
    for n in only_usr:
        for p in usr[n]:
            w(f"  {rel_of(p, usr_root)}\n")
    w("\n")

    w(f"[C] 两边都有且一致 ({len(same)})\n")
    for n in same:
        if args.verbose:
            w(f"  {n}\n")
        else:
            w(f"  {n}")
    if not args.verbose:
        w("\n")
    w("\n")

    w(f"[D] 两边都有但内容不同 ({len(differ)})\n")
    for n, (a, b, (only_a, only_b, changed)) in differ:
        w(f"  {n}\n")
        w(f"    src: {rel_of(a, src_root)}\n")
        w(f"    usr: {rel_of(b, usr_root)}\n")
        for f in only_a:
            w(f"    - 仅源码有: {f}\n")
        for f in only_b:
            w(f"    + 仅用户有: {f}\n")
        for f in changed:
            w(f"    ~ 内容不同: {f}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
