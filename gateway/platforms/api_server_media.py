"""API-server delivery of agent-produced files (``MEDIA:<path>`` tags).

Remote OpenAI-compatible frontends cannot read the gateway's local filesystem.
Image tags are inlined as markdown data URLs (existing ``_resolve_media_to_data_urls``).
Every remaining deliverable file is *ingested* into a Hermes-managed store
directory and served from ``GET /v1/media/{media_id}`` — never a raw path. The
same ``validate_media_delivery_path`` gate used by Feishu/Telegram applies at
registration time.

The store directory *is* the index. An entry is a single file named
``<media_id>__<original name>``, so the id, the download filename and the MIME
type are all recoverable from the directory listing — there is no in-memory
table and no separate manifest. Two consequences follow:

* A gateway restart loses nothing. The catalogue is whatever is on disk, so
  the store lives exactly as long as the session DB it feeds and cannot drift
  out of sync with it.
* The store owns the bytes. Delivery no longer depends on where the agent
  happened to write the file, so a container-local ``/tmp`` that vanishes with
  the container, a scratch directory the agent cleans up later, or a path that
  drifts into a denylisted prefix can no longer break an already-issued card.

Callers attach the public file list to the OpenAI ``hermes.files`` extra so
streaming clients (xy-portal) can render download cards after the finish chunk.
"""
from __future__ import annotations

import logging
import mimetypes
import os
import re
import secrets
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

logger = logging.getLogger(__name__)

MEDIA_DOWNLOAD_PATH = "/v1/media/{media_id}"
_MEDIA_ID_RE = re.compile(r"^med_[A-Za-z0-9_-]{8,64}$")
_STORE_FILE_RE = re.compile(r"^med_[A-Za-z0-9_-]{8,64}__")
_NAME_SEP = "__"
_PART_SUFFIX = ".part"

# Lives under ``cache/documents`` — an unconditionally trusted root in
# ``gateway.platforms.base.MEDIA_DELIVERY_SAFE_ROOTS`` — so downloads keep
# passing the delivery gate even with ``gateway.strict`` enabled, and the
# directory sits on the same persistent volume as the rest of the profile.
_STORE_SUBDIR = ("cache", "documents", "api-media")
_STORE_DIR_ENV = "HERMES_API_MEDIA_STORE_DIR"
_STORE_TTL_ENV = "HERMES_API_MEDIA_STORE_TTL_HOURS"

_DEFAULT_TTL_HOURS = 720.0  # 30 days: session history stays browsable far longer
_DEFAULT_MAX_ENTRIES = 4096
_DEFAULT_MAX_FILE_MB = 64
_DEFAULT_MAX_TOTAL_MB = 2048
# Registrations are the only way the store grows, so bounding the sweep by
# registration count (rather than by wall clock) guarantees the entry/byte caps
# are enforced within a fixed number of deliveries even under a burst, and that
# an idle store never accumulates expired entries indefinitely.
_SWEEP_EVERY_N_REGISTRATIONS = 32
_PART_MAX_AGE_SECONDS = 3600.0

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
    for ch in ('"', "\r", "\n", "\\", "/"):
        name = name.replace(ch, "")
    return name[:180] or "download"


def default_store_dir() -> Path:
    """Return the managed media store root for this process's Hermes home."""
    from hermes_constants import get_hermes_home

    return get_hermes_home().joinpath(*_STORE_SUBDIR)


def _positive_float(env_value: Optional[str], cfg_value: Any, *, default: float) -> float:
    """First positive numeric of ``env_value`` then ``cfg_value``, else default."""
    for raw in (env_value, cfg_value):
        if raw is None or raw == "":
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return default


def _load_media_store_config() -> Dict[str, Any]:
    """Read ``gateway.api_server.media_store`` from config.yaml. Never raises."""
    try:
        from hermes_cli.config import cfg_get, load_config

        section = cfg_get(load_config(), "gateway", "api_server", "media_store", default={})
    except Exception:  # noqa: BLE001 - a config miss must not break delivery
        return {}
    return section if isinstance(section, dict) else {}


