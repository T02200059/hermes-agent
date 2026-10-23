"""C08: interim BOS/EOS scrub — thin wrap of official O8 + stream_delivery hang."""

from __future__ import annotations

_BOS = "<｜begin▁of▁sentence｜>"
_EOS = "<｜end▁of▁sentence｜>"


def test_scrub_strips_bos_eos_mid_and_edges():
    from owner.outbound_special_token_scrub import scrub_outbound_text

    assert scrub_outbound_text(_BOS + "你好" + _EOS) == "你好"
    assert scrub_outbound_text("前" + _EOS + "后") == "前后"
    assert scrub_outbound_text("普通旁白") == "普通旁白"


def test_scrub_pure_specials_become_empty():
    from owner.outbound_special_token_scrub import scrub_outbound_text

    assert scrub_outbound_text(_BOS + _EOS) == ""
    assert scrub_outbound_text(_EOS + "\n") == ""
    assert scrub_outbound_text(None) == ""


def test_stream_delivery_interim_scrub_before_callback():
    """Interim emit path must scrub before interim_assistant_callback (stream_consumer bypasses status prepare)."""
    from agent.stream_delivery import StreamDeliveryMixin

    class _Agent(StreamDeliveryMixin):
        pass

    agent = _Agent()
    agent._delivered_interim_texts = set()
    agent.show_commentary = True
    agent._strip_think_blocks = lambda text: text  # mixin normally from AIAgent
    seen: list[str] = []

    def _cb(text: str, *, already_streamed: bool = False) -> None:
        seen.append(text)

    agent.interim_assistant_callback = _cb
    agent._fire_streamed_codex_commentary(_BOS + "中间旁白" + _EOS)
    assert seen == ["中间旁白"]

    seen.clear()
    agent._fire_streamed_codex_commentary(_BOS + _EOS)
    assert seen == []  # pure specials → no delivery
