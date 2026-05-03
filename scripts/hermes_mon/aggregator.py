#!/usr/bin/env python3
"""
Hermes 性能数据聚合/截断器 — 每小时运行一次

职责：
1. 处理已关闭的 raw 小时文件（当前小时之前的）→ 聚合到小时级统计
2. 超过 24h 的 raw 文件删除（节约空间）
3. 超过 30 天的小时级数据 → 进一步聚合到天级

零竞态设计：只处理"已关闭"的小时文件（当前小时永远不会被处理），
采集器和聚合器永远不会同时写同一个文件。
"""

import csv
import glob
import os
import statistics
import sys
import time

# ---- 配置 ----
RAW_DIR = os.path.expanduser("~/.local/share/hermes/mon/raw")
HOUR_DIR = os.path.expanduser("~/.local/share/hermes/mon/hourly")
DAY_DIR = os.path.expanduser("~/.local/share/hermes/mon/daily")

RAW_RETENTION_HOURS = 24       # 原始秒级数据保留 24 小时
HOUR_RETENTION_DAYS = 30       # 小时聚合数据保留 30 天
# ----------------


def _hour_start(path: str) -> int:
    """从 raw 文件名解析小时起始时间戳。

    >>> _hour_start('hermes_20260503_14.csv')
    1746280800  # 2026-05-03 14:00:00
    """
    base = os.path.basename(path).replace(".csv", "")
    parts = base.split("_")
    if len(parts) >= 3:
        try:
            date_str = parts[-2]
            hour_str = parts[-1]
            y, mo, d = int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8])
            h = int(hour_str)
            return int(time.mktime((y, mo, d, h, 0, 0, 0, 0, 0)))
        except (ValueError, IndexError, OSError):
            pass
    return 0


def _aggregate(rows: list[dict]) -> dict:
    """对一组数据行做聚合统计（均值 / 最大 / 最小）。"""
    cpu = [r["cpu_pct"] for r in rows]
    mem = [r["mem_pct"] for r in rows]
    rss = [r["rss_kb"] for r in rows]
    vsz = [r["vsz_kb"] for r in rows]
    return {
        "avg_cpu": round(statistics.mean(cpu), 2),
        "max_cpu": round(max(cpu), 2),
        "min_cpu": round(min(cpu), 2),
        "avg_mem": round(statistics.mean(mem), 2),
        "max_mem": round(max(mem), 2),
        "min_mem": round(min(mem), 2),
        "avg_rss": int(statistics.mean(rss)),
        "max_rss": max(rss),
        "min_rss": min(rss),
        "avg_vsz": int(statistics.mean(vsz)),
        "sample_count": len(rows),
    }


def _get_processed_hours() -> set[int]:
    """读取已有 hourly 文件，返回已聚合过的小时时间戳集合。"""
    processed: set[int] = set()
    if not os.path.isdir(HOUR_DIR):
        return processed
    for fname in os.listdir(HOUR_DIR):
        if not fname.startswith("hourly_") or not fname.endswith(".csv"):
            continue
        ts = _hour_start(fname.replace("hourly_", "", 1))
        if ts > 0:
            processed.add(ts)
    return processed


