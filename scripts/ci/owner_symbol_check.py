#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""owner 侧 CI 冒烟：换码宿主符号级验证（T2-20 A5 固化）。

方法（fb6b4c07d1 确立、A5-2 固化为 CI 步骤）：
  AST walk 换码宿主（gateway/run*.py + platforms/base.py/event.py）的
  **全部** from-import（含函数体内的惰性 import —— 顶层 sweep 的盲区，
  A5-2 曾由此抓出第 9/10/11 起前移未落盘）→ 逐符号 hasattr 实测，
  `from P import M` 的 M 为子模块时做形态感知 → 报告缺口。

退出码：有缺口 ⇒ 1（CI 挡板）。
"""
import ast
import importlib
import sys
from pathlib import Path

REPO = Path.home() / ".hermes" / "hermes-agent"
HOSTS = sorted((REPO / "gateway").glob("run*.py")) + [
    REPO / "gateway" / "platforms" / "base.py",
    REPO / "gateway" / "platforms" / "event.py",
]
OPTIONAL_MODULES = {"mutagen", "msvcrt", "aiohttp_socks"}

# cwd 切到仓库，保证 repo 顶层模块（hermes_constants 等）可解析
import os
os.chdir(REPO)
sys.path.insert(0, str(REPO))

missing = []
checked = 0
for host in HOSTS:
    tree = ast.parse(host.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            if node.module.split(".")[0] in OPTIONAL_MODULES:
                continue
            try:
                mod = importlib.import_module(node.module)
            except Exception as exc:
                # 「from P import M」的 M 可能是子模块：先试 import P.M
                sub_ok = False
                for alias in node.names:
                    try:
                        importlib.import_module(f"{node.module}.{alias.name}")
                        sub_ok = True
                        break
                    except Exception:
                        pass
                if sub_ok:
                    mod = importlib.import_module(node.module)
                else:
                    missing.append((str(host.relative_to(REPO)), node.module, f"<module> ({exc})"))
                    continue
            for alias in node.names:
                checked += 1
                if alias.name == "*":
                    continue
                if not hasattr(mod, alias.name):
                    # 子模块形态：from P import M（M 是 P 的子模块）
                    try:
                        importlib.import_module(f"{node.module}.{alias.name}")
                        continue
                    except Exception:
                        pass
                    missing.append((str(host.relative_to(REPO)), node.module, alias.name))

print(f"[info] 扫描 {len(HOSTS)} 个换码宿主，实测 {checked} 个符号")
if missing:
    print(f"[FAIL] {len(missing)} 个符号缺口:")
    for f, m, s in missing:
        print(f"    {f}: from {m} import {s}")
    sys.exit(1)
print("[ok] 换码宿主 from-import 符号级零缺口")
