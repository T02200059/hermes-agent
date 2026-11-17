"""[owner] C13 recap — 超输入预算时的混合回顾兜底.

不到 ``max_input_chars``（默认 64k）时仍走全量压平，行为不变。
只有可见 User/Agent 正文即将/已经尾部截断时，才把「上一次进度回顾」
作为被省略前半段的说明，再拼上截断后保留的近期原文。

旧回顾只作为单独的先前回顾块进入 prompt，不经 flatten 混进对话流。
定位范围是当前 tip 的 compression 链（``get_compression_lineage``），
不沿 session_reset / branch / delegate 链。找不到旧回顾时退回纯尾部截断。

在 64k 以上路径里，每连续使用 ``HYBRID_CALIBRATION_EVERY`` 次混合后，
下一次改为不依赖旧回顾的纯尾部截断（calibration），减轻误差累积。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from owner.explainers.common import DEFAULT_MAX_INPUT_CHARS, clip_input
from owner.explainers.persist import NOTICE_ROLE
from owner.explainers.recap.flatten import (
    flatten_messages_uncapped,
    iter_visible_dialogue_messages,
)
from owner.explainers.recap.prompt import PREFIX

logger = logging.getLogger("hermes.owner.explainers.recap")

# After this many hybrid recaps on the over-budget path, the next one is
# a tail-only calibration that ignores the previous recap text.
HYBRID_CALIBRATION_EVERY = 3

MODE_FULL = "full"
MODE_HYBRID = "hybrid"
MODE_CALIBRATION = "calibration"
MODE_TAIL = "tail"

# Only these modes count toward the calibration cadence.
_COUNTED_MODES = frozenset({MODE_HYBRID, MODE_CALIBRATION})


@dataclass
class PriorRecap:
    content: str
    row_id: Optional[int] = None
    session_id: str = ""
    input_mode: Optional[str] = None
    display_metadata: Optional[dict[str, Any]] = None


@dataclass
class RecapPlan:
    dialogue: str
    mode: str
    full_chars: int
    prior_recap: Optional[str] = None
    prior_recap_id: Optional[int] = None
    covered_last_message_id: Optional[Any] = None
    truncated: bool = False

    def extra_meta(self) -> dict[str, Any]:
        meta: dict[str, Any] = {
            "input_mode": self.mode,
            "full_chars": self.full_chars,
            "truncated": self.truncated,
        }
        if self.prior_recap_id is not None:
            meta["prior_recap_id"] = self.prior_recap_id
        if self.covered_last_message_id is not None:
            meta["covered_last_message_id"] = self.covered_last_message_id
        return meta


def recap_body_text(content: Any) -> str:
    """Strip the notice delivery prefix so the prior recap is plain prose."""
    text = str(content or "").strip()
    if text.startswith(PREFIX):
        text = text[len(PREFIX) :].strip()
    return text


def _parse_meta(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    if isinstance(raw, str):
        try:
            val = json.loads(raw)
        except Exception:
            return {}
        return val if isinstance(val, dict) else {}
    return {}


def _input_mode_of(notice: PriorRecap) -> Optional[str]:
    if notice.input_mode:
        return str(notice.input_mode)
    meta = notice.display_metadata or {}
    mode = meta.get("input_mode")
    return str(mode) if mode else None


def should_calibrate(
    prior_notices: Iterable[PriorRecap],
    *,
    calibration_every: int = HYBRID_CALIBRATION_EVERY,
) -> bool:
    """True when the next over-budget recap should skip the previous recap.

    Count prior notices whose ``input_mode`` is hybrid or calibration.
    After every ``calibration_every`` hybrid uses, the following recap is
    calibration: with the default 3, the 4th / 8th / … over-budget recap
    in that counted series is tail-only.
    """
    every = max(1, int(calibration_every or HYBRID_CALIBRATION_EVERY))
    counted = sum(1 for n in prior_notices if _input_mode_of(n) in _COUNTED_MODES)
    return counted % (every + 1) == every


def _covered_last_message_id(messages: Iterable[Any]) -> Optional[Any]:
    last = None
    for msg in iter_visible_dialogue_messages(messages):
        for key in ("_row_id", "id", "message_uid"):
            val = msg.get(key)
            if val is not None and str(val).strip():
                last = val
                break
    return last


def plan_recap_input(
    messages: Iterable[Any],
    *,
    max_input_chars: int = DEFAULT_MAX_INPUT_CHARS,
    prior_notices: Optional[list[PriorRecap]] = None,
    session_id: Optional[str] = None,
    db: Any = None,
    calibration_every: int = HYBRID_CALIBRATION_EVERY,
) -> RecapPlan:
    """Decide full / hybrid / tail / calibration input for one recap call.

    ``prior_notices`` short-circuits DB lookup (tests). Otherwise, when
    ``session_id`` or ``db`` is given, notices are loaded from the
    compression lineage. Fail-open: lookup errors become "no prior recap".
    """
    dialogue_full = flatten_messages_uncapped(messages)
    full_chars = len(dialogue_full)
    covered = _covered_last_message_id(messages)
    try:
        budget = int(max_input_chars)
    except (TypeError, ValueError):
        budget = DEFAULT_MAX_INPUT_CHARS
    if budget <= 0:
        budget = DEFAULT_MAX_INPUT_CHARS

    if full_chars <= budget:
        return RecapPlan(
            dialogue=dialogue_full,
            mode=MODE_FULL,
            full_chars=full_chars,
            covered_last_message_id=covered,
            truncated=False,
        )

    tail = clip_input(dialogue_full, budget)
    notices = prior_notices
    if notices is None:
        notices = load_prior_recaps(session_id or "", db=db) if (session_id or db) else []

    latest = notices[-1] if notices else None
    prior_text = recap_body_text(latest.content) if latest else ""
    prior_id = latest.row_id if latest else None

    if not prior_text:
        return RecapPlan(
            dialogue=tail,
            mode=MODE_TAIL,
            full_chars=full_chars,
            covered_last_message_id=covered,
            truncated=True,
        )

    if should_calibrate(notices, calibration_every=calibration_every):
        return RecapPlan(
            dialogue=tail,
            mode=MODE_CALIBRATION,
            full_chars=full_chars,
            prior_recap_id=prior_id,
            covered_last_message_id=covered,
            truncated=True,
        )

    return RecapPlan(
        dialogue=tail,
        mode=MODE_HYBRID,
        full_chars=full_chars,
        prior_recap=prior_text,
        prior_recap_id=prior_id,
        covered_last_message_id=covered,
        truncated=True,
    )


def compression_lineage_ids(db: Any, session_id: str) -> list[str]:
    """Session ids on the current tip's compression chain; never reset parents."""
    sid = str(session_id or "").strip()
    if not sid or db is None:
        return [sid] if sid else []
    resolved = sid
    try:
        resolve = getattr(db, "resolve_session_id", None)
        if callable(resolve):
            resolved = resolve(sid) or sid
    except Exception:
        resolved = sid
    tip = resolved
    try:
        get_tip = getattr(db, "get_compression_tip", None)
        if callable(get_tip):
            tip = get_tip(resolved) or resolved
    except Exception:
        tip = resolved
    try:
        get_lineage = getattr(db, "get_compression_lineage", None)
        if callable(get_lineage):
            lineage = [str(x) for x in (get_lineage(tip) or []) if str(x or "").strip()]
            if lineage:
                return lineage
    except Exception as exc:
        logger.debug("recap hybrid lineage failed sid=%s: %s", sid, exc)
    return [str(tip)]


