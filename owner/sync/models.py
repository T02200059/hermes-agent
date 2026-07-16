"""Core data structures for the hermes-agent upstream sync pipeline.

All dataclasses are defined here to provide a single source of truth for the
data contracts exchanged between the orchestrator, classifier, merger, health
checker and notifier modules.

Reference: architecture doc section 3.3.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class UpstreamCommit:
    """A single upstream commit to be evaluated by the classifier."""

    hash: str
    short_hash: str
    message: str
    files: list[str]
    author: str
    date: str  # ISO 8601


@dataclass
class DimensionResult:
    """Result of a single classification dimension (D1-D7).

    Attributes:
        dimension: Dimension identifier, e.g. "D1".
        name: Human-readable name, e.g. "改动规模".
        passed: True when the dimension allows AUTO_MERGE, False when it
            triggers a red line.
        details: Human-readable explanation of the verdict.
        triggered_red_line: True when this dimension forced MANUAL_REVIEW.
    """

    dimension: str
    name: str
    passed: bool
    details: str
    triggered_red_line: bool = False


@dataclass
class FingerprintMatch:
    """A suspected duplicate bug-fix match between an upstream commit and an
    owner-local fix fingerprint."""

    fingerprint_id: str
    fingerprint_title: str
    owner_commit: str  # 改动清单章节号, e.g. "2.2.1"
    upstream_commit_hash: str
    upstream_commit_message: str
    file_intersection_rate: float
    keyword_hit_rate: float
    combined_similarity: float
    confidence: str  # "high" | "medium"


@dataclass
class ChangeClassification:
    """Aggregated classification result for a batch of upstream commits."""

    decision: str  # "AUTO_MERGE" | "MANUAL_REVIEW"
    dimensions: list[DimensionResult]
    upstream_commits: list[UpstreamCommit]
    total_files_changed: int
    total_commits: int
    reasons: list[str] = field(default_factory=list)
    fingerprint_matches: list[FingerprintMatch] = field(default_factory=list)


@dataclass
class MergeResult:
    """Outcome of a trial or completed merge."""

    success: bool
    output: str
    conflict_files: list[str] = field(default_factory=list)


@dataclass
class HealthCheckResult:
    """Result of running merge_health_check.py (D6)."""

    exit_code: int  # 0=passed, 1=failed
    passed: bool
    output: str
    summary: str


@dataclass
class TestResult:
    """Result of running the owner test suite (D7)."""

    exit_code: int
    passed: bool
    output: str
    summary: str


@dataclass
class SyncReport:
    """Full report of a single sync run.

    Optional fields are ``None`` when the corresponding stage was not reached
    (e.g. ``merge_result`` is ``None`` for a dry-run).
    """

    timestamp: str  # ISO 8601
    pre_merge_head: str
    upstream_head: str
    merge_base: str
    total_commits: int
    classification: Optional[ChangeClassification] = None
    merge_result: Optional[MergeResult] = None
    health_check: Optional[HealthCheckResult] = None
    test_result: Optional[TestResult] = None
    rolled_back: bool = False
    decision: str = "SKIPPED"  # AUTO_MERGE | MANUAL_REVIEW | SKIPPED | ERROR
    log_file: str = ""
    error: Optional[str] = None
