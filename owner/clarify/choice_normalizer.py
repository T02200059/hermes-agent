"""
Choice normalization for clarify tool.

Converts model-provided choices (str or dict) to a canonical
``{"display": str, "key": Optional[str]}`` format.
"""

from typing import Any, Dict, List, Optional


# Maximum number of predefined choices the agent can offer.
# A 5th "Other (type your answer)" option is always appended by the UI.
MAX_CHOICES = 4


# Body field priority used when a model returns a dict for a choice. Some
# models ignore the ``items: {type: string}`` schema and emit ``{key, ...}``
# or ``{label, content}`` shaped objects. We pick the most descriptive field
# available for ``display``; the bare identifier (key/label) is preserved as
# ``key`` so platforms (Feishu) can return a stable ID to the model.
_CHOICE_BODY_FIELDS = ("description", "content", "text", "value", "label", "key")
_CHOICE_ID_FIELDS = ("key", "label")


def normalize_choice(c: Any) -> Optional[Dict[str, Optional[str]]]:
    """Coerce a single choice item to ``{"display": str, "key": str|None}``.

    Returns ``None`` when the item cannot be reduced to a non-empty string
    (caller will skip the item).

    Rules:
    - ``str``  → ``{"display": s, "key": s}`` (key == display, so platforms
      that only need display work and Feishu still gets a clean ID back).
    - ``dict`` → ``display`` is the most descriptive body field, optionally
      prefixed by an identifier as ``"key — body"``; ``key`` is the bare
      identifier or ``None`` if absent.
    - other   → ``str(c)`` for legacy compatibility (int/bool).
    """
    if isinstance(c, str):
        s = c.strip()
        if not s:
            return None
        return {"display": s, "key": s}
    if isinstance(c, dict):
        return render_dict_choice(c)
    s = str(c).strip()
    if not s:
        return None
    return {"display": s, "key": s}


def normalize_choices(choices: Any) -> Optional[List[Dict[str, Optional[str]]]]:
    """Normalize a list of choice items and trim to ``MAX_CHOICES``.

    Items that normalize to empty are dropped. An empty input list returns
    ``None`` so the caller can treat it as open-ended.
    """
    if choices is None:
        return None
    if not isinstance(choices, list):
        return None

    normalized: List[Dict[str, Optional[str]]] = []
    for c in choices:
        pair = normalize_choice(c)
        if pair is not None:
            normalized.append(pair)

    if len(normalized) > MAX_CHOICES:
        normalized = normalized[:MAX_CHOICES]

    if not normalized:
        return None
    return normalized


def render_dict_choice(d: dict) -> Optional[Dict[str, Optional[str]]]:
    """Render a dict-shaped choice into ``{"display": str, "key": str|None}``.

    See ``_CHOICE_BODY_FIELDS`` / ``_CHOICE_ID_FIELDS`` for the field
    priority. Returns ``None`` if the dict has no usable string field.
    """
    identifier = ""
    for k in _CHOICE_ID_FIELDS:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            identifier = v.strip()
            break

    body = ""
    for k in _CHOICE_BODY_FIELDS:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            body = v.strip()
            break

    if not body and not identifier:
        return None

    if identifier and body and body != identifier:
        display = f"{identifier} — {body}"
        return {"display": display, "key": identifier}

    # Only one of (identifier, body) was present → display == whatever we have,
    # and key is None so Feishu falls back to sending display as the value.
    only = body or identifier
    return {"display": only, "key": identifier or None}
