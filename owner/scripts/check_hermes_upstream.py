#!/usr/bin/env python3
"""
Hermes upstream update checker script.
Checks if official Hermes repo has new commits and returns summary.
"""

import subprocess
import os

HERMES_REPO = os.path.expanduser("~/.hermes/hermes-agent")

def run_git(cmd):
    """Run git command and return output."""
    result = subprocess.run(
        cmd,
        cwd=HERMES_REPO,
        capture_output=True,
        text=True,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    )
    return result.stdout.strip(), result.returncode

def check_updates():
    """Check for upstream updates and return summary."""
    
    # Fetch upstream
    run_git(["git", "fetch", "upstream", "--quiet"])
    
    # Get current custom branch HEAD
    current_head, _ = run_git(["git", "rev-parse", "custom"])
    
    # Get upstream/main HEAD
    upstream_head, _ = run_git(["git", "rev-parse", "upstream/main"])
    
    # Get the merge base (common ancestor)
    merge_base, _ = run_git(["git", "merge-base", "custom", "upstream/main"])
    
    if upstream_head == merge_base:
        # No new commits upstream
        return {
            "has_updates": False,
            "message": "✅ Hermes 官方仓库无新更新，你的 custom 分支已是最新。"
        }
    
    # Get new commits from upstream
    new_commits, _ = run_git([
        "git", "log", 
        f"{merge_base}..upstream/main",
        "--oneline", "--no-merges", "-10"
    ])
    
    # Get count of new commits
    count_output, _ = run_git([
        "git", "rev-list", "--count",
        f"{merge_base}..upstream/main"
    ])
    
    count = int(count_output) if count_output else 0
    
    # Get latest upstream commit date
    date_output, _ = run_git([
        "git", "log", "-1", "--format=%ci", "upstream/main"
    ])
    
    return {
        "has_updates": True,
        "count": count,
        "latest_date": date_output,
        "commits": new_commits,
        "message": f"""🔔 Hermes 官方仓库有新更新！

📊 统计信息：
- 新提交数：{count} 个
- 最新提交时间：{date_output}

📝 最近 10 个提交：
{new_commits}

💡 建议：
运行 `git fetch upstream && git checkout main && git merge upstream/main && git checkout custom && git rebase main` 来同步更新。

⚠️ 注意：合并前请确保 custom 分支的修改已保存。"""
    }

if __name__ == "__main__":
    result = check_updates()
    print(result["message"])