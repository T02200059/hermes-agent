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
import time
from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, List, Optional, Tuple, TYPE_CHECKING

from owner.patch_config import _load_patch_owner_config

if TYPE_CHECKING:
    from gateway.platforms.feishu import FeishuAdapter

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

    Reads ``display.platforms.feishu.streaming`` from config.yaml.
    Auto-card only activates when streaming is off, because streaming mode
    chops the response into short chunks that never reach the length threshold.
    """
    try:
        import yaml
        from hermes_constants import get_hermes_home
        path = get_hermes_home() / "config.yaml"
        if path.exists():
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            platforms = data.get("display", {}).get("platforms") or {}
            feishu_cfg = platforms.get("feishu") or {}
            return feishu_cfg.get("streaming", True) is False
    except Exception:
        pass
    return False


# ---------------------------------------------------------------------------
# Card construction
# ---------------------------------------------------------------------------

def make_auto_card(markdown_text: str) -> Dict[str, Any]:
    """Build the auto-card JSON envelope around a single markdown body."""
    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "body": {
            "elements": [{"tag": "markdown", "content": markdown_text}],
        },
    }


def estimate_auto_card_json_bytes(markdown_text: str) -> int:
    """Byte length of the serialized auto-card JSON for this body."""
    return len(
        json.dumps(
            {
                "schema": "2.0",
                "config": {"wide_screen_mode": True},
                "body": {"elements": [{"tag": "markdown", "content": markdown_text}]},
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


def _evaluate_card_feasibility(text: str) -> _FeishuCardPlan:
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
            estimated_json_bytes=estimate_auto_card_json_bytes(text),
        )

    budget = get_auto_card_split_max_chars()
    estimated = estimate_auto_card_json_bytes(text)
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

def _split_text_for_card(text: str, max_chars: int) -> List[str]:
    """Paragraph-aware splitter that keeps fenced code blocks intact.

    Cut priority (in order): paragraph break ``\\n\\n``, line break ``\\n``,
    space. When a cut lands inside a fenced block the fence is closed on the
    current chunk and reopened (with the original language tag) on the next
    chunk. ``INDICATOR_RESERVE = 30`` leaves room for the ``_(N/M)_``
    indicator appended by the caller.
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
        if headroom < 1:
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
        total_fences = body.count("```")
        inside_fence = (total_fences % 2) == 1

        if inside_fence:
            last_open = body.rfind("```")
            if last_open >= 0:
                after = body[last_open + 3 :].lstrip("\n").split("\n", 1)[0]
                carry_lang = after if after and " " not in after else ""
            body += FENCE_CLOSE
        else:
            carry_lang = None

        chunks.append(body.strip("\n"))
        remaining = remaining[cut:].lstrip("\n")

    return [c for c in chunks if c]


# ---------------------------------------------------------------------------
# Tool-progress detection (skip auto-card for tool_progress messages)
# ---------------------------------------------------------------------------
#
# Tool-progress bubbles are emitted by ``BasePlatformAdapter.format_tool_event``
# (see gateway/platforms/base.py) and follow the shape::
#
#     ``{emoji} {tool_name}[":" | "(" | "." | " " | "\"" | "'"]...``
#
# Detection is intentionally decoupled: we independently verify that the
# leading token is a tool-display emoji AND the following token is a
# registered tool name. The two predicates share no state — emoji matching
# does not require the same tool_name to be registered, and vice versa.
# This lets skin overrides, custom emojis, and shared fallback emojis all
# pass through without any hardcoded emoji list.

# Permissive on the emoji (``\S{1,8}`` covers ZWJ sequences like 👨‍💻 and
# variation selectors like ⚙️) but strict on the terminator — must be a char
# that ``format_tool_event`` actually emits after the tool name. Without the
# terminator, plain prose like "📚 hello world" would not match.
_TOOL_HEADER_RE = re.compile(
    r"^(\S{1,8})\s+(\S+?)([:(\.\s\"']|$)",
    re.UNICODE,
)

