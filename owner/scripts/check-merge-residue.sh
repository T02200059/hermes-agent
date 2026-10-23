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
#   owner/scripts/check-merge-residue.sh --full           # 跑标准入口全量 tests/
#   owner/scripts/check-merge-residue.sh --list           # 只列目标，不执行
#   owner/scripts/check-merge-residue.sh --base <ref>     # 显式指定基线
#
# 两档模式：
#   默认（targeted）  tests/owner + 本次改动过的测试文件 —— 秒级到十几分钟
#   --full            标准入口全量 tests/ —— 约 30 分钟，零漏判
#
#   为什么需要 --full：动态项只认「本次改动过的**测试**文件」。一次只改了产品
#   代码、没动测试的 merge，targeted 档完全不会看那些文件的测试，而这类改动
#   恰恰是「解冲把上游调用方搬进来、被调方没跟」的高发区。2026-10-23 收口
#   T2-21 时，12 个真产品 bug 的失败全落在 tests/gateway、tests/tools、
#   tests/plugins、tests/monitoring —— 正是这个缺口放过的那类。sync 后应及时
#   跑一次 --full；targeted 档留作日常快速自检。
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
FULL=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --list) LIST_ONLY=1; shift ;;
        --full) FULL=1; shift ;;
        --base) BASE="${2:-}"; shift 2 ;;
        -h|--help) sed -n '2,34p' "$0"; exit 0 ;;
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
if [[ "$FULL" -eq 1 ]]; then
    echo "   模式        : --full（标准入口全量 tests/，零漏判）"
else
    echo "   模式        : targeted（tests/owner + 范围内改动的测试文件）"
fi
echo "   固定用例    : tests/owner"
echo "   范围内改动的测试文件: ${#CHANGED_TESTS[@]} 个"
for f in "${CHANGED_TESTS[@]:-}"; do [[ -n "$f" ]] && echo "                 - $f"; done
echo "═══════════════════════════════════════════════════════════════"

if [[ "$LIST_ONLY" -eq 1 ]]; then
    if [[ "$FULL" -eq 1 ]]; then
        echo "tests/  (--full: 标准入口全量)"
    else
        printf '%s\n' "${TARGETS[@]}"
    fi
    exit 0
fi

# ─── 执行 ───
LOG_DIR="$REPO_ROOT/owner/logs/merge-residue"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/${TARGET_SHA}.log"

START_TS=$(date +%s)
if [[ "$FULL" -eq 1 ]]; then
    # 标准入口：per-file 子进程隔离 + env -i + TZ=UTC/LANG=C.UTF-8/PYTHONHASHSEED=0。
    # 必须用它而不是裸 pytest：targeted 档的裸 pytest 是单进程全量，与 CI/权威
    # 基线口径不同，结果可能分叉（T2-21 的「测试入口」注记即此）。
    RUNNER="$REPO_ROOT/scripts/run_tests.sh"
    if [[ ! -x "$RUNNER" ]]; then
        echo "[merge-residue] 找不到标准入口: $RUNNER" >&2
        exit 2
    fi
    "$RUNNER" tests/ >"$LOG_FILE" 2>&1
    RC=$?
else
    "$PY" -m pytest "${TARGETS[@]}" -q -p no:cacheprovider 2>&1 | tee "$LOG_FILE"
    RC="${PIPESTATUS[0]}"
fi
END_TS=$(date +%s)
ELAPSED=$(( END_TS - START_TS ))

# --full 的摘要行是 "=== Summary: N files, X passed, Y failed, Z skipped ..."；
# targeted 档是 pytest 自带的 "N passed, M failed in ..."。两种都认。
# 去掉行首的 "=== " 装饰，避免拼进 "result===" 里多出一串等号。
SUMMARY="$(grep -E '^=== Summary:|^[0-9]+ (passed|failed)' "$LOG_FILE" | tail -1 | sed 's/^[[:space:]]*//; s/^=== Summary: /Summary: /')"
if [[ -z "$SUMMARY" ]]; then SUMMARY="（未能解析摘要，见 $LOG_FILE）"; fi

# 并行 runner 有一次性 FLAKY 重试：attempt 1 的 FAILED 行会留在输出里，但重试通过
# 不计入 failed。所以「grep 到 FAILED 行」与「Summary 的 failed 数」不一致不是矛盾。
FAILED_LINES="$(grep -c '^FAILED ' "$LOG_FILE" 2>/dev/null || true)"
FAILED_LINES="${FAILED_LINES:-0}"

# ─── 结果与 commit message 片段 ───
VERDICT="PASS"
[[ "$RC" -eq 0 ]] || VERDICT="FAIL"

echo
echo "───────── 可粘贴进 commit message 的校验记录 ─────────"
echo "merge-residue-check: $VERDICT"
echo "  base=$BASE_SHA target=$TARGET_SHA elapsed=${ELAPSED}s"
if [[ "$FULL" -eq 1 ]]; then
    echo "  mode=full targets=tests/ (standard runner)"
else
    echo "  mode=targeted targets=tests/owner + ${#CHANGED_TESTS[@]} changed test file(s)"
fi
echo "  result=$SUMMARY"
if [[ "$FAILED_LINES" -gt 0 ]]; then
    echo "  failed-rows=$FAILED_LINES（含 FLAKY 首轮失败痕迹，实际 failed 数见上行 Summary）"
fi
echo "──────────────────────────────────────────────────────"

if [[ "$RC" -ne 0 ]]; then
    echo "[merge-residue] 校验未通过（rc=${RC}），日志：${LOG_FILE}" >&2
    exit 1
fi
echo "[merge-residue] 校验通过，日志：${LOG_FILE}"
exit 0
