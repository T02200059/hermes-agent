"""Feishu recall card builders for qdrant-memory-recall hook."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

# Regex for extracting markdown heading (H1-H6) from first line of content.
_HEADING_RE = re.compile(r"^#{1,6}\s+(.+)")

# Markdown special characters that must be escaped for safe inline insertion.
# Mirrors _MARKDOWN_SPECIAL_CHARS_RE in gateway/platforms/feishu.py.
_MARKDOWN_SPECIAL_CHARS_RE = re.compile(r"([\\`*_{}\[\]()#+\-!|>~])")


def _extract_title(payload: dict, short_uri: str) -> str:
    """Extract display title from payload with a consistent fallback chain.

    Priority: name → abstract → first-line markdown heading → short_uri.

    Both compact and expanded cards share this function, ensuring the user
    sees the same title regardless of card state.
    """
    title = payload.get("name") or payload.get("abstract")
    if title:
        return str(title)

    body = payload.get("content") or payload.get("text") or ""
    body = str(body).replace("\r\n", "\n").replace("\r", "\n")
    first_line = body.split("\n", 1)[0].strip()

    m = _HEADING_RE.match(first_line)
    if m:
        return m.group(1).strip()

    return str(short_uri)


def _sanitize_markdown_inline(text: str) -> str:
    """Clean text for safe inline insertion into a Feishu markdown block.

    - Normalises \\r\\n / \\r → \\n
    - Collapses newlines to spaces (they would break inline markdown)
    - Escapes markdown special characters
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\n", " ")
    text = _MARKDOWN_SPECIAL_CHARS_RE.sub(r"\\\1", text)
    return text.strip()


