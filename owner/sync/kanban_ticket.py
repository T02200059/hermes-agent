"""K0: open a Kanban card when upstream sync needs human review.

Creates a blocked, human-ops card via ``hermes kanban create`` so MANUAL
runs are trackable on the board (audit trail + close-the-loop), without
spawning an agent worker. See ``owner/docs/upstream-sync-kanban.md``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from owner.sync.config import SyncConfig
from owner.sync.models import SyncReport
from owner.sync.report import ReportBuilder


@dataclass
class KanbanTicketResult:
    """Outcome of attempting to open (or reuse) a kanban card."""

    created: bool
    task_id: Optional[str]
    title: str
    idempotency_key: str
    workspace: str
    error: Optional[str] = None
    reused: bool = False
    raw_output: str = ""


class KanbanTicketOpener:
    """Create idempotent blocked kanban cards for MANUAL_REVIEW runs."""

    def __init__(self, config: SyncConfig) -> None:
        self.config = config

    def maybe_open(self, report: SyncReport) -> Optional[KanbanTicketResult]:
        """Open a card when enabled and decision is in create_on list.

        Returns:
            ``None`` when kanban is disabled or the decision is not eligible.
            Otherwise a :class:`KanbanTicketResult` (including soft failures).
        """
        if not self.config.kanban_enabled:
            return None
        if report.decision not in self.config.kanban_create_on:
            return None
        return self.open_for_report(report)

    def open_for_report(self, report: SyncReport) -> KanbanTicketResult:
        """Always attempt to open a card for ``report`` (ignores create_on)."""
        workspace = self.config.kanban_workspace
        workspace.mkdir(parents=True, exist_ok=True)

        date = _date_str(report.timestamp)
        upstream_short = (report.upstream_head or "unknown")[:12]
        idem = f"owner-upstream-{date}-{upstream_short}"

        reason = _primary_reason(report)
        title = f"[upstream-sync] MANUAL {date} · {reason[:60]}"
        if len(reason) > 60:
            title = title.rstrip() + "…"

        # Materialize report + meta into the shared workspace.
        md_content = ReportBuilder.build_manual_review_report(report)
        report_name = f"{date}-{upstream_short}-manual-review.md"
        report_path = workspace / report_name
        report_path.write_text(
            md_content if md_content.endswith("\n") else md_content + "\n",
            encoding="utf-8",
        )

        meta = {
            "timestamp": report.timestamp,
            "decision": report.decision,
            "pre_merge_head": report.pre_merge_head,
            "upstream_head": report.upstream_head,
            "merge_base": report.merge_base,
            "total_commits": report.total_commits,
            "reasons": list(report.classification.reasons)
            if report.classification
            else [],
            "soft_warnings": list(report.classification.soft_warnings)
            if report.classification
            else [],
            "report_file": str(report_path),
            "log_file": report.log_file,
            "idempotency_key": idem,
            "rolled_back": report.rolled_back,
            "error": report.error,
        }
        meta_path = workspace / f"{date}-{upstream_short}-meta.json"
        meta_path.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        # Pointer for humans / scripts
        latest = workspace / "LATEST.md"
        latest.write_text(
            f"# Latest upstream-sync MANUAL ticket material\n\n"
            f"- date: {date}\n"
            f"- upstream: `{report.upstream_head}`\n"
            f"- report: `{report_path.name}`\n"
            f"- meta: `{meta_path.name}`\n"
            f"- idempotency_key: `{idem}`\n"
            f"- reason: {reason}\n",
            encoding="utf-8",
        )

        body = _build_card_body(
            report=report,
            reason=reason,
            report_path=report_path,
            meta_path=meta_path,
            workspace=workspace,
            idem=idem,
        )

        return self._create_card(
            title=title,
            body=body,
            idem=idem,
            workspace=workspace,
        )

    def _create_card(
        self,
        *,
        title: str,
        body: str,
        idem: str,
        workspace: Path,
    ) -> KanbanTicketResult:
        hermes = self.config.kanban_hermes_bin
        if not shutil.which(hermes) and not Path(hermes).is_file():
            return KanbanTicketResult(
                created=False,
                task_id=None,
                title=title,
                idempotency_key=idem,
                workspace=str(workspace),
                error=f"hermes binary not found: {hermes!r}",
            )

        cmd: list[str] = [
            hermes,
            "kanban",
            "create",
            title,
            "--body",
            body,
            "--tenant",
            self.config.kanban_tenant,
            "--workspace",
            f"dir:{workspace}",
            "--idempotency-key",
            idem,
            "--priority",
            str(self.config.kanban_priority),
            "--created-by",
            self.config.kanban_created_by,
            "--initial-status",
            self.config.kanban_initial_status,
            "--json",
        ]
        if self.config.kanban_assignee:
            cmd.extend(["--assignee", self.config.kanban_assignee])
        if self.config.kanban_max_runtime:
            cmd.extend(["--max-runtime", self.config.kanban_max_runtime])

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.config.kanban_timeout_seconds,
                env=dict(os.environ),
            )
        except subprocess.TimeoutExpired as exc:
            return KanbanTicketResult(
                created=False,
                task_id=None,
                title=title,
                idempotency_key=idem,
                workspace=str(workspace),
                error=f"hermes kanban create timed out after {exc.timeout}s",
            )
        except OSError as exc:
            return KanbanTicketResult(
                created=False,
                task_id=None,
                title=title,
                idempotency_key=idem,
                workspace=str(workspace),
                error=f"failed to run hermes: {exc}",
            )

        raw = (proc.stdout or "") + (
            ("\n" + proc.stderr) if proc.stderr else ""
        )
        if proc.returncode != 0:
            return KanbanTicketResult(
                created=False,
                task_id=None,
                title=title,
                idempotency_key=idem,
                workspace=str(workspace),
                error=f"hermes kanban create exit {proc.returncode}: {raw.strip()[:500]}",
                raw_output=raw,
            )

        task_id, reused = _parse_create_json(proc.stdout)
        if not task_id:
            return KanbanTicketResult(
                created=False,
                task_id=None,
                title=title,
                idempotency_key=idem,
                workspace=str(workspace),
                error=f"could not parse task id from: {proc.stdout[:500]!r}",
                raw_output=raw,
            )

        # Side-car for cron QQ message / humans
        pointer = workspace / "latest-task.json"
        pointer.write_text(
            json.dumps(
                {
                    "task_id": task_id,
                    "title": title,
                    "idempotency_key": idem,
                    "reused": reused,
                    "updated_at": datetime.now(timezone.utc).strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    ),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        return KanbanTicketResult(
            created=not reused,
            task_id=task_id,
            title=title,
            idempotency_key=idem,
            workspace=str(workspace),
            reused=reused,
            raw_output=raw,
        )


def _date_str(timestamp: str) -> str:
    """Extract YYYY-MM-DD from an ISO timestamp, else UTC today."""
    if timestamp and len(timestamp) >= 10:
        return timestamp[:10]
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _primary_reason(report: SyncReport) -> str:
    if report.classification and report.classification.reasons:
        return report.classification.reasons[0]
    if report.error:
        return report.error
    return "需要人工确认"


def _build_card_body(
    *,
    report: SyncReport,
    reason: str,
    report_path: Path,
    meta_path: Path,
    workspace: Path,
    idem: str,
) -> str:
    hard_lines: list[str] = []
    soft_lines: list[str] = []
    if report.classification:
        for dim in report.classification.dimensions:
            if dim.triggered_red_line:
                hard_lines.append(f"- **{dim.dimension} {dim.name}**: {dim.details}")
            elif dim.soft_warning:
                soft_lines.append(f"- {dim.dimension} {dim.name}: {dim.details}")

    fp_lines: list[str] = []
    if report.classification and report.classification.fingerprint_matches:
        for m in report.classification.fingerprint_matches[:8]:
            fp_lines.append(
                f"- [{m.confidence}] {m.fingerprint_id} · "
                f"§{m.owner_commit} · sim={m.combined_similarity:.2f} · "
                f"upstream `{m.upstream_commit_hash[:12]}`"
            )

    parts = [
        "## K0 人工闸门（upstream-sync）",
        "",
        "本卡由自动同步在 **MANUAL_REVIEW** 时创建，**默认 blocked**，不自动派 worker。",
        "目标：把「可能丢 owner 改动清单」的上游窗口变成可关闭的工单。",
        "",
        "### 摘要",
        f"- 原因：{reason}",
        f"- 时间：{report.timestamp}",
        f"- 上游 HEAD：`{report.upstream_head}`",
        f"- 本地 pre-merge：`{report.pre_merge_head}`",
        f"- merge-base：`{report.merge_base}`",
        f"- 上游 commit 数：{report.total_commits}",
        f"- 已回滚：{'是' if report.rolled_back else '否/未知'}",
        f"- idempotency_key：`{idem}`",
        "",
        "### 硬红线",
    ]
    parts.extend(hard_lines or ["- （无维度明细，见报告文件）"])
    if soft_lines:
        parts.append("")
        parts.append("### 软信号（未单独阻断）")
        parts.extend(soft_lines)
    if fp_lines:
        parts.append("")
        parts.append("### 疑似重复修复")
        parts.extend(fp_lines)

    parts.extend(
        [
            "",
            "### 材料路径",
            f"- workspace：`{workspace}`",
            f"- 报告：`{report_path}`",
            f"- meta：`{meta_path}`",
            f"- 同步日志目录：`owner/logs/upstream-sync/`",
            "",
            "### 建议操作（人工）",
            "1. 读报告与 `owner/docs/owner改动清单.md` 附录 B / anchors",
            "2. 在干净的 `owner` 分支上完成 merge / 解冲突 / 适配胶水",
            "3. 跑：`python3 owner/validation/merge_health_check.py`",
            "4. 跑：`pytest tests/owner/ -x -q`（或项目约定套件）",
            "5. 指纹命中时更新 `owner/validation/fix_fingerprints.yaml` status",
            "6. 完成后：",
            "   ```bash",
            "   .venv/bin/python owner/scripts/upstream_sync.py --resolve",
            f"   hermes kanban complete <本卡id> --summary \"merged/adapted: {reason[:80]}\"",
            "   ```",
            "",
            "### 禁止",
            "- 自动 `git push`（保持手动）",
            "- 在无 D6 健康检查通过的情况下把卡标 done",
            "- 跳过改动清单对照「盲合」",
            "",
            "### 观察指标",
            "见 `owner/docs/upstream-sync-kanban.md` §观察清单。",
            "",
        ]
    )
    return "\n".join(parts)


def _parse_create_json(stdout: str) -> tuple[Optional[str], bool]:
    """Parse ``hermes kanban create --json`` stdout → (task_id, reused)."""
    text = (stdout or "").strip()
    if not text:
        return None, False
    # stdout may have leading log lines; find first JSON object
    start = text.find("{")
    if start < 0:
        return None, False
    try:
        data: Any = json.loads(text[start:])
    except json.JSONDecodeError:
        # try line-by-line
        for line in reversed(text.splitlines()):
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    data = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue
        else:
            return None, False

    if not isinstance(data, dict):
        return None, False

    task_id = (
        data.get("id")
        or data.get("task_id")
        or data.get("taskId")
    )
    if task_id is not None:
        task_id = str(task_id)

    reused = bool(
        data.get("reused")
        or data.get("idempotent_hit")
        or data.get("existing")
        or data.get("deduped")
    )
    # Some CLIs return {"task": {"id": "..."}}
    if not task_id and isinstance(data.get("task"), dict):
        task_id = data["task"].get("id") or data["task"].get("task_id")
        if task_id is not None:
            task_id = str(task_id)

    return task_id, reused
