"""Report rendering for the upstream sync pipeline.

All three builders produce Markdown matching the PRD 7.1/7.2 templates so the
output is directly human-readable and can be appended to the daily log file.
"""

from __future__ import annotations

from typing import Optional

from owner.sync.models import (
    ChangeClassification,
    DimensionResult,
    FingerprintMatch,
    HealthCheckResult,
    MergeResult,
    SyncReport,
    TestResult,
    UpstreamCommit,
)


class ReportBuilder:
    """Static helpers that render :class:`SyncReport` into Markdown."""

    # ------------------------------------------------------------------
    # 7.1 Auto-merge success (lightweight)
    # ------------------------------------------------------------------
    @staticmethod
    def build_success_report(report: SyncReport) -> str:
        """Render the lightweight AUTO_MERGE success notice (PRD 7.1)."""
        lines: list[str] = []
        lines.append("## ✅ hermes-agent 上游同步完成")
        lines.append("")
        lines.append(f"- 时间：{report.timestamp}")
        lines.append(f"- 合并 commit 数：{report.total_commits} 个")

        latest = _latest_commit(report.classification)
        if latest is not None:
            lines.append(
                f"- 上游最新 commit：`{latest.short_hash}` — "
                f"{_first_line(latest.message)}"
            )

        if report.health_check is not None:
            hc = report.health_check
            tag = "✅" if hc.passed else "❌"
            lines.append(f"- 健康检查：{hc.summary or ('通过' if hc.passed else '失败')} {tag}")

        if report.test_result is not None:
            tr = report.test_result
            tag = "✅" if tr.passed else "❌"
            lines.append(f"- 测试：{tr.summary or ('全部通过' if tr.passed else '有失败')} {tag}")

        if report.log_file:
            lines.append(f"- 日志：{report.log_file}")
        else:
            lines.append("- 日志：owner/logs/upstream-sync/")

        lines.append("")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 7.2 Manual review (detailed)
    # ------------------------------------------------------------------
    @staticmethod
    def build_manual_review_report(report: SyncReport) -> str:
        """Render the detailed MANUAL_REVIEW report (PRD 7.2)."""
        lines: list[str] = []
        lines.append("## ⚠️ hermes-agent 上游同步需要人工确认")
        lines.append("")
        lines.append(f"- 时间：{report.timestamp}")
        lines.append(f"- 上游新增 commit 数：{report.total_commits} 个")

        # Pause reason summary.
        cls = report.classification
        if cls is not None and cls.reasons:
            lines.append(f"- 暂停原因：{cls.reasons[0]}")
        elif report.error:
            lines.append(f"- 暂停原因：{report.error}")
        else:
            lines.append("- 暂停原因：触发人工确认红线")
        lines.append("")

        # Red-line dimension table.
        lines.append("### 触发的分级红线")
        lines.append("")
        lines.append("| 维度 | 结果 | 详情 |")
        lines.append("|------|------|------|")
        if cls is not None:
            for dim in cls.dimensions:
                verdict = "🔴 触发" if dim.triggered_red_line else ("🟢 通过" if dim.passed else "🔴 触发")
                # Escape pipes in details for Markdown table safety.
                safe_details = dim.details.replace("|", "\\|")
                lines.append(
                    f"| {dim.dimension}. {dim.name} | {verdict} | {safe_details} |"
                )
        lines.append("")

        # Upstream commit list (latest 10).
        lines.append("### 上游 commit 列表（最近 10 个）")
        lines.append("")
        if cls is not None and cls.upstream_commits:
            recent = cls.upstream_commits[-10:]
            for idx, commit in enumerate(reversed(recent), start=1):
                lines.append(
                    f"{idx}. `{commit.short_hash}` — {_first_line(commit.message)}"
                )
        else:
            lines.append("_(无 commit 信息)_")
        lines.append("")

        # Suspected duplicate fixes.
        lines.append("### 疑似重复修复")
        lines.append("")
        if cls is not None and cls.fingerprint_matches:
            high = [m for m in cls.fingerprint_matches if m.confidence == "high"]
            medium = [m for m in cls.fingerprint_matches if m.confidence == "medium"]
            for match in high:
                lines.extend(_format_fingerprint(match, "高置信度"))
            for match in medium:
                lines.extend(_format_fingerprint(match, "中置信度"))
        else:
            lines.append("_(未检测到疑似重复修复)_")
        lines.append("")

        # Health check / test output (when triggered by D6/D7).
        if report.health_check is not None and not report.health_check.passed:
            lines.append("### 健康检查失败详情（D6）")
            lines.append("")
            lines.append("```")
            lines.append(report.health_check.summary or report.health_check.output or "(无输出)")
            lines.append("```")
            lines.append("")
        if report.test_result is not None and not report.test_result.passed:
            lines.append("### 测试失败详情（D7）")
            lines.append("")
            lines.append("```")
            lines.append(report.test_result.summary or report.test_result.output or "(无输出)")
            lines.append("```")
            lines.append("")

        # Merge conflicts (when triggered by D4).
        if (
            report.merge_result is not None
            and not report.merge_result.success
            and report.merge_result.conflict_files
        ):
            lines.append("### 冲突文件列表（D4）")
            lines.append("")
            for f in report.merge_result.conflict_files:
                lines.append(f"- `{f}`")
            lines.append("")

        # Suggested actions.
        lines.append("### 建议操作")
        lines.append("")
        if cls is not None:
            lines.extend(_suggest_actions(cls))
        lines.append("1. 处理完毕后标记 resolved，恢复自动同步")

        # Resolve command.
        lines.append("")
        lines.append("### 人工处理后")
        lines.append("")
        lines.append("```bash")
        lines.append("# 确认完成后标记 resolved")
        lines.append("python owner/scripts/upstream_sync.py --resolve")
        lines.append("```")
        lines.append("")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Error / skipped
    # ------------------------------------------------------------------
    @staticmethod
    def build_error_report(report: SyncReport) -> str:
        """Render an ERROR/SKIPPED report."""
        lines: list[str] = []
        lines.append("## ⏭️ hermes-agent 上游同步跳过/错误")
        lines.append("")
        lines.append(f"- 时间：{report.timestamp}")
        lines.append(f"- 决策：{report.decision}")
        if report.error:
            lines.append(f"- 原因：{report.error}")
        if report.pre_merge_head:
            lines.append(f"- 当前 HEAD：`{report.pre_merge_head}`")
        if report.log_file:
            lines.append(f"- 日志：{report.log_file}")
        lines.append("")
        lines.append("### 后续操作")
        lines.append("")
        if report.decision == "SKIPPED" and "pending review" in (report.error or "").lower():
            lines.append("存在 pending review，请先处理人工确认事项后执行：")
            lines.append("")
            lines.append("```bash")
            lines.append("python owner/scripts/upstream_sync.py --resolve")
            lines.append("```")
        elif report.decision == "SKIPPED" and "工作区" in (report.error or ""):
            lines.append("工作区不干净，请先提交或 stash 本地改动后等待下一轮 cron。")
        else:
            lines.append("请检查日志排查错误原因，修复后等待下一轮 cron 或手动重跑。")
        lines.append("")
        return "\n".join(lines)