def _sanitize_body_text(text: str) -> str:
    """Normalise body text for safe insertion into markdown content.

    The body is rendered as its own markdown segment (not inline), so we
    normalise line endings but preserve newlines.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text


def _truncate(v: str, max_len: int) -> str:
    """Truncate string to max_len codepoints, appending '...' if trimmed."""
    if len(v) > max_len:
        return v[: max_len - 3] + "..."
    return v


def build_recall_card_compact(
    hits: list[dict],
    cfg: dict,
    elapsed_ms: float,
    recall_id: str,
) -> dict:
    """Build Feishu 2.0 card (compact: metadata only, no body content)."""
    top_score = hits[0].get("score", 0)
    collections = sorted({h.get("_collection", "?") for h in hits})

    summary = (
        f"**{len(hits)} 条匹配** · 最高 **{top_score:.3f}** · "
        f"{len(collections)} collection · {elapsed_ms:.0f}ms"
    )

    hit_lines = []
    for h in hits:
        payload = h.get("payload") or {}
        uri = payload.get("uri") or f"unknown-{h.get('id')}"
        score = h.get("score", 0.0)
        coll = h.get("_collection", "?")
        short_uri = uri.split("/")[-1] if "/" in uri else uri
        title = _sanitize_markdown_inline(_extract_title(payload, short_uri))
        title = _truncate(title, 35)
        hit_lines.append(f"• `{coll}` **{score:.3f}** {title}")

    hits_md = "\n".join(hit_lines)

    expand_btn = {
        "tag": "button",
        "text": {"tag": "plain_text", "content": "🔍 展开详情"},
        "type": "default",
        "width": "fill",
        "behaviors": [
            {"type": "callback", "value": {"expand_recall": True, "recall_id": recall_id}}
        ],
    }

    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "🧠 知识库召回"},
            "template": "blue",
        },
        "body": {
            "elements": [
                {"tag": "markdown", "content": summary},
                {"tag": "hr"},
                {"tag": "markdown", "content": hits_md},
                expand_btn,
            ],
        },
    }


def build_recall_card_expanded(
    hits: list[dict],
    cfg: dict,
    elapsed_ms: float,
    recall_id: str,
) -> dict:
    """Build Feishu 2.0 card (expanded: full hit content)."""
    top_score = hits[0].get("score", 0)
    collections = sorted({h.get("_collection", "?") for h in hits})

    summary = (
        f"**{len(hits)} 条匹配** · 最高 **{top_score:.3f}** · "
        f"{len(collections)} collection · {elapsed_ms:.0f}ms"
    )

    hit_elements: list[dict[str, Any]] = []
    for i, h in enumerate(hits):
        payload = h.get("payload") or {}
        uri = payload.get("uri") or f"unknown-{h.get('id')}"
        score = h.get("score", 0.0)
        coll = h.get("_collection", "?")

        body = (
            payload.get("content")
            or payload.get("text")
            or payload.get("description")
        )
        if not body:
            meta = [
                f"{k}={v}"
                for k, v in payload.items()
                if k not in ("uri", "name") and v
            ]
            body = " | ".join(meta) if meta else (payload.get("name") or "")
        body = _sanitize_body_text(str(body))
        if len(body) > cfg["body_max_chars"]:
            body = body[: cfg["body_max_chars"]] + "..."

        if i > 0:
            hit_elements.append({"tag": "hr"})

        short_uri = uri.split("/")[-1] if "/" in uri else uri
        title = _sanitize_markdown_inline(_extract_title(payload, short_uri))
        title = _truncate(title, 80)
        hit_elements.append({
            "tag": "markdown",
            "content": f"**[{coll}] {score:.3f}** {title}\n{body}",
        })

    collapse_btn = {
        "tag": "button",
        "text": {"tag": "plain_text", "content": "⬆️ 折叠"},
        "type": "default",
        "width": "fill",
        "behaviors": [
            {"type": "callback", "value": {"collapse_recall": True, "recall_id": recall_id}}
        ],
    }

    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "🧠 知识库召回"},
            "template": "blue",
        },
        "body": {
            "elements": [
                {"tag": "markdown", "content": summary},
                {"tag": "hr"},
                *hit_elements,
                collapse_btn,
            ],
        },
    }



def handle_recall_card_action(
    adapter: Any,
    action_value: Dict[str, Any],
    lark_api: Any,
) -> Any:
    """Handle expand_recall / collapse_recall button clicks.

    Looks up the cached hits by recall_id, rebuilds the card in the
    requested state, and returns a P2CardActionTriggerResponse that
    replaces the card inline.

    Returns:
        P2CardActionTriggerResponse with the replacement card, or
        an empty response if the cache entry has expired.
    """
    recall_id = action_value.get("recall_id", "")
    if not recall_id:
        return _empty_card_response(lark_api)

    cache = getattr(adapter, "_recall_cache", None)
    if cache is None:
        return _empty_card_response(lark_api)

    try:
        from owner.feishu.card_cache import cache_get
        entry = cache_get(cache, recall_id)
    except ImportError:
        entry = cache.get(recall_id) if cache else None
    if entry is None:
        return _empty_card_response(lark_api)

    hits = entry.get("hits", [])
    cfg = entry.get("cfg", {})
    elapsed_ms = entry.get("elapsed_ms", 0.0)

    if action_value.get("expand_recall"):
        card = build_recall_card_expanded(hits, cfg, elapsed_ms, recall_id)
    elif action_value.get("collapse_recall"):
        card = build_recall_card_compact(hits, cfg, elapsed_ms, recall_id)
    else:
        return _empty_card_response(lark_api)

    response_cls, callback_cls = _lark_card_response_classes()
    if response_cls is None:
        return None
    resp = response_cls()
    if callback_cls is not None and card:
        cb = callback_cls()
        cb.type = "raw"
        cb.data = card
        resp.card = cb
    return resp


def _lark_card_response_classes() -> tuple:
    """Return ``(P2CardActionTriggerResponse, CallBackCard)`` or ``(None, None)``.

    These classes live in ``lark_oapi.event.callback.model.p2_card_action_trigger``
    and are NOT exported on the top-level ``lark_oapi`` module, so importing from
    the submodule (as every other card handler does) is the only correct access —
    ``lark_oapi.P2CardActionTriggerResponse`` raises ``AttributeError`` on
    lark-oapi 1.5.x.
    """
    try:
        from lark_oapi.event.callback.model.p2_card_action_trigger import (
            CallBackCard,
            P2CardActionTriggerResponse,
        )

        return P2CardActionTriggerResponse, CallBackCard
    except ImportError:
        return None, None


def _empty_card_response(lark_api: Any) -> Any:
    """Return an empty (no-op) P2CardActionTriggerResponse."""
    response_cls, _ = _lark_card_response_classes()
    if response_cls is None:
        return None
    return response_cls()

