"""Shared library for OpenViking memory quality tools.

Connection config is read ONLY from Hermes:

1. Process environment variables (OPENVIKING_*)
2. ``$HERMES_HOME/.env`` (default ``~/.hermes/.env``)

No fallback to ``~/.openviking/ov.conf`` / ``ovcli.conf``.
No admin user-key resolution. No network I/O on import.

Scan focus (read-only analysis for later pipelines):
- non-Chinese natural-language content
- near-duplicates by stored dense vectors (NOT exact peer mirrors)
- preference / hard-claim candidates + human_* governance tags
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GENERATED_SUMMARY_NAMES = {
    ".abstract.md",
    ".overview.md",
    ".read.md",
    ".full.md",
    ".relations.json",
}

# Skip pure system noise under memories (not user knowledge).
SKIP_DIR_NAMES = {
    "privacy",
}

# Categories that are mostly auto-extracted event logs; still scannable but
# near-dup noise is high. Callers can exclude via --exclude-category.
DEFAULT_EXCLUDE_SIMILAR_CATEGORIES = frozenset()

MIN_STOPWORD_HITS = 3
MIN_DENSITY = 0.10
MIN_LATIN_WORDS = 3
# English-heavy / mixed Latin content with very little Chinese.
MIN_LATIN_CHARS_FOR_EN = 40
MAX_ZH_RATIO_FOR_FLAG = 0.30

EMBED_SNIPPET_LIMIT = 2000
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.5

_PEER_SEGMENT_RE = re.compile(r"/peers/[^/]+")
_LATIN_WORD_RE = re.compile(r"[a-z\u00c0-\u024f]+", re.IGNORECASE)
_ZH_RE = re.compile(r"[\u4e00-\u9fff]")
_LATIN_CHAR_RE = re.compile(r"[A-Za-z\u00c0-\u024f]")

LATIN_STOPWORDS: Dict[str, set] = {
    "pt": set(
        "a as com da de do dos e em este esta isso lhe mais mas mesmo na no nos "
        "o os ou para por que se sem ser sua sao um uma usuario preferencias "
        "projeto documento configuracao".split()
    ),
    "es": set(
        "a al como con de del el ella ellos en es esta este esto ha la las le "
        "les lo los mas me mi muy no nos o para por que se su sus un una "
        "usuario preferencias proyecto documento configuracion".split()
    ),
    "it": set(
        "che chi ci come con da del della di e il in la le lo piu non o per "
        "questa questo si un una utente preferenze progetto documento "
        "configurazione".split()
    ),
    "fr": set(
        "au aux avec ce ces dans de des du elle en est et il ils je la le les "
        "leur mais me mon ne nos nous on ou par pas plus pour que qui se son "
        "sur tu un une utilisateur preferences projet document configuration".split()
    ),
    "de": set(
        "aber auch auf das dem den der des die ein eine es fuer habe hat ich "
        "in ist mit nach nicht sich sie sind so und von wir zu benutzer "
        "dokument projekt konfiguration".split()
    ),
    # Lightweight English signal (common function words).
    "en": set(
        "the a an and or but if then else when while for with without from to "
        "of in on at by as is are was were be been being this that these those "
        "it its they them their we our you your not no yes can could should "
        "would will just also more most other into about over after before "
        "user preference project document configuration memory".split()
    ),
}

LATIN_ACCENT_PATTERNS: Dict[str, re.Pattern] = {
    "pt": re.compile(r"[áâãàçéêíóôõú]", re.IGNORECASE),
    "es": re.compile(r"[áéíóúüñ¿¡]", re.IGNORECASE),
    "it": re.compile(r"[àèéìòù]", re.IGNORECASE),
    "fr": re.compile(r"[àâæçéèêëîïôœùûüÿ]", re.IGNORECASE),
    "de": re.compile(r"[äöüß]", re.IGNORECASE),
    "en": re.compile(r"$a"),  # no-op; English has no special accents required
}

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"


def get_logger(name: str = "viking-memory") -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()  # stderr
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


logger = get_logger()


# ---------------------------------------------------------------------------
# Config (HERMES_HOME/.env only)
# ---------------------------------------------------------------------------


def hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes")).expanduser()


def hermes_env_path() -> Path:
    return hermes_home() / ".env"


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("\"", "'"):
        return value[1:-1]
    return value


def read_dotenv(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return values
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = _strip_quotes(value.strip())
    return values


@dataclass(frozen=True)
class OVConfig:
    endpoint: str
    api_key: str
    account: str
    user: str
    agent: str
    source: str

    @property
    def user_memories_uri(self) -> str:
        return f"viking://user/{self.user}/memories"

    @property
    def peer_memories_uri(self) -> str:
        return f"viking://user/{self.user}/peers/{self.agent}/memories"


def load_ov_config(*, dotenv_path: Optional[Path] = None) -> OVConfig:
    """Resolve OpenViking connection from env + HERMES_HOME/.env."""
    path = dotenv_path or hermes_env_path()
    file_vals = read_dotenv(path)

    def pick(*keys: str, default: str = "") -> str:
        for key in keys:
            if key in os.environ and os.environ[key] != "":
                return os.environ[key].strip()
            if key in file_vals and file_vals[key] != "":
                return file_vals[key].strip()
        return default

    endpoint = pick("OPENVIKING_ENDPOINT", "OV_API", default="").rstrip("/")
    api_key = pick("OPENVIKING_API_KEY", "OV_ROOT_KEY", "OV_API_KEY", default="")
    account = pick("OPENVIKING_ACCOUNT", default="default")
    user = pick("OPENVIKING_USER", "OPENVIKING_USER_ID", "OV_USER_ID", default="")
    agent = pick("OPENVIKING_AGENT", default="hermes")

    if not endpoint:
        raise RuntimeError(
            "OPENVIKING_ENDPOINT not set. Add it to $HERMES_HOME/.env "
            f"(looked at {path})"
        )
    if not api_key:
        raise RuntimeError(
            "OPENVIKING_API_KEY not set. Add it to $HERMES_HOME/.env "
            f"(looked at {path})"
        )
    if not user:
        raise RuntimeError(
            "OPENVIKING_USER not set. Add it to $HERMES_HOME/.env "
            f"(looked at {path})"
        )

    source = f"env+{path}" if path.exists() else "env"
    return OVConfig(
        endpoint=endpoint,
        api_key=api_key,
        account=account,
        user=user,
        agent=agent,
        source=source,
    )


# ---------------------------------------------------------------------------
# URI helpers
# ---------------------------------------------------------------------------


def canonical_uri(uri: str) -> str:
    """Strip ``/peers/<name>`` so user and peer mirror paths align."""
    return _PEER_SEGMENT_RE.sub("", uri or "")


def is_peer_uri(uri: str) -> bool:
    return "/peers/" in (uri or "")


def memory_rel_path(uri: str, user: str) -> str:
    """Return path under memories/ (same key for user and peer mirrors)."""
    uri = uri or ""
    # peer: viking://user/{user}/peers/{agent}/memories/{rel}
    peer_prefix = f"viking://user/{user}/peers/"
    if uri.startswith(peer_prefix):
        rest = uri[len(peer_prefix) :]  # {agent}/memories/...
        _agent, _, after_agent = rest.partition("/")
        if after_agent.startswith("memories/"):
            return after_agent[len("memories/") :]
        # fallback: strip to first /memories/
        m = re.search(r"/memories/(.+)$", uri)
        return m.group(1) if m else after_agent

    user_prefix = f"viking://user/{user}/memories/"
    if uri.startswith(user_prefix):
        return uri[len(user_prefix) :]

    m = re.search(r"/memories/(.+)$", uri)
    return m.group(1) if m else uri.rstrip("/").split("/")[-1]


def get_category(uri: str, user: str = "") -> str:
    rel = memory_rel_path(uri, user) if user else ""
    if not rel:
        m = re.search(r"/memories/(.+)$", canonical_uri(uri))
        rel = m.group(1) if m else ""
    if not rel:
        return "_root"
    # top-level file like identity.md
    if "/" not in rel.rstrip("/"):
        name = rel.rsplit("/", 1)[-1]
        if name.endswith(".md"):
            return "_root"
        return name
    return rel.split("/", 1)[0]


def content_sha256(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------


def detect_non_chinese(
    text: str,
    *,
    include_english: bool = True,
) -> Optional[Dict[str, Any]]:
    """Detect non-Chinese natural language (any Latin-heavy / low Chinese).

    Default includes English. Set ``include_english=False`` to only flag
    pt/es/it/fr/de (+ accent-heavy Latin).

    Returns None when content looks Chinese-primary or has too little signal.
    """
    if not text or len(text.strip()) < 20:
        return None

    words = _LATIN_WORD_RE.findall(text.lower())
    zh_chars = len(_ZH_RE.findall(text))
    latin_chars = len(_LATIN_CHAR_RE.findall(text))
    total_signal = zh_chars + latin_chars
    if total_signal == 0:
        return None

    zh_ratio = zh_chars / total_signal
    if zh_ratio > MAX_ZH_RATIO_FOR_FLAG:
        return None

    if len(words) < MIN_LATIN_WORDS and latin_chars < MIN_LATIN_CHARS_FOR_EN:
        return None

    scores: Dict[str, float] = {}
    for lang, stopwords in LATIN_STOPWORDS.items():
        hits = sum(1 for w in words if w in stopwords)
        accent_bonus = 0
        pattern = LATIN_ACCENT_PATTERNS.get(lang)
        if pattern is not None and lang != "en":
            accent_bonus = len(pattern.findall(text))
        scores[lang] = float(hits + accent_bonus)

    # Prefer non-English languages for primary classification when strong.
    non_en_scores = {k: v for k, v in scores.items() if k != "en"}
    best_lang, best_score = max(non_en_scores.items(), key=lambda x: x[1])
    density = best_score / max(len(words), 1)

    # Romance/Germanic contamination.
    if best_score >= MIN_STOPWORD_HITS and density >= MIN_DENSITY:
        return {
            "language": best_lang,
            "stopword_hits": int(best_score),
            "density": round(density, 3),
            "zh_ratio": round(zh_ratio, 3),
            "latin_chars": latin_chars,
            "zh_chars": zh_chars,
            "word_count": len(words),
            "reason": "latin_stopwords",
        }

    # Accent-heavy Latin without enough stopwords still suspicious.
    accent_total = sum(
        len(LATIN_ACCENT_PATTERNS[lang].findall(text))
        for lang in ("pt", "es", "it", "fr", "de")
    )
    if accent_total >= 4 and zh_ratio < 0.15 and latin_chars >= 40:
        return {
            "language": best_lang if best_score >= 1 else "latin",
            "stopword_hits": int(best_score),
            "density": round(density, 3),
            "zh_ratio": round(zh_ratio, 3),
            "latin_chars": latin_chars,
            "zh_chars": zh_chars,
            "word_count": len(words),
            "reason": "latin_accents",
            "accent_hits": accent_total,
        }

    if include_english:
        en_hits = scores.get("en", 0)
        en_density = en_hits / max(len(words), 1)
        # English-heavy prose
        if (
            zh_ratio <= MAX_ZH_RATIO_FOR_FLAG
            and latin_chars >= MIN_LATIN_CHARS_FOR_EN
            and en_hits >= 5
            and en_density >= 0.10
        ):
            return {
                "language": "en",
                "stopword_hits": int(en_hits),
                "density": round(en_density, 3),
                "zh_ratio": round(zh_ratio, 3),
                "latin_chars": latin_chars,
                "zh_chars": zh_chars,
                "word_count": len(words),
                "reason": "english_heavy",
            }
        # Low Chinese + substantial Latin script, language unclear → still flag
        if zh_ratio <= 0.20 and latin_chars >= MIN_LATIN_CHARS_FOR_EN and len(words) >= 8:
            return {
                "language": "en" if en_hits >= best_score else (best_lang if best_score >= 2 else "latin"),
                "stopword_hits": int(max(en_hits, best_score)),
                "density": round(max(en_density, density), 3),
                "zh_ratio": round(zh_ratio, 3),
                "latin_chars": latin_chars,
                "zh_chars": zh_chars,
                "word_count": len(words),
                "reason": "low_zh_latin_script",
            }

    return None


def cosine_sim(v1: Sequence[float], v2: Sequence[float]) -> float:
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = 0.0
    n1 = 0.0
    n2 = 0.0
    for a, b in zip(v1, v2):
        dot += a * b
        n1 += a * a
        n2 += b * b
    if n1 <= 0 or n2 <= 0:
        return 0.0
    return dot / (math.sqrt(n1) * math.sqrt(n2))


# ---------------------------------------------------------------------------
# HTTP client (stdlib only)
# ---------------------------------------------------------------------------


class OVClient:
    """Minimal OpenViking HTTP client using the user API key from Hermes .env."""

    def __init__(self, config: Optional[OVConfig] = None, log: Optional[logging.Logger] = None):
        self.config = config or load_ov_config()
        self.log = log or logger
        self.endpoint = self.config.endpoint.rstrip("/")
        self.api_key = self.config.api_key
        self.account = self.config.account
        self.user = self.config.user
        self.agent = self.config.agent

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "X-API-Key": self.api_key,
            "Authorization": f"Bearer {self.api_key}",
        }
        # Prefer key-derived identity; send tenant headers as optional hints
        # (API-key mode usually ignores them; trusted mode may need them).
        if self.account:
            headers["X-OpenViking-Account"] = self.account
        if self.user:
            headers["X-OpenViking-User"] = self.user
        if self.agent:
            headers["X-OpenViking-Actor-Peer"] = self.agent
        return headers

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        body: Optional[dict] = None,
        timeout: float = REQUEST_TIMEOUT,
    ) -> Dict[str, Any]:
        url = f"{self.endpoint}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(
                {k: v for k, v in params.items() if v is not None}
            )
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        last_error: Optional[Exception] = None
        for attempt in range(MAX_RETRIES):
            req = urllib.request.Request(
                url, data=data, headers=self._headers(), method=method
            )
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    raw = resp.read().decode("utf-8")
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError as exc:
                    return {
                        "status": "error",
                        "error": f"invalid JSON: {exc}",
                        "error_kind": "parse",
                        "body": raw[:300],
                    }
                if not isinstance(payload, dict):
                    return {"status": "ok", "result": payload}
                return payload
            except urllib.error.HTTPError as exc:
                body_text = ""
                try:
                    body_text = exc.read().decode("utf-8", errors="replace")
                except Exception:
                    pass
                if exc.code in (429, 502, 503, 504) and attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_BASE_DELAY * (2 ** attempt))
                    continue
                return {
                    "status": "error",
                    "error": f"HTTP {exc.code} {exc.reason}",
                    "error_kind": "http",
                    "http_status": exc.code,
                    "body": body_text[:500],
                }
            except urllib.error.URLError as exc:
                last_error = exc
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_BASE_DELAY * (2 ** attempt))
                    continue
                return {
                    "status": "error",
                    "error": f"network error: {exc.reason}",
                    "error_kind": "network",
                }
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_BASE_DELAY * (2 ** attempt))
                    continue
                return {
                    "status": "error",
                    "error": str(exc),
                    "error_kind": "unexpected",
                }
        return {
            "status": "error",
            "error": str(last_error or "request failed"),
            "error_kind": "unexpected",
        }

    def health(self) -> bool:
        # Prefer a cheap ls of user root.
        result = self.fs_ls(f"viking://user/{self.user}")
        return result is not None

    def fs_ls(self, uri: str) -> Optional[List[dict]]:
        payload = self._request("GET", "/api/v1/fs/ls", params={"uri": uri})
        if payload.get("status") == "error":
            self.log.debug("fs_ls error %s: %s", uri, payload.get("error"))
            return None
        result = payload.get("result", [])
        if isinstance(result, dict):
            result = (
                result.get("entries")
                or result.get("items")
                or result.get("children")
                or []
            )
        return result if isinstance(result, list) else []

    def content_read(self, uri: str) -> Optional[str]:
        payload = self._request("GET", "/api/v1/content/read", params={"uri": uri})
        if payload.get("status") == "error":
            self.log.debug("content_read error %s: %s", uri, payload.get("error"))
            return None
        result = payload.get("result", "")
        if isinstance(result, str):
            return result
        if isinstance(result, dict):
            for key in ("content", "text"):
                value = result.get(key)
                if isinstance(value, str):
                    return value
            return json.dumps(result, ensure_ascii=False)
        return str(result) if result is not None else ""

    def scroll_vectors(
        self,
        *,
        uri_prefix: Optional[str] = None,
        limit: int = 500,
        max_records: int = 5000,
    ) -> List[dict]:
        """Paginate ``/api/v1/debug/vector/scroll`` (uses stored dense vectors)."""
        records: List[dict] = []
        cursor: Optional[str] = None
        while len(records) < max_records:
            params: Dict[str, Any] = {"limit": min(limit, max_records - len(records))}
            if cursor:
                params["cursor"] = cursor
            if uri_prefix:
                params["uri"] = uri_prefix
            payload = self._request(
                "GET",
                "/api/v1/debug/vector/scroll",
                params=params,
                timeout=60,
            )
            if payload.get("status") == "error":
                self.log.warning("vector scroll failed: %s", payload.get("error"))
                break
            result = payload.get("result") or {}
            if not isinstance(result, dict):
                break
            batch = result.get("records") or []
            if not isinstance(batch, list) or not batch:
                break
            records.extend(batch)
            cursor = result.get("next_cursor") or result.get("cursor")
            if not cursor:
                break
        return records

    def content_write(self, uri: str, content: str, *, mode: str = "create") -> bool:
        # OpenViking rejects mode=overwrite; use create for new files.
        # For replace-in-place: DELETE old then create, or write a new URI then delete.
        payload = self._request(
            "POST",
            "/api/v1/content/write",
            body={"uri": uri, "content": content, "mode": mode},
        )
        return payload.get("status") == "ok"

    def fs_delete(self, uri: str) -> bool:
        payload = self._request(
            "DELETE",
            "/api/v1/fs",
            params={"uri": uri, "recursive": "false"},
        )
        return payload.get("status") == "ok"

    def fs_attrs(self, uri: str) -> Dict[str, Any]:
        payload = self._request("GET", "/api/v1/fs/attrs", params={"uri": uri})
        if payload.get("status") == "error":
            return {}
        result = payload.get("result") or {}
        return result if isinstance(result, dict) else {}

    def set_tags(
        self,
        uri: str,
        tags: Sequence[str],
        *,
        mode: str = "replace",
        recursive: bool = False,
    ) -> Dict[str, Any]:
        """Set k=v tags on a URI. Mode: replace (default; OV rejects merge)."""
        payload = self._request(
            "POST",
            "/api/v1/content/set_tags",
            body={
                "uri": uri,
                "tags": list(tags),
                "mode": mode,
                "recursive": recursive,
            },
        )
        return payload


# ---------------------------------------------------------------------------
# Human review tags (governance)
# ---------------------------------------------------------------------------

# OpenViking lowercases tag strings; avoid ISO "T" (becomes "t").
# Format: 2026-07-16_10-43-18+0800
HUMAN_REVIEWED_KEY = "human_reviewed"
HUMAN_REVIEWED_AT_KEY = "human_reviewed_at"
# human_reviewed=1 means permanently skip re-queue (no TTL) until tag cleared.


def format_human_reviewed_at(when: Optional[datetime] = None) -> str:
    dt = when or datetime.now().astimezone()
    # %z → +0800; replace colon form if any
    return dt.strftime("%Y-%m-%d_%H-%M-%S%z")


def parse_tag_map(tags: Sequence[str] | None) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for raw in tags or []:
        if not isinstance(raw, str) or "=" not in raw:
            continue
        k, _, v = raw.partition("=")
        out[k.strip().lower()] = v.strip()
    return out


def tags_from_attrs(attrs_payload: Dict[str, Any]) -> List[str]:
    attrs = attrs_payload.get("attrs") if isinstance(attrs_payload, dict) else None
    if not isinstance(attrs, dict):
        return []
    tags = attrs.get("tags") or []
    return list(tags) if isinstance(tags, list) else []


def is_human_reviewed(tags: Sequence[str] | Dict[str, str] | None) -> bool:
    """True when human_reviewed=1 (no TTL re-queue)."""
    if tags is None:
        return False
    if isinstance(tags, dict):
        m = {str(k).lower(): str(v) for k, v in tags.items()}
    else:
        m = parse_tag_map(tags)
    return m.get(HUMAN_REVIEWED_KEY) in {"1", "true", "yes"}


def human_review_tag_list(
    *,
    reviewed: bool = True,
    reviewed_at: Optional[datetime] = None,
    extra: Optional[Dict[str, str]] = None,
) -> List[str]:
    """Build tag list for set_tags (replace mode)."""
    tags = [
        f"{HUMAN_REVIEWED_KEY}={'1' if reviewed else '0'}",
        f"{HUMAN_REVIEWED_AT_KEY}={format_human_reviewed_at(reviewed_at)}",
    ]
    if extra:
        for k, v in extra.items():
            if not k or v is None:
                continue
            tags.append(f"{k}={v}")
    return tags


def mark_human_reviewed(
    client: OVClient,
    uri: str,
    *,
    reviewed_at: Optional[datetime] = None,
    extra: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    tags = human_review_tag_list(reviewed=True, reviewed_at=reviewed_at, extra=extra)
    result = client.set_tags(uri, tags, mode="replace")
    return {"uri": uri, "tags": tags, "response": result}


# Absolute / over-strong preference language (zh + light en)
_HARD_CLAIM_RE = re.compile(
    r"(明确要求|明确表示|必须|务必|禁止|永远|始终|不要再|以后都|一律|绝对|"
    r"只能|不得|严禁|一定要|强制|"
    r"\balways\b|\bnever\b|\bmust\b|\bexplicitly\s+require)",
    re.IGNORECASE,
)


def preference_risk_flags(content: str, *, uri: str = "") -> List[str]:
    """Heuristic risk flags for preference / hard-claim review."""
    flags: List[str] = []
    text = content or ""
    if _HARD_CLAIM_RE.search(text):
        flags.append("absolute_language")
    # Preferences path is inherently preference-shaped
    if "/preferences/" in (uri or ""):
        flags.append("in_preferences")
    # Single-line or very short "preference" bodies still get reviewed if absolute
    if "用户" in text and any(w in text for w in ("要求", "偏好", "不要", "必须")):
        flags.append("user_preference_voice")
    return flags


def scan_preference_candidates(
    client: OVClient,
    *,
    include_peer: bool = True,
    skip_reviewed: bool = True,
    limit: int = 50,
) -> Dict[str, Any]:
    """Layer-3: scan preference memories for human-review candidates.

    Skips URIs with human_reviewed=1 when skip_reviewed is True (no TTL).
    """
    files = collect_memory_files(
        client,
        include_peer=include_peer,
        categories=["preferences"],
    )
    # Also include peer preferences that live under peers/.../preferences
    # collect_memory_files already walks peer root; category filter uses get_category.

    candidates: List[Dict[str, Any]] = []
    skipped_reviewed = 0
    scanned = 0
    read_failures = 0

    for item in files:
        scanned += 1
        attrs = client.fs_attrs(item.uri)
        tag_list = tags_from_attrs(attrs)
        tag_map = parse_tag_map(tag_list)
        if skip_reviewed and is_human_reviewed(tag_map):
            skipped_reviewed += 1
            continue

        text = client.content_read(item.uri)
        if text is None:
            read_failures += 1
            continue
        flags = preference_risk_flags(text, uri=item.uri)
        # Always surface preference files; rank by flag strength
        score = 0
        if "absolute_language" in flags:
            score += 10
        if "user_preference_voice" in flags:
            score += 3
        if "in_preferences" in flags:
            score += 1
        snippet = " ".join(text[:240].split())
        candidates.append(
            {
                "uri": item.uri,
                "rel": item.rel,
                "space": item.space,
                "flags": flags,
                "score": score,
                "tags": tag_map,
                "human_reviewed": is_human_reviewed(tag_map),
                "human_reviewed_at": tag_map.get(HUMAN_REVIEWED_AT_KEY),
                "snippet": snippet,
                "content_len": len(text),
            }
        )

    candidates.sort(key=lambda c: (-c["score"], c["uri"]))
    if limit > 0:
        candidates = candidates[:limit]

    return {
        "scan_time": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "scanned_files": scanned,
        "skipped_human_reviewed": skipped_reviewed,
        "read_failures": read_failures,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "tag_schema": {
            HUMAN_REVIEWED_KEY: "1 = permanently skip re-queue (no TTL)",
            HUMAN_REVIEWED_AT_KEY: "datetime like 2026-07-16_10-43-18+0800",
        },
    }


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------


@dataclass
class MemoryFile:
    uri: str
    rel: str
    space: str  # "user" | "peer"
    category: str
    size: int = 0
    content: Optional[str] = None
    content_hash: Optional[str] = None
    is_mirror: bool = False
    mirror_of: Optional[str] = None

    def to_public_dict(self) -> Dict[str, Any]:
        return {
            "uri": self.uri,
            "rel": self.rel,
            "space": self.space,
            "category": self.category,
            "size": self.size,
            "is_mirror": self.is_mirror,
            "mirror_of": self.mirror_of,
        }


def _is_memory_file_uri(uri: str) -> bool:
    if not uri or not uri.endswith(".md"):
        return False
    name = uri.rsplit("/", 1)[-1]
    if name in GENERATED_SUMMARY_NAMES or name.startswith("."):
        return False
    return True


def collect_memory_files(
    client: OVClient,
    *,
    include_peer: bool = True,
    categories: Optional[Iterable[str]] = None,
    exclude_categories: Optional[Iterable[str]] = None,
) -> List[MemoryFile]:
    """Walk user (and optional peer) memory trees."""
    allow = set(categories) if categories else None
    deny = set(exclude_categories or ())
    files: List[MemoryFile] = []

    roots: List[Tuple[str, str]] = [("user", client.config.user_memories_uri)]
    if include_peer:
        roots.append(("peer", client.config.peer_memories_uri))

    for space, root in roots:
        stack = [root]
        while stack:
            current = stack.pop()
            entries = client.fs_ls(current)
            if entries is None:
                client.log.warning("failed to list %s", current)
                continue
            for entry in entries:
                uri = entry.get("uri") or ""
                if not uri:
                    continue
                is_dir = bool(
                    entry.get("isDir")
                    or entry.get("is_dir")
                    or entry.get("type") == "dir"
                )
                name = uri.rstrip("/").split("/")[-1]
                if is_dir:
                    if name in SKIP_DIR_NAMES:
                        continue
                    # Never recurse into nested peers from user root again.
                    if space == "user" and name == "peers":
                        continue
                    stack.append(uri)
                    continue
                if not _is_memory_file_uri(uri):
                    continue
                rel = memory_rel_path(uri, client.user)
                category = get_category(uri, client.user)
                if allow is not None and category not in allow:
                    continue
                if category in deny:
                    continue
                files.append(
                    MemoryFile(
                        uri=uri,
                        rel=rel,
                        space=space,
                        category=category,
                        size=int(entry.get("size") or 0),
                    )
                )
    return files


def mark_exact_mirrors(files: List[MemoryFile], contents: Dict[str, str]) -> int:
    """Mark peer files that are exact content mirrors of user files.

    Matching key: canonical relative path under memories/ + identical hash.
    Returns number of peer mirrors marked.
    """
    user_by_rel: Dict[str, MemoryFile] = {}
    for item in files:
        if item.space != "user":
            continue
        content = contents.get(item.uri)
        if content is None:
            continue
        item.content_hash = content_sha256(content)
        user_by_rel[item.rel] = item

    marked = 0
    for item in files:
        if item.space != "peer":
            continue
        content = contents.get(item.uri)
        if content is None:
            continue
        item.content_hash = content_sha256(content)
        user_item = user_by_rel.get(item.rel)
        if not user_item or not user_item.content_hash:
            continue
        if user_item.content_hash == item.content_hash:
            item.is_mirror = True
            item.mirror_of = user_item.uri
            marked += 1
    return marked


def load_contents(
    client: OVClient,
    files: Sequence[MemoryFile],
    *,
    progress_every: int = 50,
) -> Tuple[Dict[str, str], int]:
    contents: Dict[str, str] = {}
    failures = 0
    for index, item in enumerate(files, 1):
        text = client.content_read(item.uri)
        if text is None:
            failures += 1
            continue
        contents[item.uri] = text
        item.content = text
        if progress_every and index % progress_every == 0:
            client.log.info("read %d/%d files", index, len(files))
    return contents, failures


# ---------------------------------------------------------------------------
# Scanners
# ---------------------------------------------------------------------------


def scan_non_chinese(
    files: Sequence[MemoryFile],
    contents: Dict[str, str],
    *,
    skip_mirrors: bool = True,
    include_english: bool = True,
) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    for item in files:
        if skip_mirrors and item.is_mirror:
            continue
        text = contents.get(item.uri) or item.content or ""
        if not text:
            continue
        detection = detect_non_chinese(text, include_english=include_english)
        if not detection:
            continue
        snippet = " ".join(text[:240].split())
        findings.append(
            {
                "uri": item.uri,
                "rel": item.rel,
                "space": item.space,
                "category": item.category,
                "detection": detection,
                "snippet": snippet,
            }
        )
    findings.sort(
        key=lambda x: (
            x["detection"].get("zh_ratio", 1.0),
            -float(x["detection"].get("density") or 0),
        )
    )
    return findings


def _vector_uri_ok(uri: str, user: str) -> bool:
    if not uri:
        return False
    if f"viking://user/{user}/" not in uri:
        return False
    if "/memories/" not in uri:
        return False
    if not uri.endswith(".md"):
        return False
    name = uri.rsplit("/", 1)[-1]
    if name in GENERATED_SUMMARY_NAMES or name.startswith("."):
        return False
    return True


def scan_similar_from_vectors(
    client: OVClient,
    *,
    threshold: float = 0.85,
    exclude_categories: Optional[Iterable[str]] = None,
    skip_exact_mirrors: bool = True,
    skip_identical_content: bool = True,
    max_pairs: int = 200,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Find near-duplicate pairs using OpenViking stored dense vectors.

    Exact peer mirrors (same rel path under user vs peers, typically identical
    commit dual-writes) are excluded when ``skip_exact_mirrors`` is True.
    """
    deny = set(exclude_categories or ())
    meta: Dict[str, Any] = {
        "threshold": threshold,
        "vectors_raw": 0,
        "vectors_used": 0,
        "pairs_raw": 0,
        "pairs_reported": 0,
        "skipped_mirror_pairs": 0,
        "skipped_identical_hash": 0,
        "skipped_category": 0,
    }

    records = client.scroll_vectors(
        uri_prefix=f"viking://user/{client.user}/",
        limit=500,
    )
    meta["vectors_raw"] = len(records)

    # Keep best vector per URI (prefer level 2 / non-empty abstract).
    by_uri: Dict[str, dict] = {}
    for rec in records:
        uri = str(rec.get("uri") or "")
        if not _vector_uri_ok(uri, client.user):
            continue
        vec = rec.get("vector")
        if not isinstance(vec, list) or not vec:
            continue
        category = get_category(uri, client.user)
        if category in deny:
            meta["skipped_category"] += 1
            continue
        prev = by_uri.get(uri)
        if prev is None:
            by_uri[uri] = rec
            continue
        # Prefer deeper / longer content description.
        prev_level = int(prev.get("level") or 0)
        cur_level = int(rec.get("level") or 0)
        if cur_level >= prev_level:
            by_uri[uri] = rec

    # Drop exact peer mirrors: if both user and peer canonical keys exist,
    # keep user side only for pairing (peer-only stays).
    if skip_exact_mirrors:
        by_canon: Dict[str, List[str]] = {}
        for uri in by_uri:
            by_canon.setdefault(canonical_uri(uri), []).append(uri)
        drop: set[str] = set()
        for canon, uris in by_canon.items():
            if len(uris) < 2:
                continue
            user_uris = [u for u in uris if not is_peer_uri(u)]
            peer_uris = [u for u in uris if is_peer_uri(u)]
            if user_uris and peer_uris:
                # Structural mirror pair — exclude peer copies from similarity.
                for peer_uri in peer_uris:
                    drop.add(peer_uri)
                    meta["skipped_mirror_pairs"] += 1
        for uri in drop:
            by_uri.pop(uri, None)

    items: List[Tuple[str, List[float], str, str, str]] = []
    for uri, rec in by_uri.items():
        vec = rec.get("vector")
        if not isinstance(vec, list):
            continue
        abstract = str(rec.get("abstract") or rec.get("content") or "")[:200]
        content_hint = str(rec.get("content") or abstract)
        items.append(
            (
                uri,
                [float(x) for x in vec],
                get_category(uri, client.user),
                abstract,
                content_sha256(content_hint),
            )
        )
    meta["vectors_used"] = len(items)

    pairs: List[Dict[str, Any]] = []
    n = len(items)
    for i in range(n):
        uri_a, vec_a, cat_a, abs_a, hash_a = items[i]
        for j in range(i + 1, n):
            uri_b, vec_b, cat_b, abs_b, hash_b = items[j]
            # Prefer same-category pairs; still allow cross-category if very high.
            sim = cosine_sim(vec_a, vec_b)
            if cat_a != cat_b and sim < max(threshold + 0.05, 0.93):
                continue
            if sim < threshold:
                continue
            meta["pairs_raw"] += 1
            if skip_identical_content and hash_a and hash_a == hash_b:
                # Likely same abstract/content fingerprint — often mirror residue.
                if canonical_uri(uri_a) == canonical_uri(uri_b):
                    meta["skipped_mirror_pairs"] += 1
                    continue
                meta["skipped_identical_hash"] += 1
                # Still report if different paths (true semantic/content clones).
            pairs.append(
                {
                    "uri_a": uri_a,
                    "uri_b": uri_b,
                    "rel_a": memory_rel_path(uri_a, client.user),
                    "rel_b": memory_rel_path(uri_b, client.user),
                    "category_a": cat_a,
                    "category_b": cat_b,
                    "same_category": cat_a == cat_b,
                    "similarity": round(sim, 4),
                    "space_a": "peer" if is_peer_uri(uri_a) else "user",
                    "space_b": "peer" if is_peer_uri(uri_b) else "user",
                    "is_structural_mirror": canonical_uri(uri_a) == canonical_uri(uri_b),
                    "snippets": [abs_a, abs_b],
                    "suggestion": "review_for_merge_or_dedup",
                }
            )

    # Drop residual structural mirrors if any slipped through.
    filtered: List[Dict[str, Any]] = []
    for pair in pairs:
        if skip_exact_mirrors and pair.get("is_structural_mirror"):
            meta["skipped_mirror_pairs"] += 1
            continue
        filtered.append(pair)

    filtered.sort(key=lambda p: p["similarity"], reverse=True)
    if max_pairs > 0:
        filtered = filtered[:max_pairs]
    meta["pairs_reported"] = len(filtered)
    return filtered, meta


