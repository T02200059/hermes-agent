"""C06: LDAP bind second-factor for api_server ``X-Hermes-Identity`` traffic.

Design: ``owner/docs/design/c06-ldap-identity-auth/README.md``.

v2 adaptations vs historical owner notes:
  - Config primary source is overlay.yaml top-level ``ldap:``; patch_feishu_profile
    is migration fallback only.
  - Routing tables come from C05 ``fleet_profiles`` synthesis (hub_only.api /
    api_server) — this module never reads identity_routes itself.
  - Official ``api_server.py`` only imports :func:`ldap_gate` via thin glue.

Gate order (enforced by identity_routing middleware): every request that carries
``X-Hermes-Identity`` hits :func:`ldap_gate` **before** whitelist / route lookup.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import tempfile
import threading
import time
from typing import Any, Optional, Callable

logger = logging.getLogger(__name__)

IDENTITY_PASSWORD_HEADER = "X-Hermes-Identity-Password"

_LOGIN_RE = re.compile(r"^[a-zA-Z0-9._-]+$")

ALLOW = "allow"
DENY_BAD_CREDENTIALS = "deny_bad_credentials"
DENY_REAUTH_REQUIRED = "deny_reauth_required"
DENY_EMPTY_PASSWORD = "deny_empty_password"
DENY_INVALID_LOGIN = "deny_invalid_login"
DENY_BACKEND_UNAVAILABLE = "deny_backend_unavailable"

_CONFIG_ERROR_CLASSES: frozenset[str] = frozenset({"no_config", "ldap3_missing"})

_positive_cache: dict[str, float] = {}
_negative_cache: dict[str, float] = {}
_seen_logins: set = set()
_cache_lock = threading.Lock()
_state_file_mtime: Optional[float] = None
_state_hmac_key: bytes = secrets.token_bytes(32)
_STATE_FILE_VERSION = 3

# Test seam: replace with a sync callable(host, port, use_ssl, timeout, dn, password)
# returning bool, or raising to simulate transport errors.
_bind_sync_impl: Optional[Callable[..., bool]] = None


def _normalize_login(login: str) -> str:
    """Canonical cache key (casefold + strip). DN construction keeps raw login."""
    return (login or "").casefold().strip()


def _env_bool(name: str) -> Optional[bool]:
    raw = os.environ.get(name)
    if raw is None:
        return None
    val = raw.strip().lower()
    if val in ("1", "true", "yes", "on"):
        return True
    if val in ("0", "false", "no", "off"):
        return False
    return None


def _apply_ldap_env_overrides(cfg: dict[str, Any]) -> dict[str, Any]:
    """Merge ``HERMES_LDAP_*`` env onto yaml config (ops/E2E; never commit secrets).

    Supported (non-secret connection / policy only):
      HERMES_LDAP_ENABLED, HERMES_LDAP_HOST, HERMES_LDAP_PORT,
      HERMES_LDAP_USE_SSL, HERMES_LDAP_TIMEOUT_SECONDS,
      HERMES_LDAP_USER_DN_TEMPLATE, HERMES_LDAP_ENFORCE,
      HERMES_LDAP_CACHE_TTL_HOURS, HERMES_LDAP_NEGATIVE_CACHE_SECONDS,
      HERMES_LDAP_FAIL_OPEN_ON_ERROR

    User bind passwords come from the request header, not env. Legacy
    ``admin_dn`` / ``admin_password`` keys in yaml are ignored by this gate.
    """
    out = dict(cfg)
    enabled = _env_bool("HERMES_LDAP_ENABLED")
    if enabled is not None:
        out["enabled"] = enabled
    host = os.environ.get("HERMES_LDAP_HOST")
    if host is not None and host.strip():
        out["host"] = host.strip()
    port = os.environ.get("HERMES_LDAP_PORT")
    if port is not None and port.strip():
        try:
            out["port"] = int(port.strip())
        except ValueError:
            logger.warning("[LDAP] ignoring invalid HERMES_LDAP_PORT=%r", port)
    use_ssl = _env_bool("HERMES_LDAP_USE_SSL")
    if use_ssl is not None:
        out["use_ssl"] = use_ssl
    timeout = os.environ.get("HERMES_LDAP_TIMEOUT_SECONDS")
    if timeout is not None and timeout.strip():
        try:
            out["timeout_seconds"] = float(timeout.strip())
        except ValueError:
            logger.warning(
                "[LDAP] ignoring invalid HERMES_LDAP_TIMEOUT_SECONDS=%r", timeout
            )
    template = os.environ.get("HERMES_LDAP_USER_DN_TEMPLATE")
    if template is not None and template.strip():
        out["user_dn_template"] = template.strip()
    enforce = os.environ.get("HERMES_LDAP_ENFORCE")
    if enforce is not None and enforce.strip():
        out["enforce"] = enforce.strip()
    ttl = os.environ.get("HERMES_LDAP_CACHE_TTL_HOURS")
    if ttl is not None and ttl.strip():
        try:
            out["cache_ttl_hours"] = float(ttl.strip())
        except ValueError:
            logger.warning(
                "[LDAP] ignoring invalid HERMES_LDAP_CACHE_TTL_HOURS=%r", ttl
            )
    neg = os.environ.get("HERMES_LDAP_NEGATIVE_CACHE_SECONDS")
    if neg is not None and neg.strip():
        try:
            out["negative_cache_seconds"] = float(neg.strip())
        except ValueError:
            logger.warning(
                "[LDAP] ignoring invalid HERMES_LDAP_NEGATIVE_CACHE_SECONDS=%r",
                neg,
            )
    fail_open = _env_bool("HERMES_LDAP_FAIL_OPEN_ON_ERROR")
    if fail_open is not None:
        out["fail_open_on_error"] = fail_open
    return out


def _load_ldap_config() -> dict[str, Any]:
    """Load top-level ``ldap:`` — overlay first, then patch fallback, then env.

    Fail-open on loader errors → ``{}`` (gate treats empty + enabled false as
    open). Env overrides always win for the keys they set.
    """
    section: dict[str, Any] = {}
    try:
        from owner.patch_config import (
            load_owner_config,
            load_patch_feishu_profile_config,
        )

        for loader in (load_owner_config, load_patch_feishu_profile_config):
            raw = loader()
            if not isinstance(raw, dict):
                continue
            found = raw.get("ldap")
            if isinstance(found, dict) and found:
                section = dict(found)
                break
            # empty dict section still "configured but empty" — prefer explicit over missing
            if isinstance(found, dict) and "ldap" in raw:
                section = dict(found)
                break
    except Exception:
        section = {}
    return _apply_ldap_env_overrides(section)


def _hermes_yaml_paths() -> list:
    paths = []
    try:
        from hermes_constants import get_hermes_home

        home = get_hermes_home()
        paths.append(home / "overlay.yaml")
        paths.append(home / "patch_feishu_profile.yaml")
    except Exception:
        pass
    return paths


def _ldap_config_broken_reason() -> Optional[str]:
    """Distinguish unreadable/malformed ldap config from 'not configured'.

    Fail-open loaders collapse parse errors to ``{}``. For a security gate that
    must not silently disable itself when a live-edited symlink half-writes YAML.
    """
    try:
        from hermes_constants import get_hermes_home

        _ = get_hermes_home()
    except Exception as exc:
        return f"hermes home unresolvable: {exc}"

    import yaml

    saw_any_file = False
    for path in _hermes_yaml_paths():
        try:
            if not path.exists():
                continue
            saw_any_file = True
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
            except Exception as exc:
                return f"{path.name} YAML parse error: {exc}"
            if data is None:
                continue
            if not isinstance(data, dict):
                return f"{path.name} top level is {type(data).__name__}, not a mapping"
            if "ldap" not in data:
                continue
            section = data["ldap"]
            if section is None:
                continue
            if not isinstance(section, dict):
                return (
                    f"{path.name} ldap section is {type(section).__name__}, "
                    "not a mapping"
                )
            return None
        except Exception as exc:
            return f"{path.name} unreadable: {exc}"
    if not saw_any_file:
        return None
    return None


def _rfc4514_escape(value: str) -> str:
    """Escape a DN attribute value (RFC 4514)."""
    out = []
    specials = set(',+"\\<>;')
    for i, ch in enumerate(value):
        if ch in specials or ch == "\x00" or (i == 0 and ch in (" ", "#")) or (
            i == len(value) - 1 and ch == " "
        ):
            out.append(chr(0x5C) + format(ord(ch), "02X"))
        else:
            out.append(ch)
    return "".join(out)


def _build_user_dn(template: str, login: str) -> Optional[str]:
    if not template or "{login}" not in template:
        return None
    if not login or not _LOGIN_RE.match(login):
        return None
    return template.replace("{login}", _rfc4514_escape(login))


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


def _state_file_mac(entries: dict[str, float], seen: list) -> str:
    body = json.dumps(
        {"entries": entries, "seen": seen}, sort_keys=True, separators=(",", ":")
    )
    return hmac.new(_state_hmac_key, body.encode("utf-8"), hashlib.sha256).hexdigest()


def _persist_positive_cache() -> None:
    path = _state_file_path()
    if path is None:
        return
    global _state_file_mtime
    try:
        entries = dict(_positive_cache)
        seen = sorted(_seen_logins)
        payload = {
            "version": _STATE_FILE_VERSION,
            "entries": entries,
            "seen": seen,
            "mac": _state_file_mac(entries, seen),
        }
        directory = os.path.dirname(path) or "."
        fd, tmp = tempfile.mkstemp(prefix=".ldap_cache.", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
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
        if not isinstance(data, dict):
            _state_file_mtime = mtime
            return
        entries = data.get("entries")
        seen = data.get("seen")
        mac = data.get("mac")
        if not (
            isinstance(entries, dict)
            and isinstance(seen, list)
            and isinstance(mac, str)
            and hmac.compare_digest(mac, _state_file_mac(entries, seen))
        ):
            logger.warning(
                "[LDAP] state file failed integrity check; ignoring "
                "(unsigned or foreign signature) — cached logins must re-auth"
            )
            _positive_cache.clear()
            _state_file_mtime = mtime
            return
        now = _now()
        fresh = {
            login: float(expires)
            for login, expires in entries.items()
            if (
                isinstance(login, str)
                and isinstance(expires, (int, float))
                and float(expires) > now
            )
        }
        _positive_cache.clear()
        _positive_cache.update(fresh)
        for login in seen:
            if isinstance(login, str):
                _seen_logins.add(login)
        _state_file_mtime = mtime
    except Exception as exc:
        logger.debug("[LDAP] load cache file failed: %s", exc)


def _cache_get(login: str) -> Optional[float]:
    key = _normalize_login(login)
    with _cache_lock:
        _load_state_file_locked()
        _prune_expired(_now())
        return _positive_cache.get(key)


def _cache_put(login: str, ttl_seconds: float) -> None:
    key = _normalize_login(login)
    with _cache_lock:
        _positive_cache[key] = _now() + max(1.0, ttl_seconds)
        _seen_logins.add(key)
        _negative_cache.pop(key, None)
        _persist_positive_cache()


def _cache_evict(login: str) -> None:
    """Drop positive cache on bad password; keep seen marker (diagnostic only)."""
    key = _normalize_login(login)
    with _cache_lock:
        _positive_cache.pop(key, None)
        _persist_positive_cache()


def _negative_put(login: str, seconds: float) -> None:
    key = _normalize_login(login)
    with _cache_lock:
        _negative_cache[key] = _now() + max(1.0, seconds)


def _negative_active(login: str) -> bool:
    key = _normalize_login(login)
    with _cache_lock:
        _prune_expired(_now())
        until = _negative_cache.get(key)
        return until is not None and until > _now()


def _bind_sync(
    host: str, port: int, use_ssl: bool, timeout: float, user_dn: str, password: str
) -> bool:
    if _bind_sync_impl is not None:
        return bool(_bind_sync_impl(host, port, use_ssl, timeout, user_dn, password))
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
        return conn.bind(read_server_info=False)
    finally:
        try:
            conn.unbind()
        except Exception:
            pass


async def _bind(user_dn: str, password: str) -> tuple[bool, Optional[str]]:
    cfg = _load_ldap_config()
    host = str(cfg.get("host", "") or "").strip()
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


def _verdict_on_unverifiable(login: str, error_class: str) -> str:
    cfg = _load_ldap_config()
    if error_class in _CONFIG_ERROR_CLASSES:
        logger.error(
            "[LDAP] identity %r cannot be verified: %s is a configuration error; "
            "denying (fail_open_on_error does not apply)",
            login,
            error_class,
        )
        return DENY_BACKEND_UNAVAILABLE
    if bool(cfg.get("fail_open_on_error", False)):
        logger.warning(
            "[LDAP] identity %r allowed WITHOUT credential verification: backend "
            "error %s and fail_open_on_error=true (explicit opt-in)",
            login,
            error_class,
        )
        return ALLOW
    logger.warning(
        "[LDAP] identity %r denied: credentials could not be verified (%s)",
        login,
        error_class,
    )
    return DENY_BACKEND_UNAVAILABLE


async def ldap_gate(login: str, password: Optional[str]) -> str:
    """Decide whether an identity-bearing request may proceed.

    Returns one of ALLOW / DENY_* strings. Middleware maps them to pass-through
    or 401/503 JSON bodies with stable ``code`` fields.
    """
    cfg = _load_ldap_config()
    if not cfg.get("enabled", False):
        broken = _ldap_config_broken_reason()
        if broken is not None:
            logger.error(
                "[LDAP] config unreadable/malformed (%s); failing CLOSED",
                broken,
            )
            return DENY_BACKEND_UNAVAILABLE
        return ALLOW

    if not login or not _LOGIN_RE.match(login):
        return DENY_INVALID_LOGIN

    try:
        ttl_hours = float(cfg.get("cache_ttl_hours", 72) or 72)
    except (TypeError, ValueError):
        ttl_hours = 72.0
    ttl_seconds = ttl_hours * 3600.0
    enforce = str(cfg.get("enforce", "always") or "always").strip().lower()
    if enforce not in ("off", "always", "seen"):
        logger.warning(
            "[LDAP] unrecognized enforce=%r; treating as 'always' (fail-closed)",
            enforce,
        )
        enforce = "always"
    try:
        neg_seconds = float(cfg.get("negative_cache_seconds", 10) or 10)
    except (TypeError, ValueError):
        neg_seconds = 10.0

    if password is not None:
        if not password.strip():
            return DENY_EMPTY_PASSWORD
        dn = _build_user_dn(str(cfg.get("user_dn_template", "") or ""), login)
        if dn is None:
            return DENY_INVALID_LOGIN
        verdict, error_class = await _bind(dn, password)
        if error_class is not None:
            return _verdict_on_unverifiable(login, error_class)
        if verdict:
            _cache_put(login, ttl_seconds)
            logger.info(
                "[LDAP] identity %r authenticated (cached %.0fh)", login, ttl_hours
            )
            return ALLOW
        _cache_evict(login)
        _negative_put(login, neg_seconds)
        logger.warning("[LDAP] identity %r rejected: invalid credentials", login)
        return DENY_BAD_CREDENTIALS

    if _cache_get(login) is not None:
        return ALLOW

    # ``seen`` is a legacy alias of ``always`` (fail-closed).
    if enforce in ("always", "seen"):
        return DENY_REAUTH_REQUIRED

    if _negative_active(login):
        return DENY_REAUTH_REQUIRED
    return ALLOW


def reset_for_tests() -> None:
    """Clear caches and test seams (unit tests only)."""
    global _state_file_mtime, _bind_sync_impl, _state_hmac_key
    with _cache_lock:
        _positive_cache.clear()
        _negative_cache.clear()
        _seen_logins.clear()
        _state_file_mtime = None
    _bind_sync_impl = None
    _state_hmac_key = secrets.token_bytes(32)
