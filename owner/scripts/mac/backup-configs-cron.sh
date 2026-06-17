#!/bin/bash
# Mac 配置文件备份 - 定时任务包装脚本
# 用于 cron job，静默模式（只输出错误）

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"$SCRIPT_DIR/backup-configs.sh" --no-success-log
