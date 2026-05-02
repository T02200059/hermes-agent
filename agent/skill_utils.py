"""Lightweight skill metadata utilities shared by prompt_builder and skills_tool.

This module intentionally avoids importing the tool registry, CLI config, or any
heavy dependency chain.  It is safe to import at module level without triggering
tool registration or provider resolution.
"""

import json
import logging
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from hermes_constants import get_config_path, get_skills_dir

logger = logging.getLogger(__name__)

# ── Platform mapping ──────────────────────────────────────────────────────

PLATFORM_MAP = {
    "macos": "darwin",
    "linux": "linux",
    "windows": "win32",
}

EXCLUDED_SKILL_DIRS = frozenset((".git", ".github", ".hub"))

# ── Lazy YAML loader ─────────────────────────────────────────────────────

_yaml_load_fn = None


def yaml_load(content: str):
    """Parse YAML with lazy import and CSafeLoader preference."""
    global _yaml_load_fn
    if _yaml_load_fn is None:
        import yaml

        loader = getattr(yaml, "CSafeLoader", None) or yaml.SafeLoader

        def _load(value: str):
            return yaml.load(value, Loader=loader)

        _yaml_load_fn = _load
    return _yaml_load_fn(content)


# ── Frontmatter parsing ──────────────────────────────────────────────────


def parse_frontmatter(content: str) -> Tuple[Dict[str, Any], str]:
    """Parse YAML frontmatter from a markdown string.

    Uses yaml with CSafeLoader for full YAML support (nested metadata, lists)
    with a fallback to simple key:value splitting for robustness.

    Returns:
        (frontmatter_dict, remaining_body)
    """
    frontmatter: Dict[str, Any] = {}
    body = content

    if not content.startswith("---"):
        return frontmatter, body

    end_match = re.search(r"\n---\s*\n", content[3:])
    if not end_match:
        return frontmatter, body

    yaml_content = content[3 : end_match.start() + 3]
    body = content[end_match.end() + 3 :]

    try:
        parsed = yaml_load(yaml_content)
        if isinstance(parsed, dict):
            frontmatter = parsed
    except Exception:
        # Fallback: simple key:value parsing for malformed YAML
        for line in yaml_content.strip().split("\n"):
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            frontmatter[key.strip()] = value.strip()

    return frontmatter, body


# ── Platform matching ─────────────────────────────────────────────────────


def skill_matches_platform(frontmatter: Dict[str, Any]) -> bool:
    """Return True when the skill is compatible with the current OS.

    Skills declare platform requirements via a top-level ``platforms`` list
    in their YAML frontmatter::

        platforms: [macos]          # macOS only
        platforms: [macos, linux]   # macOS and Linux

    If the field is absent or empty the skill is compatible with **all**
    platforms (backward-compatible default).
    """
    platforms = frontmatter.get("platforms")
    if not platforms:
        return True
    if not isinstance(platforms, list):
        platforms = [platforms]
    current = sys.platform
    for platform in platforms:
        normalized = str(platform).lower().strip()
        mapped = PLATFORM_MAP.get(normalized, normalized)
        if current.startswith(mapped):
            return True
    return False


# ── Disabled skills ───────────────────────────────────────────────────────


