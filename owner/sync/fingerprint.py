"""Bug duplicate-fix fingerprint detection.

Maintains an in-memory view of ``fix_fingerprints.yaml`` (active entries only)
and scores each upstream commit against each fingerprint using a weighted
combination of file-intersection rate and keyword-hit rate.

Scoring (architecture doc section 6.2.2)::

    file_intersection_rate = |commit.files ∩ fp.fixed_files| / |fp.fixed_files|
    keyword_hit_rate       = |fp.fix_keywords present in commit.message| / |fp.fix_keywords|
    combined_similarity    = file_rate * file_weight + kw_rate * keyword_weight

Only matches with ``combined_similarity > medium_confidence_threshold`` are
returned; their confidence is ``"high"`` when above
``high_confidence_threshold`` and ``"medium"`` otherwise.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from owner.sync.config import SyncConfig
from owner.sync.models import FingerprintMatch, UpstreamCommit


class FingerprintDetector:
    """Detect suspected duplicate bug-fixes between upstream and owner."""

    def __init__(self, config: SyncConfig) -> None:
        """Initialize the detector.

        Args:
            config: Loaded :class:`SyncConfig`.
        """
        self.config: SyncConfig = config
        self._fingerprints: list[dict[str, Any]] | None = None

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------
    def load_fingerprints(self) -> list[dict[str, Any]]:
        """Load active fingerprints from the configured YAML file.

        Returns only entries with ``status == "active"``. The result is cached
        for the lifetime of the detector instance.

        Returns:
            List of fingerprint dicts. Returns an empty list if the file is
            missing or contains no active entries.
        """
        if self._fingerprints is not None:
            return self._fingerprints

        path: Path = self.config.fingerprint_path
        if not path.exists():
            self._fingerprints = []
            return self._fingerprints

        with path.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        if not isinstance(raw, dict):
            self._fingerprints = []
            return self._fingerprints

        fixes = raw.get("fixes", []) or []
        active: list[dict[str, Any]] = []
        for entry in fixes:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("status", "")).lower() == "active":
                active.append(entry)
        self._fingerprints = active
        return active

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------
    def detect(self, commits: list[UpstreamCommit]) -> list[FingerprintMatch]:
        """Score every (commit, fingerprint) pair and return likely matches.

        A match is returned when ``combined_similarity >
        medium_confidence_threshold``. Matches are sorted by descending
        similarity so the most suspicious candidates appear first.

        Args:
            commits: Upstream commits to evaluate.

        Returns:
            List of :class:`FingerprintMatch` sorted by descending
            ``combined_similarity``.
        """
        fingerprints = self.load_fingerprints()
        if not fingerprints or not commits:
            return []

        matches: list[FingerprintMatch] = []
        for commit in commits:
            for fp in fingerprints:
                similarity, file_rate, kw_rate = self._compute_similarity(
                    commit, fp
                )
                if similarity <= self.config.medium_confidence_threshold:
                    continue
                confidence = (
                    "high"
                    if similarity > self.config.high_confidence_threshold
                    else "medium"
                )
                matches.append(
                    FingerprintMatch(
                        fingerprint_id=str(fp.get("id", "")),
                        fingerprint_title=str(fp.get("title", "")),
                        owner_commit=str(fp.get("owner_commit", "")),
                        upstream_commit_hash=commit.hash,
                        upstream_commit_message=commit.message,
                        file_intersection_rate=file_rate,
                        keyword_hit_rate=kw_rate,
                        combined_similarity=similarity,
                        confidence=confidence,
                    )
                )
        matches.sort(key=lambda m: m.combined_similarity, reverse=True)
        return matches

    # ------------------------------------------------------------------
    # Internal scoring
    # ------------------------------------------------------------------
    def _compute_similarity(
        self, commit: UpstreamCommit, fingerprint: dict[str, Any]
    ) -> tuple[float, float, float]:
        """Compute (combined_similarity, file_rate, keyword_rate) for one pair.

        Args:
            commit: An upstream commit.
            fingerprint: A fingerprint dict from ``fix_fingerprints.yaml``.

        Returns:
            A ``(combined_similarity, file_intersection_rate,
            keyword_hit_rate)`` tuple. Rates are ``0.0`` when the fingerprint
            has no files/keywords.
        """
        fixed_files = fingerprint.get("fixed_files", []) or []
        fix_keywords = fingerprint.get("fix_keywords", []) or []

        # File intersection rate: fraction of fingerprint files touched.
        if fixed_files:
            fp_file_set = {f.strip() for f in fixed_files if str(f).strip()}
            commit_file_set = {f.strip() for f in commit.files if f.strip()}
            intersection = fp_file_set & commit_file_set
            file_rate = len(intersection) / len(fp_file_set) if fp_file_set else 0.0
        else:
            file_rate = 0.0

        # Keyword hit rate: fraction of keywords present in the commit message.
        if fix_keywords:
            msg_lower = commit.message.lower()
            hits = sum(
                1
                for kw in fix_keywords
                if str(kw).strip() and str(kw).lower() in msg_lower
            )
            kw_rate = hits / len(fix_keywords)
        else:
            kw_rate = 0.0

        combined = (
            file_rate * self.config.file_weight
            + kw_rate * self.config.keyword_weight
        )
        return combined, file_rate, kw_rate
