#!/usr/bin/env python3
"""
feishu_weekly_ops.py — 精确读取"运维管理部-部门周会"文档中
"运维管理"标题下表格的指定周列（含所有行）。

文档结构：heading1 "运维管理" → 1个 table (26列×3行)
  Row 0: 周标题（🎯本年度重点工作计划 | 第26周 | 第25周 | ...）
  Row 1: 工作内容
  Row 2: 补充内容（客户售后等）

用法:
  python3 feishu_weekly_ops.py              # 读最新一周（左起第二列，所有行）
  python3 feishu_weekly_ops.py --col 3      # 读左起第三列
  python3 feishu_weekly_ops.py --list       # 列出所有周列
  python3 feishu_weekly_ops.py --dump-json  # 输出表格结构 JSON（调试用）

依赖: requests
凭据: ~/.hermes/.env 中的 FEISHU_APP_ID / FEISHU_APP_SECRET
"""
import argparse
import json
import os
import sys
import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
WIKI_NODE_TOKEN = "XzvFwmRCGiJKHTkY8WBcZaIPnYd"
BASE_URL = "https://open.feishu.cn/open-apis"
ENV_FILE = os.path.expanduser("~/.hermes/.env")
TARGET_HEADING = "运维管理"


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def load_env(path=ENV_FILE):
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def get_token():
    load_env()
    app_id = os.environ.get("FEISHU_APP_ID")
    app_secret = os.environ.get("FEISHU_APP_SECRET")
    if not app_id or not app_secret:
        sys.exit("ERROR: FEISHU_APP_ID / FEISHU_APP_SECRET not set")
    r = requests.post(
        f"{BASE_URL}/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["tenant_access_token"]


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------
def resolve_wiki_node(token, headers):
    r = requests.get(
        f"{BASE_URL}/wiki/v2/spaces/get_node",
        headers=headers, params={"token": token}, timeout=10,
    )
    r.raise_for_status()
    node = r.json()["data"]["node"]
    return node["obj_token"], node["obj_type"]


def fetch_all_blocks(doc_token, headers):
    blocks = []
    page_token = None
    while True:
        params = {"document_id": doc_token, "page_size": 500}
        if page_token:
            params["page_token"] = page_token
        r = requests.get(
            f"{BASE_URL}/docx/v1/documents/{doc_token}/blocks",
            headers=headers, params=params, timeout=30,
        )
        r.raise_for_status()
        data = r.json()["data"]
        blocks.extend(data.get("items", []))
        if not data.get("has_more"):
            break
        page_token = data.get("page_token")
    return blocks


# ---------------------------------------------------------------------------
# Block text extraction
# ---------------------------------------------------------------------------
def get_text(block):
    texts = []
    for v in block.values():
        if isinstance(v, dict) and "elements" in v:
            for el in v["elements"]:
                tr = el.get("text_run")
                if tr:
                    texts.append(tr.get("content", ""))
    return "".join(texts)


def collect_cell_text(by_id, cell_block_id, max_depth=8):
    """Recursively collect all text lines from a table cell."""
    lines = []

    def _walk(bid, depth):
        b = by_id.get(bid)
        if not b or depth > max_depth:
            return
        txt = get_text(b).strip()
        bt = b.get("block_type")
        if txt:
            if bt in (12, 13):  # bullet / ordered list
                lines.append(f"  • {txt}")
            elif bt in (3, 4, 5, 6, 7, 8):  # headings
                lines.append(f"\n## {txt}")
            else:
                lines.append(txt)
        for cid in b.get("children", []):
            _walk(cid, depth + 1)

    _walk(cell_block_id, 0)
    return lines


# ---------------------------------------------------------------------------
# Locate target table
# ---------------------------------------------------------------------------
def find_ops_table(blocks):
    """Find the table (block_type 31) under the '运维管理' heading1.
    Returns (table_block, by_id, column_size, row_size, cells).
    """
    by_id = {b["block_id"]: b for b in blocks}

    heading = None
    for b in blocks:
        if b.get("block_type") == 3 and get_text(b).strip() == TARGET_HEADING:
            heading = b
            break
    if not heading:
        sys.exit(f"ERROR: heading '{TARGET_HEADING}' not found")

    root = by_id[heading["parent_id"]]
    root_children = root.get("children", [])
    idx = root_children.index(heading["block_id"])

    for i in range(idx + 1, len(root_children)):
        b = by_id[root_children[i]]
        if b.get("block_type") == 3:
            break
        if b.get("block_type") == 31:
            table = b.get("table", {})
            prop = table.get("property", {})
            col_size = prop.get("column_size", 0)
            row_size = prop.get("row_size", 0)
            cells = table.get("cells", [])
            return b, by_id, col_size, row_size, cells

    sys.exit("ERROR: no table found under '运维管理'")


def get_column_cells(cells, col_size, col_idx_0based):
    """Get all cell block_ids for a given column (0-based), across all rows."""
    row_count = len(cells) // col_size if col_size else 0
    result = []
    for row in range(row_count):
        cell_idx = row * col_size + col_idx_0based
        if cell_idx < len(cells):
            result.append(cells[cell_idx])
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Read weekly ops column from Feishu weekly meeting doc")
    parser.add_argument("--col", type=int, default=2,
                        help="1-based column index (default: 2 = second from left = latest week)")
    parser.add_argument("--list", action="store_true",
                        help="List all columns with header + content line count")
    parser.add_argument("--dump-json", action="store_true",
                        help="Dump table structure as JSON")
    args = parser.parse_args()

    token = get_token()
    headers = {"Authorization": f"Bearer {token}"}

    obj_token, obj_type = resolve_wiki_node(WIKI_NODE_TOKEN, headers)
    if obj_type != "docx":
        sys.exit(f"ERROR: expected docx, got {obj_type}")

    blocks = fetch_all_blocks(obj_token, headers)
    table, by_id, col_size, row_size, cells = find_ops_table(blocks)

    if args.dump_json:
        print(json.dumps({
            "table_block_id": table["block_id"],
            "column_size": col_size,
            "row_size": row_size,
            "total_cells": len(cells),
            "columns": [
                {
                    "col_1based": c + 1,
                    "cells": get_column_cells(cells, col_size, c),
                    "header": get_text(by_id.get(cells[c], {})).strip() if c < len(cells) else "",
                }
                for c in range(col_size)
            ],
        }, ensure_ascii=False, indent=2))
        return

    if args.list:
        print(f"Table under '{TARGET_HEADING}': {col_size} columns × {row_size} rows\n")
        for c in range(col_size):
            col_cells = get_column_cells(cells, col_size, c)
            header = get_text(by_id.get(col_cells[0], {})).strip() if col_cells else "(empty)"
            total_lines = 0
            for cell_id in col_cells[1:]:  # skip header row
                total_lines += len(collect_cell_text(by_id, cell_id))
            print(f"  col[{c+1:2d}] {header}  ({total_lines} content lines)")
        return

    # Read specific column (all rows)
    col_idx = args.col - 1
    if col_idx < 0 or col_idx >= col_size:
        sys.exit(f"ERROR: column {args.col} out of range (table has {col_size} columns)")

    col_cells = get_column_cells(cells, col_size, col_idx)

    # Row 0 = header
    header = get_text(by_id.get(col_cells[0], {})).strip() if col_cells else ""
    print(f"# {header}\n")

    # Rows 1+ = content
    has_content = False
    for row_idx, cell_id in enumerate(col_cells[1:], start=1):
        lines = collect_cell_text(by_id, cell_id)
        if lines:
            has_content = True
            print(f"--- Row {row_idx} ---")
            print("\n".join(lines))
            print()

    if not has_content:
        print("(no content in this column)")


if __name__ == "__main__":
    main()
