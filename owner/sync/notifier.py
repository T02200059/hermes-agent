"""Notification layer (Strategy pattern).

Two implementations ship today:

    LogNotifier      — P0, writes Markdown reports + JSONL structured logs
                       to ``owner/logs/upstream-sync/``.
    FeishuNotifier   — P2 placeholder; only instantiated when a webhook URL
                       is configured.

The orchestrator registers notifiers at construction time and fans each
report out to all of them. JSONL lines are machine-readable and feed the
P2-03 weekly statistics report.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from owner.sync.config import SyncConfig
from owner.sync.models import SyncReport
from owner.sync.report import ReportBuilder


class Notifier(ABC):
    """Abstract notification sink."""

    @abstractmethod
    def notify_success(self, report: SyncReport) -> None:
        """Send a lightweight AUTO_MERGE success notification."""

    @abstractmethod
    def notify_manual_review(self, report: SyncReport) -> None:
        """Send a detailed MANUAL_REVIEW notification."""

    @abstractmethod
    def notify_error(self, report: SyncReport) -> None:
        """Send an ERROR/SKIPPED notification."""


class LogNotifier(Notifier):
    """Write Markdown reports and JSONL structured logs to disk.

    Files produced per run (date = report timestamp date)::

        <date>-auto.md            AUTO_MERGE success report
        <date>-manual-review.md   MANUAL_REVIEW detailed report
        <date>-error.md           ERROR/SKIPPED report
        <date>.jsonl              one structured line per run (appended)
    """

    def __init__(self, config: SyncConfig) -> None:
        """Initialize the log notifier.

        Args:
            config: Loaded :class:`SyncConfig`.
        """
        self.config: SyncConfig = config
        self.log_dir: Path = config.log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Notifier interface
    # ------------------------------------------------------------------
    def notify_success(self, report: SyncReport) -> None:
        """Write the success Markdown report + a JSONL line."""
        content = ReportBuilder.build_success_report(report)
        date = self._date_str(report.timestamp)
        self._write_log(f"{date}-auto.md", content)
        self._write_jsonl(report)

    def notify_manual_review(self, report: SyncReport) -> None:
        """Write the manual-review Markdown report + a JSONL line."""
        content = ReportBuilder.build_manual_review_report(report)
        date = self._date_str(report.timestamp)
        path = self._write_log(f"{date}-manual-review.md", content)
        report.log_file = str(path)
        self._write_jsonl(report)

    def notify_error(self, report: SyncReport) -> None:
        """Write the error Markdown report + a JSONL line."""
        content = ReportBuilder.build_error_report(report)
        date = self._date_str(report.timestamp)
        path = self._write_log(f"{date}-error.md", content)
        report.log_file = str(path)
        self._write_jsonl(report)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _write_log(self, filename: str, content: str) -> Path:
        """Write ``content`` to ``log_dir/filename`` and return the path."""
        target = self.log_dir / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as fh:
            fh.write(content)
            if not content.endswith("\n"):
                fh.write("\n")
        return target

    def _write_jsonl(self, report: SyncReport) -> None:
        """Append one structured JSON line summarising the run."""
        date = self._date_str(report.timestamp)
        jsonl_path = self.log_dir / f"{date}.jsonl"
        record = self._build_jsonl_record(report)
        with jsonl_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False))
            fh.write("\n")

    def _build_jsonl_record(self, report: SyncReport) -> dict[str, Any]:
        """Build the JSONL record dict for a report."""
        classification = report.classification
        health = report.health_check
        tests = report.test_result
        return {
            "timestamp": report.timestamp,
            "decision": report.decision,
            "total_commits": report.total_commits,
            "pre_merge_head": report.pre_merge_head,
            "upstream_head": report.upstream_head,
            "merge_base": report.merge_base,
            "health_check_passed": health.passed if health else None,
            "test_passed": tests.passed if tests else None,
            "rolled_back": report.rolled_back,
            "fingerprint_matches": (
                len(classification.fingerprint_matches)
                if classification
                else 0
            ),
            "classification_decision": (
                classification.decision if classification else None
            ),
            "log_file": report.log_file,
            "error": report.error,
        }

    @staticmethod
    def _date_str(timestamp: str) -> str:
        """Extract the ``YYYY-MM-DD`` prefix from an ISO 8601 timestamp.

        Falls back to the current UTC date when the timestamp is empty or
        unparseable.
        """
        if not timestamp:
            return datetime.now(timezone.utc).strftime("%Y-%m-%d")
        try:
            # Accept both "YYYY-MM-DDTHH:MM:SS" and trailing "Z"/offset.
            return timestamp.split("T")[0][:10]
        except Exception:
            return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class FeishuNotifier(Notifier):
    """Placeholder Feishu webhook notifier (P2).

    Only instantiated when ``config.feishu_webhook`` is non-empty. The actual
    HTTP call is intentionally not implemented yet; this class exists so the
    orchestrator can register it and the webhook wiring is ready for a future
    sprint. For now it logs the intent to the standard log dir.
    """

    def __init__(self, config: SyncConfig) -> None:
        """Initialize the Feishu notifier.

        Args:
            config: Loaded :class:`SyncConfig` with a non-empty
                ``feishu_webhook``.
        """
        self.config: SyncConfig = config
        self.webhook_url: str = config.feishu_webhook

    def notify_success(self, report: SyncReport) -> None:
        """P2 placeholder — would POST a success card to the webhook."""
        # Intentionally a no-op until the card schema is finalized.
        return

    def notify_manual_review(self, report: SyncReport) -> None:
        """P2 placeholder — would POST a review card to the webhook."""
        return

    def notify_error(self, report: SyncReport) -> None:
        """P2 placeholder — would POST an error card to the webhook."""
        return


def build_notifiers(config: SyncConfig) -> list[Notifier]:
    """Build the active notifier list based on config.

    ``LogNotifier`` is always registered. ``FeishuNotifier`` is only added
    when ``config.feishu_webhook`` is non-empty.

    Args:
        config: Loaded :class:`SyncConfig`.

    Returns:
        Ordered list of notifiers (log first, feishu last).
    """
    notifiers: list[Notifier] = [LogNotifier(config)]
    if config.feishu_webhook:
        notifiers.append(FeishuNotifier(config))
    return notifiers
