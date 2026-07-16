"""Change classification: the D1-D5 pre-merge grading pipeline.

The classifier evaluates a batch of upstream commits across five dimensions
before any real merge is committed:

    D1  改动规模          total changed files ≤ d1_max_files
    D2  锚点文件触及      no touched file appears in anchors.yaml
    D3  重度侵入文件触及   no touched file is in d3_heavily_intruded_files
    D5  commit 关键词     no commit message contains a dangerous keyword
    D4  试合并冲突预检    ``git merge --no-commit --no-ff`` produces no conflicts

D4 is intentionally evaluated **last** because it mutates the working tree
(staging the merge result). When D4 fails the classifier immediately calls
``git merge --abort`` to restore the workdir. When D4 succeeds the merge stays
staged so D6/D7 can run against the merged tree; the orchestrator is then
responsible for either ``complete_merge()`` or ``rollback()``.

A pre-check short-circuits to MANUAL_REVIEW when the commit count exceeds
``max_commits_threshold``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from owner.sync.config import SyncConfig
from owner.sync.gitops import GitError, GitOps
from owner.sync.models import (
    ChangeClassification,
    DimensionResult,
    UpstreamCommit,
)


class ChangeClassifier:
    """Grade upstream commits across D1-D5 and return a classification."""

    def __init__(self, config: SyncConfig, gitops: GitOps) -> None:
        """Initialize the classifier.

        Args:
            config: Loaded :class:`SyncConfig`.
            gitops: :class:`GitOps` bound to the same repository.
        """
        self.config: SyncConfig = config
        self.gitops: GitOps = gitops
        self._anchor_files: set[str] | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def classify(self, commits: list[UpstreamCommit]) -> ChangeClassification:
        """Run D1-D5 over ``commits`` and return the classification.

        Args:
            commits: Upstream commits newer than the merge-base, oldest first.

        Returns:
            A :class:`ChangeClassification` whose ``decision`` is either
            ``"AUTO_MERGE"`` (all dimensions passed) or ``"MANUAL_REVIEW"``
            (at least one red line triggered).
        """
        reasons: list[str] = []
        dimensions: list[DimensionResult] = []
        total_commits = len(commits)

        # Pre-check: commit count threshold (>100 → MANUAL_REVIEW, skip D1-D5).
        if total_commits > self.config.max_commits_threshold:
            reason = (
                f"上游积累 {total_commits} 个 commit，超过阈值 "
                f"{self.config.max_commits_threshold}，自动转人工确认"
            )
            reasons.append(reason)
            # Still record a synthetic dimension for reporting clarity.
            dimensions.append(
                DimensionResult(
                    dimension="D0",
                    name="commit 数量前置检查",
                    passed=False,
                    details=reason,
                    triggered_red_line=True,
                )
            )
            return ChangeClassification(
                decision="MANUAL_REVIEW",
                dimensions=dimensions,
                upstream_commits=commits,
                total_files_changed=0,
                total_commits=total_commits,
                reasons=reasons,
                fingerprint_matches=[],
            )

        # Compute the full changed-file set between merge-base and upstream HEAD.
        merge_base = self.gitops.get_merge_base()
        upstream_head = self.gitops.get_upstream_head()
        changed_files = self.gitops.get_changed_files(merge_base, upstream_head)

        # D1: total changed files.
        d1 = self._check_d1(changed_files)
        dimensions.append(d1)
        if d1.triggered_red_line:
            reasons.append(d1.details)

        # D2: anchor file touches.
        d2 = self._check_d2(changed_files)
        dimensions.append(d2)
        if d2.triggered_red_line:
            reasons.append(d2.details)

        # D3: heavily-intruded file touches.
        d3 = self._check_d3(changed_files)
        dimensions.append(d3)
        if d3.triggered_red_line:
            reasons.append(d3.details)

        # D5: dangerous keywords in commit messages.
        d5 = self._check_d5(commits)
        dimensions.append(d5)
        if d5.triggered_red_line:
            reasons.append(d5.details)

        # D4: trial-merge conflict pre-check (LAST — mutates the workdir).
        d4 = self._check_d4()
        dimensions.append(d4)
        if d4.triggered_red_line:
            reasons.append(d4.details)

        decision = (
            "AUTO_MERGE"
            if all(dim.passed for dim in dimensions)
            else "MANUAL_REVIEW"
        )
        return ChangeClassification(
            decision=decision,
            dimensions=dimensions,
            upstream_commits=commits,
            total_files_changed=len(changed_files),
            total_commits=total_commits,
            reasons=reasons,
            fingerprint_matches=[],
        )

    # ------------------------------------------------------------------
    # Dimension checks
    # ------------------------------------------------------------------
    def _check_d1(self, changed_files: list[str]) -> DimensionResult:
        """D1: total changed files must not exceed ``d1_max_files``."""
        count = len(changed_files)
        threshold = self.config.d1_max_files
        passed = count <= threshold
        return DimensionResult(
            dimension="D1",
            name="改动规模",
            passed=passed,
            details=(
                f"总改动文件数 {count} ≤ {threshold}"
                if passed
                else f"总改动文件数 {count} > {threshold}，触发红线"
            ),
            triggered_red_line=not passed,
        )

    def _check_d2(self, changed_files: list[str]) -> DimensionResult:
        """D2: no changed file may be an anchor file from anchors.yaml."""
        anchor_files = self._load_anchor_files()
        changed_set = {f.strip() for f in changed_files if f.strip()}
        touched = sorted(changed_set & anchor_files)
        passed = not touched
        if passed:
            details = "未触及任何 anchors.yaml 锚点文件"
        else:
            details = (
                f"触及 {len(touched)} 个锚点文件：{', '.join(touched[:10])}"
                + ("…" if len(touched) > 10 else "")
            )
        return DimensionResult(
            dimension="D2",
            name="锚点文件触及",
            passed=passed,
            details=details,
            triggered_red_line=not passed,
        )

    def _check_d3(self, changed_files: list[str]) -> DimensionResult:
        """D3: no changed file may be a heavily-intruded file."""
        heavy_files = {f.strip() for f in self.config.d3_heavily_intruded_files if f.strip()}
        changed_set = {f.strip() for f in changed_files if f.strip()}
        touched = sorted(changed_set & heavy_files)
        passed = not touched
        if passed:
            details = "未触及任何重度侵入文件"
        else:
            details = (
                f"触及 {len(touched)} 个重度侵入文件：{', '.join(touched[:10])}"
                + ("…" if len(touched) > 10 else "")
            )
        return DimensionResult(
            dimension="D3",
            name="重度侵入文件触及",
            passed=passed,
            details=details,
            triggered_red_line=not passed,
        )

    def _check_d5(self, commits: list[UpstreamCommit]) -> DimensionResult:
        """D5: no commit message may contain a dangerous keyword."""
        dangerous = [kw.lower() for kw in self.config.d5_dangerous_keywords]
        hits: list[tuple[str, str]] = []  # (short_hash, keyword)
        for commit in commits:
            msg_lower = commit.message.lower()
            for kw in dangerous:
                if kw in msg_lower:
                    hits.append((commit.short_hash, kw))
        passed = not hits
        if passed:
            details = "commit message 未含危险关键词"
        else:
            sample = ", ".join(f"{h[0]}({h[1]})" for h in hits[:5])
            details = (
                f"检测到 {len(hits)} 处危险关键词命中：{sample}"
                + ("…" if len(hits) > 5 else "")
            )
        return DimensionResult(
            dimension="D5",
            name="commit message 关键词",
            passed=passed,
            details=details,
            triggered_red_line=not passed,
        )

    def _check_d4(self) -> DimensionResult:
        """D4: trial-merge must produce no conflicts.

        Runs ``git merge --no-commit --no-ff``. On conflict the merge is
        immediately aborted so the workdir is clean for the next run. On
        success the merge stays staged (the orchestrator finalizes or rolls
        it back later).
        """
        try:
            success, output, conflict_files = self.gitops.try_merge_no_commit()
        except GitError as exc:
            return DimensionResult(
                dimension="D4",
                name="试合并冲突预检",
                passed=False,
                details=f"试合并执行失败：{exc}",
                triggered_red_line=True,
            )
        if success:
            return DimensionResult(
                dimension="D4",
                name="试合并冲突预检",
                passed=True,
                details="试合并无冲突（merge 已暂存未提交）",
                triggered_red_line=False,
            )
        # Conflict: abort immediately to restore the workdir.
        try:
            self.gitops.abort_merge()
        except GitError:
            # If abort fails the orchestrator's rollback() will reset_hard.
            pass
        sample = ", ".join(conflict_files[:10])
        details = (
            f"试合并产生 {len(conflict_files)} 个冲突文件：{sample}"
            + ("…" if len(conflict_files) > 10 else "")
        )
        return DimensionResult(
            dimension="D4",
            name="试合并冲突预检",
            passed=False,
            details=details,
            triggered_red_line=True,
        )

    # ------------------------------------------------------------------
    # Anchor loading
    # ------------------------------------------------------------------
    def _load_anchor_files(self) -> set[str]:
        """Load the set of anchor ``file`` values from anchors.yaml.

        Cached for the lifetime of the classifier. Returns an empty set when
        the file is missing or malformed (D2 then trivially passes).
        """
        if self._anchor_files is not None:
            return self._anchor_files

        path: Path = self.config.d2_anchors_file
        files: set[str] = set()
        if not path.exists():
            self._anchor_files = files
            return files
        with path.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        if not isinstance(raw, dict):
            self._anchor_files = files
            return files
        anchors = raw.get("anchors", []) or []
        for entry in anchors:
            if not isinstance(entry, dict):
                continue
            file_value = entry.get("file")
            if file_value:
                files.add(str(file_value).strip())
        self._anchor_files = files
        return files
