"""OpenViking owner recall extensions (精简版).

Patches the official OpenViking provider at runtime with three owner-specific
extensions that are NOT in official main:

1. Advisory memory-context wording (soften authoritative tone).
2. Peer-mirror URI canonical deduplication (avoid user + peer duplicate recall).
3. Recall card visualization (Feishu interactive card / QQ Bot text).

Official main already provides synchronous prefetch, queue_prefetch no-op,
limit/context_type/session-search fallback, etc.; this patch does NOT replace
those.

All changes are runtime monkey-patches in ``owner/``; the only official glue
is a fail-open import in ``gateway/run.py``.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

import agent.memory_manager as _memory_manager_module
from owner.patches.openviking_recall_config import (
    load_recall_card_config as _load_card_cfg,
    load_sync_recall_config as _load_sync_cfg,
)

logger = logging.getLogger("openviking_owner_recall")

_originals: Dict[str, Any] = {}
_applied: Dict[str, bool] = {"advisory": False, "dedup": False, "card": False}

# Token caches for Feishu/QQ recall-card sends: key -> (token, expires_at)
_TOKEN_CACHE: Dict[str, tuple[str, float]] = {}

# WR-04: bound the recall-card send threads. A naive threading.Thread
# per recall can spawn tens of threads/sec under load; Feishu would
# rate-limit (and eventually ban) the bot. Two layers of throttling:
# 1) a bounded executor (max_workers) caps concurrent Feishu/QQ sends.
# 2) a per-chat debounce (keyed by chat_id) collapses repeated recalls
#    in the same chat within _RECALL_DEBOUNCE_SECONDS into one card.
_RECALL_DEBOUNCE_SECONDS = 5.0
_RECALL_MAX_WORKERS = 3
_recall_last_fired_at: Dict[str, float] = {}
_recall_last_fired_lock = threading.Lock()
_recall_executor: Optional[ThreadPoolExecutor] = None
_recall_executor_lock = threading.Lock()


def _get_recall_executor() -> ThreadPoolExecutor:
    """Lazy-init the recall-card send executor (max_workers=3).

    The pool is module-scoped so all recall sends across threads share
    the same worker cap. Daemon threads so the executor doesn't block
    process exit (same guarantee the old threading.Thread daemon=True
    path had).
    """
    global _recall_executor
    if _recall_executor is None:
        with _recall_executor_lock:
            if _recall_executor is None:
                _recall_executor = ThreadPoolExecutor(
                    max_workers=_RECALL_MAX_WORKERS,
                    thread_name_prefix="ov-recall-card",
                )
    return _recall_executor


def _is_chat_debounced(chat_id: str) -> bool:
    """Return True if a recall was already fired for this chat within
    the debounce window. The first call in a window returns False and
    records the timestamp; subsequent calls within the window return
    True (skipped)."""
    now = time.time()
    with _recall_last_fired_lock:
        last = _recall_last_fired_at.get(chat_id, 0.0)
        if now - last < _RECALL_DEBOUNCE_SECONDS:
            return True
        _recall_last_fired_at[chat_id] = now
        return False

_PEER_SEGMENT_RE = re.compile(r"/peers/[^/]+")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dedup_uri_canonical(uri: str) -> str:
    """Return the URI with any ``/peers/<name>/`` segment stripped.

    Examples
    --------
    >>> _dedup_uri_canonical(
    ...     "viking://user/yangtb/peers/hermes/memories/events/x.md"
    ... )
    'viking://user/yangtb/memories/events/x.md'
    """
    return _PEER_SEGMENT_RE.sub("", uri or "")


def _dedup_peer_mirrors(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove duplicate peer-mirror items, keeping the first occurrence.

    Peer mirrors share the same canonical URI as the owner copy but live under
    ``/peers/<name>/``. When both are returned we keep whichever appears first
    (the owner copy is usually ranked higher).
    """
    seen: set = set()
    filtered: List[Dict[str, Any]] = []
    for item in items:
        uri = str(item.get("uri") or "").strip()
        if not uri:
            filtered.append(item)
            continue
        canon = _dedup_uri_canonical(uri)
        if canon in seen:
            continue
        seen.add(canon)
        filtered.append(item)
    return filtered


def _truncate(text: str, max_len: int) -> str:
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


