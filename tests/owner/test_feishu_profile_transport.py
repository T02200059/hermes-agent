"""Cross-process Feishu profile transport contract tests."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.config import Platform, PlatformConfig
from gateway.platforms.base import MessageEvent, MessageType
from plugins.platforms.feishu.adapter import FeishuAdapter
from gateway.session import SessionSource


@pytest.mark.asyncio
async def test_forward_payload_preserves_full_event_envelope(monkeypatch):
    from owner.feishu import profile_routing

    captured = {}

    class _Response:
        status = 202

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        def post(self, url, **kwargs):
            captured["url"] = url
            captured.update(kwargs)
            return _Response()

    monkeypatch.setattr("aiohttp.ClientSession", _Session)

    accepted = await profile_routing._forward_to_profile_container(
        endpoint="http://profile.test",
        api_key="secret",
        text="",
        open_id="ou_open",
        user_id="u_tenant",
        union_id="on_union",
        chat_id="oc_chat",
        chat_type="group",
        message_id="om_message",
        message_type="photo",
        is_bot=False,
        thread_id="omt_thread",
        reply_to_message_id="om_parent",
        reply_to_text="quoted text",
        raw_message_type="image",
        raw_content='{"image_key":"img_key"}',
        media_expected=True,
    )

    assert accepted is True
    assert captured["url"].endswith("/v1/feishu/inbound")
    body = captured["json"]
    assert body["schema_version"] == 1
    assert body["media_expected"] is True
    assert body["raw_content"] == '{"image_key":"img_key"}'
    assert body["thread_id"] == "omt_thread"
    assert body["reply_to_message_id"] == "om_parent"
    assert body["reply_to_text"] == "quoted text"
    assert body["user_id"] == "u_tenant"
    assert body["union_id"] == "on_union"


@pytest.mark.asyncio
async def test_native_ingress_passes_complete_envelope_to_profile_router(monkeypatch):
    routed = AsyncMock(return_value=True)
    fake = SimpleNamespace(
        _extract_message_content=AsyncMock(
            return_value=(
                "caption",
                MessageType.PHOTO,
                ["/ingress/cache/image.jpg"],
                ["image/jpeg"],
                [],
            )
        ),
        _fetch_message_text=AsyncMock(return_value="quoted text"),
        _user_store=SimpleNamespace(cache_p2p_chat_id=MagicMock(return_value=False)),
    )
    monkeypatch.setattr(
        "plugins.platforms.feishu.adapter._owner_import",
        lambda module, symbol: (
            routed
            if (module, symbol)
            == ("owner.feishu.profile_routing", "try_route_inbound_message")
            else None
        ),
    )
    message = SimpleNamespace(
        chat_id="oc_chat",
        thread_id="omt_thread",
        root_id="om_root",
        parent_id="om_parent",
        upper_message_id=None,
        message_type="image",
        content='{"image_key":"img_key"}',
    )
    sender_id = SimpleNamespace(
        open_id="ou_open",
        user_id="u_tenant",
        union_id="on_union",
    )

    await FeishuAdapter._process_inbound_message(
        fake,
        data=SimpleNamespace(),
        message=message,
        sender_id=sender_id,
        chat_type="group",
        message_id="om_message",
    )

    routed.assert_awaited_once_with(
        fake,
        chat_id="oc_chat",
        open_id="ou_open",
        chat_type="group",
        text="caption",
        message_id="om_message",
        message_type="photo",
        user_id="u_tenant",
        union_id="on_union",
        is_bot=False,
        thread_id="omt_thread",
        reply_to_message_id="om_parent",
        reply_to_text="quoted text",
        raw_message_type="image",
        raw_content='{"image_key":"img_key"}',
        media_expected=True,
    )


def _forwarded_event_adapter(*, extracted=None):
    fake = SimpleNamespace()
    fake.config = SimpleNamespace(extra={})
    fake.get_chat_info = AsyncMock(
        return_value={"name": "Test group", "type": "group"}
    )
    fake._resolve_sender_profile = AsyncMock(
        return_value={
            "user_id": "ou_open",
            "user_name": "Alice",
            "user_id_alt": "on_union",
        }
    )
    fake.build_source = MagicMock(
        side_effect=lambda **kwargs: SessionSource(
            platform=Platform.FEISHU,
            chat_id=kwargs["chat_id"],
            chat_name=kwargs.get("chat_name"),
            chat_type=kwargs["chat_type"],
            user_id=kwargs.get("user_id"),
            user_name=kwargs.get("user_name"),
            user_id_alt=kwargs.get("user_id_alt"),
            thread_id=kwargs.get("thread_id"),
            is_bot=kwargs.get("is_bot", False),
        )
    )
    fake._extract_message_content = AsyncMock(
        return_value=extracted
        or ("", MessageType.PHOTO, ["/child/cache/image.jpg"], ["image/jpeg"], [])
    )
    return fake


@pytest.mark.asyncio
async def test_child_rehydrates_media_and_preserves_thread_reply_context():
    fake = _forwarded_event_adapter()

    event = await FeishuAdapter.build_forwarded_inbound_event(
        fake,
        text="",
        open_id="ou_open",
        user_id="u_tenant",
        union_id="on_union",
        chat_id="oc_chat",
        chat_type="group",
        message_id="om_message",
        message_type="photo",
        thread_id="omt_thread",
        reply_to_message_id="om_parent",
        reply_to_text="quoted text",
        raw_message_type="image",
        raw_content='{"image_key":"img_key"}',
        media_expected=True,
    )

    assert event is not None
    assert event.message_type is MessageType.PHOTO
    assert event.media_urls == ["/child/cache/image.jpg"]
    assert event.media_types == ["image/jpeg"]
    assert event.source.thread_id == "omt_thread"
    assert event.reply_to_message_id == "om_parent"
    assert event.reply_to_text == "quoted text"
    fake._extract_message_content.assert_awaited_once()
    media_message = fake._extract_message_content.await_args.args[0]
    assert media_message.message_id == "om_message"
    assert media_message.content == '{"image_key":"img_key"}'


@pytest.mark.asyncio
async def test_child_rejects_media_without_resource_envelope():
    fake = _forwarded_event_adapter()

    with pytest.raises(ValueError, match="requires message_id"):
        await FeishuAdapter.build_forwarded_inbound_event(
            fake,
            text="",
            open_id="ou_open",
            chat_id="oc_chat",
            chat_type="group",
            message_type="photo",
            media_expected=True,
        )


def _api_adapter():
    return __import__(
        "gateway.platforms.api_server", fromlist=["APIServerAdapter"]
    ).APIServerAdapter(
        PlatformConfig(enabled=True, extra={"key": "strong-test-key-123456"})
    )


@pytest.mark.asyncio
async def test_api_ack_tracks_dispatch_task_until_completion(monkeypatch):
    api = _api_adapter()
    release = asyncio.Event()
    event = MessageEvent(
        text="hello",
        source=SessionSource(
            platform=Platform.FEISHU,
            chat_id="oc_chat",
            user_id="ou_open",
        ),
    )

    class _Feishu:
        build_forwarded_inbound_event = AsyncMock(return_value=event)

        async def _dispatch_inbound_event(self, _event):
            await release.wait()

    feishu = _Feishu()
    monkeypatch.setattr(
        "gateway.platforms.api_server._owner_import",
        lambda _module, symbol: (
            (lambda: feishu) if symbol == "_get_inprocess_feishu_adapter" else None
        ),
    )
    api._check_auth = MagicMock(return_value=None)
    api._read_json_body = AsyncMock(
        return_value=(
            {
                "schema_version": 1,
                "text": "hello",
                "open_id": "ou_open",
                "chat_id": "oc_chat",
                "message_id": "om_message",
                "thread_id": "omt_thread",
            },
            None,
        )
    )

    response = await api._handle_feishu_inbound(SimpleNamespace())
    payload = json.loads(response.text)
    assert response.status == 202
    assert payload == {
        "accepted": True,
        "schema_version": 1,
        "message_id": "om_message",
    }
    assert len(api._background_tasks) == 1
    task = next(iter(api._background_tasks))

    release.set()
    await task
    await asyncio.sleep(0)
    assert api._background_tasks == set()


@pytest.mark.asyncio
async def test_api_observes_and_reaps_post_ack_dispatch_failure(monkeypatch):
    api = _api_adapter()
    event = MessageEvent(
        text="hello",
        source=SessionSource(
            platform=Platform.FEISHU,
            chat_id="oc_chat",
            user_id="ou_open",
        ),
    )

    class _Feishu:
        build_forwarded_inbound_event = AsyncMock(return_value=event)

        async def _dispatch_inbound_event(self, _event):
            raise RuntimeError("dispatch failed")

    feishu = _Feishu()
    monkeypatch.setattr(
        "gateway.platforms.api_server._owner_import",
        lambda _module, symbol: (
            (lambda: feishu) if symbol == "_get_inprocess_feishu_adapter" else None
        ),
    )
    error_log = MagicMock()
    monkeypatch.setattr("gateway.platforms.api_server.logger.error", error_log)
    api._check_auth = MagicMock(return_value=None)
    api._read_json_body = AsyncMock(
        return_value=(
            {
                "schema_version": 1,
                "text": "hello",
                "open_id": "ou_open",
                "chat_id": "oc_chat",
                "message_id": "om_message",
            },
            None,
        )
    )

    response = await api._handle_feishu_inbound(SimpleNamespace())
    assert response.status == 202
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert api._background_tasks == set()
    error_log.assert_called_once()
    assert "forwarded Feishu inbound task failed" in error_log.call_args.args[0]


@pytest.mark.asyncio
async def test_api_does_not_ack_failed_event_preparation(monkeypatch):
    api = _api_adapter()
    feishu = SimpleNamespace(
        build_forwarded_inbound_event=AsyncMock(
            side_effect=RuntimeError("media download failed")
        )
    )
    monkeypatch.setattr(
        "gateway.platforms.api_server._owner_import",
        lambda _module, symbol: (
            (lambda: feishu) if symbol == "_get_inprocess_feishu_adapter" else None
        ),
    )
    api._check_auth = MagicMock(return_value=None)
    api._read_json_body = AsyncMock(
        return_value=(
            {
                "schema_version": 1,
                "text": "",
                "open_id": "ou_open",
                "chat_id": "oc_chat",
                "message_id": "om_message",
                "media_expected": True,
                "raw_message_type": "image",
                "raw_content": '{"image_key":"img_key"}',
            },
            None,
        )
    )

    response = await api._handle_feishu_inbound(SimpleNamespace())
    payload = json.loads(response.text)
    assert response.status == 503
    assert payload["error"]["code"] == "feishu_inbound_admission_failed"
    assert api._background_tasks == set()


@pytest.mark.asyncio
async def test_api_rejects_unknown_inbound_schema_without_dispatch():
    api = _api_adapter()
    api._check_auth = MagicMock(return_value=None)
    api._read_json_body = AsyncMock(
        return_value=({"schema_version": 99, "text": "hello"}, None)
    )

    response = await api._handle_feishu_inbound(SimpleNamespace())
    payload = json.loads(response.text)
    assert response.status == 400
    assert payload["error"]["code"] == "unsupported_schema_version"
    assert api._background_tasks == set()
