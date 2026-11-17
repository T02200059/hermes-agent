"""[owner] C13 recap — flatten session transcript to User/Agent dialogue.

Drops tool calls, tool results, system prompts, notice 旁白, and reasoning
blobs so the explainer sees a readable conversation (avoids recap-in-recap).
Truncation prefers the **tail** (recent turns) under ``max_input_chars``
(shared default 64k).
"""

from __future__ import annotations

from typing import Any, Iterable, Iterator, Optional

from owner.explainers.common import DEFAULT_MAX_INPUT_CHARS, clip_input


def _content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                if part.get("type") in {"text", "input_text", "output_text"} or "text" in part:
                    parts.append(str(part.get("text") or ""))
        return "\n".join(p.strip() for p in parts if p and str(p).strip()).strip()
    return str(content).strip()


def _role_label(role: str) -> Optional[str]:
    r = str(role or "").strip().lower()
    if r == "user":
        return "User"
    if r in {"assistant", "model", "agent"}:
        return "Agent"
    return None


def iter_visible_dialogue_messages(messages: Iterable[Any]) -> Iterator[dict[str, Any]]:
    """Yield User/Agent rows that have visible text. Skip tool/system/notice."""
    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        label = _role_label(str(msg.get("role") or ""))
        if label is None:
            continue
        text = _content_to_text(msg.get("content"))
        if not text:
            continue
        yield msg


def flatten_messages_uncapped(messages: Iterable[Any]) -> str:
    """Return the full User/Agent transcript with no input-budget clip."""
    lines: list[str] = []
    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        label = _role_label(str(msg.get("role") or ""))
        if label is None:
            continue
        text = _content_to_text(msg.get("content"))
        if not text:
            continue
        lines.append(f"{label}: {text}")
    if not lines:
        return ""
    return "\n\n".join(lines)


def flatten_messages(
    messages: Iterable[Any],
    *,
    max_input_chars: int = DEFAULT_MAX_INPUT_CHARS,
) -> str:
    """Return a User/Agent transcript string, clipped to ``max_input_chars``.

    Empty / non-dict / tool-only / notice rows are skipped. Prefer recent
    content when the flattened text exceeds the budget.
    """
    flat = flatten_messages_uncapped(messages)
    if not flat:
        return ""
    return clip_input(flat, max_input_chars)
