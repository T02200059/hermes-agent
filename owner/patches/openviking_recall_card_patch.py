"""OpenViking recall visualization patch.

Adds a user-visible recall card (Feishu) or plain-text fallback (QQ Bot)
when the synchronous OpenViking recall returns hits. The LLM injection
path (``## OpenViking Context``) stays inside the provider unchanged.

All changes are runtime patches in ``owner/``; no official source file is
modified.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional

from plugins.memory.openviking import OpenVikingMemoryProvider

# [owner] recall-config: load from patch.yaml with env fallback
from owner.patches.openviking_recall_config import (
    load_recall_card_config as _load_card_cfg,
)

logger = logging.getLogger("openviking_recall_card")

# Patch state
_originals: Dict[str, Any] = {}
_applied: bool = False

# Token cache: key -> (token, expires_at)
_TOKEN_CACHE: Dict[str, tuple[str, float]] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _truncate(text: str, max_len: int) -> str:
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


_MARKDOWN_SPECIAL_CHARS_RE = __import__("re").compile(r"([\\`*_{}\[\]()#+\-!|>~])")


def _sanitize_markdown_inline(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\n", " ")
    text = _MARKDOWN_SPECIAL_CHARS_RE.sub(r"\\\1", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Card / text builders
# ---------------------------------------------------------------------------

def build_viking_recall_card(hits: List[dict], elapsed_ms: float) -> Optional[dict]:
    if not hits:
        return None
    top_score = max(h.get("score", 0) for h in hits)
    types = sorted({h.get("type", "memory") for h in hits})

    summary = (
        f"**{len(hits)} 条匹配** · 最高 **{top_score:.3f}** · "
        f"{len(types)} 类 · {elapsed_ms:.0f}ms"
    )

    hit_lines = []
    for h in hits:
        score = h.get("score", 0.0)
        htype = h.get("type", "memory")
        abstract = _sanitize_markdown_inline(_truncate(h.get("abstract", ""), 60))
        hit_lines.append(f"• `{htype}` **{score:.3f}** {abstract}")

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
                {"tag": "markdown", "content": "\n".join(hit_lines)},
            ],
        },
    }


def build_viking_recall_text(hits: List[dict], elapsed_ms: float) -> str:
    if not hits:
        return ""
    top_score = max(h.get("score", 0) for h in hits)
    lines = [
        f"🧠 **OpenViking 召回** · {len(hits)} 条匹配 · 最高 **{top_score:.3f}** · {elapsed_ms:.0f}ms",
        "",
    ]
    for h in hits:
        score = h.get("score", 0.0)
        htype = h.get("type", "memory")
        abstract = _truncate(h.get("abstract", ""), 200)
        lines.append(f"- `{htype}` **{score:.3f}** {abstract}")

    text = "\n".join(lines)
    if len(text) > 3800:
        text = text[:3797] + "..."
    return text


# ---------------------------------------------------------------------------
# Platform senders
# ---------------------------------------------------------------------------

def _acquire_feishu_token(app_id: str, app_secret: str) -> Optional[str]:
    key = f"feishu:{app_id}"
    now = time.time()
    token, expires_at = _TOKEN_CACHE.get(key, (None, 0))
    if token and now < expires_at - 60:
        return token

    try:
        import requests as _requests
        resp = _requests.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": app_id, "app_secret": app_secret},
            timeout=10,
        )
        data = resp.json()
        token = data.get("tenant_access_token", "")
        if not token:
            logger.warning("feishu token acquire failed: %s", data)
            return None
        expires_in = int(data.get("expire", 7200))  # Feishu returns 'expire' seconds
        _TOKEN_CACHE[key] = (token, now + expires_in)
        return token
    except Exception as e:
        logger.warning("feishu token request failed: %s", e)
        return None


def _send_feishu_card_sync(chat_id: str, card: dict, metadata: dict) -> bool:
    import requests as _requests

    app_id = os.environ.get("FEISHU_APP_ID", "")
    app_secret = os.environ.get("FEISHU_APP_SECRET", "")
    if not app_id or not app_secret:
        logger.warning("FEISHU_APP_ID/SECRET missing")
        return False

    token = _acquire_feishu_token(app_id, app_secret)
    if not token:
        return False

    raw_chat_type = (metadata.get("chat_type") or "").strip().lower()
    is_dm = raw_chat_type in ("p2p", "dm")
    if is_dm:
        receive_id = metadata.get("open_id") or metadata.get("sender_open_id") or chat_id
        receive_id_type = "open_id"
    else:
        receive_id = chat_id
        receive_id_type = "chat_id"

    try:
        payload = json.dumps(card, ensure_ascii=False)
        resp = _requests.post(
            f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type={receive_id_type}",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={"receive_id": receive_id, "msg_type": "interactive", "content": payload},
            timeout=15,
        )
        data = resp.json()
        code = data.get("code", -1)
        if code != 0:
            logger.warning("feishu card send API error (code %s): %s", code, data.get("msg", "unknown"))
            return False
        return True
    except Exception as e:
        logger.warning("feishu card send failed: %s", e)
        return False


def _acquire_qq_token(app_id: str, client_secret: str) -> Optional[str]:
    key = f"qq:{app_id}"
    now = time.time()
    token, expires_at = _TOKEN_CACHE.get(key, (None, 0))
    if token and now < expires_at - 60:
        return token

    try:
        import requests as _requests
        resp = _requests.post(
            "https://bots.qq.com/app/getAppAccessToken",
            json={"appId": app_id, "clientSecret": client_secret},
            timeout=10,
        )
        data = resp.json()
        token = data.get("access_token", "")
        if not token:
            logger.warning("qq token acquire failed: %s", data)
            return None
        expires_in = int(data.get("expires_in", 7200))
        _TOKEN_CACHE[key] = (token, now + expires_in)
        return token
    except Exception as e:
        logger.warning("qq token request failed: %s", e)
        return None


def _send_qqbot_text_sync(chat_id: str, content: str, metadata: dict) -> bool:
    import requests as _requests

    app_id = os.environ.get("QQ_APP_ID", "")
    client_secret = os.environ.get("QQ_CLIENT_SECRET", "")
    if not app_id or not client_secret:
        logger.warning("QQ_APP_ID/CLIENT_SECRET missing")
        return False

    token = _acquire_qq_token(app_id, client_secret)
    if not token:
        return False

    chat_type = (metadata.get("chat_type") or "").lower()
    if chat_type == "group":
        url = f"https://api.sgroup.qq.com/v2/groups/{chat_id}/messages"
    else:
        user_openid = metadata.get("open_id") or chat_id
        url = f"https://api.sgroup.qq.com/v2/users/{user_openid}/messages"

    try:
        resp = _requests.post(
            url,
            headers={"Authorization": f"QQBot {token}", "Content-Type": "application/json"},
            json={"content": content, "msg_type": 0},
            timeout=10,
        )
        if resp.status_code != 200:
            logger.warning("qq text send failed: HTTP %s: %s", resp.status_code, resp.text[:200])
            return False
        return True
    except Exception as e:
        logger.warning("qq text send failed: %s", e)
        return False


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def _fire_recall_display(hits: List[dict], ctx: dict, elapsed_ms: float) -> None:
    if not hits:
        return
    platform = (ctx.get("platform") or "").lower()
    chat_id = ctx.get("chat_id", "")
    if not chat_id:
        return

    _card_cfg = _load_card_cfg()
    feishu_card_enabled = bool(_card_cfg["feishu_card"])
    qqbot_text_enabled = bool(_card_cfg["qqbot_text"])

    if platform == "feishu" and feishu_card_enabled:
        card = build_viking_recall_card(hits, elapsed_ms)
        if card:
            metadata = {
                "chat_type": ctx.get("chat_type", ""),
                "open_id": ctx.get("user_id", ""),
            }
            threading.Thread(
                target=_send_feishu_card_sync,
                args=(chat_id, card, metadata),
                daemon=True,
                name="ov-feishu-card",
            ).start()

    elif platform == "qqbot" and qqbot_text_enabled:
        text = build_viking_recall_text(hits, elapsed_ms)
        if text:
            metadata = {
                "chat_type": ctx.get("chat_type", ""),
                "open_id": ctx.get("user_id", ""),
            }
            threading.Thread(
                target=_send_qqbot_text_sync,
                args=(chat_id, text, metadata),
                daemon=True,
                name="ov-qq-text",
            ).start()


# ---------------------------------------------------------------------------
# Wrappers
# ---------------------------------------------------------------------------

def _wrap_initialize(orig_init):
    def wrapped(self, session_id, **kwargs):
        orig_init(self, session_id, **kwargs)
        self._recall_card_ctx = {
            "platform": kwargs.get("platform", ""),
            "chat_id": kwargs.get("chat_id", ""),
            "chat_type": kwargs.get("chat_type", ""),
            "user_id": kwargs.get("user_id", ""),
            "user_name": kwargs.get("user_name", ""),
            "chat_name": kwargs.get("chat_name", ""),
        }
    return wrapped


def _wrap_sync_prefetch(orig_sync):
    def wrapped(self, query, *, session_id=""):
        start = time.time()
        ctx_text = orig_sync(self, query, session_id=session_id)
        elapsed_ms = (time.time() - start) * 1000

        hits = getattr(self, "_recall_card_hits", [])
        _card_cfg = _load_card_cfg()
        display_enabled = bool(_card_cfg["enabled"])
        if hits and display_enabled:
            _fire_recall_display(hits, getattr(self, "_recall_card_ctx", {}), elapsed_ms)

        return ctx_text
    return wrapped


# ---------------------------------------------------------------------------
# Patch registration
# ---------------------------------------------------------------------------

def apply_patch() -> None:
    global _applied
    if _applied:
        return

    provider_cls = OpenVikingMemoryProvider
    _originals["initialize"] = provider_cls.initialize
    _originals["prefetch"] = provider_cls.prefetch

    provider_cls.initialize = _wrap_initialize(_originals["initialize"])
    provider_cls.prefetch = _wrap_sync_prefetch(_originals["prefetch"])

    _applied = True
    logger.info("openviking_recall_card_patch applied")


def revert_patch() -> None:
    global _applied
    provider_cls = OpenVikingMemoryProvider
    orig_initialize = _originals.pop("initialize", None)
    orig_prefetch = _originals.pop("prefetch", None)
    if orig_initialize is not None:
        provider_cls.initialize = orig_initialize
    if orig_prefetch is not None:
        provider_cls.prefetch = orig_prefetch
    _applied = False
    logger.info("openviking_recall_card_patch reverted")