# ----------------------------------------------------------------------
# Private formatting helpers
# ----------------------------------------------------------------------
def _first_line(message: str) -> str:
    """Return the first non-empty line of a commit message."""
    for line in message.splitlines():
        if line.strip():
            return line.strip()
    return message.strip()


def _latest_commit(
    classification: Optional[ChangeClassification],
) -> Optional[UpstreamCommit]:
    """Return the newest upstream commit in the classification, or None."""
    if classification is None or not classification.upstream_commits:
        return None
    return classification.upstream_commits[-1]


def _format_fingerprint(match: FingerprintMatch, label: str) -> list[str]:
    """Format a single fingerprint match as Markdown lines."""
    return [
        f"#### {label}：{match.fingerprint_id}",
        f"- owner 本地修复：§{match.owner_commit} {match.fingerprint_title}",
        f"- 上游 commit：`{match.upstream_commit_hash[:12]}` — "
        f"{_first_line(match.upstream_commit_message)}",
        f"- 综合相似度：{match.combined_similarity:.2f}"
        f"（文件交集率 {match.file_intersection_rate:.2f}，"
        f"关键词命中率 {match.keyword_hit_rate:.2f}）",
        "",
    ]


def _suggest_actions(cls: ChangeClassification) -> list[str]:
    """Generate suggested actions from triggered red lines."""
    actions: list[str] = []
    for dim in cls.dimensions:
        if not dim.triggered_red_line:
            continue
        if dim.dimension == "D2":
            actions.append("1. 检查触及的锚点文件中 owner 胶水是否需要适配上游变更")
        elif dim.dimension == "D3":
            actions.append("2. 检查重度侵入文件中 owner 定制逻辑是否受影响")
        elif dim.dimension == "D4":
            actions.append("3. 解决试合并产生的冲突文件")
        elif dim.dimension == "D5":
            actions.append("4. 评估含危险关键词的 commit 是否引入架构级变更")
        elif dim.dimension == "D1":
            actions.append("5. 评估大批量改动是否需要拆分多次合并")
        elif dim.dimension == "D0":
            actions.append("6. 积压 commit 过多，建议分批追赶或评估上游节奏")
    for match in cls.fingerprint_matches:
        if match.confidence == "high":
            actions.append(
                "7. 高置信度疑似重复修复，评估是否删除 owner 本地修复取上游版本"
            )
            break
    if not actions:
        actions.append("1. 检查分级报告并确认是否可安全合并")
    # Re-number sequentially.
    renumbered: list[str] = []
    for idx, action in enumerate(actions, start=1):
        # Replace leading "N. " with the correct sequential number.
        stripped = action.split(". ", 1)
        if len(stripped) == 2:
            renumbered.append(f"{idx}. {stripped[1]}")
        else:
            renumbered.append(f"{idx}. {action}")
    return renumbered
