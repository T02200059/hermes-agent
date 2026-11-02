"""[owner] C13 — english explainer (zh UI + English final → notice card)."""

from owner.explainers.english.detect import looks_like_english_reply, looks_like_non_chinese_output
from owner.explainers.english.explain import explain, explain_async
from owner.explainers.english.hook import maybe_explain_english_reply, register_hooks
from owner.explainers.english.prompt import PREFIX, format_delivery

# Alias used by older tests / docs
should_explain = looks_like_english_reply

__all__ = [
    "PREFIX",
    "explain",
    "explain_async",
    "format_delivery",
    "looks_like_english_reply",
    "looks_like_non_chinese_output",
    "maybe_explain_english_reply",
    "register_hooks",
    "should_explain",
]