def process_raw_files():
    """处理所有已关闭（past hour）的 raw CSV 文件。"""
    now = time.time()
    # 当前小时的起始时间戳 — 之前的文件才被视为"已关闭"
    current_hour = int(now // 3600) * 3600
    cutoff = current_hour - RAW_RETENTION_HOURS * 3600  # 24h 前的 cutoff

    # 读取已聚合的小时集合，避免重复写入
    processed_hours = _get_processed_hours()
    if processed_hours:
        print(f"[aggregator] 已聚合小时数: {len(processed_hours)}，跳过重复处理")

    files = sorted(glob.glob(os.path.join(RAW_DIR, "hermes_*.csv")))

    for fp in files:
        ts = _hour_start(fp)
        if ts <= 0 or ts >= current_hour:
            continue  # 跳过当前小时及无法解析的文件

        # 如果该小时已聚合过，跳过处理（但仍执行超期清理）
        if ts in processed_hours:
            if ts < cutoff:
                os.remove(fp)
            continue

        try:
            with open(fp, "r") as f:
                reader = csv.DictReader(f)
                rows = [r for r in reader]

            if not rows:
                os.remove(fp)
                continue

            # 类型转换
            for r in rows:
                r["cpu_pct"] = float(r["cpu_pct"])
                r["mem_pct"] = float(r["mem_pct"])
                r["rss_kb"] = int(r["rss_kb"])
                r["vsz_kb"] = int(r["vsz_kb"])

            agg = _aggregate(rows)

            # 写入小时级聚合
            hour_file = os.path.join(HOUR_DIR, f"hourly_{os.path.basename(fp)}")
            write_header = not os.path.isfile(hour_file)
            with open(hour_file, "a", newline="") as f:
                w = csv.writer(f)
                if write_header:
                    w.writerow([
                        "hour_ts", "avg_cpu", "max_cpu", "min_cpu",
                        "avg_mem", "max_mem", "min_mem",
                        "avg_rss", "max_rss", "min_rss",
                        "avg_vsz", "sample_count",
                    ])
                w.writerow([
                    ts, agg["avg_cpu"], agg["max_cpu"], agg["min_cpu"],
                    agg["avg_mem"], agg["max_mem"], agg["min_mem"],
                    agg["avg_rss"], agg["max_rss"], agg["min_rss"],
                    agg["avg_vsz"], agg["sample_count"],
                ])

            # 超过 24h 的 raw 文件删除
            if ts < cutoff:
                os.remove(fp)

            print(f"[aggregator] 已聚合: {os.path.basename(fp)} → {agg['sample_count']} 采样点")

        except Exception as e:
            print(f"[aggregator] 处理 {fp} 失败: {e}", file=sys.stderr)


def process_hourly_files():
    """将超过 30 天的小时级数据聚合到天级后删除。"""
    now = time.time()
    cutoff = now - HOUR_RETENTION_DAYS * 86400

    files = sorted(glob.glob(os.path.join(HOUR_DIR, "hourly_*.csv")))

    for fp in files:
        ts = _hour_start(fp.replace("hourly_", "", 1))
        if ts <= 0 or ts >= cutoff:
            continue

        try:
            with open(fp, "r") as f:
                reader = csv.DictReader(f)
                rows = [r for r in reader]

            if not rows:
                os.remove(fp)
                continue

            # 按天分组
            groups: dict[int, list] = {}
            for r in rows:
                day_ts = int(float(r["hour_ts"]) // 86400) * 86400
                groups.setdefault(day_ts, []).append(r)

            day_file = os.path.join(DAY_DIR, "daily.csv")
            write_header = not os.path.isfile(day_file)
            with open(day_file, "a", newline="") as f:
                w = csv.writer(f)
                if write_header:
                    w.writerow([
                        "day_ts", "avg_cpu", "max_cpu", "min_cpu",
                        "avg_mem", "max_mem", "min_mem",
                        "avg_rss", "max_rss", "min_rss",
                        "avg_vsz", "total_samples",
                    ])

                for day_ts in sorted(groups):
                    grp = groups[day_ts]
                    w.writerow([
                        day_ts,
                        round(statistics.mean(float(r["avg_cpu"]) for r in grp), 2),
                        max(float(r["max_cpu"]) for r in grp),
                        min(float(r["min_cpu"]) for r in grp),
                        round(statistics.mean(float(r["avg_mem"]) for r in grp), 2),
                        max(float(r["max_mem"]) for r in grp),
                        min(float(r["min_mem"]) for r in grp),
                        int(statistics.mean(float(r["avg_rss"]) for r in grp)),
                        max(float(r["max_rss"]) for r in grp),
                        min(float(r["min_rss"]) for r in grp),
                        int(statistics.mean(float(r["avg_vsz"]) for r in grp)),
                        sum(int(r["sample_count"]) for r in grp),
                    ])

            os.remove(fp)
            print(f"[aggregator] 已归档天级: {os.path.basename(fp)}")

        except Exception as e:
            print(f"[aggregator] 处理 {fp} 失败: {e}", file=sys.stderr)


def main():
    os.makedirs(HOUR_DIR, exist_ok=True)
    os.makedirs(DAY_DIR, exist_ok=True)
    process_raw_files()
    process_hourly_files()
    print("[aggregator] 完成")


if __name__ == "__main__":
    main()
