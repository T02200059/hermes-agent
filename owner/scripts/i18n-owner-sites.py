#!/usr/bin/env python3
"""列出 owner 在官方文件里新增的 i18n ``t()`` 调用点（T1-4 工作清单）。

背景
----
``t()`` 是上游自带的 i18n 机制，译文放在 ``locales/<lang>.yaml``。上游按
「thin slice」原则只覆盖少量静态消息；owner 把它扩展到了数十个官方文件。
代价不在译文（``locales/zh.yaml`` 是官方认可位置，追加式写入几乎不冲突），
而在**调用点**——``t()`` 嵌在官方函数体内，每次 sync 都会产生冲突块。

本脚本产出 T1-4 的执行清单：每个调用点属于哪一类、以及对应的英文原文与
中文译文（来自 catalog，无需人工转写）。

分类
----
``shared``   该键上游也在用 → 调用点若与上游同形可直接回退为上游写法
``owner``    该键仅 owner 有 → 需回退为英文原文 + 由展示层过滤器中文化
``bare``     调用点形如 ``t(<表达式>)``，首个参数不是字符串字面量 → 需人工看

用法
----
    owner/scripts/i18n-owner-sites.py                # 摘要
    owner/scripts/i18n-owner-sites.py --list         # 逐条清单
    owner/scripts/i18n-owner-sites.py --md <path>    # 写入 Markdown 报告
    owner/scripts/i18n-owner-sites.py --base <ref>   # 换上游参照（默认 upstream/main）
"""

from __future__ import annotations

import argparse
import ast
import pathlib
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

# 官方文件范围：排除 owner 自有代码、测试、前端与虚拟环境
_EXCLUDED_PREFIXES = ("owner/", "tests/", "apps/", "locales/")
_EXCLUDED_PARTS = ("/.git/", "/.venv/", "/venv/", "/node_modules/", "/__pycache__/")


@dataclass
class Site:
    file: str
    line: int
    key: str
    en: str
    zh: str
    kind: str  # shared | owner
    dynamic_args: bool = False
    # 英文原文是否逐字出现在上游文件中。True 表示「owner 在该处的唯一改动
    # 就是把英文串包进了 t()」——回退即恢复上游字节，该冲突块归零。
    pure_wrapping: bool = False


@dataclass
class Report:
    sites: List[Site] = field(default_factory=list)
    bare: List[Tuple[str, int, str]] = field(default_factory=list)
    files_with_t: List[str] = field(default_factory=list)

    @property
    def by_file(self) -> Dict[str, List[Site]]:
        out: Dict[str, List[Site]] = {}
        for site in self.sites:
            out.setdefault(site.file, []).append(site)
        return out


def _flatten(node: object, prefix: str, out: Dict[str, str]) -> None:
    if not isinstance(node, dict):
        return
    for key, value in node.items():
        dotted = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            _flatten(value, dotted, out)
        elif isinstance(value, str):
            out[dotted] = value


def load_catalog(path: pathlib.Path) -> Dict[str, str]:
    if not path.is_file():
        return {}
    try:
        import yaml
    except ImportError:
        return {}
    out: Dict[str, str] = {}
    _flatten(yaml.safe_load(path.read_text(encoding="utf-8")), "", out)
    return out


def git_show(ref: str, path: str) -> Optional[str]:
    proc = subprocess.run(
        ["git", "show", f"{ref}:{path}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    return proc.stdout if proc.returncode == 0 else None


def upstream_catalog_keys(ref: str) -> set[str]:
    """上游官方文件里出现过的 i18n 键。"""
    listing = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", ref],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    ).stdout.split()

    keys: set[str] = set()
    for name in listing:
        if not name.endswith(".py") or name.startswith(_EXCLUDED_PREFIXES):
            continue
        src = git_show(ref, name)
        if not src or "agent.i18n" not in src:
            continue
        keys |= _literal_keys(src)
    return keys


def _literal_keys(source: str) -> set[str]:
    """用 AST 取 ``t("k")`` 这类字面量键（不误伤 ``t(f"...")`` 与 ``obj.t()``）。"""
    keys: set[str] = set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return keys
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Name) and func.id == "t"):
            continue
        if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            keys.add(node.args[0].value)
    return keys


