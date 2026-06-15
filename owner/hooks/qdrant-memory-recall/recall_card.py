"""Feishu recall card builders for qdrant-memory-recall hook."""

from __future__ import annotations

from typing import Any


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
        title = payload.get("name") or payload.get("abstract")
        if not title:
            _body = payload.get("content") or payload.get("text") or ""
            _first_line = str(_body).split("\n", 1)[0].strip()
            if _first_line.startswith("# "):
                title = _first_line[2:].strip()
        title = str(title or short_uri)
        if len(title) > 35:
            title = title[:32] + "..."
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
        body = str(body)
        if len(body) > cfg["body_max_chars"]:
            body = body[: cfg["body_max_chars"]] + "..."

        if i > 0:
            hit_elements.append({"tag": "hr"})

        short_uri = uri.split("/")[-1] if "/" in uri else uri
        title = payload.get("name") or payload.get("abstract") or short_uri
        title = str(title)
        if len(title) > 80:
            title = title[:77] + "..."
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