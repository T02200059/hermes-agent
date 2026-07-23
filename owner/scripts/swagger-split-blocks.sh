#!/usr/bin/env bash
# swagger-split-blocks.sh
# 将 starryshore-manager 的 handler 按模块分块，输出 blocks.json
# 用法: ./swagger-split-blocks.sh [--days N]
set -o pipefail

PROJECT="/Users/yangtb/workspace/westcloud/damodel/starryshore-manager"
HANDLER_DIR="biz/handler"
ROUTER_FILE="biz/router/group_router.go"
OUTPUT_DIR="${SWAGGER_WS:-/Users/yangtb/.hermes/kanban/workspaces/swagger-check}"
DAYS=2

while [[ $# -gt 0 ]]; do
    case $1 in
        --days) DAYS="$2"; shift 2 ;;
        *) shift ;;
    esac
done

cd "$PROJECT" || { echo "❌ 项目目录不存在"; exit 1; }

SINCE=$(date -v-${DAYS}d +%Y-%m-%d 2>/dev/null || date -d "${DAYS} days ago" +%Y-%m-%d)

python3 - "$PROJECT" "$HANDLER_DIR" "$ROUTER_FILE" "$SINCE" "$OUTPUT_DIR" << 'PYEOF'
import json, os, subprocess, sys
from pathlib import Path
from collections import defaultdict

project, handler_dir, router_file, since, output_dir = sys.argv[1:6]

blocks_def = {
    "customer": ["customer"],
    "resource_manager": ["resource_manager"],
    "storage": ["storage"],
    "user": ["user"],
    "other": ["bill", "coupon", "marketing", "ops", "order", "export",
              "ticket", "wallet", "image", "maas", "recharge", "statistics", "oplog"],
}

all_handlers = []
for root, dirs, files in os.walk(os.path.join(project, handler_dir)):
    for f in files:
        if f.endswith(".go") and not f.endswith("_test.go"):
            rel = os.path.relpath(os.path.join(root, f), project)
            all_handlers.append(rel)

block_files = defaultdict(list)
for f in all_handlers:
    parts = f.split("/")
    module = parts[2] if len(parts) >= 3 else "other"
    assigned = False
    for block_name, prefixes in blocks_def.items():
        if module in prefixes:
            block_files[block_name].append(f)
            assigned = True
            break
    if not assigned:
        block_files["other"].append(f)

changed = set()
try:
    result = subprocess.run(
        ["git", "log", f"--since={since}", "--name-only", "--pretty=format:", "--", handler_dir],
        capture_output=True, text=True, cwd=project
    )
    for line in result.stdout.strip().split("\n"):
        line = line.strip()
        if line and line.endswith(".go") and not line.endswith("_test.go"):
            changed.add(line)
except:
    pass

router_content = Path(os.path.join(project, router_file)).read_text(encoding="utf-8")

def extract_route_snippet(block_name):
    func_names = {
        "customer": ["CustomerRegister"],
        "resource_manager": ["NodeRegister", "InstanceRegister", "GPUSpecRegister", "ClusterRegister"],
        "storage": ["StorageRegister"],
        "user": ["UserRegister", "AuthRegister"],
        "other": ["OrderRegister", "CouponRegister", "MarketingRegister", "OpsRegister",
                  "TicketRegister", "WalletRegister", "ImageRegister", "MaasRegister",
                  "RechargeRegister", "StatisticsRegister", "ExportRegister", "OpLogRegister"],
    }
    names = func_names.get(block_name, [])
    snippets = []
    lines = router_content.split("\n")
    for func_name in names:
        in_func = False
        brace_count = 0
        snippet_lines = []
        for line in lines:
            if f"func {func_name}(" in line:
                in_func = True
                brace_count = 0
            if in_func:
                snippet_lines.append(line)
                brace_count += line.count("{") - line.count("}")
                if brace_count == 0 and snippet_lines:
                    snippets.append("\n".join(snippet_lines))
                    in_func = False
                    snippet_lines = []
    return "\n\n".join(snippets)

output_blocks = []
for block_name in ["customer", "resource_manager", "storage", "user", "other"]:
    files = sorted(block_files.get(block_name, []))
    block_changed = [f for f in files if f in changed]
    route_snippet = extract_route_snippet(block_name)
    output_blocks.append({
        "name": block_name,
        "handlers": files,
        "handler_count": len(files),
        "route_snippet": route_snippet,
        "changed_files": block_changed,
        "has_changes": len(block_changed) > 0,
    })

output = {
    "project": project,
    "since": since,
    "total_handlers": len(all_handlers),
    "total_changed": len(changed),
    "blocks": output_blocks,
}

Path(output_dir).mkdir(parents=True, exist_ok=True)
Path(os.path.join(output_dir, "blocks.json")).write_text(
    json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
)

print(f"## 分块结果")
print(f"- 项目: {project}")
print(f"- 时间: {since} ~ 今天")
print(f"- 总 handler: {len(all_handlers)}, 变更: {len(changed)}")
print()
for b in output_blocks:
    status = "🔴" if b["has_changes"] else "✅"
    print(f"- **{b['name']}**: {b['handler_count']} 文件 {status}")
    for f in b["changed_files"]:
        print(f"  - {f}")
print()
print(f"输出: {output_dir}/blocks.json")
PYEOF
