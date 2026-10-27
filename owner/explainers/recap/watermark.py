"""[owner] C13 recap — durable auto-recap watermark per session.

Mirrors Grok Build ``last_recap_main_turn``: written only after a successful
(manual or auto) recap commit so the next auto wait for a *new* user turn.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Union

logger = logging.getLogger("hermes.owner.explainers.recap")

_SAFE_SID = re.compile(r"[^A-Za-z0-9._-]+")


def _root() -> Path:
    try:
        from hermes_constants import get_hermes_home

        base = Path(get_hermes_home())
    except Exception:
        base = Path.home() / ".hermes"
    return base / "owner" / "recap_watermarks"


def _path(session_id: str) -> Path:
    sid = _SAFE_SID.sub("_", str(session_id or "").strip()) or "_unknown"
    return _root() / sid


def load_recap_watermark(session_id: str) -> int:
    path = _path(session_id)
    try:
        raw = path.read_text(encoding="utf-8").strip()
        return int(raw) if raw else 0
    except Exception:
        return 0


def save_recap_watermark(session_id: str, main_turns: int) -> None:
    sid = str(session_id or "").strip()
    if not sid:
        return
    try:
        turns = max(0, int(main_turns))
    except (TypeError, ValueError):
        return
    path = _path(sid)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(turns), encoding="utf-8")
    except Exception as exc:
        logger.debug("recap watermark save failed session=%s: %s", sid, exc)


def clear_recap_watermark(session_id: str) -> None:
    try:
        _path(session_id).unlink(missing_ok=True)  # type: ignore[call-arg]
    except TypeError:
        # py<3.8 compat not needed on v2, but be safe
        p = _path(session_id)
        if p.exists():
            try:
                p.unlink()
            except Exception:
                pass
    except Exception:
        pass
