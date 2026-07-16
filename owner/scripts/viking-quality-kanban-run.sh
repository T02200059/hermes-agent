#!/usr/bin/env bash
# viking-quality-kanban-run.sh
#
# Template launcher for OpenViking memory-quality Kanban pipeline.
# Cron-friendly: --no-agent script mode prints a short status line.
#
# Usage:
#   viking-quality-kanban-run.sh scan              # 建 T1；worker 只串行 fan-out T2+T3（不建 T4）
#   viking-quality-kanban-run.sh apply             # 从既有 plan 建 T2b+T3b APPLY + T4-verify（非偏好）
#   viking-quality-kanban-run.sh pref              # 只扫偏好候选 JSON（不建看板）
#   viking-quality-kanban-run.sh pref-card         # 用户明确要求时：从 report/扫描建 T4 人审卡
#   viking-quality-kanban-run.sh status            # list viking-quality tasks
#
# Daily cron (noon, no-agent → QQ):
#   args: {"mode":"scan"}   # MUST be scan, not apply
#   流水线边界：T1 → T2 翻译 → T3 去重；T4 偏好人审仅手动 pref-card
#
# Env overrides:
#   VIKING_WS, VIKING_TENANT, VIKING_ASSIGNEE, VIKING_THRESHOLD, VIKING_IDEM_PREFIX
#   VIKING_PREF_LIMIT, VIKING_INCLUDE_ENGLISH (1/0, default 1)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WS_DIR="${VIKING_WS:-/Users/yangtb/.hermes/kanban/workspaces/viking-quality}"
TPL_DIR="${WS_DIR}/templates"
TENANT="${VIKING_TENANT:-viking-quality}"
ASSIGNEE="${VIKING_ASSIGNEE:-viking-curator}"
THRESHOLD="${VIKING_THRESHOLD:-0.85}"
# tier3 偏好人审每轮条数上限（T1 扫描与人审卡共用）
PREF_LIMIT="${VIKING_PREF_LIMIT:-10}"
# tier1 是否包含英文等非中文（默认开）
INCLUDE_ENGLISH="${VIKING_INCLUDE_ENGLISH:-1}"
WORKSPACE_SPEC="dir:${WS_DIR}"
DATE_TAG="$(date +%Y%m%d)"
IDEM_PREFIX="${VIKING_IDEM_PREFIX:-viking-quality}"
MODE="scan"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode)
      MODE="$2"
      shift 2
      ;;
    *)
      break
      ;;
  esac
done
if [[ "$MODE" == "scan" && -n "${1:-}" ]]; then
  MODE="$1"
  shift || true
fi

mkdir -p "$WS_DIR" "$TPL_DIR"

render() {
  # render template placeholders via python (multiline-safe)
  local file="$1"
  python3 - "$file" "${TPL_DIR}/00-global.md" "$THRESHOLD" "$PREF_LIMIT" \
    "${WS_DIR}/report.json" \
    "${WS_DIR}/translate-plan.json" \
    "${WS_DIR}/merge-plan-dry-run.md" <<'PY'
import sys
from pathlib import Path
path, global_path, threshold, pref_limit, report, tplan, mplan = sys.argv[1:8]
text = Path(path).read_text(encoding="utf-8")
global_txt = Path(global_path).read_text(encoding="utf-8")
for k, v in {
    "{{GLOBAL}}": global_txt,
    "{{THRESHOLD}}": threshold,
    "{{PREF_LIMIT}}": pref_limit,
    "{{REPORT_PATH}}": report,
    "{{TRANSLATE_PLAN_PATH}}": tplan,
    "{{MERGE_PLAN_PATH}}": mplan,
}.items():
    text = text.replace(k, v)
sys.stdout.write(text)
PY
}

