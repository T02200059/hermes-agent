"""[owner] Outbound scrub of leaked DeepSeek-style special tokens (BOS/EOS).

Some upstream decoders occasionally emit tokenizer control tokens as visible
assistant text. Hermes then delivers that text to chat surfaces (final reply
and ``interim_assistant_messages``). This module strips those literals at the
outbound boundary.

Matching is by token literal only (no provider / model gate): the DeepSeek
BOS/EOS glyph sequence is specific enough that false positives are negligible,
and avoiding a provider gate keeps the official glue to a one-line fail-open
delegate.
"""

from __future__ import annotations

import re
from typing import Any

# DeepSeek chat-template specials (fullwidth ｜ + SentencePiece ▁).
_BOS = "<｜begin▁of▁sentence｜>"
_EOS = "<｜end▁of▁sentence｜>"
_TOKEN_RE = re.compile(re.escape(_BOS) + "|" + re.escape(_EOS))


def scrub_outbound_text(text: Any) -> str:
    """Strip leaked BOS/EOS literals from outbound text.

    ``None`` → ``""``. Non-strings are stringified. If the payload is only
    specials (+ whitespace), return ``""`` so interim/final paths treat it as
    no visible content. Does not raise on normal inputs.
    """
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    if not text:
        return text
    if _BOS not in text and _EOS not in text:
        return text
    cleaned = _TOKEN_RE.sub("", text)
    if not cleaned.strip():
        return ""
    return cleaned


__all__ = ["scrub_outbound_text"]
