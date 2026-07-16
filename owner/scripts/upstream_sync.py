#!/usr/bin/env python3
"""hermes-agent upstream auto-sync orchestrator + CLI entry point.

This is the top-level script wired into cron. It assembles the full pipeline:

    前置检查 → fetch → 变更检测 → 分级(D1-D5) → [dry-run] →
    [MANUAL_REVIEW] → D6 健康检查 → D7 测试 → 完成 merge → 通知

Exit codes:
    0  成功 (AUTO_MERGE 完成 / 无新 commit / dry-run 完成)
    1  需人工确认 (MANUAL_REVIEW)
    2  跳过/错误 (工作区不干净 / pending review / 异常)

Usage::

    .venv/bin/python owner/scripts/upstream_sync.py               # 正常 cron 运行
    .venv/bin/python owner/scripts/upstream_sync.py --dry-run     # 只做分级判定
    .venv/bin/python owner/scripts/upstream_sync.py --resolve     # 标记人工确认完成
    .venv/bin/python owner/scripts/upstream_sync.py --config <path>
"""

from __future__ import annotations

import argparse
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Ensure ``owner.sync`` is importable when run as a script.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from owner.sync.classifier import ChangeClassifier
from owner.sync.config import SyncConfig
from owner.sync.fingerprint import FingerprintDetector
from owner.sync.gitops import GitError, GitOps
from owner.sync.health import HealthChecker
from owner.sync.merger import Merger
from owner.sync.models import (
    ChangeClassification,
    DimensionResult,
    MergeResult,
    SyncReport,
)
from owner.sync.notifier import Notifier, build_notifiers
from owner.sync.report import ReportBuilder
from owner.sync.state import StateManager

# Default config path relative to repo root.
_DEFAULT_CONFIG = "owner/config/upstream_sync.yaml"

# Exit code mapping (architecture doc section 8.1).
_EXIT_CODE_MAP: dict[str, int] = {
    "AUTO_MERGE": 0,
    "MANUAL_REVIEW": 1,
    "SKIPPED": 2,
    "ERROR": 2,
}


