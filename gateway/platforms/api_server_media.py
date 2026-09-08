"""API-server delivery of agent-produced files (``MEDIA:<path>`` tags).

Remote OpenAI-compatible frontends cannot read the gateway's local filesystem.
Image tags are inlined as markdown data URLs (existing ``_resolve_media_to_data_urls``).
Every remaining deliverable file is registered under an opaque id and served
from ``GET /v1/media/{media_id}`` — never a raw path. The same
``validate_media_delivery_path`` gate used by Feishu/Telegram applies on both
register and download.

Callers attach the public file list to the OpenAI ``hermes.files`` extra so
streaming clients (xy-portal) can render download cards after the finish chunk.
"""
from __future__ import annotations

import logging
import mimetypes
import re
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

logger = logging.getLogger(__name__)

MEDIA_DOWNLOAD_PATH = "/v1/media/{media_id}"
_MEDIA_ID_RE = re.compile(r"^med_[A-Za-z0-9_-]{8,64}$")
_DEFAULT_TTL_SECONDS = 24 * 3600
_DEFAULT_MAX_ENTRIES = 512
_DEFAULT_MAX_BYTES = 64 * 1024 * 1024

_MIME_BY_SUFFIX = {
    ".md": "text/markdown; charset=utf-8",
    ".markdown": "text/markdown; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".csv": "text/csv; charset=utf-8",
    ".tsv": "text/tab-separated-values; charset=utf-8",
    ".json": "application/json",
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".pdf": "application/pdf",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".zip": "application/zip",
    ".gz": "application/gzip",
    ".tgz": "application/gzip",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".svg": "image/svg+xml",
}


def guess_media_mime(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in _MIME_BY_SUFFIX:
        return _MIME_BY_SUFFIX[suffix]
    guessed, _ = mimetypes.guess_type(path)
    return guessed or "application/octet-stream"


def _safe_filename(path: str) -> str:
    name = Path(path).name.strip() or "download"
    return name.replace('"', "").replace("\r", "").replace("\n", "")[:180]


@dataclass
class MediaRecord:
    media_id: str
    path: str
    name: str
    mime: str
    size: int
    created_at: float
    session_id: str = ""

    def to_public_dict(self) -> Dict[str, Any]:
        return {
            "id": self.media_id,
            "name": self.name,
            "mime": self.mime,
            "size": self.size,
            "download": MEDIA_DOWNLOAD_PATH.format(media_id=self.media_id),
        }


class ApiMediaStore:
    """TTL-bounded in-memory index of files the agent tagged with MEDIA:."""

    def __init__(
        self,
        *,
        ttl_seconds: float = _DEFAULT_TTL_SECONDS,
        max_entries: int = _DEFAULT_MAX_ENTRIES,
        max_bytes: int = _DEFAULT_MAX_BYTES,
    ) -> None:
        self._ttl = float(ttl_seconds)
        self._max_entries = int(max_entries)
        self._max_bytes = int(max_bytes)
        self._lock = threading.Lock()
        self._records: Dict[str, MediaRecord] = {}

    def register(self, path: str, *, session_id: str = "") -> Optional[Dict[str, Any]]:
        from gateway.platforms.base import validate_media_delivery_path

        safe = validate_media_delivery_path(path)
        if not safe:
            return None
        p = Path(safe)
        try:
            st = p.stat()
        except OSError:
            return None
        if not p.is_file():
            return None
        if st.st_size > self._max_bytes:
            logger.warning("API media skipped (too large): %s (%s bytes)", p.name, st.st_size)
            return None

        rec = MediaRecord(
            media_id="med_" + secrets.token_urlsafe(12),
            path=str(p),
            name=_safe_filename(str(p)),
            mime=guess_media_mime(str(p)),
            size=int(st.st_size),
            created_at=time.time(),
            session_id=session_id or "",
        )
        with self._lock:
            self._sweep_locked(now=rec.created_at)
            while len(self._records) >= self._max_entries:
                oldest = min(self._records.values(), key=lambda r: r.created_at)
                self._records.pop(oldest.media_id, None)
            self._records[rec.media_id] = rec
        return rec.to_public_dict()

    def get(self, media_id: str) -> Optional[MediaRecord]:
        if not media_id or not _MEDIA_ID_RE.match(media_id):
            return None
        now = time.time()
        with self._lock:
            self._sweep_locked(now=now)
            rec = self._records.get(media_id)
            if rec is None:
                return None
            if now - rec.created_at > self._ttl:
                self._records.pop(media_id, None)
                return None
            return rec

    def _sweep_locked(self, *, now: float) -> None:
        expired = [k for k, r in self._records.items() if now - r.created_at > self._ttl]
        for k in expired:
            self._records.pop(k, None)


def finalize_api_media(
    text: str,
    store: ApiMediaStore,
    *,
    session_id: str = "",
) -> Tuple[str, List[Dict[str, Any]]]:
    """Inline small images, register remaining MEDIA files, strip tags.

    Returns ``(display_text, public_file_list)``. ``display_text`` has image
    tags replaced with markdown data URLs and remaining ``MEDIA:`` tags
    removed so they never leak raw paths to the client. The file list is
    empty when the reply had no deliverable attachments.
    """
    from gateway.platforms.api_server import _resolve_media_to_data_urls
    from gateway.platforms.base import BasePlatformAdapter

    raw = text or ""
    if "MEDIA:" not in raw:
        return raw, []

    inlined = _resolve_media_to_data_urls(raw)
    pairs, cleaned = BasePlatformAdapter.extract_media(inlined)
    safe = BasePlatformAdapter.filter_media_delivery_paths(pairs)
    files: List[Dict[str, Any]] = []
    for path, _is_voice in safe:
        public = store.register(path, session_id=session_id)
        if public:
            files.append(public)
    return cleaned, files


def attach_hermes_files(payload: Dict[str, Any], files: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Merge ``files`` into ``payload["hermes"]["files"]`` when non-empty."""
    if files:
        payload.setdefault("hermes", {})["files"] = files
    return payload


def content_disposition(filename: str) -> str:
    ascii_name = filename.encode("ascii", "ignore").decode("ascii") or "download"
    utf8 = quote(filename, safe="")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{utf8}"
