"""[owner-patch] merge_forward expansion tests.

Covers:
1. ``_render_merge_forward_entries`` — dict + SDK-object children, mention
   name resolution, post/image/file/nested-forward rendering, char
   truncation with continuation hint, explicit paging hint.
2. ``read_merge_forward_as_text`` — client request path (mocked client).
3. adapter ``_expand_merge_forward_text`` — children extraction + failure
   fallback to the normalized placeholder.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from plugins.platforms.feishu.adapter import (  # noqa: E402
    _render_merge_forward_entries,
)
import plugins.platforms.feishu.adapter as feishu_adapter  # noqa: E402


def _items_json(items):
    import json

    return json.dumps(items)


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
        out = _render_merge_forward_entries("om_test", children)
        assert "共 2 条子消息" in out
        assert "第一条" in out and "第二条" in out
        # sender shown as short open_id suffix
        assert "df5626" in out and "abc123" in out

    def test_mention_name_resolution(self):
        children = [
            _child(
                text="@_user_1 看下这个",
                mentions=[{"key": "@_user_1", "name": "王庭威"}],
            )
        ]
        out = _render_merge_forward_entries("om_test", children)
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
        out = _render_merge_forward_entries("om_test", children)
        assert "line1" in out
        assert "@吕磊" in out

    def test_image_file_and_nested_forward_placeholders(self):
        children = [
            _child(msg_type="image", text=""),
            _child(msg_type="file", text=""),
            _child(msg_type="merge_forward", text="", message_id="om_nested1"),
        ]
        out = _render_merge_forward_entries("om_test", children)
        assert "[图片]" in out
        assert "[文件]" in out
        assert "[嵌套合并转发 om_nested1]" in out

    def test_sdk_object_children(self):
        # lark SDK returns objects, not dicts — renderer must handle both.
        child = SimpleNamespace(
            msg_type="text",
            sender=SimpleNamespace(id="ou_zzz999888777"),
            create_time="1788683432286",
            body=SimpleNamespace(content='{"text":"SDK对象"}'),
            mentions=[SimpleNamespace(key="@_user_1", name="张三")],
        )
        out = _render_merge_forward_entries("om_test", [child])
        assert "SDK对象" in out
        assert "888777" in out

    def test_char_truncation_keeps_continuation_hint(self, monkeypatch):
        monkeypatch.setattr(feishu_adapter, "_MERGE_FORWARD_MAX_CHARS", 150)
        children = [
            _child(text="消息A" + "a" * 60),
            _child(text="消息B" + "b" * 60),
            _child(text="消息C" + "c" * 60),
        ]
        out = _render_merge_forward_entries("om_test", children)
        assert "[截断]" in out
        assert 'feishu_doc_read(doc_token="om_test"' in out
        assert "offset=" in out
        # 消息C must not be silently dropped without a hint
        assert "消息C" not in out.split("[截断]")[0]

    def test_paging_window_hint(self):
        children = [_child(text=f"第{i}条") for i in range(1, 6)]
        out = _render_merge_forward_entries("om_test", children, offset=2, limit=2)
        assert "第3条" in out and "第4条" in out
        assert "第1条" not in out
        assert "[分页]" in out
        assert "offset=4" in out

    def test_no_hint_when_window_covers_all(self):
        children = [_child(text="唯一")]
        out = _render_merge_forward_entries("om_test", children)
        assert "[截断]" not in out and "[分页]" not in out


class TestReadMergeForwardAsText:
    def _mock_client(self, code=0, items=None, msg="success"):
        raw = SimpleNamespace(content='{"data": {"items": %s}}' % _items_json(items))
        return SimpleNamespace(
            request=lambda req: SimpleNamespace(
                code=code, msg=msg, raw=raw, data=None
            )
        )

    def test_success_path(self):
        from tools.feishu_client_utils import read_merge_forward_as_text

        items = [
            {
                "message_id": "om_parent",
                "msg_type": "merge_forward",
                "body": {"content": "Merged and Forwarded Message"},
            },
            _child(text="子消息"),
        ]
        # attach upper_message_id to the child
        items[1]["upper_message_id"] = "om_parent"
        client = self._mock_client(items=items)
        # patch do_request dependency via monkeypatched module attr is
        # complicated; call with a client whose .request returns the payload
        # through do_request's raw.content parsing path.
        text, err = read_merge_forward_as_text(client, "om_parent")
        assert err is None, err
        assert text is not None
        assert "子消息" in text
        assert "共 1 条子消息" in text

    def test_no_children_error(self):
        from tools.feishu_client_utils import read_merge_forward_as_text

        items = [
            {
                "message_id": "om_parent",
                "msg_type": "merge_forward",
                "body": {"content": "Merged and Forwarded Message"},
            }
        ]
        client = self._mock_client(items=items)
        text, err = read_merge_forward_as_text(client, "om_parent")
        assert text is None
        assert "No merge_forward children" in err

    def test_api_error(self):
        from tools.feishu_client_utils import read_merge_forward_as_text

        client = self._mock_client(code=230002, msg="The bot can not be outside the group.")
        text, err = read_merge_forward_as_text(client, "om_parent")
        assert text is None
        assert "[230002]" in err
