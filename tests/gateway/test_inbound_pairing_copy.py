"""The stranger-facing pairing DM is assembled at call time and runs through ``agent.i18n``.

Upstream's split of ``gateway/run.py`` moved the copy into
``gateway/run_inbound_unauthorized.py`` and left it hard-coded English (a
``pairing_code_reply()`` body plus a module-level ``PAIRING_RATE_LIMITED_REPLY``).
The owner customization is the i18n pass, so the assertions below are about
**behaviour**, not source text:

* what a first-time sender actually receives (byte-exact English, localized Chinese);
* that the language is resolved **per call** — a module-level ``t()`` would freeze
  both the copy and the language at import, and that is observable by flipping the
  language after import and calling again;
* that dropping the constant did not disturb the send/rate-limit bookkeeping around it;
* that the *old* key still serves the monolith call site, which stays live until A4.

The mixin is not on ``GatewayRunner``'s MRO yet, so these tests drive
``GatewayInboundMixin._hm_offer_pairing_code`` through a minimal stand-in rather than
going through ``GatewayRunner`` (which would dispatch to the monolith).
"""
import pytest

import gateway.run_inbound_unauthorized as unauth
from gateway.config import Platform
from gateway.run_inbound import GatewayInboundMixin
from gateway.session import SessionSource

