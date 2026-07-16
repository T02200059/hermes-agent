"""Persistent state management for the upstream sync pipeline.

The :class:`StateManager` persists the pre-merge HEAD, the pending-review flag
and the last report path to ``.sync_state.json`` (location configured in
``upstream_sync.yaml``). Writes are atomic: the file is first written to a
``.tmp`` sibling and then ``os.replace``-d over the target so a crash mid-write
never leaves a truncated state file.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional


class StateError(RuntimeError):
    """Raised on state file read/write failures."""


class StateManager:
    """Manage ``.sync_state.json`` with atomic writes.

    State schema (see architecture doc section 8.6)::

        {
          "pre_merge_head": "<hash>",
          "timestamp": "<ISO8601>",
          "pending_review": false,
          "review_reason": null,
          "report_path": "<path>"
        }
    """

    def __init__(self, state_file: Path | str) -> None:
        """Initialize the state manager.

        Args:
            state_file: Absolute path to the state JSON file. Parent
                directories are created on first write.
        """
        self.state_file: Path = Path(state_file)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _ensure_parent(self) -> None:
        """Create the parent directory of the state file if missing."""
        parent = self.state_file.parent
        parent.mkdir(parents=True, exist_ok=True)

    def _atomic_write(self, data: dict[str, Any]) -> None:
        """Atomically write ``data`` to the state file.

        Writes to ``<state_file>.tmp`` then ``os.replace`` over the target.

        Raises:
            StateError: If the write or rename fails.
        """
        self._ensure_parent()
        tmp_path = self.state_file.with_suffix(self.state_file.suffix + ".tmp")
        try:
            with tmp_path.open("w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path, self.state_file)
        except OSError as exc:
            # Best-effort cleanup of the temp file.
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass
            raise StateError(f"Failed to write state file {self.state_file}: {exc}") from exc

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def save_pre_merge(self, head: str, timestamp: str) -> None:
        """Record the pre-merge HEAD and timestamp, clearing pending review.

        Args:
            head: The HEAD hash captured immediately before a merge attempt.
            timestamp: ISO 8601 timestamp of the sync run.
        """
        data: dict[str, Any] = {
            "pre_merge_head": head,
            "timestamp": timestamp,
            "pending_review": False,
            "review_reason": None,
            "report_path": None,
        }
        self._atomic_write(data)

    def load_state(self) -> Optional[dict[str, Any]]:
        """Load and return the current state, or ``None`` if no state file.

        Returns:
            The parsed state dict, or ``None`` when the file does not exist.

        Raises:
            StateError: If the file exists but cannot be parsed as JSON.
        """
        if not self.state_file.exists():
            return None
        try:
            with self.state_file.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except json.JSONDecodeError as exc:
            raise StateError(
                f"State file {self.state_file} is not valid JSON: {exc}"
            ) from exc
        if not isinstance(data, dict):
            raise StateError(
                f"State file {self.state_file} must contain a JSON object"
            )
        return data

    def clear_state(self) -> None:
        """Remove the state file.

        Called after a successful AUTO_MERGE so the next run starts clean.
        Missing files are silently ignored.
        """
        if self.state_file.exists():
            try:
                self.state_file.unlink()
            except OSError as exc:
                raise StateError(
                    f"Failed to remove state file {self.state_file}: {exc}"
                ) from exc

    def is_pending_review(self) -> bool:
        """Return True when a previous run left a pending manual review."""
        state = self.load_state()
        if state is None:
            return False
        return bool(state.get("pending_review", False))

    def mark_pending_review(self, reason: str = "") -> None:
        """Flag the current state as awaiting manual review.

        Preserves the pre-merge HEAD so a later ``--resolve`` knows what to
        reset to if needed, and records the triggering reason.

        Args:
            reason: Human-readable description of why manual review is needed.
        """
        state = self.load_state() or {}
        state["pending_review"] = True
        state["review_reason"] = reason or None
        self._atomic_write(state)

    def mark_resolved(self) -> None:
        """Clear the pending-review flag and drop the state file.

        After this the next cron run will proceed normally.
        """
        self.clear_state()

    def save_report_path(self, path: str) -> None:
        """Persist the path to the most recent report file.

        Args:
            path: Relative or absolute path to the report Markdown file.
        """
        state = self.load_state() or {}
        state["report_path"] = path
        self._atomic_write(state)

    def get_pre_merge_head(self) -> Optional[str]:
        """Return the recorded pre-merge HEAD, or ``None`` if unavailable."""
        state = self.load_state()
        if state is None:
            return None
        return state.get("pre_merge_head")
