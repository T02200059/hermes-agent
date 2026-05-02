#!/usr/bin/env python3
"""
precompute-skills-usage.py — 一次性 Seed 脚本

扫描历史会话文件，提取「用户第一条消息 → 调用过的 skill」映射，
输出为 JSONL 格式的 TF-IDF 训练索引。

位置：~/.local/share/hermes/skills-usage-index.jsonl
参考格式：~/.local/share/hermes/token-stats.jsonl（同目录 JSONL 先例）

用法：
    python scripts/precompute-skills-usage.py
    # 可选覆盖路径：
    python scripts/precompute-skills-usage.py --sessions ~/.hermes/sessions --output ~/.local/share/hermes/skills-usage-index.jsonl
"""

import json
import glob
import os
import sys
import argparse
from collections import OrderedDict
from datetime import datetime


def extract_first_user_message(messages):
    """返回会话中第一条 role='user' 的消息文本。"""
    for msg in messages:
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, str):
                return content.strip()
            if isinstance(content, list):
                texts = [
                    p.get("text", "")
                    for p in content
                    if isinstance(p, dict) and p.get("type") == "text"
                ]
                return " ".join(texts).strip()
    return ""


def extract_skill_view_calls(messages):
    """
    提取所有通过 skill_view 工具调用加载过的 skill 名称。

    匹配模式：
        tool_calls → function.name == "skill_view"
        → function.arguments == {"name": "...", ...}

    也兼容 function.name 包含 skill_view 的其他变体。
    """
    skills = set()
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function", {})
            name = fn.get("name", "")
            if name.lower() == "skill_view":
                try:
                    args_raw = fn.get("arguments", "{}")
                    args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
                    if isinstance(args, dict):
                        sname = args.get("name", "").strip()
                        if sname:
                            skills.add(sname)
                except (json.JSONDecodeError, TypeError):
                    continue
    return skills


def parse_timestamp(ts_str):
    """尝试解析多种时间戳格式，返回可比较的 datetime 或 None。"""
    if not ts_str:
        return None
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(ts_str[:26], fmt)
        except (ValueError, IndexError):
            continue
    return None


