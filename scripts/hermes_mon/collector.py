#!/usr/bin/env python3
"""
Hermes 性能监控采集器 — 按小时分片写入 CSV

用 launchd 每 10 秒运行一次（one-shot），采集当前所有 hermes 进程的
CPU/MEM/RSS/VSZ 指标，追加到当前小时对应的 CSV 文件中。

文件结构: ~/.hermes/local/hermes_mon/raw/hermes_YYYYMMDD_HH.csv

零竞态设计：采集只写当前小时的文件，聚合脚本只处理已过小时的"已关闭"文件。
"""

import csv
import os
import subprocess
import sys
import time

DATA_DIR = os.path.expanduser("~/.hermes/local/hermes_mon/raw")


def get_hermes_pids():
    """通过 pgrep -f 查找所有含 hermes 的进程 PID"""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "hermes"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if not result.stdout.strip():
            return []
        return [int(p) for p in result.stdout.strip().split("\n") if p.strip()]
    except (subprocess.TimeoutExpired, ValueError, OSError) as e:
        print(f"[collector] pgrep error: {e}", file=sys.stderr)
        return []


def get_process_stats(pid):
    """获取单进程的 CPU%, MEM%, RSS(KB), VSZ(KB)"""
    try:
        result = subprocess.run(
            [
                "ps", "-p", str(pid),
                "-o", "%cpu=,%mem=,rss=,vsz=",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        parts = result.stdout.strip().split()
        if len(parts) >= 4:
            return {
                "pid": pid,
                "cpu_pct": float(parts[0]),
                "mem_pct": float(parts[1]),
                "rss_kb": int(parts[2]),
                "vsz_kb": int(parts[3]),
            }
    except (subprocess.TimeoutExpired, ValueError, IndexError, OSError) as e:
        print(f"[collector] ps error for pid {pid}: {e}", file=sys.stderr)
    return None


def current_hour_file():
    """返回当前小时对应的 CSV 路径，如 hermes_20260503_14.csv"""
    t = time.localtime()
    filename = f"hermes_{t.tm_year}{t.tm_mon:02d}{t.tm_mday:02d}_{t.tm_hour:02d}.csv"
    return os.path.join(DATA_DIR, filename)


def main():
    os.makedirs(DATA_DIR, exist_ok=True)

    now = int(time.time())
    pids = get_hermes_pids()
    filepath = current_hour_file()

    file_exists = os.path.isfile(filepath)

    with open(filepath, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["ts", "pid", "cpu_pct", "mem_pct", "rss_kb", "vsz_kb"])

        for pid in pids:
            stats = get_process_stats(pid)
            if stats:
                writer.writerow([
                    now,
                    stats["pid"],
                    stats["cpu_pct"],
                    stats["mem_pct"],
                    stats["rss_kb"],
                    stats["vsz_kb"],
                ])


if __name__ == "__main__":
    main()
