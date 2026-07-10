"""Shared Xiaomi MiMo thinking wire format.

Official MiMo (``mimo-v2.5`` / ``mimo-v2.5-pro``) controls deep thinking via
``extra_body.thinking.type`` = ``enabled`` | ``disabled`` (default enabled).
There is no ``thinking: adaptive``. Multi-turn tool-call turns must also echo
``reasoning_content`` (handled elsewhere in the agent runtime).

``reasoning_effort`` (``low`` / ``medium`` / ``high``) is optional and may be
ignored by the official server; relays/proxies that accept it get a clamped
value so Hermes' richer effort scale does not 400.

Used by both the direct ``xiaomi`` provider and the ``damodel`` NewAPI proxy
when routing MiMo models (same upstream protocol).
"""

from __future__ import annotations

import re
from typing import Any

# MiMo chat models only — TTS / ASR / voice* do not support thinking.
_MIMO_CHAT_RE = re.compile(r"^mimo(?!.*(?:tts|asr|voice))", re.IGNORECASE)


def is_mimo_thinking_model(model: str | None) -> bool:
    """True for MiMo chat models that accept ``thinking.type``.

    Matches ``mimo-v2.5``, ``mimo-v2.5-pro`` (and future ``mimo-*`` chat ids).
    Excludes TTS / ASR / voice-design / voice-clone variants which reject
    the thinking field per Xiaomi docs.
    """
    m = (model or "").strip()
    return bool(m and _MIMO_CHAT_RE.match(m))


def build_mimo_thinking_extras(
    *,
    reasoning_config: dict | None = None,
    model: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Map Hermes ``reasoning_config`` onto MiMo's OpenAI-compat wire shape.

    Returns ``(extra_body, top_level)``:
      * ``extra_body["thinking"] = {"type": "enabled"|"disabled"}`` always
        when the model supports thinking (explicit disable is required —
        omitting the field leaves the server default of enabled).
      * ``top_level["reasoning_effort"]`` only when an effort preference is
        set and thinking is enabled; clamped to low/medium/high.
    """
    extra_body: dict[str, Any] = {}
    top_level: dict[str, Any] = {}

    if not is_mimo_thinking_model(model):
        return extra_body, top_level

    enabled = True
    if isinstance(reasoning_config, dict) and reasoning_config.get("enabled") is False:
        enabled = False

    extra_body["thinking"] = {"type": "enabled" if enabled else "disabled"}

    if not enabled:
        return extra_body, top_level

    if not isinstance(reasoning_config, dict):
        return extra_body, top_level

    effort = (reasoning_config.get("effort") or "").strip().lower()
    if not effort or effort == "none":
        return extra_body, top_level

    # Official docs only document thinking.type; effort is best-effort for
    # relays. Clamp Hermes extras (xhigh/max/minimal) onto low|medium|high.
    if effort in {"xhigh", "max"}:
        top_level["reasoning_effort"] = "high"
    elif effort == "minimal":
        top_level["reasoning_effort"] = "low"
    elif effort in {"low", "medium", "high"}:
        top_level["reasoning_effort"] = effort

    return extra_body, top_level