# Cached (registered_tool_names, tool_emojis_used) tuple, refreshed every
# 60s. ``tool_emojis_used`` is the output of ``get_tool_emoji`` for every
# registered tool — this naturally includes registry-declared emojis, active
# skin overrides, AND shared fallbacks (because get_tool_emoji returns the
# fallback string when no emoji is configured).
_TOOL_INDEX_CACHE: Optional[Tuple[float, FrozenSet[str], FrozenSet[str]]] = None
_TOOL_INDEX_TTL_SECONDS = 60.0


def _refresh_tool_index() -> Tuple[FrozenSet[str], FrozenSet[str]]:
    """Return ``(registered_tool_names, tool_emojis_used)`` from the registry.

    Fail-open: on any import/registry error, returns two empty frozensets.
    Empty sets cause ``_is_tool_activity_message`` to return False, which
    means auto-card takes over (i.e. we err toward extra cards rather than
    dropping them silently).
    """
    global _TOOL_INDEX_CACHE
    now = time.monotonic()
    if _TOOL_INDEX_CACHE is not None:
        ts, names, emojis = _TOOL_INDEX_CACHE
        if now - ts < _TOOL_INDEX_TTL_SECONDS:
            return names, frozenset(emojis)

    names: FrozenSet[str] = frozenset()
    emojis: set[str] = set()
    try:
        from agent.display import get_tool_emoji
        from tools.registry import registry
        for entry in registry._snapshot_entries():
            names = names | {entry.name}
            e = get_tool_emoji(entry.name)
            if e:
                emojis.add(e)
    except Exception:
        pass

    _TOOL_INDEX_CACHE = (now, frozenset(names), frozenset(emojis))
    return _TOOL_INDEX_CACHE[1], _TOOL_INDEX_CACHE[2]


def _is_tool_emoji(emoji: str) -> bool:
    """True iff ``emoji`` is the display emoji of at least one registered tool."""
    if not emoji:
        return False
    _, tool_emojis = _refresh_tool_index()
    return emoji in tool_emojis


def _is_tool_name(name: str) -> bool:
    """True iff ``name`` is a registered tool name."""
    if not name:
        return False
    registered, _ = _refresh_tool_index()
    return name in registered


def _is_tool_activity_message(formatted_text: str) -> bool:
    """Detect ``format_tool_event`` output by AND-ing two independent checks:
    the leading token must be a tool emoji, AND the following token must
    be a registered tool name. Returns False (fail-open) on any error.
    """
    if not formatted_text:
        return False
    m = _TOOL_HEADER_RE.match(formatted_text)
    if not m:
        return False
    emoji, tool_name = m.group(1), m.group(2)
    # Sanity: tool_name segment should not itself contain emoji codepoints
    # (defensive against malformed input that could otherwise sneak past).
    if any(ord(c) > 0x2700 for c in tool_name):
        return False
    return _is_tool_emoji(emoji) and _is_tool_name(tool_name)


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
    threshold = get_auto_card_threshold()
    if threshold <= 0:
        return None
    if not force and not is_feishu_streaming_disabled():
        return None
    if not force and len(formatted_text) <= threshold:
        return None

    if _is_tool_activity_message(formatted_text):
        return None

    plan = _evaluate_card_feasibility(formatted_text)
    if not plan.can_use_card:
        logger.info(
            "[Feishu] auto-card skipped (%s); falling through to plain text",
            "; ".join(plan.risk_reasons),
        )
        return None

    split_enabled = get_auto_card_split_enabled()
    if plan.needs_split and split_enabled:
        budget = get_auto_card_split_max_chars()
        body_chunks = _split_text_for_card(formatted_text, budget)
    else:
        body_chunks = [formatted_text]

    n_chunks = len(body_chunks)
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

    for idx, body in enumerate(body_chunks):
        if n_chunks > 1:
            card_text = f"{body}\n\n_({idx + 1}/{n_chunks})_"
        else:
            card_text = body
        card = make_auto_card(card_text)

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

    # All chunks sent successfully.
    if n_chunks == 1 and card_result is not None:
        return card_result
    return SendResult(success=True, message_id="auto-card")
