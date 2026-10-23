"""Guard: the runtime footer actually renders on Feishu, end to end.

New-baseline owner test (2026-10-23). Not a localization divergence — it pins the
delivery chain this fork depends on.

Why the fork owns it: Feishu replies go out as interactive cards
(``owner/feishu/agent_end.try_auto_card_on_end``, invoked with ``force=True`` so
every reply is a card). The card path returns ``("", "")`` and sets
``already_sent``, which suppresses the downstream plain-text send — so **the card
is the only carrier of the footer**. Two independent gates can empty it, and both
fail silently:

1. ``GatewayRunner._hmwa_runtime_footer_line`` builds the string;
``gateway/runtime_footer.build_footer_line`` returns ``""`` when every configured
field lacks data, and the caller swallows exceptions into ``""`` as well.
2. ``try_auto_card_on_end`` used to pass the footer to the card only when
``response.endswith(footer_line)``; on any mismatch the card was sent with
``footer=""`` — body intact, footer gone, nothing logged.

The observed symptom was exactly that: replies arrived with no footer while the
gateway log read ``response ready: ... response=22 chars`` (the body alone, i.e.
the footer string was empty before any delivery decision).
"""

from __future__ import annotations

import asyncio
import types
from unittest.mock import MagicMock, patch

import pytest

from gateway.config import Platform
from gateway.run import GatewayRunner

# The deployment shape this guards: footer on, model + context % + cwd.
FOOTER_CFG = {
    "display": {"runtime_footer": {"enabled": True, "fields": ["model", "context_pct", "cwd"]}}
}


@pytest.fixture(autouse=True)
def _pin_footer_config(monkeypatch):
    """Pin the config: the pytest env has no ``config.yaml`` at all, and the whole
    point of these cases is the RENDERING, not what this machine happens to set."""
    import gateway.run as gateway_run

    monkeypatch.setattr(gateway_run, "_load_gateway_config", lambda *a, **k: FOOTER_CFG)


def _source():
    return types.SimpleNamespace(platform=Platform.FEISHU, chat_id="oc_test")


@pytest.mark.parametrize(
    "agent_result",
    [
        # Typical Feishu turn: model known, compressor reported a context length.
        {"model": "xy-max", "last_prompt_tokens": 5000, "context_length": 128000},
        # No compressor (cached agent without one): context_pct drops out, model stays.
        {"model": "xy-max", "last_prompt_tokens": 0, "context_length": 0},
        # Model unknown but length known — still a footer, never a bare separator.
        {"last_prompt_tokens": 5000, "context_length": 128000},
    ],
)
def test_runtime_footer_line_is_never_empty_for_a_real_turn(agent_result):
    """A configured footer must render at least one field for a normal turn.

    ``display.runtime_footer`` is enabled with ``model · context_pct · cwd`` in
    this deployment; the failure mode being guarded is the string coming back
    empty so no delivery path has anything to send.
    """
    out = GatewayRunner._hmwa_runtime_footer_line(None, agent_result, _source(), 2.0)
    assert out, f"footer rendered empty for {agent_result!r} — reply loses its footer"
    # Single-field footers are legitimate (e.g. cwd unavailable); what must never
    # happen is a bare separator or a padded line from a field that had no data.
    assert out == out.strip(" ·")


def test_runtime_footer_line_is_gated_by_config(monkeypatch):
    """Disabled config must stay disabled — the guard must not force a footer on."""
    import gateway.run as gateway_run

    monkeypatch.setattr(
        gateway_run,
        "_load_gateway_config",
        lambda *a, **k: {"display": {"runtime_footer": {"enabled": False}}},
    )
    out = GatewayRunner._hmwa_runtime_footer_line(
        None, {"model": "xy-max", "context_length": 128000}, _source(), 1.0
    )
    assert out == ""


def _card_footer_for(response: str, footer_line: str):
    """Run try_auto_card_on_end against a stubbed card sender; return the footer arg."""
    import owner.feishu.agent_end as agent_end

    captured = {}

    async def fake_try_auto_card(adapter, text, meta, **kw):
        captured["text"] = text
        captured["footer"] = kw.get("footer")
        return {"ok": True}

    runner = MagicMock()
    runner.adapters = {Platform.FEISHU: MagicMock()}
    runner._thread_metadata_for_source.return_value = {}
    runner._reply_anchor_for_event.return_value = None

    with patch("owner.feishu.auto_card.try_auto_card", fake_try_auto_card):
        asyncio.run(
            agent_end.try_auto_card_on_end(
                runner=runner,
                source=_source(),
                event=MagicMock(),
                agent_result={"model": "xy-max"},
                response=response,
                footer_line=footer_line,
            )
        )
    return captured


FOOTER = "xy-max · 4% · ~/.hermes"


def test_card_carries_the_footer_after_the_hr_divider():
    """Normal shape: body and footer arrive joined; the card gets them separately."""
    captured = _card_footer_for(f"答案正文\n\n{FOOTER}", FOOTER)
    assert captured["footer"] == FOOTER
    assert captured["text"] == "答案正文"


def test_card_still_carries_the_footer_when_the_suffix_does_not_match():
    """Regression: a reformatted body must not take the footer down with it.

    The card sets ``already_sent``, so a footer dropped here is never re-sent by
    any other path.
    """
    captured = _card_footer_for(f"答案正文\n\n{FOOTER}\n", FOOTER)
    assert captured["footer"] == FOOTER
    assert FOOTER not in captured["text"]


def test_card_carries_the_footer_when_the_body_never_had_it():
    """A caller that forgot to append the footer still gets it rendered once."""
    captured = _card_footer_for("答案正文", FOOTER)
    assert captured["footer"] == FOOTER
    assert captured["text"] == "答案正文"


def test_no_footer_configured_leaves_the_card_untouched():
    captured = _card_footer_for("答案正文", "")
    assert captured["footer"] == ""
    assert captured["text"] == "答案正文"
