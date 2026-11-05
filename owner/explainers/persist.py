"""[owner] C13 — persist explainer notices into ``messages`` (role=notice).

Design: ``owner/docs/design/explainer-notice-persist/README.md``.

Zero ALTER: reuse ``role`` / ``display_kind`` / ``display_metadata`` /
``owner_provider_name`` / ``platform_message_id``. Fail-open: never raise into
旁白 / recap send paths.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

NOTICE_ROLE = "notice"
NOTICE_KINDS = frozenset({"recap", "progress", "english"})


def _normalize_provider_slug(provider: Optional[str]) -> Optional[str]:
    raw = (str(provider).strip().lower() if provider else "") or None
    if not raw or raw in {"auto", "default", "none"}:
        return None
    if raw.startswith("custom:"):
        slug = raw.split(":", 1)[1].strip()
        return slug or None
    return raw


def _normalize_model(model: Optional[str]) -> Optional[str]:
    raw = (str(model).strip() if model else "") or None
    if not raw or raw.lower() in {"auto", "default", "none"}:
        return None
    return raw


def resolve_channel_for_kind(
    kind: str,
    *,
    cfg: Optional[dict[str, Any]] = None,
    route_info: Optional[dict[str, Any]] = None,
) -> tuple[Optional[str], Optional[str], str]:
    """Return ``(provider_slug, model, task)`` for persist metadata.

    Prefer *route_info* (actual call_llm resolve) over config intent.
    """
    from owner.explainers.registry import task_name_for

    task = task_name_for(kind)
    provider = model = None
    if isinstance(route_info, dict):
        provider = route_info.get("provider")
        model = route_info.get("model")
    if provider is None and model is None:
        try:
            from owner.explainers.llm import resolve_explainer_call

            resolved = resolve_explainer_call(kind, cfg)
            provider = resolved.get("provider")
            model = resolved.get("model")
            task = str(resolved.get("task") or task)
        except Exception:
            logger.debug("persist resolve_explainer_call failed kind=%s", kind, exc_info=True)
    return _normalize_provider_slug(provider), _normalize_model(model), task


def persist_notice(
    session_id: str,
    kind: str,
    body: str,
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    task: Optional[str] = None,
    trigger: Optional[str] = None,
    platform_message_id: Optional[str] = None,
    extra_meta: Optional[dict[str, Any]] = None,
    cfg: Optional[dict[str, Any]] = None,
    route_info: Optional[dict[str, Any]] = None,
    db: Any = None,
) -> Optional[int]:
    """Append a ``role=notice`` row after a successful Feishu (or other) send.

    Returns row id or None. Never raises.
    """
    try:
        sid = str(session_id or "").strip()
        kind_l = str(kind or "").strip().lower()
        content = str(body or "")
        if not sid or kind_l not in NOTICE_KINDS or not content.strip():
            return None

        provider_slug = _normalize_provider_slug(provider)
        model_id = _normalize_model(model)
        task_name = (str(task).strip() if task else "") or None
        if provider_slug is None and model_id is None:
            provider_slug, model_id, task_name = resolve_channel_for_kind(
                kind_l, cfg=cfg, route_info=route_info
            )
        elif task_name is None:
            _, _, task_name = resolve_channel_for_kind(kind_l, cfg=cfg, route_info=route_info)

        meta: dict[str, Any] = {
            "explainer_kind": kind_l,
            "task": task_name,
        }
        if trigger:
            meta["trigger"] = str(trigger)
        if provider_slug:
            meta["provider"] = provider_slug
        if model_id:
            meta["model"] = model_id
        if isinstance(extra_meta, dict):
            for key, val in extra_meta.items():
                if val is not None and key not in meta:
                    meta[key] = val

        owns_db = db is None
        if owns_db:
            from hermes_state import SessionDB

            db = SessionDB()
        try:
            # Ensure session row exists so FK / counters stay coherent.
            ensure = getattr(db, "ensure_session", None)
            if callable(ensure):
                try:
                    ensure(sid, source="explainer_notice")
                except Exception:
                    logger.debug("persist ensure_session failed sid=%s", sid, exc_info=True)

            row_id = db.append_message(
                session_id=sid,
                role=NOTICE_ROLE,
                content=content,
                display_kind=kind_l,
                display_metadata=meta,
                platform_message_id=(str(platform_message_id).strip() or None)
                if platform_message_id
                else None,
                timestamp=time.time(),
            )
            if provider_slug and row_id:
                # append_message only binds owner_provider_name for role=assistant.
                try:
                    db._write_sql(
                        "UPDATE messages SET owner_provider_name = ? WHERE id = ?",
                        (provider_slug, int(row_id)),
                    )
                except Exception:
                    logger.debug(
                        "persist owner_provider_name UPDATE failed id=%s",
                        row_id,
                        exc_info=True,
                    )
            return int(row_id) if row_id is not None else None
        finally:
            if owns_db:
                try:
                    db.close()
                except Exception:
                    pass
    except Exception:
        logger.debug(
            "persist_notice failed kind=%s session=%s",
            kind,
            session_id,
            exc_info=True,
        )
        return None