def upstream_string_literals(ref: str) -> set[str]:
    """上游官方 .py 中出现过的全部字符串字面量。

    用于判定某条英文原文是否**逐字**存在于上游——若是，则 owner 在该处的
    唯一改动就是把英文串包进了 ``t()``，回退即恢复上游字节、冲突块归零。

    用 AST 取字面量而非整文件子串：语义精确（不会把注释/文档里的巧合命中
    算进来），且集合查找是 O(1)。跨文件汇总，因为上游会把大文件拆成
    ``run_*.py`` / ``slash_commands_*.py``，字面量未必留在同名文件里。
    """
    listing = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", ref],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    ).stdout.split()

    out: set[str] = set()
    for name in listing:
        if not name.endswith(".py") or name.startswith(_EXCLUDED_PREFIXES):
            continue
        src = git_show(ref, name)
        if not src:
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                out.add(node.value)
    return out


def collect(ref: str, with_pure_wrapping: bool = True) -> Report:
    en_catalog = load_catalog(REPO_ROOT / "locales" / "en.yaml")
    zh_catalog = load_catalog(REPO_ROOT / "locales" / "zh.yaml")
    upstream_keys = upstream_catalog_keys(ref)
    up_literals = upstream_string_literals(ref) if with_pure_wrapping else set()

    report = Report()
    for path in sorted(REPO_ROOT.rglob("*.py")):
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel.startswith(_EXCLUDED_PREFIXES):
            continue
        if any(part in f"/{rel}" for part in _EXCLUDED_PARTS):
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if "agent.i18n" not in source:
            continue
        report.files_with_t.append(rel)

        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Name) and func.id == "t"):
                continue

            first = node.args[0] if node.args else None
            if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
                snippet = ast.get_source_segment(source, first) or "<无参数>"
                report.bare.append((rel, node.lineno, snippet))
                continue

            key = first.value
            kind = "shared" if key in upstream_keys else "owner"
            en_text = en_catalog.get(key, "")
            report.sites.append(
                Site(
                    file=rel,
                    line=node.lineno,
                    key=key,
                    en=en_text,
                    zh=zh_catalog.get(key, ""),
                    kind=kind,
                    dynamic_args=bool(node.keywords),
                    pure_wrapping=bool(en_text) and en_text in up_literals,
                )
            )
    report.sites.sort(key=lambda s: (s.file, s.line))
    report.bare.sort()
    return report


