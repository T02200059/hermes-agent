"""[owner] C12-merge-forward-recv — shared renderer for Feishu merge_forward children.

Single GET /im/v1/messages/{id} on a merge_forward parent returns the parent
plus N children (children carry upper_message_id = parent message_id).

Used by:
- gateway auto-expansion (adapter._expand_merge_forward_text)
- tools-side feishu_doc_read om_ path (read_merge_forward_as_text)
"""

from __future__ import annotations

import datetime as _dt
import json
from typing import Any, Optional, Sequence

MERGE_FORWARD_MAX_ENTRIES = 100
MERGE_FORWARD_MAX_CHARS = 40_000


def render_merge_forward_entries(
    parent_id: str,
    children: Sequence[Any],
    *,
    offset: int = 0,
    limit: Optional[int] = None,
) -> str:
    """Render merge_forward child messages as a readable transcript.

    children items are dicts (adapter path) or lark SDK objects (tool path);
    both expose message_id / msg_type / create_time / sender.id / body.content /
    mentions. Truncation keeps a message_id continuation hint instead of
    silently dropping entries.
    """

    def _get(item: Any, key: str, default: Any = None) -> Any:
        if isinstance(item, dict):
            return item.get(key, default)
        return getattr(item, key, default)

    def _body_content(item: Any) -> str:
        body = _get(item, "body")
        if isinstance(body, dict):
            return str(body.get("content", "") or "")
        return str(getattr(body, "content", "") or "")

    def _sender_label(item: Any) -> str:
        sender = _get(item, "sender") or {}
        if isinstance(sender, dict):
            sid = str(sender.get("id", "") or "")
        else:
            sid = str(getattr(sender, "id", "") or "")
        if not sid:
            return "unknown"
        # Short open_id label (ou_xxxx → last 6 chars) — real display names
        # require contact scopes we intentionally do not grant.
        return sid[-6:] if sid.startswith("ou_") else sid

    def _mentions_map(item: Any) -> dict[str, str]:
        out: dict[str, str] = {}
        mentions = _get(item, "mentions") or []
        for mu in mentions:
            if isinstance(mu, dict):
                key = mu.get("key", "")
                name = mu.get("name", "")
                uid = mu.get("id", "")
            else:
                key = getattr(mu, "key", "")
                name = getattr(mu, "name", "")
                uid = getattr(mu, "id", "")
            if key and name:
                out[str(key)] = str(name)
            # post "at" segments reference users by user_id/open_id, not key
            if uid and name:
                out[str(uid)] = str(name)
        return out

    total = len(children)
    if offset or limit is not None:
        end = total if limit is None else min(offset + (limit or total), total)
        window = children[offset:end]
    else:
        window = children

    lines: list[str] = [
        f"[合并转发消息 {parent_id}] 共 {total} 条子消息",
    ]

    for raw in window:
        msg_type = str(_get(raw, "msg_type", "") or "")
        sender = _sender_label(raw)
        ts = str(_get(raw, "create_time", "") or "")
        stamp = ""
        try:
            if ts:
                stamp = _dt.datetime.fromtimestamp(int(ts) / 1000).strftime("%m-%d %H:%M")
        except (ValueError, OverflowError, OSError):
            stamp = ""
        prefix = f"[{stamp}] " if stamp else ""
        mention_map = _mentions_map(raw)
        content_json = _body_content(raw)
        payload: dict[str, Any] = {}
        try:
            payload = json.loads(content_json) if content_json else {}
            if not isinstance(payload, dict):
                payload = {"content": payload}
        except json.JSONDecodeError:
            payload = {"text": content_json}
        text = str(payload.get("text", "") or "")
        for key, name in mention_map.items():
            text = text.replace(key, f"@{name}")
        if msg_type == "post":
            post_lines: list[str] = []
            post_content = payload.get("content") or []
            for para in post_content:
                if not isinstance(para, list):
                    continue
                seg_text = []
                for seg in para:
                    if not isinstance(seg, dict):
                        continue
                    tag = str(seg.get("tag", ""))
                    if tag == "text":
                        seg_text.append(str(seg.get("text", "") or ""))
                    elif tag == "at":
                        uid = str(seg.get("user_id", "") or "")
                        seg_text.append(f"@{mention_map.get(uid, uid)}")
                if seg_text:
                    post_lines.append("".join(seg_text))
            if post_lines:
                text = "\n".join(post_lines)
        elif msg_type == "image":
            text = "[图片]"
        elif msg_type == "file":
            text = "[文件]"
        elif msg_type == "merge_forward":
            nested_id = str(_get(raw, "message_id", "") or "")
            text = f"[嵌套合并转发 {nested_id}]"
        elif not text and msg_type not in {"text"}:
            text = f"[{msg_type or 'unknown'}]"
        lines.append(f"{prefix}{sender}: {text}")

    # Truncation with continuation hint (never silently drop)
    rendered = "\n".join(lines)
    if len(rendered) > MERGE_FORWARD_MAX_CHARS:
        keep = "\n".join(lines[:MERGE_FORWARD_MAX_ENTRIES])
        # character trim: walk back to a whole line boundary
        while keep and len(keep) > MERGE_FORWARD_MAX_CHARS:
            idx = keep.rfind("\n")
            if idx <= 0:
                keep = ""
                break
            keep = keep[:idx]
        shown = len(keep.split("\n")) - 1  # minus header
        keep = keep + (
            f"\n[截断] 已显示 {offset + shown}/{total} 条（上限 100 条 / 40000 字符）。"
            f"读取后续内容：feishu_doc_read(doc_token=\"{parent_id}\", offset={offset + shown})"
        )
        return keep

    # Explicit paging window that does not cover everything: keep a
    # continuation hint so the agent knows more entries remain.
    if offset or limit is not None:
        shown = len(window)
        if offset + shown < total:
            rendered += (
                f"\n[分页] 已显示第 {offset + 1}-{offset + shown} 条 / 共 {total} 条。"
                f"读取后续内容：feishu_doc_read(doc_token=\"{parent_id}\", offset={offset + shown})"
            )
    return rendered
