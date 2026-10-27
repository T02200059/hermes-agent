"""C12-merge-forward-recv — merge_forward renderer + adapter expansion."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from owner.feishu import merge_forward as mf
from owner.feishu.merge_forward import render_merge_forward_entries


def _child(msg_type="text", text="hello", sender="ou_df5626", ts="1788683432286", **extra):
    body = {"content": f'{{"text":"{text}"}}'}
    if msg_type == "post":
        body = {
            "content": (
                '{"title":"t","content":[[{"tag":"text","text":"line1"},'
                '{"tag":"at","user_id":"ou_111111111111111"}]]}'
            )
        }
    base = {
        "msg_type": msg_type,
        "sender": {"id": sender},
        "create_time": ts,
        "body": body,
    }
    base.update(extra)
    return base


class TestRenderMergeForwardEntries:
    def test_basic_transcript(self):
        children = [
            _child(text="第一条"),
            _child(text="第二条", sender="ou_abc123"),
        ]
        out = render_merge_forward_entries("om_test", children)
        assert "共 2 条子消息" in out
        assert "第一条" in out and "第二条" in out
        assert "df5626" in out and "abc123" in out

    def test_mention_name_resolution(self):
        children = [
            _child(
                text="@_user_1 看下这个",
                mentions=[{"key": "@_user_1", "name": "王庭威"}],
            )
        ]
        out = render_merge_forward_entries("om_test", children)
        assert "@王庭威" in out
        assert "@_user_1" not in out

    def test_post_message_rendered(self):
        children = [
            _child(
                msg_type="post",
                mentions=[
                    {"key": "@_user_1", "id": "ou_111111111111111", "name": "吕磊"}
                ],
            )
        ]
        out = render_merge_forward_entries("om_test", children)
        assert "line1" in out
        assert "@吕磊" in out

    def test_image_file_and_nested_forward_placeholders(self):
        children = [
            _child(msg_type="image", text=""),
            _child(msg_type="file", text=""),
            _child(msg_type="merge_forward", text="", message_id="om_nested1"),
        ]
        out = render_merge_forward_entries("om_test", children)
        assert "[图片]" in out
        assert "[文件]" in out
        assert "[嵌套合并转发 om_nested1]" in out

    def test_sdk_object_children(self):
        child = SimpleNamespace(
            msg_type="text",
            sender=SimpleNamespace(id="ou_zzz999888777"),
            create_time="1788683432286",
            body=SimpleNamespace(content='{"text":"SDK对象"}'),
            mentions=[SimpleNamespace(key="@_user_1", name="张三")],
        )
        out = render_merge_forward_entries("om_test", [child])
        assert "SDK对象" in out
        assert "888777" in out

    def test_char_truncation_keeps_continuation_hint(self, monkeypatch):
        monkeypatch.setattr(mf, "MERGE_FORWARD_MAX_CHARS", 150)
        children = [
            _child(text="消息A" + "a" * 60),
            _child(text="消息B" + "b" * 60),
            _child(text="消息C" + "c" * 60),
        ]
        out = render_merge_forward_entries("om_test", children)
        assert "[截断]" in out
        assert 'feishu_doc_read(doc_token="om_test"' in out
        assert "offset=" in out
        assert "消息C" not in out.split("[截断]")[0]

    def test_paging_window_hint(self):
        children = [_child(text=f"第{i}条") for i in range(1, 6)]
        out = render_merge_forward_entries("om_test", children, offset=2, limit=2)
        assert "第3条" in out and "第4条" in out
        assert "第1条" not in out
        assert "[分页]" in out
        assert "offset=4" in out

    def test_no_hint_when_window_covers_all(self):
        children = [_child(text="唯一")]
        out = render_merge_forward_entries("om_test", children)
        assert "[截断]" not in out and "[分页]" not in out


@pytest.mark.asyncio
class TestExpandMergeForwardText:
    async def test_expands_children(self):
        from plugins.platforms.feishu.adapter import FeishuAdapter

        adapter = FeishuAdapter.__new__(FeishuAdapter)
        adapter._client = MagicMock()
        child = SimpleNamespace(
            upper_message_id="om_parent",
            msg_type="text",
            sender=SimpleNamespace(id="ou_df5626"),
            create_time="1788683432286",
            body=SimpleNamespace(content='{"text":"展开成功"}'),
            mentions=[],
            message_id="om_child1",
        )
        parent = SimpleNamespace(upper_message_id="", message_id="om_parent")
        response = MagicMock()
        response.success = lambda: True
        response.data = SimpleNamespace(items=[parent, child])
        adapter._run_blocking = AsyncMock(return_value=response)
        adapter._build_get_message_request = MagicMock(return_value=object())

        out = await adapter._expand_merge_forward_text("om_parent")
        assert out is not None
        assert "展开成功" in out
        assert "共 1 条子消息" in out

    async def test_failure_returns_none(self):
        from plugins.platforms.feishu.adapter import FeishuAdapter

        adapter = FeishuAdapter.__new__(FeishuAdapter)
        adapter._client = MagicMock()
        response = MagicMock()
        response.success = lambda: False
        response.code = 230002
        response.msg = "outside group"
        adapter._run_blocking = AsyncMock(return_value=response)
        adapter._build_get_message_request = MagicMock(return_value=object())

        out = await adapter._expand_merge_forward_text("om_parent")
        assert out is None

    async def test_no_client_returns_none(self):
        from plugins.platforms.feishu.adapter import FeishuAdapter

        adapter = FeishuAdapter.__new__(FeishuAdapter)
        adapter._client = None
        assert await adapter._expand_merge_forward_text("om_parent") is None
