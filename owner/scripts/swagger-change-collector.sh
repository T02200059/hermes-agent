#!/usr/bin/env bash
# swagger-change-collector.sh
# 收集近 N 天 swagger 相关变更数据，输出结构化 markdown 给 AI 分析
# 用法: ./swagger-change-collector.sh --days 2
set -o pipefail

PROJECT="/Users/yangtb/workspace/westcloud/damodel/starryshore-manager"
HANDLER_DIR="biz/handler"
ROUTER_FILE="biz/router/group_router.go"

# 解析参数
DAYS=2
while [[ $# -gt 0 ]]; do
    case $1 in
        --days) DAYS="$2"; shift 2 ;;
        *) shift ;;
    esac
done

cd "$PROJECT" || { echo "❌ 项目目录不存在: $PROJECT"; exit 1; }

# 1. Pull（保留 stderr 供诊断）
PULL_OUTPUT=$(git pull --ff-only 2>&1)
PULL_EXIT=$?
if [ $PULL_EXIT -ne 0 ]; then
    echo "⚠️ git pull 失败 (exit=$PULL_EXIT): $PULL_OUTPUT"
    echo ""
fi

# 2. 获取变更文件
SINCE=$(date -v-${DAYS}d +%Y-%m-%d 2>/dev/null || date -d "${DAYS} days ago" +%Y-%m-%d)
CHANGED=$(git log --since="$SINCE" --name-only --pretty=format: -- "$HANDLER_DIR/" | sort -u | grep '\.go$' | grep -v '_test.go' || true)

if [ -z "$CHANGED" ]; then
    echo "NO_CHANGES"
    echo ""
    echo "(诊断: DAYS=$DAYS SINCE=$SINCE PWD=$(pwd) BRANCH=$(git branch --show-current))"
    echo "(最近3条commit:)"
    git log --oneline -3 2>&1
    exit 0
fi

# 3. 输出变更摘要
CHANGED_COUNT=$(echo "$CHANGED" | wc -l | tr -d ' ')
echo "## 变更范围"
echo "- 项目: starryshore-manager"
echo "- 分支: $(git branch --show-current)"
echo "- 时间: ${SINCE} ~ $(date +%Y-%m-%d)"
echo "- 变更 handler 文件数: ${CHANGED_COUNT}"
echo ""

# 4. 变更文件列表
echo "## 变更文件"
echo "$CHANGED" | sed 's/^/- /'
echo ""

# 5. 每个变更文件的 swagger diff
echo "## Swagger 注释变更 diff"
for f in $CHANGED; do
    DIFF=$(git diff "HEAD~10" -- "$f" 2>/dev/null | grep -E '^\+.*(@Summary|@Tags|@Param|@Success|@Router|@Produce|@Accept)' || true)
    if [ -n "$DIFF" ]; then
        echo "### $f"
        echo '```diff'
        echo "$DIFF"
        echo '```'
        echo ""
    fi
done

# 6. 变更文件完整内容
echo "## 变更文件内容"
for f in $CHANGED; do
    if [ -f "$f" ]; then
        echo "### $f"
        echo '```go'
        cat "$f"
        echo '```'
        echo ""
    fi
done

# 7. 路由注册
echo "## 路由注册"
echo "### $ROUTER_FILE"
echo '```go'
cat "$ROUTER_FILE"
echo '```'