create_card() {
  local title="$1"
  local body_file="$2"
  local idem="$3"
  local max_rt="${4:-45m}"
  shift 4 || true
  # remaining: optional args "parent:ID"
  local -a create_args=(
    kanban create "$title"
    --assignee "$ASSIGNEE"
    --workspace "$WORKSPACE_SPEC"
    --tenant "$TENANT"
    --priority 20
    --max-runtime "$max_rt"
    --idempotency-key "$idem"
    --body "$(cat "$body_file")"
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
    print("ERROR create failed:", raw[:300], file=sys.stderr)
    sys.exit(1)
# tolerate control chars in body echo
d = json.loads(raw[i:], strict=False)
print(d.get("id",""), d.get("status",""), (d.get("title") or "")[:60])
'
}

cmd_scan() {
  local body
  body="$(mktemp)"
  render "${TPL_DIR}/T1-scan.md" >"$body"
  local idem="${IDEM_PREFIX}-scan-${DATE_TAG}"
  local out tid st title
  out="$(create_card \
    "viking-scan: OpenViking quality ${DATE_TAG}" \
    "$body" \
    "$idem" \
    "30m" || true)"
  rm -f "$body"
  tid="$(echo "$out" | awk '{print $1}')"
  st="$(echo "$out" | awk '{print $2}')"
  title="$(echo "$out" | cut -d' ' -f3-)"

  hermes kanban dispatch >/dev/null 2>&1 || true

  local board_file report_file
  board_file="$(mktemp)"
  hermes kanban list --assignee "$ASSIGNEE" 2>/dev/null | head -25 >"$board_file" || true
  report_file="${WS_DIR}/report.json"

  # 中文摘要：cron --no-agent 会把 stdout 原文投递到 QQ
  python3 - "$tid" "$st" "$title" "$idem" "$ASSIGNEE" "$WS_DIR" "$report_file" "$board_file" <<'PY'
import json, sys
from pathlib import Path
tid, st, title, idem, assignee, ws, report_path, board_path = sys.argv[1:9]

st_map = {
    "ready": "就绪",
    "running": "执行中",
    "todo": "等待前置",
    "blocked": "阻塞(待人工)",
    "done": "已完成",
}
st_cn = st_map.get((st or "").lower(), st or "未知")

lines = []
lines.append("【OpenViking 记忆质量巡检】")
if not tid or str(tid).startswith("ERROR"):
    lines.append("⚠️ 扫描卡创建失败，请检查 gateway / viking-curator。")
    if title:
        lines.append(f"详情：{title}")
else:
    lines.append(f"扫描卡：{tid}（{st_cn}）")
    if title:
        lines.append(f"标题：{title}")
    lines.append(f"执行角色：{assignee}")

rp = Path(report_path)
if rp.is_file():
    try:
        d = json.loads(rp.read_text(encoding="utf-8"))
        s = d.get("summary") or {}
        inv = d.get("inventory") or {}
        t1 = (d.get("tier1") or {}).get("flagged")
        if t1 is None:
            t1 = s.get("non_chinese_count")
        t2 = (d.get("tier2") or {}).get("pairs")
        if t2 is None:
            t2 = s.get("similar_pairs_count")
        t2d = (d.get("tier2") or {}).get("deferred_for_translate")
        if t2d is None:
            t2d = s.get("similar_pairs_deferred_translate_count")
        t3 = (d.get("tier3") or {}).get("candidates")
        if t3 is None:
            t3 = s.get("preference_candidate_count")
        lines.append(
            f"上一份报告快照：共 {inv.get('total_files')} 条，"
            f"镜像 {inv.get('exact_mirrors_marked')}，"
            f"待译 {t1}，待去重 {t2}（延后 {t2d}），偏好候选 {t3}"
        )
        if d.get("scan_time"):
            lines.append(f"报告时间：{d.get('scan_time')}")
    except Exception as e:
        lines.append(f"上一份报告：无法解析（{e}）")
else:
    lines.append("上一份报告：尚无（本轮扫描由看板异步跑完后才会更新）")

lines.append("流水线：扫描 → 翻译 → 去重（串行）")
lines.append(
    "本轮不自动开偏好人审（T4）。"
    "若报告里偏好候选 > 0，需你明确说「走偏好审核」后再触发。"
)
lines.append(
    "说明：定时任务只负责建 T1 并触发调度；"
    "翻译/去重由 viking-curator 在看板串行执行；T4 需手动。"
)

board = Path(board_path).read_text(encoding="utf-8", errors="replace") if Path(board_path).is_file() else ""
open_lines = [ln for ln in board.splitlines() if ln.strip() and not ln.strip().startswith("✓")]
if open_lines:
    lines.append("当前未完成卡：")
    for ln in open_lines[:6]:
        lines.append("· " + ln.strip()[:100])

print("\n".join(lines))
PY
  rm -f "$board_file"
}

cmd_apply() {
  local tplan="${WS_DIR}/translate-plan.json"
  local mplan="${WS_DIR}/merge-plan-dry-run.md"
  if [[ ! -f "$tplan" ]]; then
    echo "ERROR: missing $tplan — run scan+dry-run first" >&2
    exit 2
  fi
  if [[ ! -f "$mplan" ]]; then
    echo "ERROR: missing $mplan — run scan+dry-run first" >&2
    exit 2
  fi

  local b2 b3 b4
  b2="$(mktemp)"; b3="$(mktemp)"; b4="$(mktemp)"
  render "${TPL_DIR}/T2b-translate-apply.md" >"$b2"
  render "${TPL_DIR}/T3b-merge-apply.md" >"$b3"
  render "${TPL_DIR}/T4-verify.md" >"$b4"

  local idem_t="${IDEM_PREFIX}-apply-translate-${DATE_TAG}"
  local idem_m="${IDEM_PREFIX}-apply-merge-${DATE_TAG}"
  local idem_v="${IDEM_PREFIX}-verify-${DATE_TAG}"

  echo "Creating APPLY translate + merge + verify ..."
  local tr mg
  tr="$(create_card "viking-apply-translate: APPLY=1 ${DATE_TAG}" "$b2" "$idem_t" "45m")"
  mg="$(create_card "viking-apply-merge: APPLY=1 ${DATE_TAG}" "$b3" "$idem_m" "45m")"
  local tr_id mg_id
  tr_id="$(echo "$tr" | awk '{print $1}')"
  mg_id="$(echo "$mg" | awk '{print $1}')"

  if [[ -z "$tr_id" || -z "$mg_id" ]]; then
    echo "ERROR: failed to parse apply card ids: tr=[$tr] mg=[$mg]" >&2
    exit 3
  fi

  local vf
  vf="$(create_card "viking-verify: after APPLY ${DATE_TAG}" "$b4" "$idem_v" "30m" \
    "parent:${tr_id}" "parent:${mg_id}")"

  # If verify came back ready without waiting (parent race), block until parents done
  local vf_id
  vf_id="$(echo "$vf" | awk '{print $1}')"
  if [[ -n "$vf_id" ]]; then
    hermes kanban link "$tr_id" "$vf_id" 2>/dev/null || true
    hermes kanban link "$mg_id" "$vf_id" 2>/dev/null || true
  fi

  rm -f "$b2" "$b3" "$b4"
  hermes kanban dispatch >/dev/null 2>&1 || true
  echo "translate: $tr"
  echo "merge:     $mg"
  echo "verify:    $vf"
}

cmd_status() {
  hermes kanban list --assignee "$ASSIGNEE" 2>/dev/null | rg "viking-|${TENANT}" || \
    hermes kanban list --assignee "$ASSIGNEE" 2>/dev/null | head -20
  echo "--- workspace ---"
  ls -la "$WS_DIR" | head -30
}

cmd_pref() {
  # Layer-3: preference / hard-claim scan; optional --tag-n N to mark samples reviewed
  local limit="${VIKING_PREF_LIMIT:-20}"
  local tag_n=0
  local dry=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --limit) limit="$2"; shift 2 ;;
      --tag-n) tag_n="$2"; shift 2 ;;
      --dry-run) dry="--dry-run"; shift ;;
      *) shift ;;
    esac
  done
  local out="${WS_DIR}/pref-candidates.json"
  python3 "${SCRIPT_DIR}/viking-quality-pref-review.py" scan \
    --limit "$limit" --output "$out"
  if [[ "$tag_n" -gt 0 ]]; then
    python3 "${SCRIPT_DIR}/viking-quality-pref-review.py" tag-sample \
      --n "$tag_n" $dry --output "${WS_DIR}/pref-tag-trial.json"
  fi
  # Short human summary for QQ / cron
  python3 - "$out" <<'PY'