def _now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class UpstreamSyncOrchestrator:
    """Coordinate the full upstream sync pipeline.

    Owns one instance of every module (config, gitops, state, classifier,
    fingerprint, merger, health, notifiers) and drives them through the
    seven-stage pipeline.
    """

    def __init__(self, config_path: Optional[Path | str] = None) -> None:
        """Initialize the orchestrator and all sub-modules.

        Args:
            config_path: Path to ``upstream_sync.yaml``. Defaults to
                ``owner/config/upstream_sync.yaml`` relative to the repo root
                derived from this script's location.
        """
        path = Path(config_path) if config_path else (
            _REPO_ROOT / _DEFAULT_CONFIG
        )
        self.config: SyncConfig = SyncConfig.load(path)
        self.gitops: GitOps = GitOps(self.config.repo_root, self.config)
        self.state: StateManager = StateManager(self.config.state_file)
        self.classifier: ChangeClassifier = ChangeClassifier(self.config, self.gitops)
        self.fingerprint: FingerprintDetector = FingerprintDetector(self.config)
        self.merger: Merger = Merger(self.config, self.gitops, self.state)
        self.health: HealthChecker = HealthChecker(self.config)
        self.notifiers: list[Notifier] = build_notifiers(self.config)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def run(self, dry_run: bool = False) -> SyncReport:
        """Execute the full sync pipeline.

        Args:
            dry_run: When True, stop after classification and report the
                decision without merging.

        Returns:
            The final :class:`SyncReport` (also used to derive the exit code).
        """
        report = SyncReport(
            timestamp=_now_iso(),
            pre_merge_head="",
            upstream_head="",
            merge_base="",
            total_commits=0,
            decision="SKIPPED",
        )

        try:
            return self._execute_pipeline(report, dry_run=dry_run)
        except GitError as exc:
            report.decision = "ERROR"
            report.error = f"git 操作失败：{exc}"
            self._send_notifications(report)
            return report
        except Exception as exc:  # noqa: BLE001 — top-level safety net
            report.decision = "ERROR"
            report.error = f"未预期异常：{exc}\n{traceback.format_exc()}"
            self._send_notifications(report)
            return report

    def resolve(self) -> None:
        """Clear a pending manual-review state so the next run proceeds."""
        self.state.mark_resolved()

    # ------------------------------------------------------------------
    # Pipeline stages
    # ------------------------------------------------------------------
    def _execute_pipeline(
        self, report: SyncReport, *, dry_run: bool
    ) -> SyncReport:
        """Run the seven-stage pipeline, mutating ``report`` in place."""

        # 1. Pre-check: pending review.
        if self.state.is_pending_review():
            report.decision = "SKIPPED"
            report.error = "存在 pending review，请先执行 --resolve 后再运行"
            self._send_notifications(report)
            return report

        # 1b. Pre-check: clean workdir.
        if not self.gitops.is_workdir_clean():
            report.decision = "SKIPPED"
            report.error = "工作区不干净（存在未提交改动），跳过本轮同步"
            self._send_notifications(report)
            return report

        # 2. Fetch + change detection.
        self.gitops.fetch_upstream()
        merge_base = self.gitops.get_merge_base()
        upstream_head = self.gitops.get_upstream_head()
        report.merge_base = merge_base
        report.upstream_head = upstream_head

        # No new commits → already up to date.
        if merge_base == upstream_head:
            report.decision = "AUTO_MERGE"
            report.error = "已是最新，无新 commit"
            self._send_notifications(report)
            return report

        commits = self.gitops.get_new_commits(merge_base)
        report.total_commits = len(commits)
        report.pre_merge_head = self.gitops.get_current_head()
        self.state.save_pre_merge(report.pre_merge_head, report.timestamp)

        # 3. Classification (D1-D5, including D4 trial merge).
        classification = self.classifier.classify(commits)
        fp_matches = self.fingerprint.detect(commits)
        classification.fingerprint_matches = fp_matches
        report.classification = classification

        # 3a. dry-run: report and exit without merging.
        # Roll back the D4 staged merge so the workdir stays clean.
        if dry_run:
            self._safe_rollback(report)
            report.rolled_back = False  # rollback in dry-run is cleanup, not failure
            report.decision = classification.decision
            self._send_notifications(report)
            return report

        # 4. Decision gate: MANUAL_REVIEW or fingerprint hits → rollback + exit.
        has_high_fp = any(m.confidence == "high" for m in fp_matches)
        has_medium_fp = any(m.confidence == "medium" for m in fp_matches)
        fp_reason = ""
        if has_high_fp or has_medium_fp:
            high_count = sum(1 for m in fp_matches if m.confidence == "high")
            medium_count = sum(1 for m in fp_matches if m.confidence == "medium")
            fp_reason = (
                f"疑似重复修复：{high_count} 高置信度，{medium_count} 中置信度"
            )

        if (
            classification.decision == "MANUAL_REVIEW"
            or has_high_fp
            or has_medium_fp
        ):
            # Roll back the D4 staged merge (if any).
            self._safe_rollback(report)
            report.decision = "MANUAL_REVIEW"
            # Augment reasons with fingerprint info.
            if fp_reason:
                classification.reasons.append(fp_reason)
            self._send_notifications(report)
            reason = "; ".join(classification.reasons) or "触发分级红线"
            self.state.mark_pending_review(reason)
            if report.log_file:
                self.state.save_report_path(report.log_file)
            return report

        # 5. AUTO_MERGE path: D4 merge is already staged.
        # Synthesize the MergeResult from the D4 dimension for the report.
        report.merge_result = self._build_merge_result(classification)

        # 6. D6: health check.
        health_result = self.health.run_health_check()
        report.health_check = health_result
        if not health_result.passed:
            self._safe_rollback(report)
            report.decision = "MANUAL_REVIEW"
            classification.reasons.append(
                f"D6 健康检查失败：{health_result.summary or '有 FAIL'}"
            )
            self._send_notifications(report)
            self.state.mark_pending_review(
                f"D6 健康检查失败：{health_result.summary}"
            )
            if report.log_file:
                self.state.save_report_path(report.log_file)
            return report

        # 7. D7: tests.
        test_result = self.health.run_tests()
        report.test_result = test_result
        if not test_result.passed:
            self._safe_rollback(report)
            report.decision = "MANUAL_REVIEW"
            classification.reasons.append(
                f"D7 测试失败：{test_result.summary or '有失败'}"
            )
            self._send_notifications(report)
            self.state.mark_pending_review(
                f"D7 测试失败：{test_result.summary}"
            )
            if report.log_file:
                self.state.save_report_path(report.log_file)
            return report

        # 8. All passed: finalize the merge.
        try:
            self.merger.complete()
        except GitError as exc:
            self._safe_rollback(report)
            report.decision = "ERROR"
            report.error = f"merge commit 失败：{exc}"
            self._send_notifications(report)
            return report

        report.decision = "AUTO_MERGE"
        self._send_notifications(report)
        self.state.clear_state()
        return report

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _safe_rollback(self, report: SyncReport) -> None:
        """Attempt a rollback and record the outcome on ``report``."""
        try:
            self.merger.rollback()
            report.rolled_back = True
        except GitError as exc:
            report.rolled_back = False
            if report.error:
                report.error += f" | rollback 失败：{exc}"
            else:
                report.error = f"rollback 失败：{exc}"

    @staticmethod
    def _build_merge_result(
        classification: ChangeClassification,
    ) -> MergeResult:
        """Synthesize a :class:`MergeResult` from the D4 dimension result."""
        d4: Optional[DimensionResult] = None
        for dim in classification.dimensions:
            if dim.dimension == "D4":
                d4 = dim
                break
        if d4 is None:
            return MergeResult(success=True, output="D4 未执行")
        return MergeResult(
            success=d4.passed,
            output=d4.details,
            conflict_files=[] if d4.passed else _extract_conflict_files(d4.details),
        )

    def _send_notifications(self, report: SyncReport) -> None:
        """Fan the report out to all registered notifiers."""
        for notifier in self.notifiers:
            try:
                if report.decision == "AUTO_MERGE":
                    notifier.notify_success(report)
                elif report.decision == "MANUAL_REVIEW":
                    notifier.notify_manual_review(report)
                else:
                    notifier.notify_error(report)
            except Exception:  # noqa: BLE001 — never let a notifier kill the run
                continue


