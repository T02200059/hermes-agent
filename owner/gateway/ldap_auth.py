"""LDAP bind-based second-factor auth for api_server identity traffic.

Gate point: ``identity_routing_middleware`` in
``gateway/platforms/api_server.py`` calls :func:`ldap_gate` after
``resolve_api_identity_route`` resolves a known identity (LDAP uid) to a
sub-profile container, and before the request is reverse-proxied.

Contract (patch_feishu_profile.yaml ``ldap:`` section):
  - password present + LDAP bind succeeds → cache the login for
    ``cache_ttl_hours`` (in-memory + state file, survives restarts)
  - password present + bind fails → 401, evict cache (password rotation
    takes effect on the very next request), short negative cache
  - no password + valid cache → allow (the "user-invisible" path; zero
    LDAP calls)
  - no password + no/expired cache → enforce policy: ``off`` allows (the
    explicit rollout mode — it provides no anti-forgery force), ``always``
    rejects every unauthenticated request, and ``seen`` is a **legacy alias
    of ``always``**. ``seen`` used to spare never-authenticated logins, which
    inverted the protection: the gate denied only users who had already
    proved their identity, so an attacker merely picked a uid that never
    logged in and passed with no password. An unrecognized ``enforce`` value
    is likewise treated as ``always`` rather than silently as ``off``
  - LDAP unreachable / ldap3 missing → ``fail_open_on_error`` decides
    (default: allow — API_SERVER_KEY remains the first trust boundary)

Security invariants:
  - the password header is stripped before proxying and never logged
  - login is validated against ``^[a-zA-Z0-9._-]+$`` and RFC4514-escaped
    before DN template substitution (DN-injection guard)
  - an empty password is rejected outright: an LDAP unauthenticated bind
    succeeds and would read as "valid credentials"
  - the DN template is anchored at ``cn=people`` so departed accounts
    (``cn=deleted``) cannot be constructed
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import tempfile
import threading
import time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

IDENTITY_PASSWORD_HEADER = "X-Hermes-Identity-Password"

_LOGIN_RE = re.compile(r"^[a-zA-Z0-9._-]+$")

# module-level state (mirrors owner/patch_config cache style); tests reset via _reset_for_tests
_positive_cache: Dict[str, float] = {}
_negative_cache: Dict[str, float] = {}
# Logins that have ever successfully authenticated. Since T2-4 made
# ``enforce=seen`` fail closed, this marker **no longer participates in the
# allow/deny decision** (every unauthenticated request without a valid cache
# is rejected regardless). It is retained because the state-file v2 schema
# carries it and it is useful when diagnosing password rotation. Historically
# ``_cache_evict`` kept the marker so an attacker could not send a wrong
# password, wait out the negative cache, then request without a password —
# that protection now comes from the fail-closed policy itself.
_seen_logins: set = set()
_cache_lock = threading.Lock()
_state_file_mtime: Optional[float] = None


def _load_ldap_config() -> Dict[str, Any]:
    """Fail-open loader for the top-level ``ldap:`` section."""
    try:
        from owner.patch_config import load_patch_feishu_profile_config

        cfg = load_patch_feishu_profile_config().get("ldap", {})
        return cfg if isinstance(cfg, dict) else {}
    except Exception:
        return {}


def _rfc4514_escape(value: str) -> str:
    escaped = value.replace("\\", "\\5c")
    escaped = escaped.replace('"', "\\22")
    escaped = escaped.replace("+", "\\2b")
    escaped = escaped.replace(",", "\\2c")
    escaped = escaped.replace(";", "\\3b")
    escaped = escaped.replace("<", "\\3c")
    escaped = escaped.replace(">", "\\3e")
    escaped = escaped.replace("\x00", "\\00")
    return escaped


def _build_user_dn(template: str, login: str) -> Optional[str]:
    if not template or "{login}" not in template:
        return None
    if not _LOGIN_RE.match(login):
        return None
    return template.replace("{login}", _rfc4514_escape(login))


# ---------------------------------------------------------------------------
# Positive cache (memory + state file) and negative cache (memory only)
# ---------------------------------------------------------------------------


def _state_file_path() -> Optional[str]:
    try:
        from hermes_constants import get_hermes_home

        return str(get_hermes_home() / "ldap_identity_cache.json")
    except Exception:
        return None


def _now() -> float:
    return time.time()


def _prune_expired(now: float) -> None:
    for login, expires in list(_positive_cache.items()):
        if expires <= now:
            del _positive_cache[login]
    for login, until in list(_negative_cache.items()):
        if until <= now:
            del _negative_cache[login]


def _persist_positive_cache() -> None:
    path = _state_file_path()
    if path is None:
        return
    global _state_file_mtime
    try:
        payload = {
            "version": 2,
            "entries": dict(_positive_cache),
            "seen": sorted(_seen_logins),
        }
        directory = os.path.dirname(path) or "."
        fd, tmp = tempfile.mkstemp(prefix=".ldap_cache.", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        _state_file_mtime = os.stat(path).st_mtime
    except Exception as exc:
        logger.debug("[LDAP] persist cache failed: %s", exc)


def _load_state_file_locked() -> None:
    path = _state_file_path()
    if path is None or not os.path.exists(path):
        return
    global _state_file_mtime
    try:
        mtime = os.stat(path).st_mtime
        if mtime == _state_file_mtime:
            return
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            if isinstance(data.get("entries"), dict):
                now = _now()
                for login, expires in data["entries"].items():
                    if (
                        isinstance(login, str)
                        and isinstance(expires, (int, float))
                        and expires > now
                    ):
                        _positive_cache[login] = float(expires)
            if isinstance(data.get("seen"), list):
                for login in data["seen"]:
                    if isinstance(login, str):
                        _seen_logins.add(login)
            elif data.get("version") != 2:
                # v1 state files (pre-seen split): any previously cached login
                # was authenticated at least once — treat it as seen so the
                # enforce=seen policy keeps denying after the window lapses.
                for login in list(_positive_cache):
                    _seen_logins.add(login)
        _state_file_mtime = mtime
    except Exception as exc:
        logger.debug("[LDAP] load cache file failed: %s", exc)


def _cache_get(login: str) -> Optional[float]:
    with _cache_lock:
        _load_state_file_locked()
        _prune_expired(_now())
        return _positive_cache.get(login)


def _cache_put(login: str, ttl_seconds: float) -> None:
    with _cache_lock:
        _positive_cache[login] = _now() + ttl_seconds
        _seen_logins.add(login)
        _negative_cache.pop(login, None)
        _persist_positive_cache()


def _cache_evict(login: str) -> None:
    # Clears the valid window only; the ``seen`` marker is kept for state-file
    # continuity and diagnostics. Since T2-4 made ``enforce=seen`` fail closed,
    # password rotation no longer needs the marker to prevent a downgrade — an
    # evicted login is re-challenged whether or not it was ever seen.
    with _cache_lock:
        _positive_cache.pop(login, None)
        _persist_positive_cache()


def _negative_put(login: str, seconds: float) -> None:
    with _cache_lock:
        _negative_cache[login] = _now() + seconds


def _negative_active(login: str) -> bool:
    with _cache_lock:
        _prune_expired(_now())
        until = _negative_cache.get(login)
        return until is not None and until > _now()


def _has_seen(login: str) -> bool:
    """True when the login has ever successfully authenticated.

    Diagnostic only since T2-4: ``ldap_gate`` no longer consults this — the
    strict modes reject every unauthenticated request without a valid cache,
    so "has this login ever authenticated" no longer changes the verdict.
    Kept as a supported introspection point for the state-file semantics.
    """
    with _cache_lock:
        _load_state_file_locked()
        return login in _seen_logins or login in _positive_cache


# ---------------------------------------------------------------------------
# Bind (sync ldap3 call) — run in executor
# ---------------------------------------------------------------------------


def _bind_sync(host: str, port: int, use_ssl: bool, timeout: float, user_dn: str, password: str) -> bool:
    """Return True/False for bind success/failure; raise on transport error."""
    import ldap3

    server = ldap3.Server(
        host,
        port=port,
        use_ssl=use_ssl,
        connect_timeout=max(1, int(timeout)),
        get_info=ldap3.NONE,
    )
    conn = ldap3.Connection(
        server,
        user=user_dn,
        password=password,
        auto_bind=False,
        raise_exceptions=False,
        authentication=ldap3.SIMPLE,
    )
    try:
        # ``read_server_info=False`` avoids the post-bind search; the bind
        # result alone is the authentication verdict.
        return conn.bind(read_server_info=False)
    finally:
        try:
            conn.unbind()
        except Exception:
            pass


async def _bind(user_dn: str, password: str) -> Tuple[bool, Optional[str]]:
    """Attempt an LDAP SIMPLE bind. Returns (verdict, error_class).

    verdict is True on success, False on credential rejection, and False
    with a non-None error_class on transport/LDAP-down (caller applies
    fail_open_on_error).
    """
    cfg = _load_ldap_config()
    host = str(cfg.get("host", ""))
    if not host:
        return False, "no_config"
    try:
        port = int(cfg.get("port", 389))
    except (TypeError, ValueError):
        port = 389
    use_ssl = bool(cfg.get("use_ssl", False))
    try:
        timeout = float(cfg.get("timeout_seconds", 5))
    except (TypeError, ValueError):
        timeout = 5.0

    try:
        result = await asyncio.to_thread(
            _bind_sync, host, port, use_ssl, timeout, user_dn, password
        )
        return bool(result), None
    except ImportError:
        return False, "ldap3_missing"
    except Exception as exc:
        logger.warning("[LDAP] bind transport error: %s", type(exc).__name__)
        return False, type(exc).__name__


# ---------------------------------------------------------------------------
# Decision verdicts
# ---------------------------------------------------------------------------

ALLOW = "allow"
DENY_BAD_CREDENTIALS = "deny_bad_credentials"
DENY_REAUTH_REQUIRED = "deny_reauth_required"
DENY_EMPTY_PASSWORD = "deny_empty_password"
DENY_INVALID_LOGIN = "deny_invalid_login"


def _denied_by_fail_open(error_class: Optional[str]) -> bool:
    if error_class is None:
        return False
    cfg = _load_ldap_config()
    return not bool(cfg.get("fail_open_on_error", True))


async def ldap_gate(login: str, password: Optional[str]) -> str:
    """Decide whether an identity-routed request may proceed.

    Returns one of ``ALLOW``, ``DENY_BAD_CREDENTIALS``,
    ``DENY_REAUTH_REQUIRED``, ``DENY_EMPTY_PASSWORD``,
    ``DENY_INVALID_LOGIN``. The middleware maps these to pass-through /
    401 responses with distinguishable error codes.
    """
    cfg = _load_ldap_config()
    if not cfg.get("enabled", False):
        return ALLOW

    if not login or not _LOGIN_RE.match(login):
        return DENY_INVALID_LOGIN

    ttl_hours = float(cfg.get("cache_ttl_hours", 72) or 72)
    ttl_seconds = ttl_hours * 3600.0
    enforce = str(cfg.get("enforce", "seen")).strip().lower()
    # [owner] T2-4: an unrecognized ``enforce`` value must not silently mean
    # "off". A typo (``enfore: always``, ``enforce: alway``) would otherwise
    # disable the gate with no signal — the same silent-failure class as a
    # dormant routing config. Normalize it to the strict mode and say so.
    if enforce not in ("off", "always", "seen"):
        logger.warning(
            "[LDAP] unrecognized enforce=%r; treating as 'always' (fail-closed)",
            enforce,
        )
        enforce = "always"
    neg_seconds = float(cfg.get("negative_cache_seconds", 10) or 10)

    if password is not None:
        # An empty/whitespace password must be rejected BEFORE any bind:
        # LDAP treats an empty password as an anonymous bind, which SUCCEEDS
        # for any existing DN — a false "valid credentials" verdict.
        if not password.strip():
            return DENY_EMPTY_PASSWORD
        dn = _build_user_dn(
            str(cfg.get("user_dn_template", "")), login
        )
        if dn is None:
            return DENY_INVALID_LOGIN
        verdict, error_class = await _bind(dn, password)
        if error_class is not None:
            if _denied_by_fail_open(error_class):
                logger.warning(
                    "[LDAP] identity %r rejected: server error (%s)",
                    login,
                    error_class,
                )
                return DENY_REAUTH_REQUIRED
            logger.warning(
                "[LDAP] identity %r fail-open on server error (%s)",
                login,
                error_class,
            )
            return ALLOW
        if verdict:
            _cache_put(login, ttl_seconds)
            logger.info("[LDAP] identity %r authenticated (cached %.0fh)", login, ttl_hours)
            return ALLOW
        _cache_evict(login)
        _negative_put(login, neg_seconds)
        logger.warning("[LDAP] identity %r rejected: invalid credentials", login)
        return DENY_BAD_CREDENTIALS

    # No password header — enforce policy against the cache.
    if _cache_get(login) is not None:
        return ALLOW

    # [owner] T2-4: ``seen`` is a legacy alias of ``always`` and fails closed.
    # It previously ALLOWed a never-authenticated login (so that rolling out
    # the password header would not break pre-existing traffic), but that
    # inverted the protection: the gate rejected only logins that had already
    # proved their identity, while an attacker just picks a uid that never
    # logged in and gets through with no password at all. The rollout role
    # belongs to ``off``, which is explicit about providing no anti-forgery
    # force. Note this also makes the negative-cache branch below reachable
    # only under ``off`` — under the strict modes the verdict is the same
    # (DENY_REAUTH_REQUIRED), so nothing observable changes.
    if enforce in ("always", "seen"):
        return DENY_REAUTH_REQUIRED

    if _negative_active(login):
        return DENY_REAUTH_REQUIRED
    return ALLOW


def reset_for_tests() -> None:
    """Clear all cache state (memory + mtime tracker) for test isolation."""
    global _state_file_mtime
    with _cache_lock:
        _positive_cache.clear()
        _negative_cache.clear()
        _seen_logins.clear()
        _state_file_mtime = None
