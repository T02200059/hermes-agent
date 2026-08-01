"""Feishu Auto-Card: wrap long text in interactive cards when streaming is off.

Core logic extracted from gateway/platforms/feishu.py per二次开发规范:
- P1 import 编排: core in owner/, feishu.py only does import + call
- Owner directory: all custom logic lives under owner/

Usage in feishu.py send():
    from owner.feishu.auto_card import try_auto_card
    result = await try_auto_card(adapter, formatted, metadata, chat_id=chat_id)
    if result is not None:
        return result
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from owner.patch_config import _load_patch_owner_config

if TYPE_CHECKING:
    # [owner] 目标分支飞书适配器已重构为插件（源码为单体 gateway/platforms/feishu.py）。
    from plugins.platforms.feishu.adapter import FeishuAdapter

try:
    from gateway.platforms.base import SendResult
except ImportError:
    SendResult = None  # type: ignore[misc,assignment]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_AUTO_CARD_THRESHOLD = 20

# P64 — Auto-card split constants (text-content budget, not JSON bytes).
_AUTO_CARD_SPLIT_DEFAULT_MAX_CHARS = 24000
_AUTO_CARD_SPLIT_MIN_MAX_CHARS = 8000
_AUTO_CARD_SPLIT_MAX_MAX_CHARS = 29000
_AUTO_CARD_SPLIT_MD_TABLE_MAX = 4
_AUTO_CARD_SPLIT_MD_TABLE_ROW_MAX = 5  # body rows, excludes the header row
_AUTO_CARD_SPLIT_CODE_BLOCK_MAX = 4000
# Loose GFM table locator: header line + separator line.
_AUTO_CARD_SPLIT_TABLE_HEADER_RE = re.compile(
    r"(?:^|\n)(\|[^\n]+\|\s*\n\|[-:|\s]+\|)([^\n]*(?:\n[^\n]*)*?)(?=\n\s*\n|\n[^\s|]|\Z)",
    re.MULTILINE,
)


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _FeishuCardPlan:
    """Pre-flight result for auto-card dispatch.

    can_use_card=False → skip card path, fall through to plain text.
    needs_split=True (with can_use_card=True) → chunk the body before wrapping.
    risk_reasons is logged at INFO when can_use_card is False.
    estimated_json_bytes is for the largest single chunk; logging only.
    """

    can_use_card: bool
    needs_split: bool
    risk_reasons: Tuple[str, ...] = ()
    estimated_json_bytes: int = 0


# ---------------------------------------------------------------------------
# Config readers (fail-open, never block main flow)
# ---------------------------------------------------------------------------

def get_auto_card_threshold() -> int:
    """Read auto-card threshold from patch.yaml.

    Reads ``owner.feishu_card.auto_card_threshold``.
    Falls back to 20 if patch.yaml is missing or the key is absent.
    Returns 0 if ``auto_card_threshold`` is explicitly set ≤ 0 (disabled).
    """
    try:
        patch = _load_patch_owner_config()
        threshold = patch.get("feishu_card", {}).get(
            "auto_card_threshold", _DEFAULT_AUTO_CARD_THRESHOLD
        )
        return max(0, int(threshold))
    except Exception:
        return _DEFAULT_AUTO_CARD_THRESHOLD


def get_auto_card_split_enabled() -> bool:
    """Read auto-card splitting master switch from patch.yaml.

    Reads ``owner.feishu_card.split_enabled``.
    Defaults to True. When False, the pre-flight check still runs (so we
    can log why the body would have split) but the actual split/loop is
    skipped; the whole body is sent as one card or falls through to text.
    """
    try:
        patch = _load_patch_owner_config()
        return bool(patch.get("feishu_card", {}).get("split_enabled", True))
    except Exception:
        return True


def get_auto_card_split_max_chars() -> int:
    """Read per-card text-content budget from patch.yaml.

    Reads ``owner.feishu_card.split_max_chars``.
    Clamped to [_AUTO_CARD_SPLIT_MIN_MAX_CHARS, _AUTO_CARD_SPLIT_MAX_MAX_CHARS].
    Default 24000 (≈ 6 KB JSON slack under the 30 KB Feishu content cap).
    """
    try:
        patch = _load_patch_owner_config()
        raw = patch.get("feishu_card", {}).get(
            "split_max_chars", _AUTO_CARD_SPLIT_DEFAULT_MAX_CHARS
        )
        value = int(raw)
    except Exception:
        value = _AUTO_CARD_SPLIT_DEFAULT_MAX_CHARS
    return max(
        _AUTO_CARD_SPLIT_MIN_MAX_CHARS,
        min(_AUTO_CARD_SPLIT_MAX_MAX_CHARS, value),
    )


def is_feishu_streaming_disabled() -> bool:
    """Check whether streaming is explicitly disabled for feishu platform.

    Reads ``display.platforms.feishu.streaming`` from config.yaml via the
    unified ``load_config_readonly()`` loader (mtime-cached, no raw I/O).
    Auto-card only activates when streaming is off, because streaming mode
    chops the response into short chunks that never reach the length threshold.
    """
    try:
        from hermes_cli.config import load_config_readonly
        cfg = load_config_readonly()
        platforms = cfg.get("display", {}).get("platforms") or {}
        feishu_cfg = platforms.get("feishu") or {}
        return feishu_cfg.get("streaming", True) is False
    except Exception:
        pass
    return False


# ---------------------------------------------------------------------------
# Card construction
# ---------------------------------------------------------------------------

def _build_card_elements(markdown_text: str, footer: str = "") -> List[Dict[str, Any]]:
    """Build the body elements for an auto-card."""
    elements: List[Dict[str, Any]] = [{"tag": "markdown", "content": markdown_text}]
    if footer:
        # [owner] auto-card: render footer after a horizontal divider
        elements.append({"tag": "hr"})
        elements.append({"tag": "markdown", "content": footer})
    return elements


def make_auto_card(markdown_text: str, footer: str = "") -> Dict[str, Any]:
    """Build the auto-card JSON envelope around a single markdown body.

    Optional footer is rendered after a horizontal divider.
    """
    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "body": {
            "elements": _build_card_elements(markdown_text, footer=footer),
        },
    }


def estimate_auto_card_json_bytes(markdown_text: str, footer: str = "") -> int:
    """Byte length of the serialized auto-card JSON for this body.

    Includes the hr + footer markdown elements when footer is non-empty.
    """
    return len(
        json.dumps(
            {
                "schema": "2.0",
                "config": {"wide_screen_mode": True},
                "body": {"elements": _build_card_elements(markdown_text, footer=footer)},
            },
            ensure_ascii=False,
        ).encode("utf-8")
    )


# ---------------------------------------------------------------------------
# Feasibility pre-check
# ---------------------------------------------------------------------------

def _count_markdown_tables(text: str) -> int:
    """Return the number of GFM tables in ``text`` (header + separator match)."""
    return sum(1 for _ in _AUTO_CARD_SPLIT_TABLE_HEADER_RE.finditer(text))


def _find_md_table_with_too_many_rows(text: str, limit: int) -> List[str]:
    """Return human-readable row counts for tables exceeding ``limit`` body rows."""
    offenders: List[str] = []
    for match in _AUTO_CARD_SPLIT_TABLE_HEADER_RE.finditer(text):
        body = match.group(2) or ""
        row_lines = [ln for ln in body.splitlines() if ln.strip()]
        if len(row_lines) > limit:
            offenders.append(f"table with {len(row_lines)} body rows")
    return offenders


def _find_code_block_over(text: str, limit: int) -> List[str]:
    """Return sizes of fenced code blocks that exceed ``limit`` characters."""
    offenders: List[str] = []
    in_fence = False
    buf: List[str] = []
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            if in_fence:
                block = "\n".join(buf)
                if len(block) > limit:
                    offenders.append(f"code block {len(block)} chars")
                in_fence = False
                buf = []
            else:
                in_fence = True
                buf = []
        elif in_fence:
            buf.append(line)
    return offenders


def _evaluate_card_feasibility(text: str, footer: str = "") -> _FeishuCardPlan:
    """Decide whether ``text`` can be auto-carded, and whether to split first.

    The JSON-byte estimate is the final authority on needs_split. The risk
    detectors catch Feishu-specific table/code-block ceilings that are not
    expressible as a single byte count: a 4 KB markdown body with 5 nested
    tables is well under 30 KB but still renders broken in the Feishu client,
    so we must downgrade to plain text.
    """
    risks: List[str] = []

    table_count = _count_markdown_tables(text)
    if table_count > _AUTO_CARD_SPLIT_MD_TABLE_MAX:
        risks.append(
            f"markdown table count {table_count} > {_AUTO_CARD_SPLIT_MD_TABLE_MAX} Feishu limit"
        )

    too_many = _find_md_table_with_too_many_rows(text, _AUTO_CARD_SPLIT_MD_TABLE_ROW_MAX)
    for desc in too_many:
        risks.append(desc)

    long_code = _find_code_block_over(text, _AUTO_CARD_SPLIT_CODE_BLOCK_MAX)
    for desc in long_code:
        risks.append(desc)

    if risks:
        return _FeishuCardPlan(
            can_use_card=False,
            needs_split=False,
            risk_reasons=tuple(risks),
            estimated_json_bytes=estimate_auto_card_json_bytes(text, footer=footer),
        )

    budget = get_auto_card_split_max_chars()
    estimated = estimate_auto_card_json_bytes(text, footer=footer)
    if len(text) > budget:
        return _FeishuCardPlan(
            can_use_card=True,
            needs_split=True,
            risk_reasons=(),
            estimated_json_bytes=estimated,
        )
    return _FeishuCardPlan(
        can_use_card=True,
        needs_split=False,
        risk_reasons=(),
        estimated_json_bytes=estimated,
    )


# ---------------------------------------------------------------------------
# Splitting
# ---------------------------------------------------------------------------

def _line_starts_fence(line: str) -> bool:
    """True for a fenced-code opening line, matching ``_find_code_block_over``.

    Counts as a fence only lines whose first non-space chars are ``\\`\\`\\``.
    Literal ``\\`\\`\\`` substrings inside a code span / inline code do NOT
    flip fence parity (the previous ``text.count("\\`\\`\\`") % 2`` heuristic
    did, which broke on bodies containing backtick-tickled examples).
    """
    return line.lstrip().startswith("```")


def _find_leading_table_end(text: str) -> int:
    """Return the exclusive end index of a GFM table that begins ``text``.

    A table "begins" when the first non-blank line is a header row
    (``| ... |``) immediately followed by a separator row
    (``| --- | ... |``). The table extends through every subsequent line
    that still looks like a table row (``|``-bearing, non-blank). Returns 0
    when ``text`` does not start with a table.

    Used by ``_split_text_for_card`` so a table is never split across two
    cards — table rows are only ``\\n``-separated, so the old paragraph /
    line / space cut priority would land between two rows and shatter the
    rendering.
    """
    lines = text.splitlines()
    if len(lines) < 2:
        return 0
    # Skip nothing — table must start at the very front (the caller already
    # lstrips leading newlines). First two lines must be header + separator.
    if not _AUTO_CARD_SPLIT_TABLE_HEADER_RE.match(text.lstrip("\n")):
        return 0
    header = lines[0]
    sep = lines[1]
    if "|" not in header or "|" not in sep:
        return 0
    if not re.match(r"^\s*\|?[\s:|-]+\|?\s*$", sep) or "-" not in sep:
        return 0
    # Consume contiguous table rows (lines containing a pipe).
    end_line = 2
    while end_line < len(lines):
        ln = lines[end_line]
        if not ln.strip() or "|" not in ln:
            break
        end_line += 1
    # Length of lines[0:end_line] joined with newlines + trailing newline.
    return sum(len(lines[i]) + 1 for i in range(end_line))


def _split_text_for_card(text: str, max_chars: int) -> List[str]:
    """Paragraph-aware splitter that keeps fenced code blocks and GFM tables intact.

    Cut priority (in order): paragraph break ``\\n\\n``, line break ``\\n``,
    space. When a cut lands inside a fenced block the fence is closed on the
    current chunk and reopened (with the original language tag) on the next
    chunk. A GFM table at the start of the remaining text is treated as an
    atomic unit — the whole table is taken in one chunk (or, if larger than
    the budget, hard-cut at a row boundary as the last resort) rather than
    letting the splitter land between two rows. ``INDICATOR_RESERVE = 30``
    leaves room for the ``_(N/M)_`` indicator appended by the caller.
    """
    if len(text) <= max_chars:
        return [text]

    FENCE_CLOSE = "\n```"
    INDICATOR_RESERVE = 30

    chunks: List[str] = []
    remaining = text
    carry_lang: Optional[str] = None

    while remaining:
        prefix = f"```{carry_lang}\n" if carry_lang is not None else ""
        headroom = max_chars - INDICATOR_RESERVE - len(prefix) - len(FENCE_CLOSE)

        # High#3: atomic GFM table at the head. Extend the cut to cover the
        # whole table so we don't land between two rows.
        table_end = _find_leading_table_end(remaining)
        if table_end > 0:
            if table_end >= len(remaining):
                cut = len(remaining)
            elif headroom < 1:
                # Degenerate dense content: hard cut.
                cut = max_chars
            elif table_end <= headroom:
                # Whole table fits in this chunk — take it whole.
                cut = table_end
                while cut < len(remaining) and remaining[cut] == "\n":
                    cut += 1
            else:
                # Table bigger than one chunk. Walk row-by-row to the last
                # row that still fits, rather than splitting mid-row.
                lines = remaining.splitlines()
                acc = len(lines[0]) + 1 + len(lines[1]) + 1  # header + sep
                cut = acc
                for ln in lines[2:]:
                    if acc + len(ln) + 1 > headroom:
                        break
                    acc += len(ln) + 1
                    cut = acc
        elif headroom < 1:
            # Degenerate: content is so dense that no splitter cut can produce
            # anything smaller than the budget. Take a hard cut at max_chars.
            cut = max_chars
        else:
            cut = 0
            for sep in ("\n\n", "\n", " "):
                idx = remaining.rfind(sep, 0, headroom)
                if idx > 0:
                    cut = idx + len(sep)
                    break
            if cut <= 0:
                cut = headroom

        body = prefix + remaining[:cut].rstrip()

        # Medium#4: line-based fence parity instead of substring count. The
        # old ``body.count("```") % 2 == 1`` counted literal backticks inside
        # inline code / prose and falsely flipped parity, leaking the fence.
        last_fence_line = -1
        fence_line_count = 0
        for i, line in enumerate(body.split("\n")):
            if _line_starts_fence(line):
                fence_line_count += 1
                last_fence_line = i
        inside_fence = (fence_line_count % 2) == 1

        if inside_fence and last_fence_line >= 0:
            # Medium#5: when the opening fence has NO info string (bare ```),
            # ``body[last_open+3:]`` would grab the first line of code as the
            # carry language. Detect an empty/whitespace-only info string and
            # explicitly reset carry_lang to "" so the next chunk reopens with
            # a bare ``` rather than smuggling code as a language tag.
            joined = body.split("\n")
            open_line = joined[last_fence_line]
            info = open_line.lstrip()[3:].strip()
            if info == "":
                carry_lang = ""
            else:
                # First token of the info string is the language; ignore any
                # trailing whitespace-only remainder.
                carry_lang = info.split()[0]
            body += FENCE_CLOSE
        else:
            carry_lang = None

        chunks.append(body.strip("\n"))
        remaining = remaining[cut:].lstrip("\n")

    return [c for c in chunks if c]


# ---------------------------------------------------------------------------
# Main entry point: try_auto_card
# ---------------------------------------------------------------------------

_MAX_CARD_SEND_ATTEMPTS = 3
_CARD_SEND_RETRY_DELAY_SECONDS = 1.0


async def try_auto_card(
    adapter: FeishuAdapter,
    formatted_text: str,
    metadata: Optional[Dict[str, Any]] = None,
    chat_id: str = "",
    force: bool = False,  # [owner] agent:end forces card dispatch regardless of streaming
    footer: str = "",  # [owner] auto-card: optional footer rendered after hr divider
) -> Optional[SendResult]:
    """Attempt to send long text as an interactive card.

    chat_id: explicit chat_id from the send context (preferred). If empty,
    falls back to adapter._chat_id for backward compat with direct callers.
    Passing the explicit chat_id from FeishuAdapter.send() eliminates the
    legacy degradation where synthetic/DM paths could have stale or missing
    adapter internal state.

    force: when True (called from agent:end), skips the streaming-disabled
    check so the card always fires for the full final response. The
    FeishuAdapter.send() caller passes force=False to preserve existing
    behaviour (cards only when streaming is off).

    Returns SendResult on success, None if auto-card should be skipped
    (short text, streaming on, threshold disabled, or feasibility risk).
    On card send failure after retries, logs a warning and returns None so
    the caller falls through to the plain-text path.
    """
    # Tool-progress bubbles are editable; never convert them to cards.
    if metadata and metadata.get("__hermes_progress_bubble"):
        return None

    threshold = get_auto_card_threshold()
    if threshold <= 0:
        return None
    if not force and not is_feishu_streaming_disabled():
        return None
    if not force and len(formatted_text) <= threshold:
        return None

    plan = _evaluate_card_feasibility(formatted_text, footer=footer)
    if not plan.can_use_card:
        logger.info(
            "[Feishu] auto-card skipped (%s); falling through to plain text",
            "; ".join(plan.risk_reasons),
        )
        return None

    split_enabled = get_auto_card_split_enabled()
    if plan.needs_split and split_enabled:
        budget = get_auto_card_split_max_chars()
        # [owner] IN-05: the footer + hr divider is appended to the FINAL chunk
        # after splitting, but _split_text_for_card sizes every chunk to
        # `budget` without knowing about it. Reserve the footer's size so a
        # near-budget final chunk + footer cannot exceed the card ceiling.
        # Footers are normally tiny, so the extra headroom is negligible.
        footer_reserve = (len(footer) + len("\n---\n")) if footer else 0
        body_chunks = _split_text_for_card(formatted_text, max(1, budget - footer_reserve))
    else:
        body_chunks = [formatted_text]

    n_chunks = len(body_chunks)
    # Low#10: all-whitespace input can survive feasibility (no risk tables /
    # code blocks) yet produce an empty chunk list once _split_text_for_card
    # filters blanks. Returning a fabricated success here would suppress the
    # plain-text fallback and show the user nothing. Bail to None instead.
    if not body_chunks:
        logger.info(
            "[Feishu] auto-card: splitter produced 0 chunks (text=%d); falling through to plain text",
            len(formatted_text),
        )
        return None
    if n_chunks > 1:
        logger.info(
            "[Feishu] auto-card: sending %d chunks (text=%d, est_json=%d bytes)",
            n_chunks,
            len(formatted_text),
            plan.estimated_json_bytes,
        )

    # [owner] Prefer explicit chat_id passed from send context (gateway has
    # the authoritative value for this turn). Only fall back to adapter
    # internal _chat_id for very old direct uses. This fixes the "chat_id
    # 推导退化" for synthetic DM / auto-card paths.
    chat_id = chat_id or getattr(adapter, "_chat_id", "") or ""
    last_error = ""
    last_card_result: Optional[SendResult] = None

    # [owner] High#2: hold a per-chat card-send lock across the WHOLE chunk
    # loop so a background-process watcher notification can't slip between
    # two card sends and reorder the message stream. The lock is distinct
    # from the inbound chat_lock (which is already held by the call path
    # into send()→try_auto_card), so re-acquiring it here would deadlock.
    # Fall back to a no-op context manager for adapters that predate this
    # helper (defensive — shouldn't happen on the current plugin adapter).
    send_lock = getattr(adapter, "_get_card_send_lock", None)
    if send_lock is None or n_chunks <= 1:
        import contextlib
        lock_ctx = contextlib.nullcontext()
    else:
        lock_ctx = send_lock(chat_id)

    async with lock_ctx:
        for idx, body in enumerate(body_chunks):
            if n_chunks > 1:
                card_text = f"{body}\n\n_({idx + 1}/{n_chunks})_"
            else:
                card_text = body
            # [owner] auto-card: footer + hr only on the last chunk
            card_footer = footer if idx == n_chunks - 1 else ""
            card = make_auto_card(card_text, footer=card_footer)

            card_result = None
            for attempt in range(_MAX_CARD_SEND_ATTEMPTS):
                card_result = await adapter.send_card(
                    chat_id=chat_id,
                    card=card,
                    metadata=metadata,
                )
                if card_result.success:
                    break
                if attempt < _MAX_CARD_SEND_ATTEMPTS - 1:
                    logger.warning(
                        "[Feishu] auto-card chunk %d/%d attempt %d/%d failed (%s), retrying in %.1fs",
                        idx + 1,
                        n_chunks,
                        attempt + 1,
                        _MAX_CARD_SEND_ATTEMPTS,
                        card_result.error or "unknown",
                        _CARD_SEND_RETRY_DELAY_SECONDS,
                    )
                    await asyncio.sleep(_CARD_SEND_RETRY_DELAY_SECONDS)

            if card_result is None or not card_result.success:
                last_error = (card_result.error or "unknown") if card_result else "unknown"
                logger.warning(
                    "[Feishu] auto-card chunk %d/%d failed after %d attempts: %s; falling back to plain text",
                    idx + 1,
                    n_chunks,
                    _MAX_CARD_SEND_ATTEMPTS,
                    last_error,
                )
                return None
            last_card_result = card_result

    # All chunks sent successfully.
    if last_card_result is not None and last_card_result.success:
        return last_card_result
    return SendResult(success=True, message_id="")
