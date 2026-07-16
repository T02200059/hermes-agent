"""Unit tests for owner.sync.fingerprint.FingerprintDetector."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from owner.sync.config import SyncConfig
from owner.sync.fingerprint import FingerprintDetector
from owner.sync.models import UpstreamCommit
from tests.owner.test_upstream_sync.conftest import (
    build_raw_config,
    write_fingerprints,
)


def _commit(hash_: str, files: list[str], message: str) -> UpstreamCommit:
    return UpstreamCommit(
        hash=hash_,
        short_hash=hash_[:7],
        message=message,
        files=files,
        author="dev",
        date="2025-01-01T00:00:00Z",
    )


def _make_detector(tmp_path: Path, fixes: list[dict[str, Any]]) -> FingerprintDetector:
    write_fingerprints(tmp_path, fixes)
    cfg = SyncConfig(build_raw_config(tmp_path))
    return FingerprintDetector(cfg)


# ── load_fingerprints ──────────────────────────────────────────────────────


def test_load_only_active_fingerprints(tmp_path: Path):
    fixes = [
        {"id": "fp-1", "status": "active", "fixed_files": ["a.py"], "fix_keywords": ["kw1"]},
        {"id": "fp-2", "status": "superseded", "fixed_files": ["b.py"], "fix_keywords": ["kw2"]},
        {"id": "fp-3", "status": "active", "fixed_files": ["c.py"], "fix_keywords": ["kw3"]},
    ]
    det = _make_detector(tmp_path, fixes)
    active = det.load_fingerprints()
    assert len(active) == 2
    assert {fp["id"] for fp in active} == {"fp-1", "fp-3"}


def test_load_fingerprints_empty_when_no_file(tmp_path: Path):
    cfg = SyncConfig(build_raw_config(tmp_path))
    det = FingerprintDetector(cfg)
    assert det.load_fingerprints() == []


def test_load_fingerprints_cached(tmp_path: Path):
    det = _make_detector(tmp_path, [
        {"id": "fp-1", "status": "active", "fixed_files": ["a.py"], "fix_keywords": ["k"]},
    ])
    first = det.load_fingerprints()
    second = det.load_fingerprints()
    assert first is second  # same list object — cached


def test_superseded_not_participating_in_detect(tmp_path: Path):
    fixes = [
        {
            "id": "fp-superseded",
            "title": "old fix",
            "owner_commit": "1.0",
            "status": "superseded",
            "fixed_files": ["a.py", "b.py"],
            "fix_keywords": ["kw1", "kw2"],
        },
    ]
    det = _make_detector(tmp_path, fixes)
    commit = _commit("h1", ["a.py", "b.py"], "fix kw1 kw2")
    matches = det.detect([commit])
    assert matches == []


# ── detect: file intersection rate ─────────────────────────────────────────


def test_full_file_intersection(tmp_path: Path):
    fixes = [{
        "id": "fp-1", "title": "bug", "owner_commit": "2.2.1",
        "status": "active",
        "fixed_files": ["a.py", "b.py"],
        "fix_keywords": [],
    }]
    det = _make_detector(tmp_path, fixes)
    commit = _commit("h1", ["a.py", "b.py", "c.py"], "msg")
    matches = det.detect([commit])
    assert len(matches) == 1
    # file_rate = 2/2 = 1.0, kw_rate = 0.0 → combined = 1.0*0.6 + 0*0.4 = 0.6
    assert matches[0].file_intersection_rate == 1.0
    assert matches[0].combined_similarity == pytest.approx(0.6)
    assert matches[0].confidence == "medium"  # 0.6 > 0.5, ≤ 0.8


def test_partial_file_intersection(tmp_path: Path):
    fixes = [{
        "id": "fp-1", "title": "bug", "owner_commit": "2.2.1",
        "status": "active",
        "fixed_files": ["a.py", "b.py", "c.py", "d.py"],
        "fix_keywords": [],
    }]
    det = _make_detector(tmp_path, fixes)
    commit = _commit("h1", ["a.py", "b.py"], "msg")
    matches = det.detect([commit])
    # file_rate = 2/4 = 0.5, kw_rate = 0 → combined = 0.5*0.6 = 0.3 ≤ 0.5 → not reported
    assert matches == []


def test_no_file_intersection(tmp_path: Path):
    fixes = [{
        "id": "fp-1", "title": "bug", "owner_commit": "2.2.1",
        "status": "active",
        "fixed_files": ["x.py", "y.py"],
        "fix_keywords": [],
    }]
    det = _make_detector(tmp_path, fixes)
    commit = _commit("h1", ["a.py", "b.py"], "msg")
    matches = det.detect([commit])
    assert matches == []


# ── detect: keyword hit rate ───────────────────────────────────────────────


def test_full_keyword_hits_below_threshold(tmp_path: Path):
    """Full keyword hits but no file intersection → combined 0.4 ≤ 0.5, not reported."""
    fixes = [{
        "id": "fp-1", "title": "bug", "owner_commit": "2.2.1",
        "status": "active",
        "fixed_files": [],
        "fix_keywords": ["api_key", "seed", "copilot"],
    }]
    det = _make_detector(tmp_path, fixes)
    commit = _commit("h1", [], "fix api_key seeding for copilot")
    matches = det.detect([commit])
    # kw_rate = 3/3 = 1.0, file_rate = 0 → combined = 0*0.6 + 1.0*0.4 = 0.4 ≤ 0.5 → not reported
    assert matches == []


def test_keyword_hits_above_threshold(tmp_path: Path):
    fixes = [{
        "id": "fp-1", "title": "bug", "owner_commit": "2.2.1",
        "status": "active",
        "fixed_files": ["a.py"],
        "fix_keywords": ["api_key", "seed", "copilot"],
    }]
    det = _make_detector(tmp_path, fixes)
    commit = _commit("h1", ["a.py"], "fix api_key seeding for copilot")
    matches = det.detect([commit])
    # file_rate = 1/1 = 1.0, kw_rate = 3/3 = 1.0
    # combined = 1.0*0.6 + 1.0*0.4 = 1.0 → high confidence
    assert len(matches) == 1
    assert matches[0].combined_similarity == pytest.approx(1.0)
    assert matches[0].confidence == "high"


def test_partial_keyword_hits(tmp_path: Path):
    fixes = [{
        "id": "fp-1", "title": "bug", "owner_commit": "2.2.1",
        "status": "active",
        "fixed_files": ["a.py", "b.py"],
        "fix_keywords": ["api_key", "seed", "copilot", "ghp_"],
    }]
    det = _make_detector(tmp_path, fixes)
    # Touch both files (file_rate=1.0), hit 2 of 4 keywords (kw_rate=0.5)
    commit = _commit("h1", ["a.py", "b.py"], "fix api_key and seed")
    matches = det.detect([commit])
    # combined = 1.0*0.6 + 0.5*0.4 = 0.6 + 0.2 = 0.8 → high (>0.8? no, ==0.8, not >0.8)
    # 0.8 > 0.5 → reported, 0.8 is NOT > 0.8 → medium
    assert len(matches) == 1
    assert matches[0].combined_similarity == pytest.approx(0.8)
    assert matches[0].confidence == "medium"


# ── detect: combined similarity formula ────────────────────────────────────


def test_combined_similarity_formula(tmp_path: Path):
    fixes = [{
        "id": "fp-1", "title": "bug", "owner_commit": "2.2.1",
        "status": "active",
        "fixed_files": ["a.py", "b.py", "c.py"],
        "fix_keywords": ["kw1", "kw2"],
    }]
    det = _make_detector(tmp_path, fixes)
    # file_rate = 2/3, kw_rate = 1/2
    commit = _commit("h1", ["a.py", "b.py"], "fix kw1 here")
    matches = det.detect([commit])
    expected = (2 / 3) * 0.6 + (1 / 2) * 0.4  # 0.4 + 0.2 = 0.6
    assert len(matches) == 1
    assert matches[0].combined_similarity == pytest.approx(expected)
    assert matches[0].confidence == "medium"


# ── detect: confidence thresholds ──────────────────────────────────────────


def test_confidence_high_above_08(tmp_path: Path):
    fixes = [{
        "id": "fp-1", "title": "t", "owner_commit": "1",
        "status": "active",
        "fixed_files": ["a.py"],
        "fix_keywords": ["k1", "k2"],
    }]
    det = _make_detector(tmp_path, fixes)
    commit = _commit("h1", ["a.py"], "k1 k2")
    # combined = 1.0*0.6 + 1.0*0.4 = 1.0 > 0.8 → high
    matches = det.detect([commit])
    assert matches[0].confidence == "high"


def test_confidence_medium_05_to_08(tmp_path: Path):
    fixes = [{
        "id": "fp-1", "title": "t", "owner_commit": "1",
        "status": "active",
        "fixed_files": ["a.py", "b.py"],
        "fix_keywords": [],
    }]
    det = _make_detector(tmp_path, fixes)
    commit = _commit("h1", ["a.py", "b.py"], "msg")
    # combined = 1.0*0.6 + 0*0.4 = 0.6, 0.5 < 0.6 ≤ 0.8 → medium
    matches = det.detect([commit])
    assert matches[0].confidence == "medium"


def test_not_reported_below_05(tmp_path: Path):
    fixes = [{
        "id": "fp-1", "title": "t", "owner_commit": "1",
        "status": "active",
        "fixed_files": ["a.py", "b.py", "c.py", "d.py"],
        "fix_keywords": [],
    }]
    det = _make_detector(tmp_path, fixes)
    commit = _commit("h1", ["a.py"], "msg")
    # file_rate = 1/4 = 0.25, combined = 0.25*0.6 = 0.15 ≤ 0.5 → not reported
    matches = det.detect([commit])
    assert matches == []


# ── detect: edge cases ─────────────────────────────────────────────────────


def test_empty_commits_returns_empty(tmp_path: Path):
    det = _make_detector(tmp_path, [
        {"id": "fp-1", "status": "active", "fixed_files": ["a.py"], "fix_keywords": ["k"]},
    ])
    assert det.detect([]) == []


def test_empty_fingerprints_returns_empty(tmp_path: Path):
    cfg = SyncConfig(build_raw_config(tmp_path))
    det = FingerprintDetector(cfg)
    commit = _commit("h1", ["a.py"], "msg")
    assert det.detect([commit]) == []


def test_results_sorted_by_descending_similarity(tmp_path: Path):
    fixes = [
        {
            "id": "fp-low", "title": "low", "owner_commit": "1",
            "status": "active",
            "fixed_files": ["a.py", "b.py"],
            "fix_keywords": [],
        },
        {
            "id": "fp-high", "title": "high", "owner_commit": "2",
            "status": "active",
            "fixed_files": ["a.py"],
            "fix_keywords": ["kw1", "kw2"],
        },
    ]
    det = _make_detector(tmp_path, fixes)
    commit = _commit("h1", ["a.py", "b.py"], "kw1 kw2")
    matches = det.detect([commit])
    assert len(matches) == 2
    # fp-high: 1.0*0.6 + 1.0*0.4 = 1.0
    # fp-low:  1.0*0.6 + 0*0.4 = 0.6
    assert matches[0].fingerprint_id == "fp-high"
    assert matches[1].fingerprint_id == "fp-low"
    assert matches[0].combined_similarity > matches[1].combined_similarity


def test_match_fields_populated(tmp_path: Path):
    fixes = [{
        "id": "fp-1", "title": "credential bug", "owner_commit": "2.2.1",
        "status": "active",
        "fixed_files": ["a.py"],
        "fix_keywords": ["kw1"],
    }]
    det = _make_detector(tmp_path, fixes)
    commit = _commit("abc123def", ["a.py"], "fix kw1 issue")
    matches = det.detect([commit])
    m = matches[0]
    assert m.fingerprint_id == "fp-1"
    assert m.fingerprint_title == "credential bug"
    assert m.owner_commit == "2.2.1"
    assert m.upstream_commit_hash == "abc123def"
    assert m.upstream_commit_message == "fix kw1 issue"


def test_keyword_matching_is_case_insensitive(tmp_path: Path):
    fixes = [{
        "id": "fp-1", "title": "t", "owner_commit": "1",
        "status": "active",
        "fixed_files": ["a.py"],
        "fix_keywords": ["API_KEY", "Copilot"],
    }]
    det = _make_detector(tmp_path, fixes)
    commit = _commit("h1", ["a.py"], "fix api_key for copilot")
    matches = det.detect([commit])
    # kw_rate = 2/2 = 1.0, file_rate = 1.0 → combined = 1.0 → high
    assert len(matches) == 1
    assert matches[0].keyword_hit_rate == pytest.approx(1.0)
