"""Feishu context-compression summary feedback.

Parses the structured handoff summary produced by ContextCompressor and
emits a short Chinese recap (goal / progress / state / files / todo) to
Feishu users after compression.  No extra LLM calls.

All logic lives in owner/; core files only contain thin [owner] glue.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from agent.context_compressor import (
    COMPRESSED_SUMMARY_METADATA_KEY,
    LEGACY_SUMMARY_PREFIX,
    SUMMARY_PREFIX,
    _HISTORICAL_SUMMARY_PREFIXES,
    _SUMMARY_END_MARKER,
)

logger = logging.getLogger(__name__)

_SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)

# Section titles are normalized by stripping "Historical " and lower-casing.
_SECTION_KEY_ALIASES: Dict[str, str] = {
    "task snapshot": "task",
    "in-progress state": "in_progress",
    "pending user asks": "pending",
    "remaining work": "remaining",
}


def _normalize_section_key(title: str) -> str:
    key = title.lower().strip()
    if key.startswith("historical "):
        key = key[len("historical "):]
    return _SECTION_KEY_ALIASES.get(key, key)


def _is_none_like(value: Optional[str]) -> bool:
    if not value:
        return True
    return value.strip().rstrip(".").lower() in {"none", "n/a", "unknown"}


def _first_line(text: Optional[str], max_chars: int = 240) -> str:
    """Return the first non-empty, non-none-like line, truncated."""
    if not text:
        return ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line and not _is_none_like(line):
            if len(line) > max_chars:
                line = line[: max_chars - 1].rstrip() + "…"
            return line
    return ""


def _first_bullets(text: Optional[str], max_items: int = 4, max_chars: int = 400) -> List[str]:
    """Return the first non-empty list items from a markdown section."""
    if not text:
        return []
    items: List[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # Strip leading list markers like "1.", "-", "*".
        line = re.sub(r"^\s*(?:\d+\.|[*\-])\s+", "", line).strip()
        if _is_none_like(line):
            continue
        # Avoid duplicating the active task wrapper.
        if line.lower().startswith("user asked:"):
            line = line[len("user asked:"):].strip()
        line = line.strip("'\"")
        if line:
            items.append(line)
        if len(items) >= max_items:
            break

    per_item_budget = max(80, max_chars // max_items)
    truncated: List[str] = []
    total = 0
    for item in items:
        budget = max_chars - total - 3 * len(truncated)
        if budget <= 0:
            break
        if len(item) > per_item_budget:
            item = item[: per_item_budget - 1].rstrip() + "…"
        if len(item) > budget:
            item = item[: budget - 1].rstrip() + "…"
        truncated.append(item)
        total += len(item)
    return truncated


def _strip_summary_prefix(summary: str) -> str:
    """Return summary body without handoff prefix and end marker."""
    text = (summary or "").strip()
    for prefix in (SUMMARY_PREFIX, LEGACY_SUMMARY_PREFIX, *_HISTORICAL_SUMMARY_PREFIXES):
        if text.startswith(prefix):
            text = text[len(prefix):].lstrip()
            break
    # Strip the end marker and everything after it.  When the summary is merged
    # into the tail message, the actual user/assistant turn follows the marker.
    marker_pos = text.find(_SUMMARY_END_MARKER)
    if marker_pos != -1:
        text = text[:marker_pos].rstrip()
    return text


def find_compressed_summary(messages: List[Dict[str, Any]]) -> Optional[str]:
    """Find and clean the first compressed-summary message in a message list."""
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        if msg.get(COMPRESSED_SUMMARY_METADATA_KEY):
            content = msg.get("content") or ""
            if isinstance(content, list):
                # Some platforms store content as a list of parts; concatenate text.
                content = "\n".join(
                    str(part.get("text", "")) for part in content
                    if isinstance(part, dict)
                )
            text = _strip_summary_prefix(str(content))
            return text if text.strip() else None
    return None


def _clean_task(content: str) -> str:
    """Strip the literal 'User asked:' wrapper and surrounding quotes."""
    line = _first_line(content, max_chars=10000)
    if line.lower().startswith("user asked:"):
        line = line[len("user asked:"):].strip()
    return line.strip("'\"")


def parse_compression_summary(summary_text: str) -> Dict[str, str]:
    """Split a structured handoff summary into section key → content."""
    text = _strip_summary_prefix(summary_text)
    if not text.strip():
        return {}
    sections: Dict[str, str] = {}
    matches = list(_SECTION_RE.finditer(text))
    for i, match in enumerate(matches):
        title = match.group(1).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[start:end].strip()
        key = _normalize_section_key(title)
        if key == "task":
            content = _clean_task(content)
        sections[key] = content
    return sections


def build_compression_summary_text(
    messages: List[Dict[str, Any]],
    before_count: int,
    after_count: int,
    compression_count: int = 1,
    before_tokens: Optional[int] = None,
    after_tokens: Optional[int] = None,
) -> Optional[str]:
    """Return a Chinese markdown summary of a completed compression, or None."""
    summary_text = find_compressed_summary(messages)
    if not summary_text:
        return None

    sections = parse_compression_summary(summary_text)

    task = _first_line(sections.get("task"), max_chars=220)
    if task.startswith("User asked:"):
        task = task[len("user asked:"):].strip()
    task = task.strip("'\"")

    goal = _first_line(sections.get("goal"), max_chars=220)
    active_task = task or goal

    completed = _first_bullets(sections.get("completed actions", ""), max_items=3, max_chars=450)
    files = _first_bullets(sections.get("relevant files", ""), max_items=4, max_chars=250)

    state_parts: List[str] = []
    active_state = _first_line(sections.get("active state", ""), max_chars=220)
    if active_state:
        state_parts.append(f"**状态**：{active_state}")
    in_progress = _first_line(sections.get("in_progress", ""), max_chars=160)
    if in_progress:
        state_parts.append(f"**进行中**：{in_progress}")
    blocked = _first_line(sections.get("blocked", ""), max_chars=160)
    if blocked:
        state_parts.append(f"**阻塞**：{blocked}")

    next_parts: List[str] = []
    pending = _first_line(sections.get("pending", ""), max_chars=160)
    if pending:
        next_parts.append(f"**待处理**：{pending}")
    remaining = _first_line(sections.get("remaining", ""), max_chars=160)
    if remaining:
        next_parts.append(f"**剩余工作**：{remaining}")

    if before_count > 0 and after_count < before_count:
        saved_pct = int((before_count - after_count) / before_count * 100)
    else:
        saved_pct = 0

    token_segment = ""
    if before_tokens is not None and after_tokens is not None:
        token_segment = f" · ~{before_tokens:,} → ~{after_tokens:,} tokens"

    headline = (
        f"🗜️ 上下文已压缩：{before_count} → {after_count} "
        f"条消息（缩短 {saved_pct}%）{token_segment}"
    )
    if compression_count > 1:
        headline += f" · 第 {compression_count} 次"

    body_lines: List[str] = [headline]
    if active_task:
        body_lines.append(f"**目标**：{active_task}")
    if completed:
        body_lines.append("**进度**：\n" + "\n".join(f"• {b}" for b in completed))
    if state_parts:
        body_lines.append("\n".join(state_parts))
    if files:
        body_lines.append("**涉及文件**：" + ", ".join(files))
    if next_parts:
        body_lines.append("\n".join(next_parts))

    return "\n\n".join(body_lines)


def emit_compression_summary(
    agent: Any,
    messages: List[Dict[str, Any]],
    before_count: int,
    after_count: int,
    compression_count: int = 1,
    before_tokens: Optional[int] = None,
    after_tokens: Optional[int] = None,
) -> None:
    """Emit a Chinese compression summary to Feishu users.

    Fail-open: any error is swallowed so a summary-delivery problem can never
    interrupt compression.
    """
    if getattr(agent, "platform", None) != "feishu":
        return

    text = build_compression_summary_text(
        messages,
        before_count=before_count,
        after_count=after_count,
        compression_count=compression_count,
        before_tokens=before_tokens,
        after_tokens=after_tokens,
    )
    if not text:
        return

    emit = getattr(agent, "_emit_status", None)
    if not callable(emit):
        return

    try:
        emit(text)
    except Exception:
        logger.debug("Failed to emit Feishu compression summary", exc_info=True)


__all__ = [
    "find_compressed_summary",
    "parse_compression_summary",
    "build_compression_summary_text",
    "emit_compression_summary",
]