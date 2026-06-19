"""Session Archiver Plugin — Archive completed sessions to Qdrant.

Fires on ``on_session_finalize`` (CLI exit, /new, /reset) for all platforms.
Reads conversation from state.db, generates Chinese summary via DeepSeek V4
Flash, writes dense+sparse vectors to the Qdrant ``events`` collection.

Env vars (from ~/.hermes/.env):
    DEEPSEEK_BASE_URL — LLM API base (default: https://api.deepseek.com/v1)
    DEEPSEEK_API_KEY  — LLM API key
    DASHSCOPE_BASE_URL — Embedding API base (default: https://dashscope.aliyuncs.com/compatible-mode/v1)
    DASHSCOPE_API_KEY  — Embedding API key
    QDRANT_URL       — Qdrant endpoint (default: http://localhost:6333)
    QDRANT_KEY       — Qdrant API key
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

# ---------------------------------------------------------------------------
# Logger — DailySizeRotatingFileHandler (same pattern as other hooks)
# ---------------------------------------------------------------------------

def _log_dir() -> Path:
    from hermes_constants import get_hermes_home

    return get_hermes_home() / "logs"


_LOG_DIR = _log_dir()

try:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    from logging.handlers import BaseRotatingHandler  # noqa: F401

    class DailySizeRotatingFileHandler(logging.Handler):
        """按天 + 按大小轮转的日志 Handler。"""

        def __init__(self, prefix, log_dir, max_bytes=5 * 1024 * 1024,
                     retention_days=30, encoding="utf-8", level=logging.NOTSET):
            super().__init__(level)
            self.prefix = prefix
            self.log_dir = Path(log_dir)
            self.max_bytes = max_bytes
            self.retention_days = retention_days
            self.encoding = encoding
            self._today = None
            self._seq = 0
            self._stream = None
            self._fp = None
            self.log_dir.mkdir(parents=True, exist_ok=True)

        def _build_path(self, seq):
            today_str = datetime.now().strftime("%Y-%m-%d")
            if seq == 0:
                return self.log_dir / f"{self.prefix}-{today_str}.log"
            return self.log_dir / f"{self.prefix}-{today_str}.{seq}.log"

        def _resolve_target(self):
            from datetime import date, timedelta
            today = date.today()
            if today != self._today:
                self._today = today
                self._seq = 0
                # Retention cleanup: remove logs older than retention_days
                if self.retention_days > 0:
                    cutoff = today - timedelta(days=self.retention_days)
                    for log_file in self.log_dir.glob(f"{self.prefix}-*.log*"):
                        try:
                            stem = log_file.stem
                            date_part = stem.rsplit(".", 1)[0] if "." in stem else stem
                            date_str = date_part.rsplit("-", 3)[-3:]
                            if len(date_str) == 3:
                                file_date = date(int(date_str[0]), int(date_str[1]), int(date_str[2]))
                                if file_date < cutoff:
                                    log_file.unlink(missing_ok=True)
                        except Exception:
                            pass
            while True:
                path = self._build_path(self._seq)
                if path.exists() and path.stat().st_size >= self.max_bytes:
                    self._seq += 1
                    continue
                break
            return path

        def _open(self, path):
            if self._fp is not None and self._stream == path:
                return
            self._close()
            self._stream = path
            self._fp = path.open("a", encoding=self.encoding)

        def _close(self):
            if self._fp is not None:
                try:
                    self._fp.close()
                except Exception:
                    pass
                self._fp = None

        def emit(self, record):
            try:
                msg = self.format(record)
                path = self._resolve_target()
                self._open(path)
                if self._fp is not None:
                    self._fp.write(msg + "\n")
                    self._fp.flush()
            except Exception:
                self.handleError(record)

        def close(self):
            self._close()
            super().close()

    _file_handler = DailySizeRotatingFileHandler(
        prefix="session-archiver",
        log_dir=_LOG_DIR,
        max_bytes=5 * 1024 * 1024,
        retention_days=30,
    )
    _file_handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger = logging.getLogger("hermes.session-archiver")
    logger.addHandler(_file_handler)
    logger.setLevel(logging.DEBUG)
except Exception:
    logger = logging.getLogger("hermes.session-archiver")
    logger.setLevel(logging.DEBUG)

# ---------------------------------------------------------------------------
# Config — relies on the main Hermes process having already loaded
# ~/.hermes/.env (via hermes_cli.env_loader).  No custom parsing here.
# ---------------------------------------------------------------------------

def _hermes_home() -> Path:
    from hermes_constants import get_hermes_home

    return get_hermes_home()


_HERMES_HOME = _hermes_home()
_STATE_DB = _HERMES_HOME / "state.db"

_EMBED_MODEL = "text-embedding-v4"
_VECTOR_DIM = 1024
_EMBED_MAX_CHARS = 30000  # DashScope OpenAI-compatible limit
_LLM_MODEL = "deepseek-v4-flash"
_LLM_TIMEOUT = 120
_QDRANT_TIMEOUT = 30
_CONTENT_MAX_CHARS = 50_000  # Hard cap for content field
_TOOL_OUTPUT_MAX_CHARS = 200



def _cfg(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


# ---------------------------------------------------------------------------
# DB helpers — read-only access to state.db
# ---------------------------------------------------------------------------

def _get_session(session_id: str) -> Optional[Dict[str, Any]]:
    """Read session metadata from state.db."""
    if not _STATE_DB.exists():
        return None
    try:
        conn = sqlite3.connect(str(_STATE_DB), timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()
    except Exception as e:
        logger.warning("Failed to read session %s: %s", session_id[:16], e)
        return None


def _get_messages(session_id: str) -> List[Dict[str, Any]]:
    """Read all messages for a session from state.db."""
    if not _STATE_DB.exists():
        return []
    try:
        conn = sqlite3.connect(str(_STATE_DB), timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT * FROM messages WHERE session_id = ? ORDER BY id",
                (session_id,),
            ).fetchall()
            messages = []
            for row in rows:
                msg = dict(row)
                # Skip thinking-prefill internal messages
                if msg.get("_thinking_prefill"):
                    continue
                if msg.get("tool_calls"):
                    try:
                        parsed = json.loads(msg["tool_calls"])
                        msg["tool_calls"] = parsed if parsed is not None else []
                    except (json.JSONDecodeError, TypeError):
                        msg["tool_calls"] = []
                messages.append(msg)
            return messages
        finally:
            conn.close()
    except Exception as e:
        logger.warning("Failed to read messages for %s: %s",
                        session_id[:16], e)
        return []


# ---------------------------------------------------------------------------
# Conversation formatter
# ---------------------------------------------------------------------------

# Strip hook-injected extra_context (recall blocks) from user messages before archiving
_RECALL_STRIP_RE = re.compile(
    r'\n*<!-- HERMES_HOOK_CONTEXT_START -->.*?<!-- HERMES_HOOK_CONTEXT_END -->\n*',
    re.DOTALL,
)

def _truncate_tool_output(text: str, max_chars: int = _TOOL_OUTPUT_MAX_CHARS) -> str:
    """Truncate tool output, keeping head."""
    if not text or len(text) <= max_chars:
        return text or ""
    return text[:max_chars] + f"... (truncated, {len(text)} chars total)"


def _format_conversation(
    session: Dict[str, Any], messages: List[Dict[str, Any]]
) -> str:
    """Format session messages as markdown content for embedding/storage."""
    title = session.get("title") or session.get("id", "unknown")
    started = session.get("started_at", 0)
    try:
        dt = datetime.fromtimestamp(started, tz=timezone.utc)
        ts = dt.strftime("%Y-%m-%d %H:%M UTC")
    except (ValueError, OSError):
        ts = "unknown"

    lines = [
        f"# Session: {title}",
        f"Started: {ts}",
        f"Model: {session.get('model', 'unknown')}",
        f"Messages: {len(messages)}",
        "",
        "---",
        "",
    ]

    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")

        if role == "user":
            text = content if isinstance(content, str) else str(content)
            text = _RECALL_STRIP_RE.sub('', text)
            lines.append(f"[user]\n{text}\n")
        elif role == "assistant":
            text = content if isinstance(content, str) else str(content)
            lines.append(f"[assistant]\n{text}\n")
        elif role == "tool":
            tool_name = msg.get("tool_name", "unknown")
            if isinstance(content, str):
                text = _truncate_tool_output(content)
            else:
                text = _truncate_tool_output(str(content))
            lines.append(f"[tool: {tool_name}]\n{text}\n")

    result = "\n".join(lines)
    if len(result) > _CONTENT_MAX_CHARS:
        result = result[:_CONTENT_MAX_CHARS] + (
            f"\n\n[... content truncated at {_CONTENT_MAX_CHARS} chars]"
        )
    return result


# ---------------------------------------------------------------------------
# LLM summary — DeepSeek API (OpenAI-compatible)
# ---------------------------------------------------------------------------

_SUMMARY_PROMPT = """你是一个对话摘要助手。请对以下对话进行总结，严格按以下格式输出：