_MARKDOWN_SPECIAL_CHARS_RE = re.compile(r"([\\`*_{}\[\]()#+\-!|>~])")


def _sanitize_markdown_inline(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\n", " ")
    text = _MARKDOWN_SPECIAL_CHARS_RE.sub(r"\\\1", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Advisory memory-context wording
# ---------------------------------------------------------------------------

def _build_advisory_memory_context_block(raw_context: str) -> str:
    """Wrap prefetched memory in a fenced block with an advisory system note."""
    if not raw_context or not raw_context.strip():
        return ""

    clean = _memory_manager_module.sanitize_context(raw_context)
    if clean != raw_context:
        logger.warning("memory provider returned pre-wrapped context; stripped")

    return (
        "<memory-context>\n"
        "[System note: The following is recalled memory context, "
        "NOT new user input. It may help inform the response, but use it "
        "only when relevant to the user's current message — treat as helpful "
        "hints, not authoritative facts.]\n\n"
        f"{clean}\n"
        "</memory-context>"
    )


def _apply_advisory() -> None:
    global _applied
    _originals["build_memory_context_block"] = _memory_manager_module.build_memory_context_block
    _memory_manager_module.build_memory_context_block = _build_advisory_memory_context_block

    # Keep already-imported aliases in sync (e.g. agent.conversation_loop).
    cl = sys.modules.get("agent.conversation_loop")
    if cl is not None:
        cl.build_memory_context_block = _build_advisory_memory_context_block

    _applied["advisory"] = True
    logger.info("openviking_owner_recall_patch applied: advisory")


def _revert_advisory() -> None:
    global _applied
    orig = _originals.pop("build_memory_context_block", None)
    if orig is not None:
        _memory_manager_module.build_memory_context_block = orig
        cl = sys.modules.get("agent.conversation_loop")
        if cl is not None:
            cl.build_memory_context_block = orig
    _applied["advisory"] = False
    logger.info("openviking_owner_recall_patch reverted: advisory")


# ---------------------------------------------------------------------------
# Peer-mirror deduplication
# ---------------------------------------------------------------------------

def _make_select_recall_candidates_wrapper(orig_fn):
    """Return a classmethod wrapper that pre-dedups peer mirrors."""
    def wrapper(cls, items, query, *, limit, score_threshold):
        cfg = _load_sync_cfg()
        if cfg.get("dedup", True):
            items = _dedup_peer_mirrors(items)
        return orig_fn(cls, items, query, limit=limit, score_threshold=score_threshold)
    return classmethod(wrapper)


def _apply_dedup() -> None:
    global _applied
    from plugins.memory.openviking import OpenVikingMemoryProvider

    # Underlying function of the classmethod.
    orig_fn = OpenVikingMemoryProvider._select_recall_candidates.__func__
    _originals["select_recall_candidates"] = OpenVikingMemoryProvider.__dict__.get(
        "_select_recall_candidates"
    )
    OpenVikingMemoryProvider._select_recall_candidates = _make_select_recall_candidates_wrapper(
        orig_fn
    )
    _applied["dedup"] = True
    logger.info("openviking_owner_recall_patch applied: dedup")


def _revert_dedup() -> None:
    global _applied
    from plugins.memory.openviking import OpenVikingMemoryProvider

    orig = _originals.pop("select_recall_candidates", None)
    if orig is not None:
        OpenVikingMemoryProvider._select_recall_candidates = orig
    _applied["dedup"] = False
    logger.info("openviking_owner_recall_patch reverted: dedup")


# ---------------------------------------------------------------------------
# Recall card visualization
# ---------------------------------------------------------------------------

def build_viking_recall_card(hits: List[dict], elapsed_ms: float) -> Optional[dict]:
    """Build a Feishu interactive card summarizing recall hits."""
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
    """Build a plain-text recall summary for QQ Bot."""
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
        expires_in = int(data.get("expire", 7200))
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
        logger.warning(
            "openviking_recall: feishu card send aborted — FEISHU_APP_ID/SECRET missing"
        )
        return False

    token = _acquire_feishu_token(app_id, app_secret)
    if not token:
        logger.warning("openviking_recall: feishu card send aborted — token acquire failed")
        return False

    raw_chat_type = (metadata.get("chat_type") or "").strip().lower()
    is_dm = raw_chat_type in ("p2p", "dm")
    if is_dm:
        receive_id = metadata.get("open_id") or metadata.get("sender_open_id") or chat_id
        receive_id_type = "open_id"
    else:
        receive_id = chat_id
        receive_id_type = "chat_id"

    logger.info(
        "openviking_recall: feishu card send start receive_id_type=%s receive_id=%s "
        "chat_type=%s",
        receive_id_type,
        (receive_id or "")[:48],
        raw_chat_type or "(empty)",
    )

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
            logger.warning(
                "openviking_recall: feishu card send API error (code %s): %s",
                code,
                data.get("msg", "unknown"),
            )
            return False
        msg_id = ""
        try:
            msg_id = str((data.get("data") or {}).get("message_id") or "")
        except Exception:
            pass
        logger.info(
            "openviking_recall: feishu card send OK message_id=%s",
            msg_id or "(none)",
        )
        return True
    except Exception as e:
        logger.warning("openviking_recall: feishu card send failed: %s", e)
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


def _query_preview(query: Any, limit: int = 80) -> str:
    text = query if isinstance(query, str) else repr(query)
    text = " ".join(text.split())
    if len(text) > limit:
        return text[:limit] + "..."
    return text


def _hit_summaries(hits: List[dict], limit: int = 6) -> List[str]:
    out: List[str] = []
    for h in (hits or [])[:limit]:
        if not isinstance(h, dict):
            out.append(str(h)[:60])
            continue
        title = (
            h.get("title")
            or h.get("name")
            or h.get("uri")
            or h.get("path")
            or h.get("id")
            or "?"
        )
        score = h.get("score")
        if score is not None:
            out.append(f"{title}(score={score})")
        else:
            out.append(str(title)[:80])
    return out


def _fire_recall_display(hits: List[dict], ctx: dict, elapsed_ms: float) -> None:
    """Dispatch recall card/text asynchronously; log every skip path."""
    ctx = ctx or {}
    if not hits:
        logger.info(
            "openviking_recall: display skip reason=no_hits elapsed_ms=%.0f",
            elapsed_ms,
        )
        return

    platform = (ctx.get("platform") or "").lower()
    chat_id = ctx.get("chat_id", "") or ""
    user_id = ctx.get("user_id", "") or ""
    chat_type = ctx.get("chat_type", "") or ""

    logger.info(
        "openviking_recall: display attempt hits=%d elapsed_ms=%.0f "
        "platform=%r chat_id=%r chat_type=%r user_id=%r",
        len(hits),
        elapsed_ms,
        platform or "(empty)",
        chat_id[:48] if chat_id else "(empty)",
        chat_type or "(empty)",
        (user_id[:32] if user_id else "(empty)"),
    )

    if not chat_id:
        logger.warning(
            "openviking_recall: display skip reason=missing_chat_id "
            "(provider initialize never got chat_id — card cannot be routed)"
        )
        return

    cfg = _load_card_cfg()
    if not cfg.get("enabled", True):
        logger.info(
            "openviking_recall: display skip reason=card_disabled cfg=%s",
            {k: cfg.get(k) for k in ("enabled", "feishu_card", "qqbot_text")},
        )
        return

    # WR-04: per-chat debounce — collapse repeated recalls in the same
    # chat within 5s into a single card. Prevents a single chat with
    # bursty memory hits from hammering Feishu/QQ with N cards.
    if _is_chat_debounced(chat_id):
        logger.info(
            "openviking_recall: display skip reason=debounced chat_id=%s "
            "window_s=%s",
            chat_id[:48],
            _RECALL_DEBOUNCE_SECONDS,
        )
        return

    metadata = {
        "chat_type": chat_type,
        "open_id": user_id,
    }

    executor = _get_recall_executor()

    if platform == "feishu" and cfg.get("feishu_card", True):
        card = build_viking_recall_card(hits, elapsed_ms)
        if not card:
            logger.warning(
                "openviking_recall: display skip reason=empty_card_build hits=%d",
                len(hits),
            )
            return
        try:
            fut = executor.submit(_send_feishu_card_sync, chat_id, card, metadata)
            logger.info(
                "openviking_recall: feishu card queued hits=%d titles=%s",
                len(hits),
                _hit_summaries(hits),
            )

            def _log_done(f):
                try:
                    ok = f.result()
                    logger.info(
                        "openviking_recall: feishu card future done ok=%s", ok
                    )
                except Exception as exc:
                    logger.warning(
                        "openviking_recall: feishu card future error: %s", exc
                    )

            fut.add_done_callback(_log_done)
        except RuntimeError:
            # Executor shut down (process exit) — fail silent.
            logger.warning(
                "openviking_recall: display skip reason=executor_shutdown"
            )

    elif platform == "qqbot" and cfg.get("qqbot_text", True):
        text = build_viking_recall_text(hits, elapsed_ms)
        if text:
            try:
                executor.submit(_send_qqbot_text_sync, chat_id, text, metadata)
                logger.info(
                    "openviking_recall: qqbot text queued hits=%d", len(hits)
                )
            except RuntimeError:
                logger.warning(
                    "openviking_recall: display skip reason=executor_shutdown"
                )
        else:
            logger.warning(
                "openviking_recall: display skip reason=empty_qq_text hits=%d",
                len(hits),
            )
    else:
        logger.info(
            "openviking_recall: display skip reason=platform_or_channel_gate "
            "platform=%r feishu_card=%s qqbot_text=%s",
            platform or "(empty)",
            cfg.get("feishu_card", True),
            cfg.get("qqbot_text", True),
        )


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
        self._owner_recall_hits = []
        has_client = bool(getattr(self, "_client", None))
        logger.info(
            "openviking_recall: initialize session_id=%s platform=%r chat_id=%r "
            "chat_type=%r user_id=%r has_client=%s",
            session_id,
            self._recall_card_ctx["platform"] or "(empty)",
            (self._recall_card_ctx["chat_id"] or "(empty)")[:48],
            self._recall_card_ctx["chat_type"] or "(empty)",
            (self._recall_card_ctx["user_id"] or "(empty)")[:32],
            has_client,
        )
    return wrapped


def _wrap_build_prefetch_entries(orig_fn):
    def wrapped(self, client, items, *, prefer_abstract, max_injected_chars, deadline, request_timeout, full_read_limit):
        cfg = _load_sync_cfg()
        top_n = max(1, int(cfg.get("top_n", 6)))
        # Store the selected hits (post-dedup) for the recall card.
        items_list = list(items) if items else []
        self._owner_recall_hits = items_list[:top_n]
        logger.info(
            "openviking_recall: build_prefetch_entries raw_items=%d top_n=%d "
            "stored_hits=%d titles=%s prefer_abstract=%s",
            len(items_list),
            top_n,
            len(self._owner_recall_hits),
            _hit_summaries(self._owner_recall_hits),
            prefer_abstract,
        )
        return orig_fn(
            self,
            client,
            items,
            prefer_abstract=prefer_abstract,
            max_injected_chars=max_injected_chars,
            deadline=deadline,
            request_timeout=request_timeout,
            full_read_limit=full_read_limit,
        )
    return wrapped


def _wrap_prefetch(orig_fn):
    def wrapped(self, query, *, session_id=""):
        # Clear stale hits so an empty search cannot re-fire a previous card.
        self._owner_recall_hits = []
        q_preview = _query_preview(query)
        q_len = len(query) if isinstance(query, str) else -1
        has_client = bool(getattr(self, "_client", None))
        ctx = getattr(self, "_recall_card_ctx", {}) or {}
        logger.info(
            "openviking_recall: prefetch start session_id=%s query_len=%s "
            "query=%r has_client=%s platform=%r chat_id=%r",
            session_id or getattr(self, "_session_id", "") or "",
            q_len,
            q_preview,
            has_client,
            (ctx.get("platform") or "(empty)"),
            (str(ctx.get("chat_id") or "(empty)"))[:48],
        )

        start = time.time()
        try:
            result = orig_fn(self, query, session_id=session_id)
        except Exception as exc:
            elapsed_ms = (time.time() - start) * 1000
            logger.warning(
                "openviking_recall: prefetch raised after %.0fms: %s",
                elapsed_ms,
                exc,
                exc_info=True,
            )
            raise

        elapsed_ms = (time.time() - start) * 1000
        result_s = result if isinstance(result, str) else ""
        hits = getattr(self, "_owner_recall_hits", []) or []
        cfg = _load_card_cfg()

        # Infer early-return reasons from empty result + empty hits.
        skip_hint = ""
        if not result_s and not hits:
            if not has_client:
                skip_hint = "likely_no_client"
            elif isinstance(query, str) and len(query.strip()) < 5:
                skip_hint = "query_shorter_than_min_chars(5)"
            else:
                skip_hint = "empty_search_or_no_entries"

        logger.info(
            "openviking_recall: prefetch done elapsed_ms=%.0f result_chars=%d "
            "hits=%d card_enabled=%s skip_hint=%s titles=%s",
            elapsed_ms,
            len(result_s),
            len(hits),
            cfg.get("enabled", True),
            skip_hint or "none",
            _hit_summaries(hits),
        )

        if hits and cfg.get("enabled", True):
            _fire_recall_display(hits, ctx, elapsed_ms)
        elif not hits:
            logger.info(
                "openviking_recall: no card — zero hits (skip_hint=%s query=%r)",
                skip_hint or "none",
                q_preview,
            )
        else:
            logger.info(
                "openviking_recall: no card — card display disabled in config"
            )

        return result
    return wrapped


def _apply_card() -> None:
    global _applied
    from plugins.memory.openviking import OpenVikingMemoryProvider

    _originals["initialize"] = OpenVikingMemoryProvider.initialize
    _originals["prefetch"] = OpenVikingMemoryProvider.prefetch
    _originals["build_prefetch_entries"] = OpenVikingMemoryProvider._build_prefetch_entries

    OpenVikingMemoryProvider.initialize = _wrap_initialize(_originals["initialize"])
    OpenVikingMemoryProvider.prefetch = _wrap_prefetch(_originals["prefetch"])
    OpenVikingMemoryProvider._build_prefetch_entries = _wrap_build_prefetch_entries(
        _originals["build_prefetch_entries"]
    )

    _applied["card"] = True
    logger.info("openviking_owner_recall_patch applied: recall-card")


def _revert_card() -> None:
    global _applied
    from plugins.memory.openviking import OpenVikingMemoryProvider

    orig_init = _originals.pop("initialize", None)
    orig_prefetch = _originals.pop("prefetch", None)
    orig_build = _originals.pop("build_prefetch_entries", None)
    if orig_init is not None:
        OpenVikingMemoryProvider.initialize = orig_init
    if orig_prefetch is not None:
        OpenVikingMemoryProvider.prefetch = orig_prefetch
    if orig_build is not None:
        OpenVikingMemoryProvider._build_prefetch_entries = orig_build
    _applied["card"] = False
    logger.info("openviking_owner_recall_patch reverted: recall-card")


# ---------------------------------------------------------------------------
# Patch registration
# ---------------------------------------------------------------------------

def apply_patch(
    advisory: Optional[bool] = None,
    dedup: Optional[bool] = None,
    card: Optional[bool] = None,
) -> None:
    """Apply owner OpenViking recall extensions.

    Args:
        advisory: Override ``owner.openviking_sync_recall.advisory``.
        dedup: Override ``owner.openviking_sync_recall.dedup``.
        card: Override ``owner.openviking_recall_card.enabled``.
    """
    sync_cfg = _load_sync_cfg()
    card_cfg = _load_card_cfg()

    advisory_enabled = advisory if advisory is not None else bool(sync_cfg["advisory"])
    dedup_enabled = dedup if dedup is not None else bool(sync_cfg["dedup"])
    card_enabled = card if card is not None else bool(card_cfg["enabled"])

    if advisory_enabled:
        if not _applied["advisory"]:
            _apply_advisory()
    else:
        if _applied["advisory"]:
            _revert_advisory()

    if dedup_enabled:
        if not _applied["dedup"]:
            _apply_dedup()
    else:
        if _applied["dedup"]:
            _revert_dedup()

    if card_enabled:
        if not _applied["card"]:
            _apply_card()
    else:
        if _applied["card"]:
            _revert_card()


def revert_patch() -> None:
    """Revert all changes made by :func:`apply_patch`."""
    if _applied["card"]:
        _revert_card()
    if _applied["dedup"]:
        _revert_dedup()
    if _applied["advisory"]:
        _revert_advisory()
