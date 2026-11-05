"""[owner] C13 recap — auto-recap eligibility gate (Grok Build aligned + char OR).

Upstream (xai-org/grok-build ``session_recap.rs``)::

    MIN_TURNS_FOR_AUTO_RECAP = 3
    RECAP_MIN_IDLE = Duration::from_secs(3 * 60)  # 180s
    recap_gate(main_turns, last, auto, idle_ok)

Manual ``/recap`` only needs ``main_turns > 0``; auto also needs a new turn
since the watermark, idle OK, and either ``>= min_user_turns`` **or**
(owner) latest assistant reply ``>= min_assistant_chars`` (0 disables the
char path; default 800 so a long single-turn reply can still auto-recap).
"""

from __future__ import annotations

from typing import Optional

# Grok Build constants (authoritative for the turns path).
MIN_TURNS_FOR_AUTO_RECAP = 3
RECAP_MIN_IDLE_SECONDS = 3 * 60

# Owner extension: OR with turns. 0 = char path off (pure Grok turns gate).
MIN_ASSISTANT_CHARS_FOR_AUTO_RECAP = 800


def recap_gate(
    main_turns: int,
    last: int,
    *,
    auto: bool,
    idle_ok: bool,
    min_user_turns: int = MIN_TURNS_FOR_AUTO_RECAP,
    assistant_chars: int = 0,
    min_assistant_chars: int = MIN_ASSISTANT_CHARS_FOR_AUTO_RECAP,
) -> Optional[str]:
    """Return ``None`` if allowed, else a stable English reason string.

    Turns-path reasons stay Grok-parity. When the char OR is configured and
    also fails, the turns-short reason is reused (same user-facing skip).
    """
    turns = int(main_turns or 0)
    watermark = int(last or 0)
    need = max(1, int(min_user_turns or MIN_TURNS_FOR_AUTO_RECAP))
    chars = max(0, int(assistant_chars or 0))
    need_chars = max(0, int(min_assistant_chars or 0))
    if turns == 0:
        return "no main turns yet"
    if auto:
        if turns <= watermark:
            return "no new main turn since last recap"
        turns_ok = turns >= need
        chars_ok = need_chars > 0 and chars >= need_chars
        if not turns_ok and not chars_ok:
            return "fewer than min turns for auto recap"
        if not idle_ok:
            return "idle threshold not met"
    return None
