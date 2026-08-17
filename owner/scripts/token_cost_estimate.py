#!/usr/bin/env python3
"""
Hermes 最近 N 天 token 用量 + 按高峰/空闲时段价格估算费用。

数据源: ~/.hermes/state.db (sessions 表)
价格表 (元/百万 tokens, 见价格图):
    输入(缓存未命中): 空闲 1.5 / 高峰 3.0
    输入(缓存命中)  : 空闲 0.05 / 高峰 0.10
    输出            : 空闲 4.5 / 高峰 9.0
高峰时段(北京时间): 9:00-12:00、14:00-18:00，其余为空闲。
计价口径: input_tokens→输入(未命中), cache_read_tokens→输入(命中),
          cache_write_tokens→忽略, output_tokens→输出。
用法:
    python3 token_cost_estimate.py [--days 30] [--model 过滤模型]
    python3 token_cost_estimate.py --assume-ark-cache   # ark 渠道按其他渠道平均命中率重算
"""

import sqlite3
import argparse
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta

DB_PATH = "/Users/yangtb/.hermes/state.db"
BEIJING_TZ = timezone(timedelta(hours=8))

# 价格 (元 / 百万 tokens)
PRICE = {
    "input_miss": {"idle": 1.5, "peak": 3.0},    # 输入(缓存未命中)
    "input_hit":  {"idle": 0.05, "peak": 0.10},  # 输入(缓存命中)
    "output":     {"idle": 4.5, "peak": 9.0},    # 输出
}

PEAK_HOURS = set(range(9, 12)) | set(range(14, 18))  # 北京时间 9-12, 14-18

# ark 套餐渠道模型前缀（这些渠道不返回缓存命中统计，命中率异常为 0）
ARK_PREFIXES = ("ark-agent-plan-", "ark-coding-plan-")


def is_peak(ts: float) -> bool:
    """按北京时间判断该时间戳是否处于高峰时段."""
    dt = datetime.fromtimestamp(ts, BEIJING_TZ)
    return dt.hour in PEAK_HOURS


def compute_non_ark_hit_rate(rows, model_filter=None):
    """计算非 ark 渠道的加权平均命中率 (命中/(命中+未命中))."""
    hit = miss = 0
    for started_at, model, inp, out, cread, cwrite in rows:
        if model.startswith(ARK_PREFIXES):
            continue
        hit += cread or 0
        miss += inp or 0
    total = hit + miss
    if total == 0:
        return None
    return hit / total