def _extract_conflict_files(details: str) -> list[str]:
    """Best-effort parse of conflict file names from a D4 details string."""
    # Details look like: "试合并产生 3 个冲突文件：a.py, b.py, c.py"
    if "：" not in details:
        return []
    after = details.split("：", 1)[1]
    parts = [p.strip().rstrip("…") for p in after.split(",")]
    return [p for p in parts if p]


# ----------------------------------------------------------------------
# CLI entry point
# ----------------------------------------------------------------------
def main() -> None:
    """Parse CLI args, run the orchestrator, and exit with the mapped code."""
    parser = argparse.ArgumentParser(
        description="hermes-agent 上游自动同步流水线",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只做分级判定（D1-D5 + 指纹检测），不执行 merge",
    )
    parser.add_argument(
        "--resolve",
        action="store_true",
        help="标记人工确认已完成，清除 pending review 状态",
    )
    parser.add_argument(
        "--config",
        default=_DEFAULT_CONFIG,
        help=f"配置文件路径（默认：{_DEFAULT_CONFIG}）",
    )
    args = parser.parse_args()

    orchestrator = UpstreamSyncOrchestrator(config_path=args.config)

    if args.resolve:
        orchestrator.resolve()
        print("已标记 resolved，下一轮 cron 将正常执行")
        sys.exit(0)

    report = orchestrator.run(dry_run=args.dry_run)

    # Print a one-line summary for the cron log.
    summary = _format_summary(report)
    print(summary, flush=True)

    exit_code = _EXIT_CODE_MAP.get(report.decision, 2)
    sys.exit(exit_code)


def _format_summary(report: SyncReport) -> str:
    """Build a single-line human-readable summary for the cron log."""
    parts = [
        f"[upstream-sync] decision={report.decision}",
        f"commits={report.total_commits}",
    ]
    if report.error:
        parts.append(f"note={report.error}")
    if report.classification is not None:
        parts.append(f"grade={report.classification.decision}")
    if report.health_check is not None:
        parts.append(f"d6={'pass' if report.health_check.passed else 'fail'}")
    if report.test_result is not None:
        parts.append(f"d7={'pass' if report.test_result.passed else 'fail'}")
    if report.rolled_back:
        parts.append("rolled_back=yes")
    return " ".join(parts)


if __name__ == "__main__":
    main()
