"""Embedding client for qdrant-memory-recall hook."""

from __future__ import annotations

import time
from typing import Any

import requests

from recall_config import get_env, logger


def embed_sync(text: str, cfg: dict[str, Any]) -> list[float] | None:
    """Synchronous embed (runs in thread pool). Returns None on failure."""
    env = get_env()
    if not env["DAMODEL_BASE_URL"] or not env["DAMODEL_API_KEY"]:
        logger.warning("DAMODEL env missing, skip embed")
        return None

    timeout = cfg["embed_timeout_sec"]
    model = cfg["embed_model"]
    last_err = None
    for attempt in range(cfg["embed_max_retries"] + 1):
        try:
            resp = requests.post(
                f"{env['DAMODEL_BASE_URL']}/embeddings",
                headers={"Authorization": f"Bearer {env['DAMODEL_API_KEY']}"},
                json={"model": model, "input": text},
                timeout=timeout,
            )
            if resp.status_code in (401, 403):
                logger.error(f"embed auth failed (HTTP {resp.status_code}): key 可能失效")
                return None
            resp.raise_for_status()
            return resp.json()["data"][0]["embedding"]
        except requests.exceptions.Timeout:
            last_err = f"embed timeout after {timeout}s"
        except requests.exceptions.RequestException as e:
            last_err = f"embed request error: {e}"
        except Exception as e:
            last_err = f"embed unexpected: {e}"

        if attempt < cfg["embed_max_retries"]:
            time.sleep(0.3 * (attempt + 1))

    logger.warning(f"embed failed after retries: {last_err}")
    return None