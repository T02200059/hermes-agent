"""OpenViking synchronous recall + advisory memory-context patch.

Replaces the async one-turn-lagged prefetch in ``OpenVikingMemoryProvider``
with a synchronous search, and softens the ``memory-context`` system note
from authoritative to advisory.

All changes are runtime patches in ``owner/``; no official source file is
modified.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any, Dict

from plugins.memory.openviking import (
    OpenVikingMemoryProvider,
    _VikingClient,
    _get_httpx,
)

import agent.memory_manager as _memory_manager_module

logger = logging.getLogger(__name__)

# Patch state
_originals: Dict[str, Any] = {}
_applied: Dict[str, bool] = {"sync": False, "advisory": False}


def _env_bool(name: str, default: bool) -> bool:
    """Read a boolean-ish environment variable."""
    value = os.environ.get(name, "")
    if value == "":
        return default
    return value.lower() not in ("0", "false", "no", "off", "")


def _search_timeout() -> float:
    """Return the synchronous search timeout in seconds (default: 10)."""
    try:
        return float(os.environ.get("OPENVIKING_SEARCH_TIMEOUT", "10"))
    except Exception:
        return 10.0


# ---------------------------------------------------------------------------
# Replacement implementations
# ---------------------------------------------------------------------------

def _sync_prefetch(self: OpenVikingMemoryProvider, query: str, *, session_id: str = "") -> str:
    """Synchronously search OpenViking and return ranked context."""
    if not query or not getattr(self, "_client", None):
        return ""

    try:
        httpx = _get_httpx()
        if httpx is None:
            raise ImportError("httpx is required for OpenViking")

        client = _VikingClient(
            self._endpoint,
            self._api_key,
            account=self._account,
            user=self._user,
            agent=self._agent,
        )
        resp = httpx.post(
            client._url("/api/v1/search/find"),
            # OpenViking FindRequest uses ``limit`` (integer, default 10);
            # ``top_k`` is rejected because ``additionalProperties`` is false.
            json={"query": query, "limit": 10},
            headers=client._headers(),
            timeout=_search_timeout(),
        )
        data = client._parse_response(resp)
        result = data.get("result", {}) if isinstance(data, dict) else {}

        parts = []
        for ctx_type in ("memories", "resources"):
            for item in result.get(ctx_type, [])[:3]:
                uri = item.get("uri", "")
                abstract = item.get("abstract", "")
                score = item.get("score", 0)
                if abstract:
                    parts.append(f"- [{score:.2f}] {abstract} ({uri})")

        if not parts:
            return ""
        joined = "\n".join(parts)
        return f"## OpenViking Context\n{joined}"
    except Exception as e:
        logger.warning("OpenViking synchronous prefetch failed: %s", e)
        return ""


def _noop_queue_prefetch(
    self: OpenVikingMemoryProvider, query: str, *, session_id: str = ""
) -> None:
    """No-op replacement for the async queue_prefetch.

    The synchronous recall path no longer needs background预热；this stub
    keeps the ``MemoryProvider`` ABC contract intact.
    """
    return None


def _build_advisory_memory_context_block(raw_context: str) -> str:
    """Wrap prefetched memory in a fenced block with an advisory system note."""
    if not raw_context or not raw_context.strip():
        return ""

    clean = _memory_manager_module.sanitize_context(raw_context)
    if clean != raw_context:
        logger.warning("memory provider returned pre-wrapped context; stripped")

    return (
        "<memory-context>\n"
        "[System note: The following is recalled memory context, "
        "NOT new user input. It may help inform the response, but use it "
        "only when relevant to the user's current message — treat as helpful "
        "hints, not authoritative facts.]\n\n"
        f"{clean}\n"
        "</memory-context>"
    )


# ---------------------------------------------------------------------------
# Patch registration
# ---------------------------------------------------------------------------

def _apply_sync() -> None:
    global _applied
    provider_cls = OpenVikingMemoryProvider
    _originals["prefetch"] = provider_cls.prefetch
    _originals["queue_prefetch"] = provider_cls.queue_prefetch
    provider_cls.prefetch = _sync_prefetch
    provider_cls.queue_prefetch = _noop_queue_prefetch
    _applied["sync"] = True
    logger.info("openviking_sync_recall_patch applied: prefetch")
    logger.info("openviking_sync_recall_patch applied: queue_prefetch")


def _revert_sync() -> None:
    global _applied
    provider_cls = OpenVikingMemoryProvider
    orig_prefetch = _originals.pop("prefetch", None)
    orig_queue_prefetch = _originals.pop("queue_prefetch", None)
    if orig_prefetch is not None:
        provider_cls.prefetch = orig_prefetch
    if orig_queue_prefetch is not None:
        provider_cls.queue_prefetch = orig_queue_prefetch
    _applied["sync"] = False
    logger.info("openviking_sync_recall_patch reverted: prefetch, queue_prefetch")


def _apply_advisory() -> None:
    global _applied
    _originals["build_memory_context_block"] = _memory_manager_module.build_memory_context_block
    _memory_manager_module.build_memory_context_block = _build_advisory_memory_context_block

    # Keep already-imported aliases in sync (e.g. agent.conversation_loop).
    cl = sys.modules.get("agent.conversation_loop")
    if cl is not None:
        cl.build_memory_context_block = _build_advisory_memory_context_block

    _applied["advisory"] = True
    logger.info("openviking_sync_recall_patch applied: build_memory_context_block")


def _revert_advisory() -> None:
    global _applied
    orig = _originals.pop("build_memory_context_block", None)
    if orig is not None:
        _memory_manager_module.build_memory_context_block = orig
        cl = sys.modules.get("agent.conversation_loop")
        if cl is not None:
            cl.build_memory_context_block = orig
    _applied["advisory"] = False
    logger.info("openviking_sync_recall_patch reverted: build_memory_context_block")


def apply_patch(force_sync: bool | None = None, advisory_tone: bool | None = None) -> None:
    """Apply the OpenViking synchronous recall and advisory wording patch.

    Args:
        force_sync: If given, override ``OPENVIKING_SYNC_RECALL``.
        advisory_tone: If given, override ``OPENVIKING_ADVISORY_MEMORY``.
    """
    sync_enabled = _env_bool("OPENVIKING_SYNC_RECALL", True) if force_sync is None else bool(force_sync)
    advisory_enabled = (
        _env_bool("OPENVIKING_ADVISORY_MEMORY", True) if advisory_tone is None else bool(advisory_tone)
    )

    if sync_enabled:
        if not _applied["sync"]:
            _apply_sync()
    else:
        if _applied["sync"]:
            _revert_sync()

    if advisory_enabled:
        if not _applied["advisory"]:
            _apply_advisory()
    else:
        if _applied["advisory"]:
            _revert_advisory()


def revert_patch() -> None:
    """Revert all changes made by :func:`apply_patch`."""
    if _applied["sync"]:
        _revert_sync()
    if _applied["advisory"]:
        _revert_advisory()
