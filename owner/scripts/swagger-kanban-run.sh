#!/usr/bin/env bash
# swagger-kanban-run.sh
# Swagger 完整性检查 kanban 流水线启动器
#
# 用法:
#   swagger-kanban-run.sh scan     # T0→T1→T2→T3 全流程
#   swagger-kanban-run.sh fix      # 只建 T4 自修复卡（依赖已有 T3）
#   swagger-kanban-run.sh review   # 建 T4 人工门闩卡：worker 整理清单后 block 等人审
#   swagger-kanban-run.sh status   # 查看当前任务状态
set -euo pipefail

WS_DIR="${SWAGGER_WS:-/Users/yangtb/.hermes/kanban/workspaces/swagger-check}"
TPL_DIR="${WS_DIR}/templates"
TENANT="${SWAGGER_TENANT:-swagger-check}"
ASSIGNEE="${SWAGGER_ASSIGNEE:-swagger-checker}"
DATE_TAG="$(date +%Y%m%d)"
IDEM_PREFIX="swagger-check"

MODE="scan"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --mode) MODE="$2"; shift 2 ;;
        *) MODE="$1"; shift ;;
    esac
done

mkdir -p "$WS_DIR"

render() {
    local file="$1"
    shift
    local text
    text="$(cat "$file")"
    text="${text//\{\{WORKSPACE\}\}/$WS_DIR}"
    while [[ $# -gt 0 ]]; do
        local key="${1%%=*}"
        local val="${1#*=}"
        text="${text//\{\{$key\}\}/$val}"
        shift
    done
    echo "$text"
}

create_card() {
    local title="$1"
    local body="$2"
    local idem="$3"
    local max_rt="${4:-30m}"
    shift 4 || true

    local -a create_args=(
        kanban create "$title"
        --assignee "$ASSIGNEE"
        --workspace "dir:${WS_DIR}"
        --tenant "$TENANT"
        --priority 20
        --max-runtime "$max_rt"
        --idempotency-key "$idem"
        --body "$body"
        --json
    )
    local a
    for a in "$@"; do
        if [[ "$a" == parent:* ]]; then
            create_args+=(--parent "${a#parent:}")
        fi
    done
    hermes "${create_args[@]}" 2>/dev/null | python3 -c '
import sys, json
raw = sys.stdin.read()
i = raw.find("{")
if i < 0:
    print("ERROR", raw[:200], file=sys.stderr)
    sys.exit(1)
d = json.loads(raw[i:], strict=False)
print(d.get("id",""), d.get("status",""), (d.get("title") or "")[:60])
'
}

cmd_scan() {
    # T0: 分块脚本卡
    local t0_body="运行分块脚本：\n\`\`\`bash\nbash ~/.hermes/scripts/swagger-split-blocks.sh --days 2\n\`\`\`\n\n输出 blocks.json 到 ${WS_DIR}/blocks.json"
    local idem0="${IDEM_PREFIX}-split-${DATE_TAG}"
    local t0_out t0_id
    t0_out="$(create_card "swagger-split: 分块 ${DATE_TAG}" "$t0_body" "$idem0" "10m" || true)"
    t0_id="$(echo "$t0_out" | awk '{print $1}')"
    echo "T0 (split): ${t0_id:-FAILED}"

    # T1 + T2: 每个分块一对卡
    local -a t1_ids=()
    local -a t2_ids=()
    local blocks=("customer" "resource_manager" "storage" "user" "other")

    for block in "${blocks[@]}"; do
        local t1_body t1_out t1_id
        t1_body="$(render "${TPL_DIR}/T1-block-check.md" "BLOCK_NAME=$block")"
        t1_out="$(create_card "swagger-check: ${block} ${DATE_TAG}" "$t1_body" "${IDEM_PREFIX}-check-${block}-${DATE_TAG}" "30m" "parent:${t0_id}" || true)"
        t1_id="$(echo "$t1_out" | awk '{print $1}')"
        t1_ids+=("$t1_id")

        local t2_body t2_out t2_id
        t2_body="$(render "${TPL_DIR}/T2-block-verify.md" "BLOCK_NAME=$block")"
        t2_out="$(create_card "swagger-verify: ${block} ${DATE_TAG}" "$t2_body" "${IDEM_PREFIX}-verify-${block}-${DATE_TAG}" "30m" "parent:${t1_id}" || true)"
        t2_id="$(echo "$t2_out" | awk '{print $1}')"
        t2_ids+=("$t2_id")
    done

    # T3: 汇总报告卡
    local t3_body t3_out t3_id
    t3_body="$(render "${TPL_DIR}/T3-final-report.md")"
    local -a t3_parents=()
    for t2_id in "${t2_ids[@]}"; do
        t3_parents+=("parent:${t2_id}")
    done
    t3_out="$(create_card "swagger-report: 最终报告 ${DATE_TAG}" "$t3_body" "${IDEM_PREFIX}-report-${DATE_TAG}" "15m" "${t3_parents[@]}" || true)"
    t3_id="$(echo "$t3_out" | awk '{print $1}')"
    echo "T3 (report): ${t3_id:-FAILED}"

    # T4: 自修复卡（T3 子卡，T3 完成后自动执行）
    local t4_body t4_out t4_id
    t4_body="$(render "${TPL_DIR}/T4-fix.md")"
    local idem4="${IDEM_PREFIX}-fix-${DATE_TAG}"
    t4_out="$(create_card "swagger-fix: 自修复 ${DATE_TAG}" "$t4_body" "$idem4" "30m" "parent:${t3_id}" || true)"
    t4_id="$(echo "$t4_out" | awk '{print $1}')"
    echo "T4 (fix): ${t4_id:-FAILED}"

    hermes kanban dispatch >/dev/null 2>&1 || true

    echo ""
    echo "═══════════════════════════════════════════════"
    echo "  Swagger 检查+自修复流水线已创建"
    echo "  Assignee: ${ASSIGNEE}"
    echo "═══════════════════════════════════════════════"
    echo "T0 → T1a-e → T2a-e → T3 → T4(fix)"
    echo "报告: ${WS_DIR}/t3-final-report.md"
    echo "修复结果: ${WS_DIR}/t4-fix-result.json"
}

cmd_fix() {
    local t3_report="${WS_DIR}/t3-final-report.md"
    if [[ ! -f "$t3_report" ]]; then
        echo "ERROR: T3 报告不存在: $t3_report"
        echo "请先运行 scan 模式"
        exit 1
    fi

    local t4_body t4_out t4_id
    t4_body="$(render "${TPL_DIR}/T4-fix.md")"
    local idem4="${IDEM_PREFIX}-fix-${DATE_TAG}"
    t4_out="$(create_card "swagger-fix: 自修复 ${DATE_TAG}" "$t4_body" "$idem4" "30m" || true)"
    t4_id="$(echo "$t4_out" | awk '{print $1}')"
    echo "T4 (fix): ${t4_id:-FAILED}"

    hermes kanban dispatch >/dev/null 2>&1 || true
    echo ""
    echo "自修复卡已创建，完成后查看: ${WS_DIR}/t4-fix-result.json"
}

cmd_review() {
    # T4: 人工门闩卡——worker 读 T3 报告整理审核清单后 block 等人审
    local t3_report="${WS_DIR}/t3-final-report.md"
    if [[ ! -f "$t3_report" ]]; then
        echo "ERROR: T3 报告不存在: $t3_report"
        echo "请先运行 scan 模式"
        exit 1
    fi

    # 从报告解析 CONFIRMED 数量（兼容表格行"16 处 CONFIRMED"与统计行"CONFIRMED: 11"）
    local n
    n="$(python3 - "$t3_report" <<'PY'
import re, sys
from pathlib import Path
txt = Path(sys.argv[1]).read_text(encoding="utf-8")
m = re.search(r'(\d+)\s*处\s*CONFIRMED', txt)
if not m:
    m = re.search(r'CONFIRMED[:：]\s*(\d+)', txt)
print(m.group(1) if m else "0")
PY
)"
    n="${n:-0}"
    if [[ "${n}" -le 0 ]]; then
        echo "【swagger 人审】T3 报告中无 CONFIRMED 问题，不建审核卡。"
        echo "报告：${t3_report}"
        exit 0
    fi

    local t4_body t4_out t4_id
    t4_body="$(render "${TPL_DIR}/T4-review.md")"
    t4_out="$(create_card "swagger-review: 人工门闩 ${DATE_TAG}" "$t4_body" "${IDEM_PREFIX}-review-${DATE_TAG}" "30m" || true)"
    t4_id="$(echo "$t4_out" | awk '{print $1}')"

    hermes kanban dispatch >/dev/null 2>&1 || true

    echo ""
    echo "═══════════════════════════════════════════════"
    echo "  swagger 人审卡已创建（${n} 处 CONFIRMED）"
    echo "  Assignee: ${ASSIGNEE}"
    echo "═══════════════════════════════════════════════"
    echo "task: ${t4_id:-FAILED}"
    echo "worker 会读 T3 报告整理中文清单后 block 等人审；"
    echo "审批：评论写 FIX=1 + 范围（如\"只修 error\"），再解阻。"
    echo "清单: ${WS_DIR}/t3-review-queue.md"
}

cmd_status() {
    hermes kanban list --assignee "$ASSIGNEE" --tenant "$TENANT" 2>/dev/null | head -20
    echo "--- workspace ---"
    ls -la "$WS_DIR"/*.json "$WS_DIR"/*.md 2>/dev/null | head -15
}

case "$MODE" in
    scan|daily) cmd_scan ;;
    fix) cmd_fix ;;
    review|human-review) cmd_review ;;
    status) cmd_status ;;
    *) echo "Unknown mode: $MODE (scan|fix|review|status)" >&2; exit 1 ;;
esac