def main():
    parser = argparse.ArgumentParser(description="Hermes token 用量 + 费用估算")
    parser.add_argument("--days", type=int, default=30, help="统计近 N 天(默认 30)")
    parser.add_argument("--model", type=str, default=None, help="只统计指定模型")
    parser.add_argument("--assume-ark-cache", action="store_true",
                        help="ark 套餐渠道按其他渠道平均命中率重算缓存命中")
    args = parser.parse_args()

    since_ts = time.time() - args.days * 86400

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    sql = """
        SELECT started_at, model,
               input_tokens, output_tokens,
               cache_read_tokens, cache_write_tokens
        FROM sessions
        WHERE started_at >= ?
          AND (input_tokens > 0 OR output_tokens > 0 OR cache_read_tokens > 0)
    """
    params = [since_ts]
    if args.model:
        sql += " AND model = ?"
        params.append(args.model)
    cur.execute(sql, params)
    rows = cur.fetchall()
    conn.close()

    if not rows:
        print(f"❌ 近 {args.days} 天无 token 数据")
        return

    # ark 渠道按其他渠道平均命中率重算
    ark_rate = None
    if args.assume_ark_cache:
        ark_rate = compute_non_ark_hit_rate(rows)
        if ark_rate is None:
            print("⚠️ 无非 ark 渠道数据，无法计算平均命中率")
            return

    # 汇总
    totals = {"input_miss": 0, "input_hit": 0, "output": 0}
    daily = defaultdict(lambda: defaultdict(int))     # date -> kind -> tokens
    peak_total = {"input_miss": 0, "input_hit": 0, "output": 0}
    idle_total = {"input_miss": 0, "input_hit": 0, "output": 0}
    by_model = defaultdict(lambda: {"input_miss": 0, "input_hit": 0, "output": 0, "sessions": 0})
    session_count = 0

    for started_at, model, inp, out, cread, cwrite in rows:
        inp = inp or 0
        out = out or 0
        cread = cread or 0
        # ark 渠道模型：按平均命中率重算，把部分未命中转为命中（保留高峰/空闲归属）
        if ark_rate is not None and model.startswith(ARK_PREFIXES):
            total_in = inp + cread
            cread = round(total_in * ark_rate)
            inp = total_in - cread
        session_count += 1
        day = datetime.fromtimestamp(started_at, BEIJING_TZ).strftime("%Y-%m-%d")
        pk = is_peak(started_at)

        totals["input_miss"] += inp
        totals["input_hit"] += cread
        totals["output"] += out
        daily[day]["input_miss"] += inp
        daily[day]["input_hit"] += cread
        daily[day]["output"] += out
        target = peak_total if pk else idle_total
        target["input_miss"] += inp
        target["input_hit"] += cread
        target["output"] += out
        bm = by_model[model]
        bm["input_miss"] += inp
        bm["input_hit"] += cread
        bm["output"] += out
        bm["sessions"] += 1

    def cost(kind_total, peak_amt):
        return (kind_total["input_miss"] / 1e6 * PRICE["input_miss"]["idle"]
                + kind_total["input_hit"] / 1e6 * PRICE["input_hit"]["idle"]
                + kind_total["output"] / 1e6 * PRICE["output"]["idle"]
                + peak_amt["input_miss"] / 1e6 * (PRICE["input_miss"]["peak"] - PRICE["input_miss"]["idle"])
                + peak_amt["input_hit"] / 1e6 * (PRICE["input_hit"]["peak"] - PRICE["input_hit"]["idle"])
                + peak_amt["output"] / 1e6 * (PRICE["output"]["peak"] - PRICE["output"]["idle"]))

    total_cost = cost(totals, peak_total)
    hit_rate = (totals["input_hit"] / (totals["input_miss"] + totals["input_hit"]) * 100
                if totals["input_miss"] + totals["input_hit"] else 0)

    n_days = len(daily)
    all_tokens = totals["input_miss"] + totals["input_hit"] + totals["output"]

    print("=" * 60)
    print(f"📅 统计周期: 近 {args.days} 天 | 有数据天数 {n_days} | 会话数 {session_count}"
          + (f" | 模型: {args.model}" if args.model else ""))
    print("=" * 60)

    print("\n📊 Token 用量汇总")
    print(f"  输入(未命中): {totals['input_miss']:>14,}  ({totals['input_miss']/1e6:.2f} M)")
    print(f"  输入(命中):   {totals['input_hit']:>14,}  ({totals['input_hit']/1e6:.2f} M)  [命中率 {hit_rate:.1f}%]")
    print(f"  输出:         {totals['output']:>14,}  ({totals['output']/1e6:.2f} M)")
    print(f"  ─────────────────────────────────")
    print(f"  合计:         {all_tokens:>14,}  ({all_tokens/1e6:.2f} M)")
    print(f"  每日平均:     {all_tokens/n_days:>14,.0f} tokens/天")
    print(f"  (输入均/天: {totals['input_miss']/n_days:,.0f}  命中均/天: {totals['input_hit']/n_days:,.0f}  输出均/天: {totals['output']/n_days:,.0f})")

    print(f"\n⏰ 高峰/空闲分布 (按北京时间会话开始时刻)")
    def fmt(t):
        return (f"未命中 {t['input_miss']/1e6:.2f}M / 命中 {t['input_hit']/1e6:.2f}M / "
                f"输出 {t['output']/1e6:.2f}M")
    print(f"  高峰时段: {fmt(peak_total)}")
    print(f"  空闲时段: {fmt(idle_total)}")

    print("\n🧾 费用估算 (元, 按价格图)")
    print(f"  输入(未命中): ¥{totals['input_miss']/1e6*PRICE['input_miss']['idle'] + peak_total['input_miss']/1e6*(PRICE['input_miss']['peak']-PRICE['input_miss']['idle']):.2f}")
    print(f"  输入(命中):   ¥{totals['input_hit']/1e6*PRICE['input_hit']['idle'] + peak_total['input_hit']/1e6*(PRICE['input_hit']['peak']-PRICE['input_hit']['idle']):.2f}")
    print(f"  输出:         ¥{totals['output']/1e6*PRICE['output']['idle'] + peak_total['output']/1e6*(PRICE['output']['peak']-PRICE['output']['idle']):.2f}")
    print(f"  ─────────────────────────────────")
    print(f"  合计:         ¥{total_cost:.2f}")
    print(f"  每日平均:     ¥{total_cost/n_days:.2f}/天")

    print("\n🏷️ 按模型 (token 占比 ≥1%):")
    grand = all_tokens
    for m, bm in sorted(by_model.items(), key=lambda kv: -(kv[1]["input_miss"]+kv[1]["input_hit"]+kv[1]["output"])):
        m_tok = bm["input_miss"] + bm["input_hit"] + bm["output"]
        pct = m_tok / grand * 100 if grand else 0
        if pct < 1:
            continue
        m_cost = (bm["input_miss"]/1e6*PRICE["input_miss"]["idle"]
                  + bm["input_hit"]/1e6*PRICE["input_hit"]["idle"]
                  + bm["output"]/1e6*PRICE["output"]["idle"])
        print(f"  {m}: {m_tok/1e6:6.1f}M ({pct:4.1f}%)  未命中{bm['input_miss']/1e6:.1f}M/命中{bm['input_hit']/1e6:.1f}M/输出{bm['output']/1e6:.1f}M  基础价¥{m_cost:.2f}")

    print("\n📌 价格口径: 输入未命中 1.5/3.0 元·M, 输入命中 0.05/0.10 元·M, 输出 4.5/9.0 元·M (空闲/高峰)")
    print(f"📌 高峰时段: 北京时间 9:00-12:00、14:00-18:00 (按会话开始时刻归属)")


if __name__ == "__main__":
    main()
