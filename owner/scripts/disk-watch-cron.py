#!/usr/bin/env python3
"""
磁盘空间监控包装脚本 — 给 cron job 使用
执行 cache-cleanup.py --disk-watch，仅在空间不足时输出告警消息供 cron 投递。
"""
import json
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).parent.resolve()
MAIN_SCRIPT = BASE / "mac" / "cache-cleanup.py"

r = subprocess.run(
    [sys.executable, str(MAIN_SCRIPT), "--disk-watch"],
    capture_output=True, text=True, timeout=30
)

if r.returncode != 0:
    print(f"❌ 脚本执行失败:\n{r.stderr[:500]}")
    sys.exit(1)

try:
    result = json.loads(r.stdout)
except json.JSONDecodeError as e:
    print(f"❌ JSON 解析失败: {e}\n输出前200字符: {r.stdout[:200]}")
    sys.exit(1)

if result.get("alert") and result.get("message"):
    print(result["message"])
    sys.exit(0)
else:
    # 空间充足，静默退出 — cron 无输出则不投递
    sys.exit(0)
