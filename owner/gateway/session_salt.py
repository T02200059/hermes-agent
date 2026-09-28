"""Server-side salt for API-server session-id derivation (T2-8, §16.5).

Why this exists
---------------
``gateway/platforms/api_server.py::_derive_chat_session_id`` turns
``(system prompt, first user message)`` into the session id used whenever a
client sends no ``X-Hermes-Session-Id``. Both inputs are client-controlled and
public — the system prompt is whatever the frontend ships, the first message is
the user's own — so an unkeyed digest is *derivable offline* by anyone who can
guess them. Keying the seed with a server secret is what removes that.

Why it is worth having, given that it does not fix ownership
------------------------------------------------------------
The security report raised this under the media-ownership assertion (S2-2),
where a salt buys nothing: the download side re-digests whatever string the
caller sends, so possessing a known id is enough and no offline computation is
needed (see ``owner/docs/owner改动清单.md`` §16.5). The reason to key the
derivation anyway is that the *derived id itself* is a bearer credential:
``/api/sessions/{id}`` (GET / PATCH / DELETE / fork) authenticates with the API
key alone and takes the id straight from the path, with no ownership check, so
a derivable id means derivable access to another caller's conversation.

What it deliberately does not do
--------------------------------
A salt makes derivation unforgeable offline; it does not make derived ids
unique. Two callers behind the same deployment with the same system prompt and
the same first message still collide — the salt is shared by every node — and
that collision is left unaddressed here. Separating them needs a per-identity
dimension this module does not have, so it is recorded as an open bound in
§16.5 rather than papered over by the key.

Precedence and shape
--------------------
``HERMES_API_SESSION_SALT`` > ``gateway.api_server.session_salt`` > a generated
secret persisted to ``<HERMES_HOME>/api_session_salt`` (mode 0600). The
generated secret is stable across restarts, so derived-session continuity
survives one. **Multi-node deployments should inject the env var (or the config
key) on every node**: independently generated secrets are per-node, so the same
conversation would derive different ids depending on which node answered.
If no secret can be persisted the module degrades to a per-process secret and
says so loudly — that keeps the forged-offline property while costing
restart continuity, which is the only honest trade available; silently
returning the unkeyed digest instead would restore the bug.
"""

from __future__ import annotations

import logging
import os
import secrets
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

#: Environment override. Wins over config.yaml so a deployment can inject the
#: secret without editing config, and so every node can be given the same one.
ENV_VAR = "HERMES_API_SESSION_SALT"

#: File name under HERMES_HOME holding the generated fallback secret.
FILE_NAME = "api_session_salt"

#: Reject anything shorter. 16 chars is not a strength target — it is a floor
#: that catches a placeholder like ``changeme`` being read as "configured".
#: The generated secret is 32 bytes of ``secrets.token_urlsafe`` (~192 bits).
MIN_SALT_CHARS = 16

_GENERATED_BYTES = 32

_ENV_LABEL = ENV_VAR
_CONFIG_LABEL = "gateway.api_server.session_salt"

_cached_salt: Optional[str] = None
_cached_source: Optional[str] = None


def _from_env() -> str:
    return (os.environ.get(ENV_VAR) or "").strip()


def _from_config() -> str:
    """Read ``gateway.api_server.session_salt``. Never raises."""
    try:
        from hermes_cli.config import cfg_get, load_config

        value = cfg_get(load_config(), "gateway", "api_server", "session_salt", default="")
    except Exception:  # noqa: BLE001 - a config miss must not break chat
        return ""
    return str(value or "").strip()


def _salt_file() -> Optional[Path]:
    try:
        from hermes_constants import get_hermes_home

        return get_hermes_home() / FILE_NAME
    except Exception:  # noqa: BLE001
        return None


def _read_secret_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception as exc:  # noqa: BLE001 - unreadable == absent, reported by caller
        logger.warning("[API] could not read the session-id salt at %s: %s", path, exc)
        return ""


