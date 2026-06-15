"""Tests for owner.feishu.inbound_context."""

from types import SimpleNamespace

from owner.feishu.inbound_context import build_feishu_inbound_context_block


def _source(**kwargs):
    base = dict(
        platform=SimpleNamespace(value="feishu"),
        user_id="ou_alice",
        chat_id="oc_chat1",
        user_name="杨天宝",
        chat_type="dm",
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


class TestBuildFeishuInboundContextBlock:
    def test_includes_open_id_chat_id_and_user_name(self):
        block = build_feishu_inbound_context_block(_source())
        assert "platform: feishu" in block
        assert "user_name: 杨天宝" in block
        assert "open_id: ou_alice" in block
        assert "chat_id: oc_chat1" in block
        assert "chat_type: dm" in block
        assert block.startswith("---")
        assert block.endswith("---")

    def test_group_chat_type(self):
        block = build_feishu_inbound_context_block(_source(chat_type="group"))
        assert "chat_type: group" in block

    def test_returns_none_when_all_fields_empty(self):
        assert build_feishu_inbound_context_block(_source(user_id="", chat_id="", user_name="")) is None

    def test_partial_fields_still_emit_block(self):
        block = build_feishu_inbound_context_block(
            _source(user_name="", user_id="ou_only", chat_id="")
        )
        assert "open_id: ou_only" in block
        assert "user_name:" not in block