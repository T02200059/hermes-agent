#!/bin/bash
# todo-scan.sh - 带超时和异常保护的待办扫描脚本（macFUSE 友好版）
set -euo pipefail

# Hermes cron 以 root 运行，$HOME 是 /var/root，从 HERMES_HOME 推导用户家目录
if [ -n "${HERMES_HOME:-}" ]; then
    USER_HOME="${HERMES_HOME%/.hermes}"
else
    USER_HOME="$HOME"
fi
export USER_HOME

TODO_DIR="$USER_HOME/projects/obsidian/todo"
TIMEOUT_SEC=12

# 目录不存在就直接返回
if [ ! -d "$TODO_DIR" ]; then
    echo "DIR_NOT_FOUND"
    exit 0
fi

# 用 timeout 包裹整个扫描逻辑，防止 macFUSE 卡死
timeout "$TIMEOUT_SEC" bash -c '
    shopt -s nullglob
    files=("$USER_HOME/projects/obsidian/todo"/[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].md)
    
    # 过滤掉 -done.md
    valid_files=()
    for f in "${files[@]}"; do
        if [[ ! "$f" =~ -done\.md$ ]]; then
            valid_files+=("$f")
        fi
    done
    
    if [ ${#valid_files[@]} -eq 0 ]; then
        echo "ALL_DONE"
        exit 0
    fi
    
    # 按文件名倒序（最新日期在前）
    IFS=$'\''\n'\'' sorted=($(sort -r <<<"${valid_files[*]}"))
    
    output=""
    for filepath in "${sorted[@]}"; do
        date_str=$(basename "$filepath" .md)
        
        # 提取未完成事项
        pending=$(grep -E "^\s*-\s+\[ \]" "$filepath" 2>/dev/null | sed "s/^\s*-\s*\[ \]\s*//" || true)
        
        if [ -n "$pending" ]; then
            count=$(echo "$pending" | wc -l | tr -d " ")
            output+="## 📋 ${date_str} — ${count} 项待办\n"
            output+="$pending\n\n"
        fi
    done
    
    if [ -n "$output" ]; then
        printf '%b\n' "$output" | sed "/^$/d"   # 去掉多余空行
    else
        echo "ALL_DONE"
    fi
' 2>/dev/null || {
    # 超时或出错时的兜底
    echo "SCAN_TIMEOUT_OR_ERROR"
    exit 0
}
