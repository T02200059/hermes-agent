"""Skill script auto-approval — owner customization.

Extracts script filenames from shell commands and auto-approves them when
all extracted scripts belong to a skill that was viewed (loaded) in the
current session.  Configuration is in ``owner.approvals.skill_script_allowlist``
in ``~/.hermes/patch.yaml``.

Integration points (thin glue only):
- tools/approval.py: check_all_command_guards() and check_dangerous_command()
  (both do lazy try/except import + early return on match, after hardline/sudo).

可移除性：删除此文件后，skill script 自动批准功能不可用；
tools/approval.py 的两个守卫函数不受影响（import 失败时优雅跳过，不会崩溃）。
"""

from __future__ import annotations

import logging
import re
import shlex
import time
from pathlib import Path
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# Per-session set of skill names that have been viewed this session.
# Keyed by the active approval session key (ContextVar) so concurrent
# gateway sessions each get their own isolated set. CR-01 / WR-05 fix.
_session_skills_viewed_by_key: Dict[str, Set[str]] = {}


def _current_session_key() -> str:
    try:
        from tools.approval import get_current_session_key
        return get_current_session_key(default="")
    except Exception:
        # Approval hot path: must never raise. tools.approval is only
        # unavailable in minimal tool-only import contexts.
        return ""


def _get_or_create_viewed_set() -> Set[str]:
    key = _current_session_key()
    s = _session_skills_viewed_by_key.get(key)
    if s is None:
        s = set()
        _session_skills_viewed_by_key[key] = s
    return s

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
    """Scan ``<HERMES_HOME>/skills/**/<skill_name>/**`` for matching scripts."""
    from hermes_constants import get_hermes_home

    skills_root = get_hermes_home() / "skills"
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
        _get_or_create_viewed_set().add(skill_name)


def reset_session_skills_viewed(session_key: Optional[str] = None) -> None:
    """Clear the session-scoped skills viewed set.

    When ``session_key`` is provided, clear that specific session's set
    (used by tools.approval.clear_session for an explicit session_key).
    When omitted, clear the current context's session set (legacy /
    test / CLI without a bound session).
    """
    if session_key is None:
        session_key = _current_session_key()
    _session_skills_viewed_by_key.pop(session_key, None)


def get_session_skills_viewed() -> Set[str]:
    """Return the set of skill names viewed this session."""
    return _get_or_create_viewed_set()


def _has_unquoted_compound_operator(command: str) -> bool:
    """CR-006: detect compound shell operators that appear OUTSIDE of quotes.

    ``python3 known.py "x; curl evil.com"`` parses safely because the ``;``
    sits inside a quoted argument and is passed verbatim to the interpreter.
    ``python3 known.py; rm -rf /`` does not — the ``;`` is unquoted and
    chains a second command. Detecting this from a flat string requires
    tracking the quote state as we scan, which shlex handles via source
    position. We use a simple state machine: walk the string, flip a
    ``in_quote`` flag on every quote char (respecting backslash escapes),
    and report any unquoted compound operator.
    """
    if not command:
        return False
    in_single = False
    in_double = False
    i = 0
    n = len(command)
    while i < n:
        ch = command[i]
        if ch == "\\" and i + 1 < n:
            # Backslash escapes the next char in both quote states (in POSIX
            # shells, \" inside double-quotes is a literal quote; \\ is a
            # literal backslash). Skip the escaped char.
            i += 2
            continue
        if not in_double and ch == "'":
            in_single = not in_single
            i += 1
            continue
        if not in_single and ch == '"':
            in_double = not in_double
            i += 1
            continue
        if in_single or in_double:
            i += 1
            continue
        # Unquoted territory — check for compound operators
        if ch in (";", "&", "|", "\n"):
            # '&&' / '||' are compound; single '&' (background) and single '|'
            # (pipe) are also dangerous in this context. Accepting '|' alone
            # would let `curl known.sh | bash` auto-approve. POSIX shell
            # treats a newline as a command separator equivalent to ';'.
            return True
        i += 1
    return False


