"""Qdrant search and hit formatting for qdrant-memory-recall hook."""

from __future__ import annotations

from typing import Any

import requests

from recall_config import get_env, logger

# Gateway-internal synthetic message prefixes — skip recall (see handler docstring).
SYNTHETIC_PREFIXES: tuple[str, ...] = (
    "[IMPORTANT:",
    "[Session was just handed off",
    "[Background process",
)


def search_collection_sync(collection: str, vector: list[float], cfg: dict) -> list[dict]:
    """Search one Qdrant collection; failures return [] without raising."""
    env = get_env()
    if not env["QDRANT_URL"] or not env["QDRANT_KEY"]:
        return []
    search_url = f"{env['QDRANT_URL']}/collections/{collection}/points/search"
    headers = {"api-key": env["QDRANT_KEY"], "Content-Type": "application/json"}
    base_params = {"limit": cfg["per_collection_k"], "with_payload": True}
    
    # Add tenant_id filter if QDRANT_TENANT_ID is set
    tenant_id = env.get("QDRANT_TENANT_ID", "")
    if tenant_id:
        tenant_filter = {"must": [{"key": "tenant_id", "match": {"value": tenant_id}}]}
    else:
        tenant_filter = None

    try:
        search_body = {"vector": {"name": "dense", "vector": vector}, **base_params}
        if tenant_filter:
            search_body["filter"] = tenant_filter
        resp = requests.post(
            search_url,
            headers=headers,
            json=search_body,
            timeout=cfg["per_collection_timeout_sec"],
        )
        if resp.status_code in (400, 404):
            logger.debug(
                f"collection={collection} named vector search returned {resp.status_code}, trying fallback"
            )
        else:
            resp.raise_for_status()
            hits = resp.json().get("result", []) or []
            if hits:
                for h in hits:
                    h["_collection"] = collection
                return hits
            logger.debug(f"collection={collection} named vector search returned 0 hits, trying fallback")
    except requests.exceptions.Timeout:
        logger.warning(f"search timeout (named): collection={collection}")
    except Exception as e:
        logger.debug(f"collection={collection} named vector search error: {e}, trying fallback")

    try:
        search_body = {"vector": vector, **base_params}
        if tenant_filter:
            search_body["filter"] = tenant_filter
        resp = requests.post(
            search_url,
            headers=headers,
            json=search_body,
            timeout=cfg["per_collection_timeout_sec"],
        )
        if resp.status_code in (400, 404):
            logger.warning(
                f"collection={collection} skipped (HTTP {resp.status_code}): "
                f"{resp.text[:200]}"
            )
            return []
        resp.raise_for_status()
        hits = resp.json().get("result", []) or []
        for h in hits:
            h["_collection"] = collection
        return hits
    except requests.exceptions.Timeout:
        logger.warning(f"search timeout (unnamed): collection={collection}")
        return []
    except Exception as e:
        logger.warning(f"search error (unnamed): {e}")
        return []


def format_hit(hit: dict, cfg: dict) -> str:
    """Format a single search hit for LLM extra_context."""
    payload = hit.get("payload") or {}
    uri = payload.get("uri") or f"unknown-{hit.get('id')}"
    score = hit.get("score", 0.0)
    coll = hit.get("_collection", "?")

    body = (
        payload.get("content")
        or payload.get("text")
        or payload.get("description")
    )
    if not body:
        meta = [
            f"{k}={v}"
            for k, v in payload.items()
            if k not in ("uri", "name") and v
        ]
        body = " | ".join(meta) if meta else (payload.get("name") or "")

    body = str(body)
    if len(body) > cfg["body_max_chars"]:
        body = body[: cfg["body_max_chars"]] + "..."

    parts = [f"[uri={uri}"]
    if cfg["include_score"]:
        parts.append(f", score={score:.3f}")
    if cfg["include_source_collection"]:
        parts.append(f", src={coll}")
    parts.append("] ")
    parts.append(body)
    return "".join(parts)