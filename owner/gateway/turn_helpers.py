"""Turn-path helpers that used to live in ``gateway/run.py``.

Side-effect-free helpers on the turn / progress path. Upstream's split
``gateway/run*.py`` defines none of the owner decision helpers; thin
``# [owner]`` glue in the split modules calls into here.
"""

from __future__ import annotations

import re
from typing import Any

# Closing fence at end of string (optional trailing whitespace / CR), possibly
# after a newline — mirrors official ``_append_progress_repeat_count``.
_CLOSING_FENCE_RE = re.compile(r"(?:^|\n)[ \t]*```[ \t]*\r?\Z")


def append_dedup_counter(base_msg: str, count: int) -> str:
    """Append a ``(×N)`` repeat counter to a deduplicated progress line.

    When ``base_msg`` ends with a closed fence (```` ``` ````) the counter MUST
    be placed on a new line: appending it inline (``"``` (×N)"``) strips the line
    of its CommonMark closed-fence status, so the code block never closes and
    subsequent terminal progress lines get swallowed into it. Only matters on
    ``supports_code_blocks`` platforms (Feishu/Slack), but the newline is
    harmless elsewhere.

    ``count`` is 0-based (first repeat → ``count=0`` → ``(×1)``); callers that
    already hold an occurrence total should pass ``occurrences - 1``.
    """
    occurrences = count + 1
    suffix = f"(×{occurrences})"
    body = base_msg.rstrip("\r\n")
    if _CLOSING_FENCE_RE.search(body):
        line_end = "\r\n" if base_msg.endswith("\r\n") else "\n"
        return f"{body}{line_end}{suffix}"
    return f"{base_msg} {suffix}"


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


__all__ = ["append_dedup_counter", "classify_edit_failure"]