def _iter_store_files(root: Path) -> List[Path]:
    """List files this store minted (plus staging leftovers); ignore the rest.

    Nothing outside the ``med_<id>__*`` / ``*.part`` shapes is ever touched, so
    pointing the store at a directory that holds unrelated content is harmless.
    """
    found: List[Path] = []
    try:
        entries = list(root.iterdir())
    except OSError:
        return found
    for entry in entries:
        name = entry.name
        if not (name.endswith(_PART_SUFFIX) or _STORE_FILE_RE.match(name)):
            continue
        try:
            if entry.is_file():
                found.append(entry)
        except OSError:
            continue
    return found


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
    """Directory-backed store of files the agent tagged with ``MEDIA:``.

    Registration ingests the bytes into ``<root>/<media_id>__<name>``; a lookup
    resolves an id by scanning the directory for that prefix. No record is held
    in memory, so the store is restart-safe by construction and safe to share
    across threads.
    """

    def __init__(
        self,
        *,
        root: Optional[Path | str] = None,
        ttl_seconds: float = _DEFAULT_TTL_HOURS * 3600.0,
        max_entries: int = _DEFAULT_MAX_ENTRIES,
        max_bytes: int = _DEFAULT_MAX_FILE_MB * 1024 * 1024,
        max_total_bytes: int = _DEFAULT_MAX_TOTAL_MB * 1024 * 1024,
    ) -> None:
        self._root = Path(root) if root is not None else default_store_dir()
        self._ttl = float(ttl_seconds)
        self._max_entries = int(max_entries)
        self._max_bytes = int(max_bytes)
        self._max_total_bytes = int(max_total_bytes)
        self._lock = threading.Lock()
        self._pending_sweep = 0
        try:
            self._root.mkdir(parents=True, exist_ok=True)
        except OSError:
            logger.warning("API media store root is not creatable: %s", self._root, exc_info=True)

    @classmethod
    def from_config(cls) -> "ApiMediaStore":
        """Build a store from ``gateway.api_server.media_store``.

        Environment variables win over config.yaml (``HERMES_API_MEDIA_STORE_DIR``
        / ``HERMES_API_MEDIA_STORE_TTL_HOURS``), matching the precedence
        convention already used by :mod:`gateway.media_policy`.
        """
        cfg = _load_media_store_config()
        configured_dir = str(os.environ.get(_STORE_DIR_ENV) or cfg.get("dir") or "").strip()
        return cls(
            root=Path(configured_dir).expanduser() if configured_dir else None,
            ttl_seconds=_positive_float(
                os.environ.get(_STORE_TTL_ENV), cfg.get("ttl_hours"), default=_DEFAULT_TTL_HOURS
            )
            * 3600.0,
            max_entries=int(
                _positive_float(None, cfg.get("max_entries"), default=_DEFAULT_MAX_ENTRIES)
            ),
            max_bytes=int(
                _positive_float(None, cfg.get("max_file_mb"), default=_DEFAULT_MAX_FILE_MB)
                * 1024
                * 1024
            ),
            max_total_bytes=int(
                _positive_float(None, cfg.get("max_total_mb"), default=_DEFAULT_MAX_TOTAL_MB)
                * 1024
                * 1024
            ),
        )

    @property
    def root(self) -> Path:
        return self._root

    def register(self, path: str, *, session_id: str = "") -> Optional[Dict[str, Any]]:
        """Ingest ``path`` under a fresh opaque id and return its public view.

        Returns ``None`` when the path is not deliverable, is not a regular
        file, exceeds the per-file cap, or cannot be ingested. The returned id
        is the only handle the client gets — the store path stays internal.
        """
        from gateway.platforms.base import validate_media_delivery_path

        safe = validate_media_delivery_path(path)
        if not safe:
            return None
        src = Path(safe)
        try:
            st = src.stat()
        except OSError:
            return None
        if not src.is_file():
            return None
        if st.st_size > self._max_bytes:
            logger.warning("API media skipped (too large): %s (%s bytes)", src.name, st.st_size)
            return None

        media_id = "med_" + secrets.token_urlsafe(12)
        name = _safe_filename(str(src))
        now = time.time()
        dest = self._root / f"{media_id}{_NAME_SEP}{name}"
        try:
            self._ingest_bytes(src, dest)
            # Stamp the registration time: ``copyfile`` leaves whatever mtime
            # the write produced, and nothing may inherit the producer's age
            # (an old source file would otherwise be born already expired).
            os.utime(dest, (now, now))
            size = int(dest.stat().st_size)
        except OSError:
            logger.warning("API media ingest failed: %s", src, exc_info=True)
            self._discard(dest)
            return None

        rec = MediaRecord(
            media_id=media_id,
            path=str(dest),
            name=name,
            mime=guess_media_mime(name),
            size=size,
            created_at=now,
            session_id=session_id or "",
        )
        self._maybe_sweep(now=now)
        return rec.to_public_dict()

    def get(self, media_id: str) -> Optional[MediaRecord]:
        """Resolve an id to its stored record, or ``None`` when unknown/expired."""
        if not media_id or not _MEDIA_ID_RE.match(media_id):
            return None
        found = self._find(media_id)
        if found is None:
            return None
        dest, name = found
        try:
            st = dest.stat()
        except OSError:
            return None
        if time.time() - st.st_mtime > self._ttl:
            self._discard(dest)
            return None
        return MediaRecord(
            media_id=media_id,
            path=str(dest),
            name=name,
            mime=guess_media_mime(name),
            size=int(st.st_size),
            created_at=st.st_mtime,
        )

    def sweep(self, *, now: Optional[float] = None) -> int:
        """Drop stale staging files, expired entries, then oldest-first overflow.

        Returns the number of files removed. Only files this store minted are
        considered (see :func:`_iter_store_files`).
        """
        moment = time.time() if now is None else float(now)
        removed = 0
        live: List[Tuple[float, int, Path]] = []
        for path in _iter_store_files(self._root):
            try:
                st = path.stat()
            except OSError:
                continue
            if path.name.endswith(_PART_SUFFIX):
                if moment - st.st_mtime > _PART_MAX_AGE_SECONDS:
                    removed += self._discard(path)
                continue
            if moment - st.st_mtime > self._ttl:
                removed += self._discard(path)
                continue
            live.append((st.st_mtime, int(st.st_size), path))
        live.sort()
        total = sum(size for _, size, _ in live)
        while live and (len(live) > self._max_entries or total > self._max_total_bytes):
            _, size, path = live.pop(0)
            removed += self._discard(path)
            total -= size
        return removed

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _find(self, media_id: str) -> Optional[Tuple[Path, str]]:
        """Resolve an id to ``(blob path, display name)`` via directory scan.

        The id is regex-validated by the caller, so the prefix carries no glob
        or path separators — a traversal can never reach the filesystem.
        """
        prefix = f"{media_id}{_NAME_SEP}"
        try:
            entries = list(self._root.iterdir())
        except OSError:
            return None
        for entry in entries:
            if not entry.name.startswith(prefix):
                continue
            try:
                if entry.is_file():
                    return entry, entry.name[len(prefix):]
            except OSError:
                continue
        return None

    def _ingest_bytes(self, src: Path, dest: Path) -> None:
        """Atomically snapshot the bytes of ``src`` at ``dest``.

        Always a copy, never a hard link: linking would share the inode, so the
        ``os.utime`` below would rewrite the *producer's* mtime (perturbing the
        ``trust_recent_files`` recency window) and a later in-place rewrite by
        the producer would silently change the bytes behind an already-issued
        card. Staging through a ``.part`` file keeps a half-written entry from
        ever being served.
        """
        staging = dest.with_name(dest.name + _PART_SUFFIX)
        shutil.copyfile(src, staging)
        try:
            os.replace(staging, dest)
        except OSError:
            self._discard(staging)
            raise

    def _maybe_sweep(self, *, now: float) -> None:
        """Run the retention sweep every ``_SWEEP_EVERY_N_REGISTRATIONS`` writes."""
        with self._lock:
            if self._pending_sweep > 0:
                self._pending_sweep -= 1
                return
            self._pending_sweep = _SWEEP_EVERY_N_REGISTRATIONS - 1
        try:
            self.sweep(now=now)
        except Exception:  # noqa: BLE001 - retention must never fail a delivery
            logger.debug("API media sweep failed", exc_info=True)

    @staticmethod
    def _discard(path: Path) -> int:
        try:
            path.unlink()
            return 1
        except OSError:
            return 0


def finalize_api_media(
    text: str,
    store: ApiMediaStore,
    *,
    session_id: str = "",
) -> Tuple[str, List[Dict[str, Any]]]:
    """Inline small images, ingest remaining MEDIA files, strip tags.

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
