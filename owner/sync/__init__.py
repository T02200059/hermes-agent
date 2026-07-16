"""hermes-agent upstream sync package.

Public API exported here so callers can do::

    from owner.sync import SyncConfig, GitOps, StateManager
    from owner.sync import UpstreamSyncOrchestrator
"""

from __future__ import annotations

from owner.sync.config import SyncConfig
from owner.sync.gitops import GitError, GitOps
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
from owner.sync.state import StateError, StateManager

__all__ = [
    # Config
    "SyncConfig",
    # Git
    "GitOps",
    "GitError",
    # State
    "StateManager",
    "StateError",
    # Models
    "UpstreamCommit",
    "DimensionResult",
    "FingerprintMatch",
    "ChangeClassification",
    "MergeResult",
    "HealthCheckResult",
    "TestResult",
    "SyncReport",
]

__version__ = "1.0.0"
