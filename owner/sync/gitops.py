"""Git operations wrapper for the upstream sync pipeline.

All git interactions go through :class:`GitOps` so that command construction,
environment handling and error reporting stay consistent. Every subprocess
call sets ``GIT_TERMINAL_PROMPT=0`` to prevent the process from blocking on
interactive credential prompts.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional

from owner.sync.config import SyncConfig
from owner.sync.models import UpstreamCommit


class GitError(RuntimeError):
    """Raised when a git command fails."""


class GitOps:
    """Thin, well-tested wrapper around the git CLI.

    The wrapper never pushes, never force-pushes and never modifies the
    upstream remote. All commands run with ``cwd=repo_root`` and
    ``GIT_TERMINAL_PROMPT=0``.
    """

    def __init__(self, repo_root: Path, config: SyncConfig) -> None:
        """Initialize the git wrapper.

        Args:
            repo_root: Absolute path to the repository root.
            config: Loaded :class:`SyncConfig`.
        """
        self.repo_root: Path = repo_root
        self.config: SyncConfig = config

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _env(self) -> dict[str, str]:
        """Build the subprocess environment, disabling git prompts."""
        env = dict(os.environ)
        env["GIT_TERMINAL_PROMPT"] = "0"
        return env

    def _run(
        self,
        args: list[str],
        *,
        check: bool = True,
        timeout: Optional[int] = None,
    ) -> subprocess.CompletedProcess[str]:
        """Run a git command and return the completed process.

        Args:
            args: git subcommand arguments, e.g. ``["fetch", "upstream"]``.
            check: When True, raise :class:`GitError` on non-zero exit.
            timeout: Optional subprocess timeout in seconds.

        Returns:
            The completed :class:`subprocess.CompletedProcess`.

        Raises:
            GitError: When the command fails and ``check`` is True.
        """
        cmd = ["git", *args]
        try:
            result = subprocess.run(
                cmd,
                cwd=str(self.repo_root),
                env=self._env(),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except FileNotFoundError as exc:
            raise GitError(f"git executable not found: {exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise GitError(
                f"git command timed out after {timeout}s: {' '.join(args)}"
            ) from exc

        if check and result.returncode != 0:
            stderr = result.stderr.strip()
            stdout = result.stdout.strip()
            detail = stderr or stdout or "(no output)"
            raise GitError(
                f"git {' '.join(args)} failed (exit {result.returncode}): {detail}"
            )
        return result

    # ------------------------------------------------------------------
    # Read-only queries
    # ------------------------------------------------------------------
    def fetch_upstream(self) -> None:
        """Fetch the upstream remote quietly."""
        self._run(["fetch", self.config.upstream_remote, "--quiet"])

    def get_merge_base(self, branch: Optional[str] = None) -> str:
        """Return the merge-base hash between ``owner`` and upstream.

        Args:
            branch: Optional branch to compare against; defaults to the
                configured ``upstream_remote/upstream_branch``.

        Returns:
            The merge-base commit hash as a string.
        """
        ref = branch or self.config.upstream_ref
        result = self._run(
            ["merge-base", "HEAD", ref], check=True
        )
        return result.stdout.strip()

    def get_upstream_head(self) -> str:
        """Return the current HEAD of ``upstream/upstream_branch``."""
        result = self._run(
            ["rev-parse", self.config.upstream_ref], check=True
        )
        return result.stdout.strip()

    def get_current_head(self) -> str:
        """Return the current HEAD hash of the working repository."""
        result = self._run(["rev-parse", "HEAD"], check=True)
        return result.stdout.strip()

    def get_owner_branch(self) -> str:
        """Return the name of the currently checked-out branch."""
        result = self._run(
            ["rev-parse", "--abbrev-ref", "HEAD"], check=True
        )
        return result.stdout.strip()

    def is_workdir_clean(self) -> bool:
        """Return True when ``git status --porcelain`` produces no output."""
        result = self._run(["status", "--porcelain"], check=True)
        return result.stdout.strip() == ""

    def get_new_commits(self, since: str) -> list[UpstreamCommit]:
        """Return upstream commits newer than ``since`` (the merge-base).

        Commits are returned oldest-first so callers see them in chronological
        order. Each commit is enriched with its modified file list.

        Args:
            since: The merge-base hash.

        Returns:
            List of :class:`UpstreamCommit` ordered oldest → newest.
        """
        # Use a unique record/field separator to avoid parsing ambiguity.
        record_sep = "\x1e"
        field_sep = "\x1f"
        fmt = f"{record_sep}%H{field_sep}%h{field_sep}%an{field_sep}%aI{field_sep}%B"
        result = self._run(
            [
                "log",
                f"--format={fmt}",
                f"{since}..{self.config.upstream_ref}",
            ],
            check=True,
        )
        commits: list[UpstreamCommit] = []
        raw = result.stdout
        if not raw.strip():
            return commits
        # The leading record separator may produce an empty first record.
        records = [r for r in raw.split(record_sep) if r.strip()]
        for record in records:
            parts = record.split(field_sep)
            if len(parts) < 5:
                continue
            full_hash, short_hash, author, date, message = parts[:5]
            commit_hash = full_hash.strip()
            files = self.get_commit_files(commit_hash)
            commits.append(
                UpstreamCommit(
                    hash=commit_hash,
                    short_hash=short_hash.strip(),
                    message=message.strip(),
                    files=files,
                    author=author.strip(),
                    date=date.strip(),
                )
            )
        # git log returns newest-first; reverse for chronological order.
        commits.reverse()
        return commits

    def get_changed_files(self, base: str, head: str) -> list[str]:
        """Return the list of files changed between ``base`` and ``head``."""
        result = self._run(
            ["diff", "--name-only", base, head], check=True
        )
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def get_commit_files(self, commit_hash: str) -> list[str]:
        """Return the list of files modified by a single commit."""
        result = self._run(
            ["show", "--no-patch", "--name-only", "--format=", commit_hash],
            check=True,
        )
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def get_commit_message(self, commit_hash: str) -> str:
        """Return the full commit message for a single commit."""
        result = self._run(
            ["log", "-1", "--format=%B", commit_hash], check=True
        )
        return result.stdout.strip()

    # ------------------------------------------------------------------
    # Merge lifecycle
    # ------------------------------------------------------------------
    def try_merge_no_commit(self) -> tuple[bool, str, list[str]]:
        """Trial-merge upstream without committing.

        Runs ``git merge --no-commit --no-ff <upstream_ref>``. On success the
        merge result is staged in the index but HEAD is unchanged, so D6/D7
        can run against the merged tree. On conflict the caller must invoke
        :meth:`abort_merge` to restore the working tree.

        Returns:
            A ``(success, output, conflict_files)`` tuple. ``conflict_files``
            is populated from ``git diff --name-only --diff-filter=U`` when the
            merge fails.
        """
        result = self._run(
            [
                "merge",
                "--no-commit",
                "--no-ff",
                self.config.upstream_ref,
            ],
            check=False,
        )
        output = (result.stdout + result.stderr).strip()
        if result.returncode == 0:
            return True, output, []

        # On conflict, gather the list of conflicted (unmerged) files.
        conflict_files: list[str] = []
        diff = self._run(
            ["diff", "--name-only", "--diff-filter=U"], check=False
        )
        conflict_files = [
            line.strip() for line in diff.stdout.splitlines() if line.strip()
        ]
        return False, output, conflict_files

    def complete_merge(self) -> None:
        """Finalize a staged merge with ``git commit --no-edit``."""
        self._run(["commit", "--no-edit"], check=True)

    def abort_merge(self) -> None:
        """Abort an in-progress merge (``git merge --abort``).

        Raises :class:`GitError` if no merge is in progress, so callers can
        detect this case and fall back to :meth:`reset_hard`.
        """
        self._run(["merge", "--abort"], check=True)

    def reset_hard(self, target: str) -> None:
        """Hard reset HEAD and the working tree to ``target``."""
        self._run(["reset", "--hard", target], check=True)

    def is_merge_in_progress(self) -> bool:
        """Return True if a merge is currently in progress (MERGE_HEAD exists)."""
        result = self._run(
            ["rev-parse", "--verify", "-q", "MERGE_HEAD"], check=False
        )
        return result.returncode == 0
