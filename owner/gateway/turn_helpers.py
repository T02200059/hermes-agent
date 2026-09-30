"""Turn-path helpers that used to live in ``gateway/run.py``.

Four small, side-effect-free helpers on the turn / progress / restart-race path.
They are ours — upstream's split ``gateway/run*.py`` defines none of them — and
the split modules call them, so they live here instead of in an official file.
``gateway/run.py`` keeps thin delegations only while the monolith is still in
use.
"""

from __future__ import annotations

import re
from typing import Any

_ESCAPE_FENCE_RE = re.compile(r'^([ \t]*)(`{3,})(.*)$', re.MULTILINE)


def append_dedup_counter(base_msg: str, count: int) -> str:
    """Append a ``(×N)`` repeat counter to a deduplicated progress line.

    When ``base_msg`` ends with a closed fence (```` ``` ````) the counter MUST
    be placed on a new line: appending it inline (``"``` (×N)"``) strips the line
    of its CommonMark closed-fence status, so the code block never closes and
    subsequent terminal progress lines get swallowed into it. Only matters on
    ``supports_code_blocks`` platforms (Feishu/Slack), but the newline is
    harmless elsewhere.

    Shared by both dedup sites in ``send_progress_messages`` (main loop and the
    drain loop) so the rule cannot drift between them.
    """
    sep = "\n" if base_msg.endswith("```") else " "
    return f"{base_msg}{sep}(×{count + 1})"


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


def is_executor_shutdown_error(exc: BaseException) -> bool:
    """True when ``exc`` is asyncio's "default executor torn down" RuntimeError.

    ``run_in_executor(None, ...)`` and ``asyncio.to_thread(...)`` raise this once
    the running loop's default ThreadPoolExecutor has been shut down — which
    happens during the asyncio teardown of a SIGTERM/restart drain while the loop
    is *briefly still serving inbound events*. A message that lands in that
    window (or an in-flight turn when SIGTERM arrives) then fails here rather
    than from a real bug, so it should surface as a transient "restarting"
    condition, not a scary generic agent error.
    """
    if not isinstance(exc, RuntimeError):
        return False
    msg = str(exc).lower()
    return (
        "executor shutdown has been called" in msg
        or "cannot schedule new futures after shutdown" in msg
        or "event loop is closed" in msg
    )


def escape_code_fences_for_inline_block(text: str) -> str:
    """Rewrite markdown code-fence lines so they can't break out of a wrapping
    ```` ``` ```` block used to display reasoning on Feishu/Telegram.

    Any line whose first non-space characters are a fence of 3+ backticks —
    including indented/tab-prefixed fences, which a naive ``re.sub(r'^```')``
    missed and thus leaked — is rewritten to the same number of single quotes.
    Inline single backticks are left untouched. The info string after the fence
    (e.g. the language tag) is preserved.
    """
    return _ESCAPE_FENCE_RE.sub(
        lambda m: m.group(1) + "'" * len(m.group(2)) + m.group(3),
        text,
    )
