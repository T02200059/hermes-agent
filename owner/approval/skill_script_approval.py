"""Skill script auto-approval — owner customization.

Extracts script filenames from shell commands and auto-approves them when
all extracted scripts belong to a skill that was viewed (loaded) in the
current session.  Configuration is in ``owner.approvals.skill_script_allowlist``
in ``~/.hermes/patch.yaml``.

可移除性：删除此文件后，skill script 自动批准功能不可用，
但 check_dangerous_command 不受影响（不会崩溃）。
"""

from __future__ import annotations

import logging
import re
import shlex
import time
from pathlib import Path
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# Session-scoped set of skill names that have been viewed this session.
# Populated by skill_view() calls, consumed by is_skill_script_allowed().
_session_skills_viewed: Set[str] = set()

_INTERPRETERS = frozenset({
    "bash", "sh", "zsh", "ksh", "dash",
    "python", "python2", "python3", "node", "nodejs", "ruby", "perl", "php",
})

_SCRIPT_EXT_RE = re.compile(r"^[a-zA-Z0-9_.+-]+\.[a-z]{1,4}$")

_SKILL_SCRIPTS_CACHE: dict = {}
_SKILL_SCRIPTS_CACHE_TTL = 300


def extract_script_filenames(command: str) -> List[str]:
    """Extract script filenames from a shell command string.

    Handles ``bash -c "python3 script.py"`` nesting,
    ``&&`` chaining, and trailing shell operators.
    Only returns names with a file extension (``.py``, ``.sh``, etc.).
    """
    if not command or not command.strip():
        return []
    filenames: List[str] = []
    segments = [command]
    processed: Set[str] = set()

    while segments:
        seg = segments.pop()
        # Unwrap bash -c / sh -c nests
        m = re.match(
            r"(?:bash|sh|zsh|ksh|dash)\s+(?:-\w+\s+)?['\"]?(.+?)['\"]?\s*$",
            seg,
            re.DOTALL,
        )
        if m:
            inner = m.group(1).strip()
            if inner not in processed:
                processed.add(inner)
                segments.append(inner)
            continue
        # Remove trailing shell operators
        seg = re.sub(r'\s*(?:&&|\|\||;|&|\||\|&)\s*$', '', seg.strip())
        parts = shlex.split(seg)
        for token in parts:
            token = token.strip()
            if not token or token in _INTERPRETERS:
                continue
            # Check if it looks like a path ending with a script extension
            if _SCRIPT_EXT_RE.match(token) or '.' in token:
                name = Path(token).name
                if _SCRIPT_EXT_RE.match(name) and name not in filenames:
                    filenames.append(name)

    return filenames


def load_skill_scripts() -> Dict[str, Set[str]]:
    """Load the script allowlist from patch.yaml, with filesystem scan.

    Returns ``{filename: {skill_name, ...}}`` mapping.
    Results cached for ``_SKILL_SCRIPTS_CACHE_TTL`` seconds.
    """
    now = time.time()
    cached = _SKILL_SCRIPTS_CACHE.get("data")
    mtime = _SKILL_SCRIPTS_CACHE.get("mtime", 0)
    if cached is not None and (now - mtime) < _SKILL_SCRIPTS_CACHE_TTL:
        return cached

    try:
        from owner.patch_config import _load_patch_owner_config

        cfg = _load_patch_owner_config()
    except Exception:
        cfg = {}

    allowlist = cfg.get("approvals", {}).get("skill_script_allowlist", [])
    if not isinstance(allowlist, list):
        allowlist = []

    result: Dict[str, Set[str]] = {}

    for entry in allowlist:
        if not isinstance(entry, dict):
            continue
        skill_name = entry.get("skill", "")
        if not skill_name:
            continue
        paths: List[str] = entry.get("paths") or []
        extensions: List[str] = entry.get("extensions") or [".sh", ".py"]
        if not isinstance(paths, list):
            paths = []
        # Resolve paths
        resolved_paths: List[Path] = []
        if not paths:
            # Empty paths → auto-scan the entire skill directory
            _scan_skill_dir(skill_name, extensions, result)
            continue
        for p in paths:
            expanded = Path(p).expanduser()
            if expanded.is_dir():
                resolved_paths.append(expanded)
        for dir_path in resolved_paths:
            _scan_directory(dir_path, extensions, skill_name, result)

    _SKILL_SCRIPTS_CACHE["data"] = result
    _SKILL_SCRIPTS_CACHE["mtime"] = now
    return result


def _scan_skill_dir(skill_name: str, extensions: List[str],
                    result: Dict[str, Set[str]]) -> None:
    """Scan ``~/.hermes/skills/**/<skill_name>/**`` for matching scripts."""
    skills_root = Path.home() / ".hermes" / "skills"
    if not skills_root.is_dir():
        return
    for cat_dir in skills_root.iterdir():
        if not cat_dir.is_dir():
            continue
        skill_dir = cat_dir / skill_name
        if skill_dir.is_dir():
            _scan_directory(skill_dir, extensions, skill_name, result)


def _scan_directory(dir_path: Path, extensions: List[str],
                    skill_name: str, result: Dict[str, Set[str]]) -> None:
    """Recursively scan a directory, adding matching scripts to result."""
    if not dir_path.is_dir():
        return
    try:
        for f in dir_path.rglob("*"):
            if not f.is_file():
                continue
            ext = f.suffix.lower()
            if ext not in extensions:
                continue
            name = f.name
            if name not in result:
                result[name] = set()
            result[name].add(skill_name)
    except PermissionError:
        pass


def track_session_skill_view(skill_name: str) -> None:
    """Record that a skill was viewed (loaded) in the current session."""
    if skill_name:
        _session_skills_viewed.add(skill_name)


def reset_session_skills_viewed() -> None:
    """Clear the session-scoped skills viewed set (called on /new)."""
    _session_skills_viewed.clear()


def get_session_skills_viewed() -> Set[str]:
    """Return the set of skill names viewed this session."""
    return _session_skills_viewed


def is_skill_script_allowed(command: str) -> Optional[str]:
    """Check if a command should be auto-approved as a skill script.

    Returns the skill name if the command is auto-approved, ``None`` otherwise.
    """
    if not _session_skills_viewed:
        return None

    filenames = extract_script_filenames(command)
    if not filenames:
        return None

    scripts = load_skill_scripts()
    for fn in filenames:
        skills = scripts.get(fn)
        if not skills:
            return None
        if not skills.intersection(_session_skills_viewed):
            return None

    # All extracted filenames belong to a viewed skill → auto-approve
    for fn in filenames:
        skills = scripts.get(fn)
        if skills:
            return next(iter(skills))
    return None


def invalidate_skill_scripts_cache() -> None:
    """Force the next ``load_skill_scripts()`` call to re-read from disk."""
    _SKILL_SCRIPTS_CACHE.clear()
