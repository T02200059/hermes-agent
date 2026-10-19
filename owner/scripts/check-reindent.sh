#!/usr/bin/env bash
# hermes-agent「整段缩进/搬迁」类改动检出（T3-20）
#
# 目的：
#   `git diff` 对「整段重排缩进」或「代码块搬迁」会产生海量噪声行，
#   审查者容易在噪声里漏掉夹带的语义改动。`git diff -w`（忽略空白）
#   能把纯缩进变化折叠为零行——两相对比即可回答：
#     * 某文件/某提交是「纯搬迁」（-w 后无 diff）
#     * 还是「搬迁 + 夹带改动」（-w 后仍有 diff，须逐行审）
#
# 用法：
#   owner/scripts/check-reindent.sh <base> [head]        # 对比区间
#   owner/scripts/check-reindent.sh <base> [head] --file <path>   # 只看一个文件
#   owner/scripts/check-reindent.sh <base> [head] --audit         # 审计模式：
#       对 -w 后仍有 diff 的文件逐个列出「-w 增删行数」，超阈值标 ⚠️
#
# 退出码：
#   0  正常完成（含「无文件」「全部纯缩进」情形）
#   1  审计模式发现 -w 后仍有大改动而未见 [owner] 标记说明的文件
#   2  参数/环境错误
#
# 判定口径（与 SKILL §9 仪器纪律一致）：
#   * 行数统计用 `git diff [-w] --numstat`，不用 grep 管道近似；
#   * 「纯缩进/搬迁」= numstat 全表 -w 后为 0/0；
#   * 审计模式只【报告】不裁决——夹带改动是否合法由人判，本脚本给证据。
set -uo pipefail

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    sed -n '2,26p' "$0"
    exit 0
fi

REPO_ROOT="${HERMES_REPO_ROOT:-$HOME/.hermes/hermes-agent}"
if [[ ! -d "$REPO_ROOT/.git" ]]; then
    echo "[reindent] 仓库根不存在或非 git 仓库: $REPO_ROOT" >&2
    exit 2
fi
cd "$REPO_ROOT" || exit 2

BASE="${1:-}"; HEAD_REF="${2:-HEAD}"
if [[ -z "$BASE" ]]; then
    echo "[reindent] 用法: check-reindent.sh <base> [head] [--file <path>|--audit]" >&2
    exit 2
fi
git rev-parse --verify "$BASE" >/dev/null 2>&1 || { echo "[reindent] base 不可解析: $BASE" >&2; exit 2; }
git rev-parse --verify "$HEAD_REF" >/dev/null 2>&1 || { echo "[reindent] head 不可解析: $HEAD_REF" >&2; exit 2; }
shift 2 || true

ONLY_FILE=""
AUDIT=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --file) ONLY_FILE="${2:-}"; shift 2 || exit 2 ;;
        --audit) AUDIT=1; shift ;;
        *) echo "[reindent] 未知参数: $1" >&2; exit 2 ;;
    esac
done

RANGE="$BASE..$HEAD_REF"
if [[ -n "$ONLY_FILE" ]]; then
    PATHSPEC=(-- "$ONLY_FILE")
else
    PATHSPEC=(-- '*.py' '*.sh' '*.yaml' '*.yml' '*.ts' '*.tsx' '*.js')
fi

# 全量 numstat（普通口径）—— bash 3.2 兼容：while-read 代替 mapfile
declare -a RAW=()
while IFS= read -r row; do
    [[ -n "$row" ]] && RAW+=("$row")
done < <(git diff --numstat "$RANGE" "${PATHSPEC[@]}" 2>/dev/null | awk '$1!="-"{print}')
# 全量 numstat（-w 口径）
declare -a WS=()
while IFS= read -r row; do
    [[ -n "$row" ]] && WS+=("$row")
done < <(git diff -w --numstat "$RANGE" "${PATHSPEC[@]}" 2>/dev/null | awk '$1!="-"{print}')

if [[ ${#RAW[@]} -eq 0 ]]; then
    echo "[reindent] 区间 $RANGE 无文本文件改动。"
    exit 0
fi

# 汇总
# NOTE: ASCII punctuation only below -- bash 3.2 (macOS) mis-parses a fullwidth
# character immediately after a variable name in arithmetic context.
raw_add=0
raw_del=0
for row in "${RAW[@]:-}"; do
    [[ -n "$row" ]] || continue
    a=$(awk '{print $1}' <<<"$row")
    d=$(awk '{print $2}' <<<"$row")
    raw_add=$((raw_add + a))
    raw_del=$((raw_del + d))
done
ws_add=0
ws_del=0
for row in "${WS[@]:-}"; do
    [[ -n "$row" ]] || continue
    a=$(awk '{print $1}' <<<"$row")
    d=$(awk '{print $2}' <<<"$row")
    ws_add=$((ws_add + a))
    ws_del=$((ws_del + d))
done

echo "[reindent] range $RANGE"
echo "  plain diff: +${raw_add} -${raw_del} (${#RAW[@]} files)"
echo "  diff -w:    +${ws_add} -${ws_del} (${#WS[@]} files)"
if [[ ${#WS[@]} -eq 0 ]]; then
    echo "  => all changes are whitespace-only (-w diff empty): pure reindent/move"
    exit 0
fi
folded=$(( (raw_add + raw_del) - (ws_add + ws_del) ))
echo "  => ${folded} whitespace-noise lines folded; files still diffing under -w need line review"

if [[ $AUDIT -eq 0 ]]; then
    exit 0
fi

# 审计模式：对 -w 后仍有改动的文件，列行数并检查是否有 [owner] 说明
echo ""
echo "[reindent] 审计模式：-w 后仍有改动的文件"
THRESHOLD="${REINDENT_AUDIT_THRESHOLD:-40}"
rc=0
for row in "${WS[@]:-}"; do
    [[ -n "$row" ]] || continue
    a=$(awk '{print $1}' <<<"$row"); d=$(awk '{print $2}' <<<"$row"); f=$(awk '{print $3}' <<<"$row")
    total=$((a+d))
    marker=""
    # grep -c (not -q): -q exits at first match and SIGPIPEs the git producer,
    # which pipefail would turn into a pipeline failure (marker never set).
    if [[ "$(git diff -w "$RANGE" -- "$f" 2>/dev/null | grep -c '\[owner\]')" -gt 0 ]]; then
        marker="has-[owner]"
    fi
    if [[ $total -ge $THRESHOLD && -z "$marker" ]]; then
        echo "  [!] ${f}  (+${a} -${d})  diff -w still >=${THRESHOLD} lines, no [owner] marker -- review closely"
        rc=1
    else
        echo "  [.] ${f}  (+${a} -${d})  ${marker:-no-marker}"
    fi
done
exit $rc