def load_prior_recaps(session_id: str, *, db: Any = None) -> list[PriorRecap]:
    """Chronological recap notices on the compression lineage. Fail-open to []."""
    owns_db = False
    sid = str(session_id or "").strip()
    try:
        if db is None:
            if not sid:
                return []
            from hermes_state import SessionDB

            db = SessionDB(read_only=True)
            owns_db = True
        ids = compression_lineage_ids(db, sid)
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        rows = db._read_all(
            f"SELECT id, session_id, content, display_metadata FROM messages "
            f"WHERE session_id IN ({placeholders}) "
            f"AND role = ? AND display_kind = ? "
            f"AND COALESCE(active, 1) = 1 "
            f"ORDER BY id ASC",
            (*ids, NOTICE_ROLE, "recap"),
        ) or []
        out: list[PriorRecap] = []
        for row in rows:
            try:
                content = row["content"]
                meta = _parse_meta(row["display_metadata"])
                raw_id = row["id"]
                row_id = int(raw_id) if raw_id is not None else None
                out.append(
                    PriorRecap(
                        content=str(content or ""),
                        row_id=row_id,
                        session_id=str(row["session_id"] or ""),
                        input_mode=str(meta["input_mode"]) if meta.get("input_mode") else None,
                        display_metadata=meta or None,
                    )
                )
            except Exception:
                logger.debug("recap hybrid skip unreadable notice row", exc_info=True)
        return out
    except Exception as exc:
        logger.debug("load_prior_recaps failed sid=%s: %s", sid, exc)
        return []
    finally:
        if owns_db and db is not None:
            try:
                db.close()
            except Exception:
                pass
