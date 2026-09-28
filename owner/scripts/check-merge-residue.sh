#!/usr/bin/env bash
# hermes-agent 解冲后置校验（merge-residue check）
#
# 目的：
#   每次 sync fork 的解冲（conflict resolution）提交后，固定执行
#   「tests/owner + 本窗口/本次 merge 改动过的全部测试文件」，把结果记入
#   commit message，防止「解冲不完整」再次逃逸。
#
#   本脚本的存在理由：本期 11 个红测试的单一根因就是一次解冲不完整
#   （merge 3155512347），而该缺陷 26 天后才被发现——因为既有流水线只跑
#   tests/owner，而逃逸的用例在 tests/plugins/memory/ 下。
#
# 用法：
#   owner/scripts/check-merge-residue.sh                  # 校验 HEAD（须为 merge 提交）
#   owner/scripts/check-merge-residue.sh <merge-commit>
#   owner/scripts/check-merge-residue.sh <merge-commit> <base>
#   owner/scripts/check-merge-residue.sh --list           # 只列目标，不执行
#   owner/scripts/check-merge-residue.sh --base <ref>     # 显式指定基线
#
# 退出码：
#   0  全绿
#   1  有用例失败（发布门槛未过）
#   2  环境/参数错误（无法校验）
#
# 结果落盘：owner/logs/merge-residue/<target>.log
set -uo pipefail

REPO_ROOT="${HERMES_REPO_ROOT:-$HOME/.hermes/hermes-agent}"
if [[ ! -d "$REPO_ROOT/.git" ]]; then
    echo "[merge-residue] 仓库根目录不存在或不是 git 仓库: $REPO_ROOT" >&2
    exit 2
fi
cd "$REPO_ROOT" || { echo "[merge-residue] 无法 cd 到 $REPO_ROOT" >&2; exit 2; }

# ─── 参数解析 ───
TARGET=""
BASE=""
LIST_ONLY=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --list) LIST_ONLY=1; shift ;;
        --base) BASE="${2:-}"; shift 2 ;;
        -h|--help) sed -n '2,28p' "$0"; exit 0 ;;
        -*) echo "[merge-residue] 未知参数: $1" >&2; exit 2 ;;
        *)  if [[ -z "$TARGET" ]]; then TARGET="$1"; else BASE="$1"; fi; shift ;;
    esac
done

# ─── 解释器 ───
PY="$REPO_ROOT/.venv/bin/python"
[[ -x "$PY" ]] || PY="$(command -v python3 || true)"
if [[ -z "$PY" ]]; then
    echo "[merge-residue] 找不到可用的 python 解释器（期望 .venv/bin/python）" >&2
    exit 2
fi

# ─── 解析 target / base ───
if [[ -z "$TARGET" ]]; then
    TARGET="HEAD"
fi
if ! git rev-parse --verify --quiet "${TARGET}^{commit}" >/dev/null; then
    echo "[merge-residue] 无法解析提交: $TARGET" >&2
    exit 2
fi
TARGET_SHA="$(git rev-parse --short "$TARGET")"

if [[ -z "$BASE" ]]; then
    # 解冲提交的第一父 = 解冲前的 owner 侧；回退到 HEAD^
    if ! BASE="$(git rev-parse --verify --quiet "${TARGET}^1")"; then
        BASE="$(git rev-parse --verify --quiet "${TARGET}^")" || {
            echo "[merge-residue] 无法推导基线，请用 --base 显式指定" >&2
            exit 2
        }
    fi
fi
BASE_SHA="$(git rev-parse --short "$BASE")"

MERGE_PARENTS="$(git rev-list --parents -n 1 "$TARGET" | wc -w | tr -d ' ')"
if [[ "$MERGE_PARENTS" -lt 3 ]]; then
    echo "[merge-residue] 提示：${TARGET_SHA} 不是 merge 提交（父数=$((MERGE_PARENTS-1))）；" \
         "仍将按普通范围校验。" >&2
fi

# ─── 收集目标测试 ───
# 1) 固定项：owner 侧全部用例
# 2) 动态项：本次范围（base..target）改动过的测试文件
declare -a TARGETS=()
TARGETS+=("tests/owner")

CHANGED_TESTS=()
while IFS= read -r f; do
    [[ -n "$f" ]] || continue
    [[ -f "$f" ]] || continue                       # 被删除的测试跳过
    [[ "$f" == tests/owner/* ]] && continue         # 已在固定项内
    CHANGED_TESTS+=("$f")
    TARGETS+=("$f")
done < <(git diff --name-only --diff-filter=AM "$BASE_SHA" "$TARGET_SHA" -- \
            'tests/**' '*/tests/**' 'test_*.py' '*/test_*.py' 2>/dev/null | sort -u)

echo "═══════════════════════════════════════════════════════════════"
echo " 解冲后置校验  merge-residue check"
echo "───────────────────────────────────────────────────────────────"
echo "   基线 base   : $BASE_SHA  ($(git log -1 --format='%ad %s' --date=short "$BASE_SHA" | cut -c1-60))"
echo "   目标 target : $TARGET_SHA  ($(git log -1 --format='%ad %s' --date=short "$TARGET_SHA" | cut -c1-60))"
echo "   固定用例    : tests/owner"
echo "   范围内改动的测试文件: ${#CHANGED_TESTS[@]} 个"
for f in "${CHANGED_TESTS[@]:-}"; do [[ -n "$f" ]] && echo "                 - $f"; done
echo "═══════════════════════════════════════════════════════════════"

if [[ "$LIST_ONLY" -eq 1 ]]; then
    printf '%s\n' "${TARGETS[@]}"
    exit 0
fi

# ─── 执行 ───
LOG_DIR="$REPO_ROOT/owner/logs/merge-residue"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/${TARGET_SHA}.log"

START_TS=$(date +%s)
"$PY" -m pytest "${TARGETS[@]}" -q -p no:cacheprovider 2>&1 | tee "$LOG_FILE"
PYTEST_RC="${PIPESTATUS[0]}"
END_TS=$(date +%s)
ELAPSED=$(( END_TS - START_TS ))

SUMMARY="$(grep -E '^[0-9]+ (passed|failed)|passed|failed|error' "$LOG_FILE" | tail -1 | sed 's/^[[:space:]]*//')"
if [[ -z "$SUMMARY" ]]; then SUMMARY="（未能解析摘要，见 $LOG_FILE）"; fi

# ─── 结果与 commit message 片段 ───
VERDICT="PASS"
[[ "$PYTEST_RC" -eq 0 ]] || VERDICT="FAIL"

echo
echo "───────── 可粘贴进 commit message 的校验记录 ─────────"
echo "merge-residue-check: $VERDICT"
echo "  base=$BASE_SHA target=$TARGET_SHA elapsed=${ELAPSED}s"
echo "  targets=tests/owner + ${#CHANGED_TESTS[@]} changed test file(s)"
echo "  result=$SUMMARY"
echo "──────────────────────────────────────────────────────"

if [[ "$PYTEST_RC" -ne 0 ]]; then
    echo "[merge-residue] 校验未通过（rc=${PYTEST_RC}），日志：${LOG_FILE}" >&2
    exit 1
fi
echo "[merge-residue] 校验通过，日志：${LOG_FILE}"
exit 0
