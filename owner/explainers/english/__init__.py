"""[owner] C13 — english explainer (zh UI + English final → notice card)."""

from owner.explainers.english.detect import looks_like_english_reply
from owner.explainers.english.explain import explain, explain_async
from owner.explainers.english.hook import maybe_explain_english_reply, register_hooks
from owner.explainers.english.prompt import PREFIX, format_delivery

# Alias used by older tests / docs
should_explain = looks_like_english_reply

__all__ = [
    "looks_like_english_reply",
    "should_explain",
    "explain",
    "explain_async",
    "maybe_explain_english_reply",
    "register_hooks",
    "PREFIX",
    "format_delivery",
]
