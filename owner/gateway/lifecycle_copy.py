"""Gateway lifecycle display copy — profile tag + translation.

Owner-side home for injecting a human-readable profile label into gateway
restart / online notices (and the sibling shutdown notice). Docker one-process
per-tenant fleets can tell which profile is going down or coming back.

Default / Hub stays untagged, so single-profile installs keep the original
wording. ``custom`` (a non-standard ``HERMES_HOME``) is also untagged, so test
homes and ad-hoc paths do not leak a meaningless ``[custom]``.

Resolution order for the label:

1. ``HERMES_LIFECYCLE_LABEL`` — free-form display override (Chinese, spaces
   allowed). Display-only: not used for routing, auth, or bot identity.
2. ``overlay.yaml`` ``fleet_profiles.<id>.display_name`` — the centralized
   short Chinese name on the Feishu + LDAP person card. This is the primary
   in-repo source. Looked up from, in order: ``HERMES_OVERLAY_PATH``,
   ``$HERMES_HOME/overlay.yaml`` (correct on Hub / the host; inside a profile
   container that path is the per-profile dir, not the fleet overlay), then
   well-known fleet paths ``/etc/hermes/overlay.yaml`` and
   ``/data/hermes/overlay.yaml``. The fleet_add compose template bind-mounts
   the host fleet overlay read-only at ``/etc/hermes/overlay.yaml`` and sets
   ``HERMES_OVERLAY_PATH``.
3. ``profile.yaml`` ``display_name`` (official profile meta).
4. ``profile.yaml`` ``description`` (longer copy such as ``杨天宝的 AI 助手``).
5. The profile id itself (``HERMES_PROFILE`` / ``HERMES_PROFILE_NAME``, else
   ``get_active_profile_name()`` when that name is a real id).

Any resolution failure returns ``""`` and logs a warning — lifecycle
notifications must never crash the shutdown/startup path over a missing name.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_UNTAGGED_PROFILE_IDS = frozenset({"", "default", "custom"})

# Insert the tag immediately after these anchors so the original punctuation
# and spacing stay intact: "Hermes 正在重启" → "Hermes [杨天宝] 正在重启",
# "网关已上线" → "网关 [杨天宝]已上线", "Gateway online" → "Gateway [杨天宝] online".
_NOTICE_ANCHORS = ("Hermes",)
_ONLINE_ANCHORS = ("网关", "Gateway")

# Profile containers typically mount code + profiles/<uid>→/root/.hermes, so
# $HERMES_HOME/overlay.yaml is not the fleet overlay. Future compose templates
# mount the host file at /etc/hermes/overlay.yaml; /data/hermes/overlay.yaml is
# the node010 fleet-root convention. Tests should monkeypatch this tuple.
_WELL_KNOWN_OVERLAY_PATHS: tuple[Path, ...] = (
    Path("/etc/hermes/overlay.yaml"),
    Path("/data/hermes/overlay.yaml"),
)


def _profile_id() -> str:
    for env_name in ("HERMES_PROFILE", "HERMES_PROFILE_NAME"):
        value = (os.environ.get(env_name) or "").strip()
        if value:
            return value
    try:
        from hermes_cli.profiles import get_active_profile_name

        return (get_active_profile_name() or "").strip()
    except Exception:
        return ""


def _profile_yaml_meta() -> dict[str, str]:
    try:
        from hermes_cli.profiles import read_profile_meta
        from hermes_constants import get_hermes_home

        meta = read_profile_meta(get_hermes_home())
    except Exception:
        return {}
    if not isinstance(meta, dict):
        return {}
    return {
        "display_name": str(meta.get("display_name") or "").strip(),
        "description": str(meta.get("description") or "").strip(),
    }


def _overlay_candidate_paths() -> list[Path]:
    candidates: list[Path] = []
    seen: set[str] = set()

    def add(path: Path) -> None:
        key = str(path)
        if not key or key in seen:
            return
        seen.add(key)
        candidates.append(path)

    extra = (os.environ.get("HERMES_OVERLAY_PATH") or "").strip()
    if extra:
        add(Path(extra))
    try:
        from hermes_constants import get_hermes_home

        add(get_hermes_home() / "overlay.yaml")
    except Exception:
        pass
    for path in _WELL_KNOWN_OVERLAY_PATHS:
        add(path)
    return candidates


def _overlay_display_name(profile_id: str) -> str:
    if not profile_id or profile_id in _UNTAGGED_PROFILE_IDS:
        return ""
    for path in _overlay_candidate_paths():
        try:
            if not path.is_file():
                continue
        except OSError:
            continue
        data = _read_yaml_dict(path)
        fleet = data.get("fleet_profiles") if data else None
        if not isinstance(fleet, dict):
            continue
        card = fleet.get(profile_id)
        if not isinstance(card, dict):
            continue
        name = str(card.get("display_name") or "").strip()
        if name:
            return name
    return ""


def _read_yaml_dict(path: Path) -> dict[str, Any]:
    try:
        import hermes_yaml as yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _resolve_label() -> str:
    label = (os.environ.get("HERMES_LIFECYCLE_LABEL") or "").strip()
    if label:
        return label

    profile_id = _profile_id()
    overlay_name = (
        _overlay_display_name(profile_id)
        if profile_id not in _UNTAGGED_PROFILE_IDS
        else ""
    )
    meta = _profile_yaml_meta()
    for candidate in (
        overlay_name,
        meta.get("display_name") or "",
        meta.get("description") or "",
        profile_id,
    ):
        name = candidate.strip()
        if name and name not in _UNTAGGED_PROFILE_IDS:
            return name
    return ""


def profile_tag() -> str:
    """Return a display tag for lifecycle messages, e.g. ``" [杨天宝]"``."""
    try:
        name = _resolve_label()
    except Exception as exc:
        logger.warning(
            "Could not resolve a profile label for lifecycle messages; "
            "using untagged gateway text: %s",
            exc,
        )
        return ""

    if not isinstance(name, str) or not name.strip():
        return ""
    return f" [{name.strip()}]"


def _splice_profile_tag(key: str, text: str, tag: str) -> str:
    """Insert ``tag`` after a known anchor when the catalog has no placeholder."""
    if not tag or not text or tag in text:
        return text
    if key in {"gateway.startup.online", "gateway.startup.restarted"}:
        anchors = _ONLINE_ANCHORS
    elif key in {"gateway.shutdown.notice_restart", "gateway.shutdown.notice_shutdown"}:
        anchors = _NOTICE_ANCHORS
    else:
        return text
    for anchor in anchors:
        idx = text.find(anchor)
        if idx >= 0:
            at = idx + len(anchor)
            return text[:at] + tag + text[at:]
    return text


def lifecycle_msg(key: str, **format_kwargs: Any) -> str:
    """Translate a gateway lifecycle key and attach the profile tag.

    Extra ``format_kwargs`` are forwarded to :func:`agent.i18n.t`. If the
    catalog already has a ``{profile_tag}`` placeholder, that wins; otherwise
    the tag is spliced after a language-appropriate anchor for the two
    restart/online notices (and the sibling shutdown notice).
    """
    from agent.i18n import t

    tag = profile_tag()
    text = t(key, profile_tag=tag, **format_kwargs)
    return _splice_profile_tag(key, text, tag)