【关键事实/进展/问题】
- （列出对话中的关键事实、重要进展、未解决的问题，每条一行，用简洁的短句）

【整体摘要】
（用100-200字概述这次对话的整体内容和结论）

注意：
- 使用中文
- 重点提取事实性信息，忽略寒暄和过程性内容
- 如果对话中有明确的决策或结论，必须包含
- 如果对话中涉及代码、配置、命令等技术细节，简要概括其目的"""


def _generate_summary(content: str) -> str:
    """Call DeepSeek API to generate a Chinese summary of the conversation."""
    api_key = _cfg("DEEPSEEK_API_KEY")
    base_url = _cfg("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")

    if not api_key:
        return "摘要生成失败: DEEPSEEK_API_KEY 未配置"

    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    llm_input = content
    if len(content) > 800_000:
        llm_input = content[:800_000] + "\n\n[... 内容过长，已截断]"

    payload = {
        "model": _LLM_MODEL,
        "messages": [
            {"role": "system", "content": _SUMMARY_PROMPT},
            {"role": "user", "content": llm_input},
        ],
        "max_tokens": 1024,
        "temperature": 0.3,
    }

    try:
        resp = requests.post(
            url, headers=headers, json=payload, timeout=_LLM_TIMEOUT
        )
        if resp.status_code != 200:
            return f"摘要生成失败: HTTP {resp.status_code} — {resp.text[:200]}"
        data = resp.json()
        choices = data.get("choices", [])
        if choices:
            return choices[0].get("message", {}).get("content", "")
        return "摘要生成失败: API 返回空 choices"
    except Exception as e:
        return f"摘要生成失败: {e}"


# ---------------------------------------------------------------------------
# Embedding — DashScope OpenAI-compatible + local BM25 sparse
# ---------------------------------------------------------------------------

def _compute_bm25_sparse(
    text: str, vocab_size: int = 100000, k1: float = 1.5, b: float = 0.75
) -> Dict[str, list]:
    def _det_hash(term: str) -> int:
        """Deterministic hash (MD5) — Python hash() is randomised per process."""
        return int.from_bytes(
            hashlib.md5(term.encode("utf-8")).digest()[:8], "big"
        )

    """Compute BM25 sparse vector from text (local, no external API).

    Tokenizes text, hashes tokens to fixed vocab, applies BM25 saturation.
    Returns {indices: [...], values: [...]} for Qdrant sparse vector format.
    """
    # Tokenize: lowercase, split on non-alphanumeric, keep 2+ char tokens + CJK
    tokens = re.findall(r"[a-z0-9\u4e00-\u9fff]{2,}", text.lower())
    if not tokens:
        return {"indices": [], "values": []}

    # Term frequency
    tf: Dict[str, int] = {}
    for t in tokens:
        tf[t] = tf.get(t, 0) + 1

    # BM25 TF saturation per term (single-doc context, no corpus IDF)
    sparse: Dict[int, float] = {}
    for term, count in tf.items():
        idx = _det_hash(term) % vocab_size
        if idx < 0:
            idx += vocab_size
        score = count * (k1 + 1) / (count + k1 * (1 - b + b * 1.0))
        sparse[idx] = sparse.get(idx, 0.0) + score

    sorted_items = sorted(sparse.items())
    return {
        "indices": [i for i, _ in sorted_items],
        "values": [round(v, 6) for _, v in sorted_items],
    }


def _try_dashscope_oai_embedding(text: str) -> Optional[List[float]]:
    """Try DashScope OpenAI-compatible /embeddings endpoint. Returns dense vector or None."""
    api_key = _cfg("DASHSCOPE_API_KEY")
    base_url = _cfg("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    if not api_key:
        return None

    url = f"{base_url.rstrip('/')}/embeddings"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": _EMBED_MODEL, "input": text}

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            items = data.get("data", [])
            if items and items[0].get("embedding"):
                return items[0]["embedding"]
        logger.debug("DashScope OAI embedding HTTP %d (no embedding returned)",
                     resp.status_code)
    except Exception as e:
        logger.debug("DashScope OAI embedding failed: %s (no embedding returned)", e)
    return None




def _get_embedding(text: str) -> Optional[Dict[str, Any]]:
    """Get dense + sparse embedding via DashScope OpenAI-compatible endpoint.

    Returns {dense: [...], sparse: {indices, values}} or None.
    """
    embed_text = text[:_EMBED_MAX_CHARS] if len(text) > _EMBED_MAX_CHARS else text

    dense = _try_dashscope_oai_embedding(embed_text)
    if dense:
        sparse = _compute_bm25_sparse(embed_text)
        logger.debug("Embedding via DashScope: dense=%dd, sparse=%d tokens",
                     len(dense), len(sparse["indices"]))
        return {"dense": dense, "sparse": sparse}

    logger.error("DashScope embedding failed")
    return None


# ---------------------------------------------------------------------------
# Qdrant helpers
# ---------------------------------------------------------------------------

def _make_point_id(uri: str) -> str:
    """Generate deterministic Qdrant point ID from URI (same as migration)."""
    return hashlib.sha256(uri.encode()).hexdigest()[:32]


def _ensure_events_collection():
    """Ensure the events collection exists with correct vector config."""
    qdrant_url = _cfg("QDRANT_URL", "http://localhost:6333")
    qdrant_key = _cfg("QDRANT_KEY")
    headers = {"api-key": qdrant_key} if qdrant_key else {}

    try:
        resp = requests.get(
            f"{qdrant_url}/collections/events",
            headers=headers,
            timeout=_QDRANT_TIMEOUT,
        )
        if resp.status_code == 200:
            return  # Already exists
    except Exception:
        pass

    # Create collection with named dense + sparse vectors
    create_payload = {
        "vectors": {
            "dense": {
                "size": _VECTOR_DIM,
                "distance": "Cosine",
            },
        },
        "sparse_vectors": {
            "sparse": {},
        },
    }
    try:
        resp = requests.put(
            f"{qdrant_url}/collections/events",
            headers={**headers, "Content-Type": "application/json"},
            json=create_payload,
            timeout=_QDRANT_TIMEOUT,
        )
        if resp.status_code in (200, 201):
            logger.info("Created events collection in Qdrant")
        else:
            logger.error(
                "Failed to create events collection: HTTP %d — %s",
                resp.status_code, resp.text[:200],
            )
    except Exception as e:
        logger.error("Failed to create events collection: %s", e)


def _upsert_point(point: Dict[str, Any]) -> bool:
    """Upsert a single point to Qdrant events collection."""
    qdrant_url = _cfg("QDRANT_URL", "http://localhost:6333")
    qdrant_key = _cfg("QDRANT_KEY")
    headers = {
        "Content-Type": "application/json",
    }
    if qdrant_key:
        headers["api-key"] = qdrant_key

    payload = {"points": [point]}
    try:
        resp = requests.put(
            f"{qdrant_url}/collections/events/points",
            headers=headers,
            json=payload,
            timeout=_QDRANT_TIMEOUT,
        )
        if resp.status_code == 200:
            return True
        logger.error(
            "Qdrant upsert failed: HTTP %d — %s",
            resp.status_code, resp.text[:200],
        )
        return False
    except Exception as e:
        logger.error("Qdrant upsert failed: %s", e)
        return False


# ---------------------------------------------------------------------------
# Main archive logic
# ---------------------------------------------------------------------------

def archive_session(
    session_id: str,
    platform: str = "",
    source: str = "plugin",
) -> None:
    """Archive a completed session to Qdrant.

    Called by the on_session_finalize plugin hook.  Reads the full conversation
    from state.db, generates an LLM summary, and writes to the events
    collection with dense+sparse vectors.

    Args:
        session_id: The session that just ended.
        platform:   Platform name (cli, feishu, telegram, etc.).
        source:     Trigger source ("plugin" or "gateway").
    """
    if not session_id:
        logger.debug("archive_session called with empty session_id, skipping")
        return

    logger.info("Archiving session %s (platform=%s)", session_id[:16], platform)

    try:
        # 1. Read from state.db
        session = _get_session(session_id)
        if not session:
            logger.warning("Session %s not found in state.db, skipping",
                           session_id[:16])
            return

        messages = _get_messages(session_id)
        if not messages:
            logger.info("Session %s has no messages, skipping",
                        session_id[:16])
            return

        # 2. Format conversation
        content = _format_conversation(session, messages)
        title = session.get("title") or session_id

        # 3. Generate LLM summary
        abstract = _generate_summary(content)

        # 4. Compute date_path and name
        started = session.get("started_at", time.time())
        try:
            dt = datetime.fromtimestamp(started, tz=timezone.utc)
            date_path = f"events/{dt.strftime('%Y/%m')}"
            display_name = f"{dt.strftime('%Y-%m-%d %H:%M')} | {title}"
        except (ValueError, OSError):
            date_path = "events/unknown"
            display_name = f"unknown | {title}"

        # 5. Build URI and point ID (idempotent)
        uri = f"urn:session:{session_id}"
        point_id = _make_point_id(uri)

        # 6. Get embedding (DashScope OpenAI-compatible + BM25 sparse)
        # Use abstract + first part of content for embedding (better search)
        embed_text = abstract + "\n\n" + content[:5000]
        emb_result = _get_embedding(embed_text)
        if not emb_result:
            logger.error("Embedding failed for session %s, aborting write",
                         session_id[:16])
            return

        dense_vector = emb_result["dense"]
        sparse_vector = emb_result["sparse"]

        # 7. Ensure collection exists
        _ensure_events_collection()

        # 8. Build and upsert point
        point = {
            "id": point_id,
            "vector": {"dense": dense_vector, "sparse": sparse_vector},
            "payload": {
                "uri": uri,
                "name": display_name,
                "category": "events",
                "type": "session",
                "abstract": abstract,
                "content": content,
                "level": 3,
                "date_path": date_path,
                "ts": int(started),  # unix epoch seconds — for Qdrant payload index + order_by
                "session_id": session_id,
                "platform": platform or session.get("source", ""),
                "model": session.get("model", ""),
                "message_count": len(messages),
                "source": source,
                "tenant_id": _cfg("QDRANT_TENANT_ID", "default"),
            },
        }

        if _upsert_point(point):
            logger.info(
                "✓ Archived session %s → Qdrant point %s "
                "(%d messages, %d chars content)",
                session_id[:16], point_id, len(messages), len(content),
            )
        else:
            logger.error("✗ Failed to archive session %s to Qdrant",
                         session_id[:16])

    except Exception as e:
        logger.error("archive_session failed for %s: %s",
                     session_id[:16], e, exc_info=True)


# ---------------------------------------------------------------------------
# Plugin entry point
# ---------------------------------------------------------------------------

def register(ctx) -> None:
    """Register session-archiver as a plugin hook."""
    def _on_session_finalize(**kwargs):
        """Callback for on_session_finalize hook."""
        session_id = kwargs.get("session_id", "")
        platform = kwargs.get("platform", "")
        if session_id:
            archive_session(session_id, platform=platform, source="plugin")

    ctx.register_hook("on_session_finalize", _on_session_finalize)
    logger.info("session-archiver plugin registered (on_session_finalize)")
