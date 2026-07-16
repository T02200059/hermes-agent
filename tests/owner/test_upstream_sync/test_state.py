"""Unit tests for owner.sync.state.StateManager."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from owner.sync.state import StateError, StateManager


@pytest.fixture
def state(tmp_path: Path) -> StateManager:
    return StateManager(tmp_path / "state.json")


# ── Basic load / save ──────────────────────────────────────────────────────


def test_load_state_returns_none_when_no_file(state: StateManager):
    assert state.load_state() is None


def test_save_pre_merge_and_load(state: StateManager):
    state.save_pre_merge("abc123", "2025-01-01T00:00:00Z")
    data = state.load_state()
    assert data is not None
    assert data["pre_merge_head"] == "abc123"
    assert data["timestamp"] == "2025-01-01T00:00:00Z"
    assert data["pending_review"] is False


def test_save_pre_merge_creates_parent_dirs(tmp_path: Path):
    state_file = tmp_path / "deep" / "nested" / "dir" / "state.json"
    sm = StateManager(state_file)
    sm.save_pre_merge("h", "t")
    assert state_file.exists()


def test_clear_state_removes_file(state: StateManager):
    state.save_pre_merge("h", "t")
    assert state.state_file.exists()
    state.clear_state()
    assert not state.state_file.exists()


def test_clear_state_silent_on_missing(state: StateManager):
    # Should not raise even when the file doesn't exist.
    state.clear_state()


# ── Pending review lifecycle ───────────────────────────────────────────────


def test_is_pending_review_false_initially(state: StateManager):
    assert state.is_pending_review() is False


def test_mark_pending_review_sets_flag(state: StateManager):
    state.save_pre_merge("head1", "2025-01-01T00:00:00Z")
    state.mark_pending_review("D4 conflict")
    assert state.is_pending_review() is True
    data = state.load_state()
    assert data["review_reason"] == "D4 conflict"


def test_mark_pending_review_preserves_pre_merge_head(state: StateManager):
    state.save_pre_merge("head1", "2025-01-01T00:00:00Z")
    state.mark_pending_review("some reason")
    assert state.get_pre_merge_head() == "head1"


def test_mark_resolved_clears_pending(state: StateManager):
    state.save_pre_merge("head1", "2025-01-01T00:00:00Z")
    state.mark_pending_review("reason")
    assert state.is_pending_review() is True
    state.mark_resolved()
    assert state.is_pending_review() is False
    assert not state.state_file.exists()


def test_mark_pending_review_empty_reason(state: StateManager):
    state.save_pre_merge("h", "t")
    state.mark_pending_review("")
    data = state.load_state()
    assert data["pending_review"] is True
    assert data["review_reason"] is None


def test_mark_pending_review_without_prior_state(state: StateManager):
    # No save_pre_merge called first — should still work.
    state.mark_pending_review("reason")
    assert state.is_pending_review() is True


# ── Report path ────────────────────────────────────────────────────────────


def test_save_report_path(state: StateManager):
    state.save_pre_merge("h", "t")
    state.save_report_path("/some/report.md")
    data = state.load_state()
    assert data["report_path"] == "/some/report.md"


def test_get_pre_merge_head_returns_none_when_no_state(state: StateManager):
    assert state.get_pre_merge_head() is None


# ── Error handling ─────────────────────────────────────────────────────────


def test_load_state_raises_on_invalid_json(tmp_path: Path):
    state_file = tmp_path / "state.json"
    state_file.write_text("{not valid json", encoding="utf-8")
    sm = StateManager(state_file)
    with pytest.raises(StateError, match="not valid JSON"):
        sm.load_state()


def test_load_state_raises_on_non_dict_json(tmp_path: Path):
    state_file = tmp_path / "state.json"
    state_file.write_text("[1, 2, 3]", encoding="utf-8")
    sm = StateManager(state_file)
    with pytest.raises(StateError, match="must contain a JSON object"):
        sm.load_state()


# ── Atomic write ───────────────────────────────────────────────────────────


def test_atomic_write_no_tmp_residue(state: StateManager):
    state.save_pre_merge("h", "t")
    # The .tmp file should have been renamed, not left behind.
    tmp_file = state.state_file.with_suffix(state.state_file.suffix + ".tmp")
    assert not tmp_file.exists()


def test_atomic_write_content_is_valid_json(state: StateManager):
    state.save_pre_merge("head123", "2025-01-01T00:00:00Z")
    content = state.state_file.read_text(encoding="utf-8")
    # Must be parseable JSON.
    data = json.loads(content)
    assert data["pre_merge_head"] == "head123"
