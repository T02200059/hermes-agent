"""[owner] C13 recap — auto-recap eligibility gate (Grok Build aligned).

Upstream (xai-org/grok-build ``session_recap.rs``)::

    MIN_TURNS_FOR_AUTO_RECAP = 3
    RECAP_MIN_IDLE = Duration::from_secs(3 * 60)  # 180s
    recap_gate(main_turns, last, auto, idle_ok)

Manual ``/recap`` only needs ``main_turns > 0``; auto also needs a new turn
since the watermark, ``>= min_user_turns``, and idle OK.
"""

from __future__ import annotations

from typing import Optional

# Grok Build constants (authoritative; do not invent softer defaults).
MIN_TURNS_FOR_AUTO_RECAP = 3
RECAP_MIN_IDLE_SECONDS = 3 * 60


def recap_gate(
    main_turns: int,
    last: int,
    *,
    auto: bool,
    idle_ok: bool,
    min_user_turns: int = MIN_TURNS_FOR_AUTO_RECAP,
) -> Optional[str]:
    """Return ``None`` if allowed, else a stable English reason string (Grok parity)."""
    turns = int(main_turns or 0)
    watermark = int(last or 0)
    need = max(1, int(min_user_turns or MIN_TURNS_FOR_AUTO_RECAP))
    if turns == 0:
        return "no main turns yet"
    if auto:
        if turns <= watermark:
            return "no new main turn since last recap"
        if turns < need:
            return "fewer than min turns for auto recap"
        if not idle_ok:
            return "idle threshold not met"
    return None