def build_index(sessions_dir, output_path, max_records=5000):
    """
    扫描会话文件，构建去重后的 msg→skills 映射，写入 JSONL。

    去重策略：相同 msg 文本 → 合并 skills 集合 + 保留最新时间戳。
    """
    pattern = os.path.join(sessions_dir, "session_*.json")
    files = sorted(glob.glob(pattern))
    print(f"Found {len(files)} session files in {sessions_dir}")

    # 时间/会话范围追踪
    earliest_ts = None
    latest_ts = None
    earliest_session = None
    latest_session = None

    # OrderedDict 保持首次出现的顺序
    index = OrderedDict()
    scanned = 0
    skipped_no_msg = 0
    skipped_no_skills = 0
    skipped_error = 0

    for fpath in files:
        basename = os.path.basename(fpath)

        # 读取 JSON
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                session = json.load(f)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
            print(f"  WARN: skipping {basename}: {e}")
            skipped_error += 1
            continue

        # 类型检查
        if not isinstance(session, dict):
            print(f"  WARN: skipping {basename}: root is not a dict")
            skipped_error += 1
            continue

        messages = session.get("messages", [])
        if not isinstance(messages, list):
            print(f"  WARN: skipping {basename}: messages is not a list")
            skipped_error += 1
            continue

        # 提取第一条用户消息
        first_msg = extract_first_user_message(messages)
        if not first_msg:
            skipped_no_msg += 1
            continue

        # 提取 skill_view 调用
        skills = extract_skill_view_calls(messages)
        if not skills:
            skipped_no_skills += 1
            continue

        # 提取元信息
        ts = session.get("session_start", "") or session.get("created_at", "")
        model = session.get("model", "")
        session_id = session.get("session_id", "")

        # 追踪时间/会话范围
        ts_dt = parse_timestamp(ts)
        if ts_dt:
            if earliest_ts is None or ts_dt < earliest_ts:
                earliest_ts = ts_dt
                earliest_session = basename
            if latest_ts is None or ts_dt > latest_ts:
                latest_ts = ts_dt
                latest_session = basename

        # 去重：相同 msg 合并 skills，保留最新 ts
        if first_msg in index:
            existing = index[first_msg]
            existing["skills"].update(skills)
            if ts:
                existing_ts = parse_timestamp(existing["ts"])
                current_ts = parse_timestamp(ts)
                if current_ts and (not existing_ts or current_ts > existing_ts):
                    existing["ts"] = ts
            if model and not existing["model"]:
                existing["model"] = model
        else:
            index[first_msg] = {
                "msg": first_msg,
                "skills": skills,
                "ts": ts,
                "model": model,
            }

        scanned += 1

    # 限制记录数
    if len(index) > max_records:
        # 保留最后 max_records 条（按会话文件顺序，即时间顺序）
        items = list(index.items())
        items = items[-max_records:]
        index = OrderedDict(items)

    # 写出 JSONL
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fout:
        for record in index.values():
            line = json.dumps(
                {
                    "msg": record["msg"],
                    "skills": sorted(record["skills"]),
                    "ts": record["ts"],
                    "model": record["model"],
                },
                ensure_ascii=False,
            )
            fout.write(line + "\n")

    # 统计
    total_skill_occurrences = sum(len(r["skills"]) for r in index.values())
    unique_skills = set()
    for r in index.values():
        unique_skills.update(r["skills"])

    # 格式化时间范围
    ts_fmt = lambda dt: dt.strftime("%Y-%m-%d %H:%M:%S") if dt else "N/A"
    time_range = f"{ts_fmt(earliest_ts)} ~ {ts_fmt(latest_ts)}"
    session_range = f"{earliest_session or 'N/A'} ~ {latest_session or 'N/A'}"

    # 写出元数据 companion 文件
    meta_path = os.path.splitext(output_path)[0] + ".meta.json"
    meta = {
        "build_time": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "session_count": scanned,
        "total_files": len(files),
        "unique_patterns": len(index),
        "unique_skills": len(unique_skills),
        "total_skill_occurrences": total_skill_occurrences,
        "earliest_timestamp": ts_fmt(earliest_ts),
        "latest_timestamp": ts_fmt(latest_ts),
        "earliest_session_file": earliest_session or "",
        "latest_session_file": latest_session or "",
        "max_records": max_records,
    }
    with open(meta_path, "w", encoding="utf-8") as fmeta:
        json.dump(meta, fmeta, indent=2, ensure_ascii=False)
        fmeta.write("\n")

    print()
    print(f"{'Scanned (had both msg + skills):':30s} {scanned}")
    print(f"{'Skipped (no user message):':30s} {skipped_no_msg}")
    print(f"{'Skipped (no skill_view calls):':30s} {skipped_no_skills}")
    print(f"{'Skipped (JSON/IO errors):':30s} {skipped_error}")
    print(f"{'─' * 50}")
    print(f"{'Time range:':30s} {time_range}")
    print(f"{'Session range:':30s} {session_range}")
    print(f"{'Unique patterns written:':30s} {len(index)}")
    print(f"{'Total skill occurrences:':30s} {total_skill_occurrences}")
    print(f"{'Unique skills found:':30s} {len(unique_skills)}")
    print(f"{'Output file:':30s} {output_path}")
    print(f"{'Meta file:':30s} {meta_path}")

    return len(index)


def main():
    parser = argparse.ArgumentParser(
        description="Pre-compute skills usage index from Hermes session files"
    )
    parser.add_argument(
        "--sessions",
        default=os.path.expanduser("~/.hermes/sessions"),
        help="Directory containing session_*.json files (default: ~/.hermes/sessions)",
    )
    parser.add_argument(
        "--output",
        default=os.path.expanduser("~/.local/share/hermes/skills-usage-index.jsonl"),
        help="Output JSONL path (default: ~/.local/share/hermes/skills-usage-index.jsonl)",
    )
    parser.add_argument(
        "--max-records",
        type=int,
        default=5000,
        help="Max unique records to keep (default: 5000)",
    )
    args = parser.parse_args()

    if not os.path.isdir(args.sessions):
        print(f"ERROR: sessions directory not found: {args.sessions}", file=sys.stderr)
        sys.exit(1)

    count = build_index(args.sessions, args.output, args.max_records)
    if count > 0:
        print(f"\nDone. Run with tfidf_filter.enabled=true in config.yaml to activate.")
    else:
        print("\nNo valid entries found. Check sessions directory path.")
        sys.exit(1)


if __name__ == "__main__":
    main()