CODE_TTL_HOURS = max(1, unauth.CODE_TTL_SECONDS // 3600)

# The two upstream sentences, written out so catalog drift fails the test instead of
# quietly redefining the expectation.
EN_CODE_REPLY = (
    "Hi! I don't recognize you yet, so I can't reply until the person running this bot "
    "approves you.\n\n"
    "Your pairing code: `ABC123` (valid for 1 hour)\n\n"
    "If you run this bot, open a terminal and run: "
    "`hermes pairing approve telegram ABC123`. "
    "Otherwise send that command to the bot owner. After approval, send your message again."
)
EN_RATE_LIMITED = (
    "Too many pairing requests right now. Wait a few minutes, then send your message again."
)


def _make_source() -> SessionSource:
    return SessionSource(
        platform=Platform.TELEGRAM,
        user_id="u1",
        chat_id="c1",
        user_name="tester",
        chat_type="dm",
    )


class _FakePairingStore:
    """Only what ``_hm_offer_pairing_code`` touches; ``code=None`` models a failed mint."""

    profile = "default"

    def __init__(self, code=None):
        self._code = code
        self.rate_limits: list[tuple[str, str]] = []

    def _is_rate_limited(self, platform_name, user_id) -> bool:
        return False

    def generate_code(self, platform_name, user_id, user_name):
        return self._code

    def _record_rate_limit(self, platform_name, user_id) -> None:
        self.rate_limits.append((platform_name, user_id))


class _FakeAdapter:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    async def send(self, chat_id, text) -> None:
        self.sent.append((chat_id, text))


class _InboundRunner(GatewayInboundMixin):
    def __init__(self, store, adapter):
        self._store = store
        self._adapter = adapter

    def _pairing_store_for(self, source):
        return self._store

    def _delivery_adapter_for(self, source):
        return self._adapter


async def _offer(store, adapter) -> list[tuple[str, str]]:
    """Send one offer and return only what *this* call put on the wire."""
    before = len(adapter.sent)
    await GatewayInboundMixin._hm_offer_pairing_code(_InboundRunner(store, adapter), _make_source())
    return adapter.sent[before:]


# --------------------------------------------------------------------------- English copy

@pytest.mark.asyncio
async def test_pairing_code_dm_is_the_upstream_sentence(monkeypatch):
    """A first-time sender gets the upstream text verbatim, with the minted code inlined."""
    monkeypatch.setenv("HERMES_LANGUAGE", "en")
    store, adapter = _FakePairingStore(code="ABC123"), _FakeAdapter()

    sent = await _offer(store, adapter)

    assert [text for _, text in sent] == [EN_CODE_REPLY]
    assert store.rate_limits == []


@pytest.mark.asyncio
async def test_rate_limited_dm_is_the_upstream_sentence(monkeypatch):
    """No code to mint ⇒ the rate-limit sentence, and the rate limit is actually recorded."""
    monkeypatch.setenv("HERMES_LANGUAGE", "en")
    store, adapter = _FakePairingStore(code=None), _FakeAdapter()

    sent = await _offer(store, adapter)

    assert [text for _, text in sent] == [EN_RATE_LIMITED]
    assert store.rate_limits == [("telegram", "u1")], "rate limit must be stamped for the silence"


@pytest.mark.asyncio
async def test_rate_limiting_sender_sends_nothing(monkeypatch):
    """The pre-existing guard still short-circuits before any copy is assembled."""
    monkeypatch.setenv("HERMES_LANGUAGE", "en")
    store, adapter = _FakePairingStore(code="ABC123"), _FakeAdapter()
    store._is_rate_limited = lambda *_: True

    assert await _offer(store, adapter) == []


# --------------------------------------------------------------------------- call-time language

@pytest.mark.asyncio
async def test_language_is_resolved_per_call_not_at_import(monkeypatch):
    """Flip the language *after* import: the copy must follow.

    A module-level ``t()`` (upstream's ``PAIRING_RATE_LIMITED_REPLY`` shape) would have
    frozen both the sentence and the language when the module was first imported, so the
    second call would still answer in English.
    """
    monkeypatch.setenv("HERMES_LANGUAGE", "en")
    store, adapter = _FakePairingStore(code=None), _FakeAdapter()
    english = (await _offer(store, adapter))[0][1]

    monkeypatch.setenv("HERMES_LANGUAGE", "zh")
    chinese = (await _offer(store, adapter))[0][1]

    assert english == EN_RATE_LIMITED
    assert chinese != english
    assert "{" not in chinese and "}" not in chinese, f"unformatted placeholder: {chinese!r}"
    assert chinese.startswith("当前配对请求过多")


@pytest.mark.asyncio
async def test_pairing_code_dm_is_localized_with_the_hours_placeholder(monkeypatch):
    """The Chinese entry phrases the TTL itself instead of embedding the English ``1 hour``."""
    monkeypatch.setenv("HERMES_LANGUAGE", "zh")
    store, adapter = _FakePairingStore(code="ABC123"), _FakeAdapter()

    text = (await _offer(store, adapter))[0][1]

    assert "{" not in text and "}" not in text, f"unformatted placeholder: {text!r}"
    assert f"{CODE_TTL_HOURS} 小时" in text
    assert "ABC123" in text
    assert "hermes pairing approve telegram ABC123" in text


@pytest.mark.asyncio
async def test_a_longer_ttl_picks_the_plural_entry_and_localizes_the_unit(monkeypatch):
    """The unit lives in the catalog, so a 2-hour TTL stays "2 hours" in English and "2 小时" in Chinese."""
    monkeypatch.setattr(unauth, "CODE_TTL_SECONDS", 7200)

    monkeypatch.setenv("HERMES_LANGUAGE", "en")
    english = (await _offer(_FakePairingStore(code="ABC123"), _FakeAdapter()))[0][1]
    assert "(valid for 2 hours)" in english

    monkeypatch.setenv("HERMES_LANGUAGE", "zh")
    chinese = (await _offer(_FakePairingStore(code="ABC123"), _FakeAdapter()))[0][1]
    assert "（有效期 2 小时）" in chinese


@pytest.mark.asyncio
async def test_profile_arg_reaches_both_catalogs(monkeypatch):
    """A non-default profile keeps its ``-p <profile> `` inside the localized command."""
    monkeypatch.setenv("HERMES_LANGUAGE", "zh")
    store, adapter = _FakePairingStore(code="ABC123"), _FakeAdapter()
    store.profile = "work"

    text = (await _offer(store, adapter))[0][1]

    assert "hermes -p work pairing approve telegram ABC123" in text


# --------------------------------------------------------------------------- monolith still served

@pytest.mark.parametrize("lang", ["en", "zh"])
def test_old_unrecognized_key_still_renders_for_the_monolith(lang):
    """``gateway.pairing.unrecognized`` keeps the monolith's placeholder shape.

    The monolith is still live until A4 and calls it with ``code`` / ``profile_arg`` /
    ``platform_name``; changing the value in place to upstream's new sentence (whose
    placeholders differ) would make ``str.format`` fail and show the raw template.
    """
    from agent.i18n import t

    value = t("gateway.pairing.unrecognized", lang=lang, code="ABC123", profile_arg="", platform_name="telegram")

    assert not value.startswith("gateway."), "key missing from the catalog"
    assert "{" not in value and "}" not in value, f"unformatted placeholder: {value!r}"
    assert "ABC123" in value
