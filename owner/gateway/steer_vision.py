"""Steer-mode vision enrichment for attached images.

When ``busy_input_mode=steer`` and an inbound event carries ``media_urls``
(e.g. a Feishu photo+text post message), the steer text must be enriched
with vision descriptions before being passed to ``agent.steer()``.

Without this, ``event.media_urls`` are silently discarded — the agent
gets the user's caption but never sees the image content.  This module
is the [owner] extension point called from ``gateway/run.py``'s busy
handler steer branch as a thin delegate.

The enrichment reuses ``GatewayRunner._enrich_message_with_vision``,
which is the same text-mode vision pipeline the normal inbound message
path uses (calls ``vision_analyze_tool`` → ``auxiliary.vision`` model).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def enrich_steer_with_vision(
    runner: Any,
    steer_text: str,
    event: Any,
    session_key: str = "",
) -> str:
    """Enrich steer text with vision descriptions for attached images.

    Args:
        runner:       GatewayRunner instance (provides
                      ``_enrich_message_with_vision``).
        steer_text:   The user's steer payload text (already stripped).
        event:        The inbound MessageEvent (checked for ``media_urls``).
        session_key:  Session key for logging.

    Returns:
        The enriched text (vision descriptions prepended), or the
        original ``steer_text`` if there are no images, the text is
        empty, or enrichment fails.  Never raises — a vision failure
        must not cause the steer itself to be lost.
    """
    media_urls = getattr(event, "media_urls", None) or []
    if not steer_text or not media_urls:
        return steer_text

    # Only vision-eligible image attachments. Voice/audio is handled by
    # STT in _prepare_busy_steer_text; passing .ogg/.mp3 into vision produces
    # noisy failure prefixes and breaks pure-voice steer.
    media_types = getattr(event, "media_types", None) or []
    image_urls: list = []
    for i, url in enumerate(media_urls):
        mt = (media_types[i] if i < len(media_types) else "") or ""
        mt = str(mt).lower()
        low = str(url).lower()
        is_audio = mt.startswith("audio/") or low.endswith(
            (".ogg", ".opus", ".mp3", ".wav", ".m4a", ".aac", ".flac", ".webm")
        )
        if is_audio:
            continue
        image_urls.append(url)
    if not image_urls:
        return steer_text

    try:
        enriched = await runner._enrich_message_with_vision(
            steer_text, image_urls,
        )
        if enriched:
            logger.info(
                "Steer vision enrichment: %d image(s) described for session %s",
                len(image_urls), session_key or "?",
            )
            return enriched
    except Exception as exc:
        logger.warning(
            "Steer vision enrichment failed for session %s, "
            "falling back to plain text: %s",
            session_key or "?", exc,
        )
    return steer_text
