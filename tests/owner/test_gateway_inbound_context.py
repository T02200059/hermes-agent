"""Tests for owner.gateway.inbound_context."""

from types import SimpleNamespace

from owner.gateway.inbound_context import append_inbound_context, build_inbound_context_block


def _source(platform: str, **kwargs):
    base = dict(
        platform=SimpleNamespace(value=platform),
        user_id="ou_alice",
        chat_id="oc_chat1",
        user_name="Alice",
        chat_type="dm",
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


class TestBuildInboundContextBlock:
    def test_feishu_returns_block(self):
        block = build_inbound_context_block(_source("feishu"))
        assert block is not None
        assert "open_id: ou_alice" in block

    def test_telegram_returns_none(self):
        assert build_inbound_context_block(_source("telegram")) is None


class TestAppendInboundContext:
    def test_feishu_appends_block(self):
        result = append_inbound_context("hello", _source("feishu"))
        assert result.startswith("hello\n\n---")
        assert "open_id: ou_alice" in result

    def test_non_feishu_unchanged(self):
        assert append_inbound_context("hello", _source("slack")) == "hello"

    def test_empty_message_returns_block_only(self):
        result = append_inbound_context("", _source("feishu"))
        assert result.startswith("---")
        assert "open_id: ou_alice" in result