import json, sys
from pathlib import Path
d = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print("📋 OpenViking 偏好/事实审核候选（L3）")
print(f"扫描 preferences: {d.get('scanned_files')}  已 human_reviewed 跳过: {d.get('skipped_human_reviewed')}")
print(f"候选: {d.get('candidate_count')}（limit 内）")
for c in (d.get("candidates") or [])[:8]:
    flags = ",".join(c.get("flags") or [])
    print(f"  [{c.get('score')}] {flags}  {c.get('rel')}")
print("tag: human_reviewed=1（无 TTL）+ human_reviewed_at=<datetime>")
print(f"报告: {sys.argv[1]}")
print("说明：本模式只产出 JSON，不建看板。要开门闩请用: pref-card")
PY
}

cmd_pref_card() {
  # Manual gate only: create T4 pref-review kanban card (never from daily cron).
  local report="${WS_DIR}/report.json"
  local limit="${PREF_LIMIT}"
  local parent_id=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --limit) limit="$2"; shift 2 ;;
      --parent) parent_id="$2"; shift 2 ;;
      --report) report="$2"; shift 2 ;;
      *) shift ;;
    esac
  done

  if [[ ! -f "$report" ]]; then
    echo "ERROR: 缺少报告 $report — 请先跑 scan 或 pipeline" >&2
    exit 2
  fi

  local n
  n="$(python3 - "$report" <<'PY'
