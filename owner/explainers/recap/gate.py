"""[owner] C13 recap — auto-recap eligibility gate.

Auto recap fires at turn end when there is a new main user turn since the
watermark, and either:

- this turn lasted ``>= min_turn_seconds`` (default 180; user message →
  ``on_session_end``), or
- the latest visible assistant reply is ``>= min_assistant_chars``
  (default 800; 0 disables the char path).

User-turn count alone no longer triggers auto recap. Manual ``/recap`` only
needs ``main_turns > 0`` and ignores both automatic thresholds.

The 180s value used to mean "idle after the turn ended". It is now a
**turn-duration** floor (``min_turn_seconds``; overlay ``idle_seconds`` is
still read as a fallback).
"""

from __future__ import annotations

from typing import Optional

# Historical Grok Build turn-count constant. Kept for config compat; no longer
# an automatic trigger by itself.
MIN_TURNS_FOR_AUTO_RECAP = 3

# Turn-duration floor (user message → agent end). Same default as the old
# post-end idle wait, new semantics.
RECAP_MIN_TURN_SECONDS = 3 * 60
RECAP_MIN_IDLE_SECONDS = RECAP_MIN_TURN_SECONDS  # deprecated alias

# Owner extension: OR with duration. 0 = char path off.
MIN_ASSISTANT_CHARS_FOR_AUTO_RECAP = 800

# Stable English reasons (auto path).
REASON_NO_TURNS = "no main turns yet"
REASON_NO_NEW_TURN = "no new main turn since last recap"
REASON_BELOW_THRESHOLDS = "turn duration and end message below auto recap thresholds"


def recap_gate(
    main_turns: int,
    last: int,
    *,
    auto: bool,
    turn_seconds: Optional[float] = None,
    min_turn_seconds: int = RECAP_MIN_TURN_SECONDS,
    assistant_chars: int = 0,
    min_assistant_chars: int = MIN_ASSISTANT_CHARS_FOR_AUTO_RECAP,
) -> Optional[str]:
    """Return ``None`` if allowed, else a stable English reason string.

    ``turn_seconds is None`` skips the duration path (caller could not time
    this turn reliably). ``min_turn_seconds <= 0`` also disables duration.
    """
    turns = int(main_turns or 0)
    watermark = int(last or 0)
    chars = max(0, int(assistant_chars or 0))
    need_chars = max(0, int(min_assistant_chars or 0))
    need_secs = int(min_turn_seconds or 0)
    if turns == 0:
        return REASON_NO_TURNS
    if auto:
        if turns <= watermark:
            return REASON_NO_NEW_TURN
        duration_ok = (
            need_secs > 0
            and turn_seconds is not None
            and float(turn_seconds) >= float(need_secs)
        )
        chars_ok = need_chars > 0 and chars >= need_chars
        if not duration_ok and not chars_ok:
            return REASON_BELOW_THRESHOLDS
    return None
