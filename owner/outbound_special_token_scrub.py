"""[owner] Thin outbound BOS/EOS scrub — reuses official O8 strip.

Final chat replies already go through ``_sanitize_gateway_final_response`` →
``_strip_deepseek_special_tokens`` (O8). Interim / status paths did not; this
module is the single owner entry so ``agent/stream_delivery`` and gateway status
glue stay fail-open one-liners without re-implementing the glyph rules.
"""

from __future__ import annotations

from typing import Any

__all__ = ["scrub_outbound_text"]


def scrub_outbound_text(text: Any) -> str:
    """Strip leaked DeepSeek BOS/EOS literals; delegates to official O8.

    ``None`` → ``""``. Non-strings are stringified. Pure-specials (+ whitespace)
    become ``""`` so interim/status treat them as no visible content.
    """
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    if not text:
        return text
    from gateway.platforms.base import _strip_deepseek_special_tokens

    return _strip_deepseek_special_tokens(text)