def build_scan_report(
    client: OVClient,
    *,
    include_peer: bool = True,
    threshold: float = 0.85,
    skip_similar: bool = False,
    skip_non_chinese: bool = False,
    include_english: bool = True,
    exclude_categories: Optional[Iterable[str]] = None,
    categories: Optional[Iterable[str]] = None,
    preference_limit: int = 10,
) -> Dict[str, Any]:
    """Run full analysis and return a JSON-serializable report.

    preference_limit: max tier3 preference candidates returned (default 10).
    Use 0 for unlimited (still capped by scan_preference_candidates if limit<=0
    means no slice — we pass max(0, preference_limit) and treat 0 as no cap).

    include_english: default True — flag any low-Chinese / Latin-heavy text
    (including English ops prefs) for the translate tier.
    """
    files = collect_memory_files(
        client,
        include_peer=include_peer,
        categories=categories,
        exclude_categories=exclude_categories,
    )
    client.log.info(
        "inventory: %d files (include_peer=%s)", len(files), include_peer
    )
    contents, read_failures = load_contents(client, files)
    mirror_count = mark_exact_mirrors(files, contents)

    user_count = sum(1 for f in files if f.space == "user")
    peer_count = sum(1 for f in files if f.space == "peer")
    peer_only = sum(1 for f in files if f.space == "peer" and not f.is_mirror)

    non_chinese: List[Dict[str, Any]] = []
    if not skip_non_chinese:
        non_chinese = scan_non_chinese(
            files,
            contents,
            skip_mirrors=True,
            include_english=include_english,
        )

    similar_pairs: List[Dict[str, Any]] = []
    similar_meta: Dict[str, Any] = {}
    if not skip_similar:
        similar_pairs, similar_meta = scan_similar_from_vectors(
            client,
            threshold=threshold,
            exclude_categories=exclude_categories,
            skip_exact_mirrors=True,
            skip_identical_content=True,
        )

    # Priority rule: if a URI is flagged for translation this round, drop any
    # similar-pair that touches it (exact URI or same canonical path).
    translate_uris = {str(item.get("uri") or "") for item in non_chinese if item.get("uri")}
    translate_canons = {canonical_uri(u) for u in translate_uris if u}
    deferred_pairs: List[Dict[str, Any]] = []
    kept_pairs: List[Dict[str, Any]] = []
    for pair in similar_pairs:
        ua = str(pair.get("uri_a") or "")
        ub = str(pair.get("uri_b") or "")
        hit = (
            ua in translate_uris
            or ub in translate_uris
            or canonical_uri(ua) in translate_canons
            or canonical_uri(ub) in translate_canons
        )
        if hit:
            deferred = dict(pair)
            deferred["deferred_reason"] = "uri_pending_translate"
            deferred["suggestion"] = "defer_until_after_translate"
            deferred_pairs.append(deferred)
            continue
        kept_pairs.append(pair)
    similar_meta = dict(similar_meta or {})
    similar_meta["skipped_pending_translate"] = len(deferred_pairs)
    similar_meta["pairs_after_translate_priority"] = len(kept_pairs)
    similar_pairs = kept_pairs

    # Layer-3 preference candidates (skip human_reviewed=1)
    pref_limit = int(preference_limit)
    pref_report = scan_preference_candidates(
        client,
        include_peer=include_peer,
        skip_reviewed=True,
        limit=pref_limit if pref_limit > 0 else 0,
    )

    report = {
        "scan_time": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "config": {
            "endpoint": client.endpoint,
            "user": client.user,
            "agent": client.agent,
            "account": client.account,
            "config_source": client.config.source,
            "include_peer": include_peer,
            "include_english": include_english,
            "threshold": threshold,
            "preference_limit": pref_limit if pref_limit > 0 else None,
            "translate_priority_over_similar": True,
            "exclude_categories": sorted(set(exclude_categories or ())),
        },
        "inventory": {
            "total_files": len(files),
            "user_files": user_count,
            "peer_files": peer_count,
            "peer_only_files": peer_only,
            "exact_mirrors_marked": mirror_count,
            "read_failures": read_failures,
            "content_loaded": len(contents),
        },
        "non_chinese": non_chinese,
        "similar_pairs": similar_pairs,
        "similar_pairs_deferred_translate": deferred_pairs,
        "similar_meta": similar_meta,
        "preferences": pref_report,
        "summary": {
            "non_chinese_count": len(non_chinese),
            "similar_pairs_count": len(similar_pairs),
            "similar_pairs_deferred_translate_count": len(deferred_pairs),
            "preference_candidate_count": pref_report.get("candidate_count", 0),
            "preference_skipped_reviewed": pref_report.get("skipped_human_reviewed", 0),
            "preference_limit": pref_limit if pref_limit > 0 else None,
            "has_work": bool(
                non_chinese
                or similar_pairs
                or (pref_report.get("candidate_count") or 0) > 0
            ),
            "mirror_pairs_excluded_from_similarity": int(
                similar_meta.get("skipped_mirror_pairs") or 0
            ),
            "exact_mirrors_marked": mirror_count,
        },
    }
    return report