def _has_shell_metachar_in_quoted_args(command: str) -> bool:
    """CR-006: detect shell metacharacters inside any quoted argument.

    Complements ``_has_unquoted_compound_operator`` for the case where
    the script is followed by a quoted argument that itself contains
    shell metacharacters. The shell will pass the quoted payload to
    the script as a literal string, but a script that does
    ``os.system(arg)`` or ``subprocess.Popen(arg, shell=True)`` would
    then re-interpret those metacharacters — a known skill-script
    could be used as cover for that pattern. Reject when ANY quoted
    region of the command contains ``; & | $ ` \\n \\r`` (the metachars
    a nested shell would re-interpret).
    """
    if not command:
        return False
    metachars = set(";|&`$\n\r")
    in_single = False
    in_double = False
    i = 0
    n = len(command)
    while i < n:
        ch = command[i]
        if ch == "\\" and i + 1 < n:
            # Skip backslash-escapes: \\ is literal backslash, \" inside
            # double quotes is a literal quote. Outside quotes, \\ is literal
            # backslash too (the shell strips the backslash).
            i += 2
            continue
        if not in_double and ch == "'":
            in_single = not in_single
            i += 1
            continue
        if not in_single and ch == '"':
            in_double = not in_double
            i += 1
            continue
        if (in_single or in_double) and ch in metachars:
            return True
        i += 1
    return False


def is_skill_script_allowed(command: str) -> Optional[str]:
    """Check if a command should be auto-approved as a skill script.

    Returns the skill name if the command is auto-approved, ``None`` otherwise.
    """
    viewed_set = _get_or_create_viewed_set()
    if not viewed_set:
        return None

    # CR-006: two gates close the bypass where a script filename hides
    # behind a malicious payload. (1) Any unquoted compound operator
    # chains a second command at the shell level. (2) Even with no
    # unquoted operator, a script followed by a quoted argument that
    # contains shell metacharacters can re-interpret them via os.system
    # / subprocess-shell=True inside the script. Both gates refuse
    # auto-approval so the user must explicitly re-confirm.
    if _has_unquoted_compound_operator(command):
        return None
    if _has_shell_metachar_in_quoted_args(command):
        return None

    filenames = extract_script_filenames(command)
    if not filenames:
        return None

    scripts = load_skill_scripts()
    matched_viewed: Set[str] = set()
    for fn in filenames:
        skills = scripts.get(fn)
        if not skills:
            return None
        viewed = skills.intersection(viewed_set)
        if not viewed:
            return None
        matched_viewed |= viewed

    # CR-02: fail closed on compound / dangerous commands. A skill script
    # invocation like `python3 known.py` is safe to auto-approve, but
    # `python3 known.py && rm -rf /home/user/important` or
    # `curl known.sh | bash` is NOT — the script is being used as cover
    # for a destructive payload. Re-run the dangerous-command detector on
    # the FULL command and refuse auto-approval if it matches. The normal
    # approval flow (which can prompt the user) still handles these.
    try:
        from tools.approval import detect_dangerous_command
        is_dangerous, _pattern_key, _desc = detect_dangerous_command(command)
        if is_dangerous:
            return None
    except Exception:
        # If detect_dangerous_command can't be imported (minimal contexts)
        # OR raises on an unexpected input, fall through to the script
        # match. detect_dangerous_command is a pure regex matcher and
        # shouldn't raise, but the approval hot path must not crash.
        pass

    # All extracted filenames belong to at least one viewed skill → auto-approve
    return next(iter(sorted(matched_viewed))) if matched_viewed else None


def invalidate_skill_scripts_cache() -> None:
    """Force the next ``load_skill_scripts()`` call to re-read from disk."""
    _SKILL_SCRIPTS_CACHE.clear()