import json, sys
from pathlib import Path
d = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
t3 = d.get("tier3") or {}
c = t3.get("candidates")
if c is None:
    c = (d.get("summary") or {}).get("preference_candidate_count")
if c is None:
    items = t3.get("items") or (d.get("preferences") or {}).get("candidates") or []
    c = len(items)
print(int(c or 0))
PY
)"

  if [[ "${n}" -le 0 ]]; then
    echo "【偏好人审】报告中无 tier3 候选（或为 0），不建 T4。"
    echo "报告：${report}"
    exit 0
  fi

  local body
  body="$(mktemp)"
  render "${TPL_DIR}/T4-pref-review.md" >"$body"
  # 在 body 末尾注明来源，避免 worker 误以为每日自动
  {
    echo ""
    echo "## 触发说明"
    echo "- **手动** pref-card（非每日 cron）"
    echo "- 报告：\`${report}\`"
    echo "- 候选条数（报告）：${n}（limit={{PREF_LIMIT}} 已在模板中）"
  } | sed "s|{{PREF_LIMIT}}|${limit}|g" >>"$body"

  local idem="${IDEM_PREFIX}-pref-review-${DATE_TAG}"
  local out tid st title
  if [[ -n "$parent_id" ]]; then
    out="$(create_card \
      "viking-pref-review: 人工门闩 ${DATE_TAG}（最多 ${limit} 条）" \
      "$body" \
      "$idem" \
      "45m" \
      "parent:${parent_id}" || true)"
  else
    out="$(create_card \
      "viking-pref-review: 人工门闩 ${DATE_TAG}（最多 ${limit} 条）" \
      "$body" \
      "$idem" \
      "45m" || true)"
  fi
  rm -f "$body"
  tid="$(echo "$out" | awk '{print $1}')"
  st="$(echo "$out" | awk '{print $2}')"
  title="$(echo "$out" | cut -d' ' -f3-)"

  hermes kanban dispatch >/dev/null 2>&1 || true

  echo "【偏好人审 T4 已手动创建】"
  echo "task: ${tid:-?}  status: ${st:-?}  ${title}"
  echo "候选约 ${n} 条（上限 ${limit}）；worker 写完中文队列后会 block 等人审。"
  echo "报告：${report}"
}

case "$MODE" in
  scan|daily)
    cmd_scan
    ;;
  apply)
    cmd_apply
    ;;
  pref|preferences|pref-review)
    cmd_pref "$@"
    ;;
  pref-card|t4|pref_card)
    cmd_pref_card "$@"
    ;;
  status)
    cmd_status
    ;;
  help|-h|--help)
    sed -n '1,45p' "$0"
    ;;
  *)
    echo "Unknown mode: $MODE (scan|apply|pref|pref-card|status)" >&2
    exit 1
    ;;
esac