def get_disabled_skill_names(platform: str | None = None) -> Set[str]:
    """Read disabled skill names from config.yaml.

    Args:
        platform: Explicit platform name (e.g. ``"telegram"``).  When
            *None*, resolves from ``HERMES_PLATFORM`` or
            ``HERMES_SESSION_PLATFORM`` env vars.  Falls back to the
            global disabled list when no platform is determined.

    Reads the config file directly (no CLI config imports) to stay
    lightweight.
    """
    config_path = get_config_path()
    if not config_path.exists():
        return set()
    try:
        parsed = yaml_load(config_path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.debug("Could not read skill config %s: %s", config_path, e)
        return set()
    if not isinstance(parsed, dict):
        return set()

    skills_cfg = parsed.get("skills")
    if not isinstance(skills_cfg, dict):
        return set()

    from gateway.session_context import get_session_env
    resolved_platform = (
        platform
        or os.getenv("HERMES_PLATFORM")
        or get_session_env("HERMES_SESSION_PLATFORM")
    )
    if resolved_platform:
        platform_disabled = (skills_cfg.get("platform_disabled") or {}).get(
            resolved_platform
        )
        if platform_disabled is not None:
            return _normalize_string_set(platform_disabled)
    return _normalize_string_set(skills_cfg.get("disabled"))


def _normalize_string_set(values) -> Set[str]:
    if values is None:
        return set()
    if isinstance(values, str):
        values = [values]
    return {str(v).strip() for v in values if str(v).strip()}


# ── External skills directories ──────────────────────────────────────────


def get_external_skills_dirs() -> List[Path]:
    """Read ``skills.external_dirs`` from config.yaml and return validated paths.

    Each entry is expanded (``~`` and ``${VAR}``) and resolved to an absolute
    path.  Only directories that actually exist are returned.  Duplicates and
    paths that resolve to the local ``~/.hermes/skills/`` are silently skipped.
    """
    config_path = get_config_path()
    if not config_path.exists():
        return []
    try:
        parsed = yaml_load(config_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(parsed, dict):
        return []

    skills_cfg = parsed.get("skills")
    if not isinstance(skills_cfg, dict):
        return []

    raw_dirs = skills_cfg.get("external_dirs")
    if not raw_dirs:
        return []
    if isinstance(raw_dirs, str):
        raw_dirs = [raw_dirs]
    if not isinstance(raw_dirs, list):
        return []

    local_skills = get_skills_dir().resolve()
    seen: Set[Path] = set()
    result: List[Path] = []

    for entry in raw_dirs:
        entry = str(entry).strip()
        if not entry:
            continue
        # Expand ~ and environment variables
        expanded = os.path.expanduser(os.path.expandvars(entry))
        p = Path(expanded).resolve()
        if p == local_skills:
            continue
        if p in seen:
            continue
        if p.is_dir():
            seen.add(p)
            result.append(p)
        else:
            logger.debug("External skills dir does not exist, skipping: %s", p)

    return result


def get_all_skills_dirs() -> List[Path]:
    """Return all skill directories: local ``~/.hermes/skills/`` first, then external.

    The local dir is always first (and always included even if it doesn't exist
    yet — callers handle that).  External dirs follow in config order.
    """
    dirs = [get_skills_dir()]
    dirs.extend(get_external_skills_dirs())
    return dirs


# ── Condition extraction ──────────────────────────────────────────────────


def extract_skill_conditions(frontmatter: Dict[str, Any]) -> Dict[str, List]:
    """Extract conditional activation fields from parsed frontmatter."""
    metadata = frontmatter.get("metadata")
    # Handle cases where metadata is not a dict (e.g., a string from malformed YAML)
    if not isinstance(metadata, dict):
        metadata = {}
    hermes = metadata.get("hermes") or {}
    if not isinstance(hermes, dict):
        hermes = {}
    return {
        "fallback_for_toolsets": hermes.get("fallback_for_toolsets", []),
        "requires_toolsets": hermes.get("requires_toolsets", []),
        "fallback_for_tools": hermes.get("fallback_for_tools", []),
        "requires_tools": hermes.get("requires_tools", []),
    }


# ── Skill config extraction ───────────────────────────────────────────────


def extract_skill_config_vars(frontmatter: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract config variable declarations from parsed frontmatter.

    Skills declare config.yaml settings they need via::

        metadata:
          hermes:
            config:
              - key: wiki.path
                description: Path to the LLM Wiki knowledge base directory
                default: "~/wiki"
                prompt: Wiki directory path

    Returns a list of dicts with keys: ``key``, ``description``, ``default``,
    ``prompt``.  Invalid or incomplete entries are silently skipped.
    """
    metadata = frontmatter.get("metadata")
    if not isinstance(metadata, dict):
        return []
    hermes = metadata.get("hermes")
    if not isinstance(hermes, dict):
        return []
    raw = hermes.get("config")
    if not raw:
        return []
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return []

    result: List[Dict[str, Any]] = []
    seen: set = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key", "")).strip()
        if not key or key in seen:
            continue
        # Must have at least key and description
        desc = str(item.get("description", "")).strip()
        if not desc:
            continue
        entry: Dict[str, Any] = {
            "key": key,
            "description": desc,
        }
        default = item.get("default")
        if default is not None:
            entry["default"] = default
        prompt_text = item.get("prompt")
        if isinstance(prompt_text, str) and prompt_text.strip():
            entry["prompt"] = prompt_text.strip()
        else:
            entry["prompt"] = desc
        seen.add(key)
        result.append(entry)
    return result


def discover_all_skill_config_vars() -> List[Dict[str, Any]]:
    """Scan all enabled skills and collect their config variable declarations.

    Walks every skills directory, parses each SKILL.md frontmatter, and returns
    a deduplicated list of config var dicts.  Each dict also includes a
    ``skill`` key with the skill name for attribution.

    Disabled and platform-incompatible skills are excluded.
    """
    all_vars: List[Dict[str, Any]] = []
    seen_keys: set = set()

    disabled = get_disabled_skill_names()
    for skills_dir in get_all_skills_dirs():
        if not skills_dir.is_dir():
            continue
        for skill_file in iter_skill_index_files(skills_dir, "SKILL.md"):
            try:
                raw = skill_file.read_text(encoding="utf-8")
                frontmatter, _ = parse_frontmatter(raw)
            except Exception:
                continue

            skill_name = frontmatter.get("name") or skill_file.parent.name
            if str(skill_name) in disabled:
                continue
            if not skill_matches_platform(frontmatter):
                continue

            config_vars = extract_skill_config_vars(frontmatter)
            for var in config_vars:
                if var["key"] not in seen_keys:
                    var["skill"] = str(skill_name)
                    all_vars.append(var)
                    seen_keys.add(var["key"])

    return all_vars


# Storage prefix: all skill config vars are stored under skills.config.*
# in config.yaml.  Skill authors declare logical keys (e.g. "wiki.path");
# the system adds this prefix for storage and strips it for display.
SKILL_CONFIG_PREFIX = "skills.config"


def _resolve_dotpath(config: Dict[str, Any], dotted_key: str):
    """Walk a nested dict following a dotted key.  Returns None if any part is missing."""
    parts = dotted_key.split(".")
    current = config
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def resolve_skill_config_values(
    config_vars: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Resolve current values for skill config vars from config.yaml.

    Skill config is stored under ``skills.config.<key>`` in config.yaml.
    Returns a dict mapping **logical** keys (as declared by skills) to their
    current values (or the declared default if the key isn't set).
    Path values are expanded via ``os.path.expanduser``.
    """
    config_path = get_config_path()
    config: Dict[str, Any] = {}
    if config_path.exists():
        try:
            parsed = yaml_load(config_path.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                config = parsed
        except Exception:
            pass

    resolved: Dict[str, Any] = {}
    for var in config_vars:
        logical_key = var["key"]
        storage_key = f"{SKILL_CONFIG_PREFIX}.{logical_key}"
        value = _resolve_dotpath(config, storage_key)

        if value is None or (isinstance(value, str) and not value.strip()):
            value = var.get("default", "")

        # Expand ~ in path-like values
        if isinstance(value, str) and ("~" in value or "${" in value):
            value = os.path.expanduser(os.path.expandvars(value))

        resolved[logical_key] = value

    return resolved


# ── Description extraction ────────────────────────────────────────────────


def extract_skill_description(frontmatter: Dict[str, Any]) -> str:
    """Extract a truncated description from parsed frontmatter."""
    raw_desc = frontmatter.get("description", "")
    if not raw_desc:
        return ""
    desc = str(raw_desc).strip().strip("'\"")
    if len(desc) > 60:
        return desc[:57] + "..."
    return desc


# ── File iteration ────────────────────────────────────────────────────────


def iter_skill_index_files(skills_dir: Path, filename: str):
    """Walk skills_dir yielding sorted paths matching *filename*.

    Excludes ``.git``, ``.github``, ``.hub`` directories.
    """
    matches = []
    for root, dirs, files in os.walk(skills_dir, followlinks=True):
        dirs[:] = [d for d in dirs if d not in EXCLUDED_SKILL_DIRS]
        if filename in files:
            matches.append(Path(root) / filename)
    for path in sorted(matches, key=lambda p: str(p.relative_to(skills_dir))):
        yield path


# ── Namespace helpers for plugin-provided skills ───────────────────────────

_NAMESPACE_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def parse_qualified_name(name: str) -> Tuple[Optional[str], str]:
    """Split ``'namespace:skill-name'`` into ``(namespace, bare_name)``.

    Returns ``(None, name)`` when there is no ``':'``.
    """
    if ":" not in name:
        return None, name
    return tuple(name.split(":", 1))  # type: ignore[return-value]


def is_valid_namespace(candidate: Optional[str]) -> bool:
    """Check whether *candidate* is a valid namespace (``[a-zA-Z0-9_-]+``)."""
    if not candidate:
        return False
    return bool(_NAMESPACE_RE.match(candidate))


# ── Shared: extract skill_view calls from messages ─────────────────────────


def extract_skill_view_calls(messages: list) -> set:
    """Extract skill names from all ``skill_view`` tool calls in *messages*.

    Shared by ``scripts/precompute-skills-usage.py`` (离线索引构建)
    and ``run_agent.py`` (会话结束时的在线反馈记录), so the extraction
    logic stays consistent.
    """
    skills = set()
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function", {})
            if fn.get("name", "").lower() != "skill_view":
                continue
            try:
                args_raw = fn.get("arguments", "{}")
                args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
                if isinstance(args, dict):
                    sname = args.get("name", "").strip()
                    if sname:
                        skills.add(sname)
            except (json.JSONDecodeError, TypeError):
                continue
    return skills


# ── TF-IDF Skill Usage Tracker ────────────────────────────────────────────


class SkillsUsageTracker:
    """Pre-computed TF-IDF index for intent-driven skill filtering.

    Loads ``skills-usage-index.jsonl`` (built by
    ``scripts/precompute-skills-usage.py``) and provides
    ``find_similar(user_message)`` to predict which skills are relevant
    for the current conversation.

    Designed as a lightweight drop-in — sklearn is imported lazily inside
    ``load()``, so the class is safe to import at module level even when
    TF-IDF filtering is disabled.
    """

    _DEFAULT_WHITELIST = frozenset({
        "hermes-agent",
        "systematic-debugging",
        "plan",
        "writing-plans",
    })

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        # Resolve config: use provided dict or auto-read from config.yaml
        cfg = config or self._read_config()

        self.enabled = bool(cfg.get("enabled", False))
        self.index_path = Path(
            os.path.expanduser(
                str(cfg.get("index_path", "~/.local/share/hermes/skills-usage-index.jsonl"))
            )
        )
        self.ngram_range = cfg.get("ngram_range", [2, 4])
        self.max_features = cfg.get("max_features", 5000)
        thresh = cfg.get("thresholds", {})
        self.high_confidence = float(thresh.get("high_confidence", 0.7))
        self.low_confidence = float(thresh.get("low_confidence", 0.4))
        self.max_history = int(cfg.get("max_history", 100))
        self.recency_exemption_hours = int(cfg.get("recency_exemption_hours", 72))
        self.max_session_exemptions = int(cfg.get("max_session_exemptions", 5))
        raw_whitelist = cfg.get("whitelist", [])
        self.whitelist = self._DEFAULT_WHITELIST | (
            set(raw_whitelist) if isinstance(raw_whitelist, list) else set()
        )

        # Runtime state (populated by load())
        self._records: List[Dict[str, Any]] = []
        self._vectorizer = None
        self._tfidf_matrix = None
        self._loaded = False

        # Session creation tracking (方案2)
        self._created_this_session: Set[str] = set()
        self.creations_path = Path(
            os.path.expanduser(
                str(cfg.get("creations_path", "~/.local/share/hermes/skills-creations.jsonl"))
            )
        )

    # ── Public API ─────────────────────────────────────────────────────

    def load(self) -> bool:
        """Load the pre-computed JSONL index and build TF-IDF vectors.

        Returns ``True`` when data was loaded successfully, ``False``
        when the index file is missing or empty (caller should fall back
        to full skill loading).

        When the JSONL file has grown beyond ``max_history * 3`` lines
        (online feedback loop keeps appending), the file is automatically
        truncated to the last ``max_history`` records to prevent unbounded
        growth.
        """
        if not self.enabled:
            return False
        if not self.index_path.exists():
            logger.info("Skills TF-IDF index not found at %s (will fall back to full load)", self.index_path)
            return False

        # Read JSONL — count lines so we can decide whether to truncate
        _all_records: List[Dict[str, Any]] = []
        _file_lines = 0
        try:
            with open(self.index_path, "r", encoding="utf-8") as f:
                for line in f:
                    _file_lines += 1
                    stripped = line.strip()
                    if stripped:
                        _all_records.append(json.loads(stripped))
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("Failed to read skills TF-IDF index %s: %s", self.index_path, e)
            return False

        if not _all_records:
            return False

        # Trim to max_history in memory
        if len(_all_records) > self.max_history:
            self._records = _all_records[-self.max_history:]
        else:
            self._records = _all_records

        # ── Auto-truncate JSONL to prevent unbounded growth ──────────
        # The online feedback loop keeps appending one line per session.
        # When the file exceeds max_history * 3 (~15 KB), rewrite it
        # with only the last max_history records so I/O cost stays flat.
        if _file_lines > self.max_history * 3:
            try:
                with open(self.index_path, "w", encoding="utf-8") as f:
                    for rec in self._records:
                        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                logger.info(
                    "Truncated skills-usage-index from %d → %d lines",
                    _file_lines, len(self._records),
                )
            except OSError as e:
                logger.warning("Failed to truncate skills-usage-index: %s", e)

        # Lazy sklearn import — only when we actually need to vectorize
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer  # type: ignore[import-untyped]
            import numpy as np  # type: ignore[import-untyped]
            from sklearn.metrics.pairwise import cosine_similarity  # type: ignore[import-untyped]
        except ImportError:
            logger.warning("scikit-learn not installed; skills TF-IDF filtering disabled")
            return False

        texts = [r["msg"] for r in self._records]
        self._vectorizer = TfidfVectorizer(
            analyzer="char",
            ngram_range=tuple(self.ngram_range),
            max_features=self.max_features,
        )
        self._tfidf_matrix = self._vectorizer.fit_transform(texts)
        self._loaded = True
        # Cache imports for hot path
        self._np = np
        self._cosine_similarity = cosine_similarity
        logger.info(
            "Skills TF-IDF tracker loaded: %d patterns, %d features",
            len(self._records),
            self._tfidf_matrix.shape[1],
        )
        return True

    def find_similar(self, user_message: str) -> Optional[List[str]]:
        """Match *user_message* against historical patterns.

        Returns a list of recommended skill names when a match is found,
        or ``None`` when no match meets the low-confidence threshold
        (caller should fall back to full skill loading).
        """
        if not self._loaded or self._tfidf_matrix is None:
            return None

        query_vec = self._vectorizer.transform([user_message])
        scores = self._cosine_similarity(query_vec, self._tfidf_matrix)[0]
        best_score = float(scores.max())

        if best_score < self.low_confidence:
            return None  # No match — caller falls back to full load

        # Collect matching skills from all records above threshold
        result = set(self.whitelist)

        if best_score >= self.high_confidence:
            # High confidence: only records above high_confidence
            for i in self._np.where(scores >= self.high_confidence)[0]:
                result.update(self._records[i].get("skills", []))
        else:
            # Medium confidence: all records above low_confidence
            for i in self._np.where(scores >= self.low_confidence)[0]:
                result.update(self._records[i].get("skills", []))

        return sorted(result)

    def get_recently_modified_skills(self, recency_hours: Optional[int] = None) -> Set[str]:
        """Return skill names whose SKILL.md was modified in the recency window.

        Scans all skill directories, checks file modification times against
        the exemption window (default: ``recency_exemption_hours`` from config,
        or the *recency_hours* parameter).  Ensures newly created or recently
        updated skills are always visible even when TF-IDF filtering would
        otherwise exclude them.

        Returns an empty set when the tracker is disabled or the window is 0.
        """
        if not self.enabled:
            return set()

        hours = recency_hours if recency_hours is not None else self.recency_exemption_hours
        if hours <= 0:
            return set()

        cutoff = time.time() - hours * 3600
        skills_dir = get_skills_dir()
        recent: Set[str] = set()

        for skill_file in iter_skill_index_files(skills_dir, "SKILL.md"):
            try:
                mtime = os.path.getmtime(skill_file)
                if mtime < cutoff:
                    continue

                # Extract skill name — prefer frontmatter ``name`` field,
                # fall back to the top-level parent directory name.
                content = skill_file.read_text(encoding="utf-8")
                fm, _ = parse_frontmatter(content)
                name = fm.get("name", "")
                if not name:
                    rel = skill_file.relative_to(skills_dir)
                    name = rel.parts[0] if len(rel.parts) > 1 else ""

                if name:
                    recent.add(name)
            except (OSError, Exception) as e:
                logger.debug("Error reading recent skill %s: %s", skill_file, e)
                continue

        if recent:
            logger.debug(
                "Recency exemption: %d skills modified within %dh — %s",
                len(recent), hours, sorted(recent),
            )

        return recent

    # ── 方案2: Session creation tracking ───────────────────────────────

    def record_skill_creation(self, skill_name: str):
        """Record that *skill_name* was created during this session.

        Called by ``run_agent.py`` when ``skill_manage(action='create')``
        succeeds.  Persisted to ``skills-creations.jsonl`` so future
        sessions can also see the skill (within a 24h window).
        """
        if not skill_name:
            return

        # Layer A: in-memory (this session only)
        self._created_this_session.add(skill_name)

        # Layer B: persistent (cross-session, 24h window)
        entry = {
            "type": "skill_created",
            "name": skill_name,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        }
        try:
            os.makedirs(self.creations_path.parent, exist_ok=True)
            with open(self.creations_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            logger.debug("Recorded skill creation: %s", skill_name)
        except OSError as e:
            logger.warning("Failed to persist skill creation record: %s", e)

    def get_session_created_skills(self) -> Set[str]:
        """Return skills created in this session (Layer A, in-memory).

        Capped at ``max_session_exemptions`` to prevent unbounded growth
        when the model creates many skills in a single conversation.
        """
        if len(self._created_this_session) <= self.max_session_exemptions:
            return self._created_this_session.copy()
        # Only keep first N (sorted for deterministic selection)
        return set(sorted(self._created_this_session)[:self.max_session_exemptions])

    def get_recently_created_skills(self, hours: int = 24) -> Set[str]:
        """Return skills created in the last *hours* from the persistent
        creations JSONL (Layer B).  Independent of the TF-IDF index.
        """
        if not self.creations_path.exists():
            return set()
        cutoff = time.time() - hours * 3600
        recent: Set[str] = set()
        try:
            with open(self.creations_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ts_str = rec.get("ts", "")
                    try:
                        ts = time.mktime(
                            time.strptime(ts_str, "%Y-%m-%dT%H:%M:%S")
                        )
                    except (ValueError, OverflowError):
                        continue
                    if ts >= cutoff:
                        name = rec.get("name", "")
                        if name:
                            recent.add(name)
        except OSError as e:
            logger.debug("Failed to read skills-creations.jsonl: %s", e)
        return recent

    def record(self, user_message: str, invoked_skills: List[str],
               model: str = "", timestamp: str = ""):
        """Append a usage record to the JSONL index file.

        Called after a conversation finishes so future sessions can
        benefit from this conversation's pattern.
        """
        if not self.enabled:
            return
        if not user_message or not invoked_skills:
            return

        record = {
            "msg": user_message,
            "skills": sorted(set(invoked_skills)),
            "ts": timestamp,
            "model": model,
        }
        try:
            os.makedirs(self.index_path.parent, exist_ok=True)
            with open(self.index_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as e:
            logger.warning("Failed to append skills usage record: %s", e)

    @property
    def is_loaded(self) -> bool:
        """Whether the tracker has loaded data and is ready for queries."""
        return self._loaded

    # ── Internal helpers ──────────────────────────────────────────────

    @staticmethod
    def _read_config() -> Dict[str, Any]:
        """Read ``skills.tfidf_filter`` from config.yaml."""
        from hermes_constants import get_config_path
        config_path = get_config_path()
        if not config_path.exists():
            return {}
        try:
            parsed = yaml_load(config_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if not isinstance(parsed, dict):
            return {}
        skills_cfg = parsed.get("skills")
        if not isinstance(skills_cfg, dict):
            return {}
        return skills_cfg.get("tfidf_filter") or {}


# ── Module-level singleton ────────────────────────────────────────────────

_tracker_instance: Optional[SkillsUsageTracker] = None
_tracker_lock = threading.Lock()


def get_skills_usage_tracker() -> SkillsUsageTracker:
    """Return the process-wide singleton ``SkillsUsageTracker``.

    Lazy-initialises on first call: reads ``config.yaml``, loads the
    JSONL index, and fits the TF-IDF vectorizer.  Subsequent calls return
    the same instance without re-reading any files.
    """
    global _tracker_instance
    if _tracker_instance is None:
        with _tracker_lock:
            if _tracker_instance is None:  # double-check
                _tracker_instance = SkillsUsageTracker()
                if _tracker_instance.load():
                    logger.info("Skills TF-IDF tracker loaded (singleton)")
    return _tracker_instance
