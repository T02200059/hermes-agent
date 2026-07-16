#!/usr/bin/env bash
# hermes-agent 上游自动同步 cron wrapper
#
# 职责：
#   1. cd 到仓库根目录
#   2. 通过 flock 获取并发锁（非阻塞，失败即跳过）
#   3. 激活 venv（仅设置 PATH，不 source activate）
#   4. 执行 owner/scripts/upstream_sync.py，重定向 stdout/stderr 到日期日志
#
# 安装方式（crontab -e）：
#   0 3 * * * /Users/yangtb/.hermes/hermes-agent/owner/scripts/upstream_sync_cron.sh
#
# 退出码与 upstream_sync.py 一致：0=成功/无更新，1=需人工确认，2=跳过/错误
set -uo pipefail

# ─── 仓库根目录（绝对路径）───
REPO_ROOT="${HERMES_REPO_ROOT:-$HOME/.hermes/hermes-agent}"
if [[ ! -d "$REPO_ROOT/.git" ]]; then
    echo "[upstream-sync] 仓库根目录不存在或不是 git 仓库: $REPO_ROOT" >&2
    exit 2
fi

cd "$REPO_ROOT" || {
    echo "[upstream-sync] 无法 cd 到 $REPO_ROOT" >&2
    exit 2
}

# ─── 日志目录 ───
LOG_DIR="$REPO_ROOT/owner/logs/upstream-sync"
mkdir -p "$LOG_DIR"

# ─── 日期与日志文件 ───
DATE="$(date +%Y-%m-%d)"
LOG_FILE="$LOG_DIR/${DATE}.log"

# ─── flock 并发锁（非阻塞）───
LOCK_FILE="${TMPDIR:-/tmp}/hermes-upstream-sync.lock"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 另一轮同步正在执行，跳过" >> "$LOG_FILE"
    exit 0
fi

# ─── 激活 venv（仅设置 PATH，避免 source activate 的副作用）───
VENV_PYTHON="$REPO_ROOT/.venv/bin/python"
if [[ ! -x "$VENV_PYTHON" ]]; then
    echo "[upstream-sync] venv python 不存在: $VENV_PYTHON" >&2
    exit 2
fi
export PATH="$REPO_ROOT/.venv/bin:$PATH"

# ─── 执行主编排脚本 ───
echo "[$(date '+%Y-%m-%d %H:%M:%S')] === 开始上游同步 ===" >> "$LOG_FILE"
"$VENV_PYTHON" "$REPO_ROOT/owner/scripts/upstream_sync.py" >> "$LOG_FILE" 2>&1
EXIT_CODE=$?
echo "[$(date '+%Y-%m-%d %H:%M:%S')] === 同步结束，退出码: $EXIT_CODE ===" >> "$LOG_FILE"

exit "$EXIT_CODE"