def _write_secret_file(path: Path, value: str) -> bool:
    """Persist the secret atomically, 0600 from the moment it exists.

    Written via a temp file in the same directory because the gateway and any
    sibling process may read it concurrently; ``os.replace`` means a reader
    never observes a half-written secret.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=f".{FILE_NAME}.", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(value + "\n")
            os.chmod(tmp, 0o600)  # mkstemp already does this; stated for readers
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("[API] failed to persist the session-id salt to %s: %s", path, exc)
        return False


def _degrade(reason: str) -> str:
    """Fall back to a per-process secret, saying why exactly once per resolution.

    The once-per-resolution property is structural rather than a separate flag:
    this branch always memoises its result, so no later call reaches it again.
    """
    global _cached_salt, _cached_source
    _cached_salt = secrets.token_urlsafe(_GENERATED_BYTES)
    _cached_source = "degraded"
    logger.error(
        "[API] %s Using a per-process session-id salt: derived session ids stay "
        "unforgeable, but they change on every restart, so derived-session continuity "
        "does not survive one. Set %s (or %s) to make the derivation deterministic "
        "across restarts and nodes.",
        reason,
        _ENV_LABEL,
        _CONFIG_LABEL,
    )
    return _cached_salt


def api_session_salt() -> str:
    """Return the process-wide salt for ``_derive_chat_session_id``.

    Configuration, filesystem and import problems are absorbed, and the result
    is never empty: once this module is importable, a keyed digest is
    guaranteed. (A failure of the OS randomness source is the one thing that
    escapes, and no caller could act on it.) Callers that must also survive the
    module being *absent* — upstream sync drops ``owner/`` — handle that on
    their own import path rather than by tolerating an empty salt here, because
    an empty salt is the original bug.
    """
    global _cached_salt, _cached_source

    if _cached_salt is not None:
        return _cached_salt

    for label, value in ((_ENV_LABEL, _from_env()), (_CONFIG_LABEL, _from_config())):
        if not value:
            continue
        if len(value) >= MIN_SALT_CHARS:
            _cached_salt, _cached_source = value, "env" if label == _ENV_LABEL else "config"
            return value
        logger.warning(
            "[API] %s is %d chars, below the %d-char minimum - ignored, so the "
            "derivation does not look configured while adding almost nothing.",
            label,
            len(value),
            MIN_SALT_CHARS,
        )

    path = _salt_file()
    if path is None:
        return _degrade("No HERMES_HOME to hold a generated salt.")

    if path.exists():
        existing = _read_secret_file(path)
        if len(existing) >= MIN_SALT_CHARS:
            _cached_salt, _cached_source = existing, "file"
            return existing
        # A secret we did not write: never overwrite it, never trust it either.
        return _degrade(
            f"{path} holds a {len(existing)}-char secret, below the "
            f"{MIN_SALT_CHARS}-char minimum; refusing to overwrite or use it."
        )

    generated = secrets.token_urlsafe(_GENERATED_BYTES)
    if not _write_secret_file(path, generated):
        return _degrade(f"Could not persist a generated salt to {path}.")
    logger.info("[API] generated a session-id salt at %s", path)
    _cached_salt, _cached_source = generated, "generated"
    return generated


def session_salt_source() -> str:
    """Which precedence tier supplied the salt — diagnostics only.

    ``env`` / ``config`` / ``file`` / ``generated`` / ``degraded``. Read-only and
    never raises, so it is safe to expose where a caller needs to attribute the
    value (the same reason §15.7 splits the routing-dormant causes apart: a
    state that cannot be attributed gets misread).
    """
    try:
        api_session_salt()
    except Exception:  # noqa: BLE001 - diagnostics never break the caller
        return "unresolved"
    return _cached_source or "unresolved"


def reset_session_salt_cache() -> None:
    """Drop the memoised secret so the next call re-resolves the precedence chain.

    For tests and for callers that changed the configuration in-process. Safe to
    call in production — a re-resolve returns the same value whenever the
    sources are unchanged.
    """
    global _cached_salt, _cached_source
    _cached_salt = None
    _cached_source = None
