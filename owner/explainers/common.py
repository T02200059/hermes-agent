"""[owner] C13 — shared coerce / platform helpers for explainers."""

from __future__ import annotations

from typing import Any

# Designed for auxiliary models with ≥256k context; input budget defaults to 64k chars.
# Kinds may override via explainers.<kind>.max_input_chars or shared explainers.max_input_chars.
DEFAULT_MAX_INPUT_CHARS = 64000


def coerce_bool(val: Any, default: bool) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        low = val.strip().lower()
        if low in {"true", "yes", "1", "on"}:
            return True
        if low in {"false", "no", "0", "off"}:
            return False
        return default
    if isinstance(val, int):
        return val != 0
    return default


def coerce_int(val: Any, default: int, minimum: int = 0) -> int:
    try:
        n = int(val)
    except (TypeError, ValueError):
        return default
    return max(minimum, n)


def norm_model_field(val: Any) -> str:
    """provider/model: ``auto`` / empty → '' (call_llm auxiliary auto chain)."""
    s = str(val or "").strip()
    if s.lower() == "auto":
        return ""
    return s


def normalize_platform(platform: Any) -> str:
    """``Platform.FEISHU`` / ``feishu`` / enum → lowercase short name."""
    if platform is None:
        return ""
    if hasattr(platform, "value"):
        platform = getattr(platform, "value", platform)
    p = str(platform or "").strip().lower()
    if "." in p:
        p = p.split(".")[-1]
    return p


def display_language() -> str:
    """``display.language`` short code; default ``zh`` on failure."""
    try:
        from hermes_cli.i18n import get_language

        lang = str(get_language() or "").strip().lower()
        if lang:
            return lang
    except Exception:
        pass
    try:
        from agent.i18n import get_language

        lang = str(get_language() or "").strip().lower()
        if lang:
            return lang
    except Exception:
        pass
    return "zh"


def display_language_is_chinese() -> bool:
    return display_language().startswith("zh")


def clip_input(text: Any, limit: int = DEFAULT_MAX_INPUT_CHARS) -> str:
    """Clip prompt *input* to ``limit`` characters (default shared 64k).

    Prefer keeping the **tail** when truncating long transcripts so recent turns survive.
    ``limit <= 0`` means no clip (return full string). When truncating, the omission
    marker is counted inside the budget so the returned string stays ≤ ``limit``.
    """
    if text is None:
        return ""
    s = str(text)
    if limit is None:
        return s
    try:
        n = int(limit)
    except (TypeError, ValueError):
        n = DEFAULT_MAX_INPUT_CHARS
    if n <= 0:
        return s
    if len(s) <= n:
        return s
    omitted = len(s) - n
    marker = f"…（已省略开头约 {omitted} 字）\n"
    if len(marker) >= n:
        return s[-n:]
    body_budget = n - len(marker)
    return marker + s[-body_budget:]

# ---------------------------------------------------------------------------
# Outbound route: keep Feishu topic cards in the topic (not the parent chat).
# ---------------------------------------------------------------------------

def coerce_session_source(raw: Any) -> Any:
    """Accept SessionSource, a dict, or None. Never promote ``root_id`` to thread_id."""
    if raw is None:
        return None
    if isinstance(raw, dict):
        class _Src:
            pass

        src = _Src()
        src.platform = raw.get("platform")
        src.chat_id = raw.get("chat_id")
        # Native topic id only — quoted replies also have root_id, which is not a topic.
        src.thread_id = raw.get("thread_id")
        src.message_id = raw.get("message_id")
        src.reply_to_message_id = raw.get("reply_to_message_id")
        return src
    return raw


def native_thread_id(source: Any) -> str:
    """SessionSource.thread_id only (Feishu native topic). Never root_id / quote id."""
    if source is None:
        return ""
    return str(getattr(source, "thread_id", "") or "").strip()


def reply_anchor_from_source(source: Any, event: Any = None) -> str:
    """A message id that already lives in the topic, used as reply_in_thread anchor."""
    candidates = []
    if source is not None:
        candidates.append(getattr(source, "message_id", None))
        candidates.append(getattr(source, "reply_to_message_id", None))
    if event is not None:
        candidates.append(getattr(event, "message_id", None))
        candidates.append(getattr(event, "reply_to_message_id", None))
    for cand in candidates:
        value = str(cand or "").strip()
        if value:
            return value
    return ""


def pack_explainer_route(
    platform: str,
    chat_id: str,
    thread_id: str = "",
    reply_to_message_id: str = "",
) -> tuple[str, str, str, str]:
    return (
        str(platform or ""),
        str(chat_id or ""),
        str(thread_id or ""),
        str(reply_to_message_id or ""),
    )


def unpack_explainer_route(val: Any) -> tuple[str, str, str, str]:
    """Normalize a stored route; older 2-tuples (platform, chat_id) still unpack."""
    if not val:
        return "", "", "", ""
    if isinstance(val, dict):
        return pack_explainer_route(
            str(val.get("platform") or ""),
            str(val.get("chat_id") or ""),
            str(val.get("thread_id") or ""),
            str(val.get("reply_to_message_id") or ""),
        )
    try:
        parts = tuple(val)
    except TypeError:
        return "", "", "", ""
    platform = str(parts[0] or "") if len(parts) > 0 else ""
    chat_id = str(parts[1] or "") if len(parts) > 1 else ""
    thread_id = str(parts[2] or "") if len(parts) > 2 else ""
    reply_to = str(parts[3] or "") if len(parts) > 3 else ""
    return pack_explainer_route(platform, chat_id, thread_id, reply_to)


def send_metadata_for_thread(
    thread_id: str = "",
    reply_to_message_id: str = "",
    *,
    source: Any = None,
    event: Any = None,
) -> dict[str, str] | None:
    """Adapter.send metadata so official outbound stays in a Feishu topic.

    Returns None when there is no native thread_id (main-chat behaviour unchanged).
    """
    tid = str(thread_id or native_thread_id(source) or "").strip()
    if not tid:
        return None
    rid = str(reply_to_message_id or "").strip() or reply_anchor_from_source(source, event)
    meta = {"thread_id": tid}
    if rid:
        meta["reply_to_message_id"] = rid
    return meta
