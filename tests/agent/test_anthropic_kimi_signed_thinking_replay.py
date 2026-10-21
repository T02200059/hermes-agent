"""Kimi-family endpoints don't need thinking blocks stripped on replay; DeepSeek does.

Contract source (retrieved 2026-10-21, platform.kimi.com ``api/messages`` +
``guide/use-thinking-models``):

* The Messages-compatible response schema carries reasoning as
  ``{"type": "thinking", "thinking": "<string>", "signature": "<string>"}`` —
  Kimi's endpoint **does** emit a signature, so it is not a signature-less
  third party.
* Preserved thinking is mandatory, not best-effort: "必须把 API 返回的完整
  assistant message 原样回传到 ``messages``"; for ``kimi-k2.7-code`` it is
  always on — "必须（而非可选）把历史轮次 assistant 消息的 ``reasoning_content``
  原样保留在 ``messages`` 中".

So on Kimi hosts the signed thinking block replays **as-is**: stripping it would
drop reasoning the endpoint requires, and a signature we cannot validate is not
ours to second-guess. An empty/absent signature still replays as an (unsigned)
thinking block — the reasoning text is what the contract protects.

An earlier owner rewrite inverted every assertion here to "third-party endpoints
strip signed thinking", contradicting both the endpoint's own response schema and
the verbatim-replay requirement above. The product behaviour was already correct;
the inverted tests were the defect. Restored per the documentation.
"""

from types import SimpleNamespace

from agent.transports import get_transport
from agent.anthropic_message_convert import convert_messages_to_anthropic

SIG = "sig-k3"

KIMI = "https://api.kimi.com/coding"
MOONSHOT = "https://api.moonshot.cn/anthropic"
DEEPSEEK = "https://api.deepseek.com/anthropic"


def _thinking_on_replay(base_url, signature=SIG, model="k3"):
    """Normalize a thinking+text turn, store it, convert to the next-turn request,
    and return its thinking blocks."""
    response = SimpleNamespace(
        content=[
            SimpleNamespace(type="thinking", thinking="five: 5 11 27 63 88", signature=signature),
            SimpleNamespace(type="text", text="5 27 88"),
        ],
        stop_reason="end_turn",
        usage=None,
    )
    normalized = get_transport("anthropic_messages").normalize_response(response)
    stored = {
        "role": "assistant",
        "content": normalized.content or "",
        "reasoning_details": (normalized.provider_data or {}).get("reasoning_details"),
    }
    messages = [
        {"role": "user", "content": "q1"},
        stored,
        {"role": "user", "content": "q2"},
    ]
    _sys, out = convert_messages_to_anthropic(messages, base_url=base_url, model=model)
    assistant = [m for m in out if m.get("role") == "assistant"][0]
    return [b for b in assistant["content"] if isinstance(b, dict) and b.get("type") == "thinking"]






def test_kimi_coding_keeps_signed_thinking():
    """``api.kimi.com/coding`` is Kimi's own Anthropic-compatible host (Claude Code route)."""
    thinking = _thinking_on_replay(KIMI)
    assert thinking and thinking[0].get("signature") == SIG


def test_moonshot_keeps_signed_thinking():
    thinking = _thinking_on_replay(MOONSHOT)
    assert thinking and thinking[0].get("signature") == SIG




def test_kimi_model_name_on_foreign_gateway_keeps_thinking():
    """A Kimi-family model slug replayed through a non-Kimi gateway hostname
    keeps its thinking blocks — upstream Kimi still enforces its replay
    semantics no matter what host fronts it (hermes-agent#13848, #17057).
    Covers both the named and bare Coding Plan slugs, and an unsigned block
    (the reasoning text survives even when no signature was ever issued)."""
    for model in ("kimi-k2.5", "k3"):
        assert _thinking_on_replay(DEEPSEEK, model=model), model
        assert _thinking_on_replay(DEEPSEEK, signature="", model=model), model


def test_direct_anthropic_keeps_signed_on_latest():
    """Native Anthropic validates signatures, so a signed block replays untouched."""
    assert _thinking_on_replay(None, model="claude-sonnet-4-20250514")




def test_orphan_tool_turn_demotes_and_leaks_no_internal_marker():
    """Signed thinking + parallel tool batch interrupted mid-flight (one orphan):
    the internal _thinking_signature_invalidated marker must be popped —
    never leak into the Kimi payload — while the thinking block itself
    replays as-is (Kimi does not enforce signatures)."""
    response = SimpleNamespace(
        content=[
            SimpleNamespace(type="thinking", thinking="plan both reads", signature=SIG),
            SimpleNamespace(type="tool_use", id="toolu_1", name="read_file", input={"path": "a.py"}),
            SimpleNamespace(type="tool_use", id="toolu_2", name="read_file", input={"path": "b.py"}),
        ],
        stop_reason="tool_use",
        usage=None,
    )
    normalized = get_transport("anthropic_messages").normalize_response(response)
    provider_data = normalized.provider_data or {}
    stored = {
        "role": "assistant",
        "content": normalized.content or "",
        "reasoning_details": provider_data.get("reasoning_details"),
        "tool_calls": [
            {"id": tc.id, "type": "function", "function": {"name": tc.name, "arguments": tc.arguments}}
            for tc in (normalized.tool_calls or [])
        ],
    }
    if provider_data.get("anthropic_content_blocks"):
        stored["anthropic_content_blocks"] = provider_data["anthropic_content_blocks"]
    messages = [
        {"role": "user", "content": "inspect both"},
        stored,
        {"role": "tool", "tool_call_id": "toolu_1", "content": "a.py: ok"},
        # toolu_2 interrupted: no tool result follows (orphan)
        {"role": "user", "content": "continue"},
    ]
    _sys, out = convert_messages_to_anthropic(messages, base_url=KIMI, model="k3")
    assistant = [m for m in out if m.get("role") == "assistant"][0]
    assert "_thinking_signature_invalidated" not in assistant, (
        f"internal marker leaked into Kimi payload: {assistant.keys()}"
    )
    types = [b.get("type") for b in assistant["content"] if isinstance(b, dict)]
    assert "thinking" in types, (
        "Kimi does not enforce signatures — even orphan-invalidated blocks "
        f"must replay as-is: {types}"
    )
