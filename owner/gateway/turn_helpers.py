"""Turn-path helpers that used to live in ``gateway/run.py``.

Side-effect-free helpers on the turn / progress path. Upstream's split
``gateway/run*.py`` defines none of the owner decision helpers; thin
``# [owner]`` glue in the split modules calls into here.
"""

from __future__ import annotations

from typing import Any


def classify_edit_failure(result: Any) -> str:
    """Classify a failed progress-message edit into a follow-up action.

    Pure decision function (no I/O) so the progress-loop's failure handling can
    be unit-tested without driving the whole async loop (WR-06). Precedence
    matches the loop's original inline order:

      - ``"retryable"``: transient (network) error — keep ``can_edit`` and let
        the next cycle catch up.
      - ``"rotate"``: the bubble is no longer editable but a fresh one is
        allowed (the adapter set ``result.rotate`` by platform error code, e.g.
        Feishu's ~20-edit cap → 230072/230075). Open a new bubble, keep editing.
      - ``"flood"``: flood control / rate limit — back off but keep editing.
      - ``"disable"``: permanent failure (not found, permissions, …) — stop
        editing and fall back to fresh sends.
    """
    if getattr(result, "retryable", False):
        return "retryable"
    if getattr(result, "rotate", False):
        return "rotate"
    err = (getattr(result, "error", "") or "").lower()
    if "flood" in err or "retry after" in err:
        return "flood"
    return "disable"


__all__ = ["classify_edit_failure"]
