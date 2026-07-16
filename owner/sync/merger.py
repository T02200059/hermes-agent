"""Merge execution and rollback.

:class:`Merger` is a thin facade over :class:`GitOps` that encapsulates the
merge lifecycle used by the orchestrator:

    try_merge()  → stage a merge without committing (D4 pre-check)
    complete()   → finalize the staged merge with ``git commit --no-edit``
    rollback()   → ``git merge --abort`` first, fall back to
                   ``git reset --hard <pre_merge_head>`` from the state file

The double-layered rollback guarantees recovery even when the index is in an
unexpected state (e.g. ``--abort`` fails because MERGE_HEAD is already gone).
"""

from __future__ import annotations

from owner.sync.config import SyncConfig
from owner.sync.gitops import GitError, GitOps
from owner.sync.models import MergeResult
from owner.sync.state import StateManager


class Merger:
    """Drive the git merge lifecycle with safe rollback."""

    def __init__(
        self,
        config: SyncConfig,
        gitops: GitOps,
        state: StateManager,
    ) -> None:
        """Initialize the merger.

        Args:
            config: Loaded :class:`SyncConfig`.
            gitops: :class:`GitOps` bound to the repository.
            state: :class:`StateManager` for pre-merge HEAD recovery.
        """
        self.config: SyncConfig = config
        self.gitops: GitOps = gitops
        self.state: StateManager = state

    def try_merge(self) -> MergeResult:
        """Stage a trial merge without committing.

        Delegates to :meth:`GitOps.try_merge_no_commit`. When the merge
        succeeds the result is staged in the index (HEAD unchanged) so D6/D7
        can run against the merged tree.

        Returns:
            A :class:`MergeResult` describing the outcome.
        """
        success, output, conflict_files = self.gitops.try_merge_no_commit()
        return MergeResult(
            success=success,
            output=output,
            conflict_files=conflict_files,
        )

    def complete(self) -> None:
        """Finalize a staged merge with ``git commit --no-edit``.

        Called only after D6 and D7 have both passed.

        Raises:
            GitError: If the commit fails.
        """
        self.gitops.complete_merge()

    def rollback(self) -> None:
        """Roll back to the pre-merge HEAD with double-layered safety.

        First attempts ``git merge --abort`` (works while a merge is staged).
        If that fails — e.g. because MERGE_HEAD no longer exists — falls back
        to ``git reset --hard <pre_merge_head>`` using the HEAD recorded by
        :class:`StateManager`.
        """
        # Layer 1: abort an in-progress merge (no-op if none is in progress).
        try:
            if self.gitops.is_merge_in_progress():
                self.gitops.abort_merge()
                return
        except GitError:
            # abort failed; fall through to hard reset.
            pass

        # Layer 2: hard reset to the recorded pre-merge HEAD.
        pre_merge_head = self.state.get_pre_merge_head()
        if pre_merge_head:
            self.gitops.reset_hard(pre_merge_head)
        else:
            # No recorded HEAD and no merge to abort — nothing we can safely do.
            raise GitError(
                "rollback failed: no merge in progress and no pre_merge_head "
                "recorded in state file"
            )