def render_markdown(report: Report, ref: str) -> str:
    by_file = report.by_file
    owner_sites = [s for s in report.sites if s.kind == "owner"]
    shared_sites = [s for s in report.sites if s.kind == "shared"]
    pure = [s for s in owner_sites if s.pure_wrapping]

    lines: List[str] = []
    lines.append("# T1-4 工作清单：官方文件内 owner 新增的 i18n 调用点")
    lines.append("")
    lines.append(
        "> 由 `owner/scripts/i18n-owner-sites.py` 生成（AST 扫描 + catalog 对照）。"
        f"上游参照：`{ref}`。"
    )
    lines.append("")
    lines.append("## 摘要")
    lines.append("")
    lines.append("| 项 | 数量 |")
    lines.append("|---|---|")
    lines.append(f"| 使用官方 `t()` 的官方文件 | {len(report.files_with_t)} |")
    lines.append(f"| `t()` 字面量调用点合计 | {len(report.sites)} |")
    lines.append(f"| 其中键仅 owner 有（需回退为英文 + 展示层翻译） | {len(owner_sites)} |")
    lines.append(
        f"| 其中**英文原文逐字见于上游**（回退即恢复上游字节，冲突块归零） | {len(pure)} |"
    )
    lines.append(
        f"| 其中上游无此文案（owner 自造，回退只减 `t()` 不消冲突） | {len(owner_sites) - len(pure)} |"
    )
    lines.append(f"| 其中键上游也在用（可与上游写法对齐） | {len(shared_sites)} |")
    lines.append(f"| `t()` 首参非字面量（需人工判定） | {len(report.bare)} |")
    lines.append("")
    lines.append("## 分类判据")
    lines.append("")
    lines.append("- **owner 键**：上游没有这个键，说明调用点是 owner 为本地化而加进官方函数体的。")
    lines.append("  回退为英文原文后，中文由 `owner/i18n/display_filter.py` 在展示层完成。")
    lines.append("- **纯包裹**（`pure_wrapping`）：该键的英文原文逐字出现在上游文件中，说明")
    lines.append("  owner 在这一行的唯一改动就是把英文串包进了 `t()`。**回退即与上游逐字节一致，")
    lines.append("  该冲突块归零**——这是 T1-4 收益的主要来源，建议优先做。")
    lines.append("- **自造文案**：上游没有这句话，冲突来自周边代码而非 `t()` 调用。回退仍然")
    lines.append("  应该做（让官方代码不再携带 `t()`，减少后续 sync 的改动面），但不消冲突。")
    lines.append("- **shared 键**：上游也用这个键。若调用点与上游同形，回退即与上游对齐。")
    lines.append("")
    lines.append("## 按文件分布")
    lines.append("")
    lines.append("| 文件 | 调用点 | owner 键 | 其中纯包裹 | shared 键 |")
    lines.append("|---|---|---|---|---|")
    for file in sorted(by_file, key=lambda f: (-len(by_file[f]), f)):
        sites = by_file[file]
        own = [s for s in sites if s.kind == "owner"]
        pure_n = sum(1 for s in own if s.pure_wrapping)
        lines.append(
            f"| `{file}` | {len(sites)} | {len(own)} | {pure_n} | {len(sites) - len(own)} |"
        )
    lines.append("")

    lines.append("## 逐条清单（owner 键）")
    lines.append("")
    lines.append("| 文件:行 | 键 | 类型 | 英文原文（回退目标） | 中文译文（展示层） |")
    lines.append("|---|---|---|---|---|")
    for site in sorted(owner_sites, key=lambda s: (not s.pure_wrapping, s.file, s.line)):
        en = site.en.replace("|", "\\|")
        zh = site.zh.replace("|", "\\|")
        flag = "纯包裹" if site.pure_wrapping else "自造文案"
        lines.append(
            f"| `{site.file}:{site.line}` | `{site.key}` | {flag} | `{en}` | `{zh}` |"
        )
    lines.append("")

    if report.bare:
        lines.append("## 首参非字面量（需人工判定）")
        lines.append("")
        lines.append("| 文件:行 | 表达式 |")
        lines.append("|---|---|")
        for rel, line, snippet in report.bare:
            lines.append(f"| `{rel}:{line}` | `{snippet.replace('|', chr(92) + '|')}` |")
        lines.append("")

    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default="upstream/main", help="上游参照（默认 upstream/main）")
    parser.add_argument("--list", action="store_true", help="逐条列出")
    parser.add_argument("--md", metavar="PATH", help="写入 Markdown 报告")
    args = parser.parse_args(argv)

    report = collect(args.base)

    if args.md:
        out = pathlib.Path(args.md)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render_markdown(report, args.base), encoding="utf-8")
        print(f"[i18n-sites] 已写入 {out}")

    if args.list:
        for site in report.sites:
            flag = "OWNER" if site.kind == "owner" else "share"
            print(f"{flag:5s} {site.file}:{site.line}  {site.key}")
        for rel, line, snippet in report.bare:
            print(f"BARE  {rel}:{line}  {snippet}")

    owner_n = sum(1 for s in report.sites if s.kind == "owner")
    shared_n = len(report.sites) - owner_n
    pure_n = sum(1 for s in report.sites if s.kind == "owner" and s.pure_wrapping)
    print(
        f"[i18n-sites] 文件={len(report.files_with_t)} "
        f"调用点={len(report.sites)} owner键={owner_n}（纯包裹={pure_n}）"
        f" shared键={shared_n} 首参非字面量={len(report.bare)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
