#!/usr/bin/env python3
"""扫描 todo 目录，输出所有非 done 文件的待办摘要。"""
import os
import re
from datetime import datetime, date, timedelta

TODO_DIR = os.path.expanduser("~/projects/obsidian/todo")

def parse_todo_file(filepath: str) -> dict:
    """解析一个 todo 文件，返回 {date_str, items: [{text, done}]}"""
    basename = os.path.basename(filepath)
    date_str = basename.replace(".md", "")
    items = []
    with open(filepath) as f:
        for line in f:
            m = re.match(r'^\s*-\s+\[([ xX])\]\s+(.+)$', line)
            if m:
                done = m.group(1).lower() == 'x'
                text = m.group(2).strip()
                items.append({"text": text, "done": done})
    return {"date": date_str, "items": items}

def get_undone_files(todo_dir: str) -> list:
    """获取所有非 -done.md 的 todo 文件，按日期倒序排列"""
    if not os.path.isdir(todo_dir):
        return []
    files = []
    for fname in os.listdir(todo_dir):
        if not fname.endswith(".md"):
            continue
        # 跳过 -done.md 和 todo-list.md（旧入口）
        if fname.endswith("-done.md") or fname == "todo-list.md":
            continue
        # 只匹配 YYYY-MM-DD.md 格式
        if not re.match(r'^\d{4}-\d{2}-\d{2}\.md$', fname):
            continue
        filepath = os.path.join(todo_dir, fname)
        files.append(filepath)
    # 按日期倒序（最新的在前面）
    files.sort(key=lambda p: os.path.basename(p), reverse=True)
    return files

def main():
    files = get_undone_files(TODO_DIR)
    if not files:
        print("ALL_DONE")
        return

    output_parts = []
    for filepath in files:
        data = parse_todo_file(filepath)
        if not data["items"]:
            continue
        total = len(data["items"])
        done_count = sum(1 for i in data["items"] if i["done"])
        pending = total - done_count

        # 格式化的日期显示
        date_obj = datetime.strptime(data["date"], "%Y-%m-%d").date()
        today = date.today()
        if date_obj == today:
            date_label = f"📋 今天 ({data['date']})"
        elif date_obj == today - timedelta(days=1):
            date_label = f"📋 昨天 ({data['date']})"
        else:
            weekday = date_obj.strftime("%A")
            date_label = f"📋 {data['date']} ({weekday})"

        # 如果该日期所有项都已完成，跳过（虽然理论上不会有 -done.md 以外的全完成文件，但以防万一）
        if pending == 0:
            continue

        status = f"{pending} 项待办"
        output_parts.append(f"## {date_label} — {status}")
        for item in data["items"]:
            if not item["done"]:
                output_parts.append(f"- [ ] {item['text']}")
        output_parts.append("")

    if output_parts:
        print("\n".join(output_parts).strip())
    else:
        print("ALL_DONE")

if __name__ == "__main__":
    main()
