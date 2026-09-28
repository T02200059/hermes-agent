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
    assert captured["timeout"].total == 20
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
async def test_child_defer_media_skips_download():
    fake = _forwarded_event_adapter()

    event = await FeishuAdapter.build_forwarded_inbound_event(
        fake,
        text="caption",
        open_id="ou_open",
        chat_id="oc_chat",
        chat_type="group",
        message_id="om_message",
        message_type="photo",
        raw_message_type="image",
        raw_content='{"image_key":"img_key"}',
        media_expected=True,
        defer_media=True,
    )

    assert event is not None
    assert event.text == "caption"
    assert event.media_urls == []
    fake._extract_message_content.assert_not_awaited()


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
async def test_api_acks_before_media_rehydration(monkeypatch):
    api = _api_adapter()
    release = asyncio.Event()
    admitted = MessageEvent(
        text="caption",
        source=SessionSource(
            platform=Platform.FEISHU, chat_id="oc_chat", user_id="ou_open"
        ),
    )
    hydrated = MessageEvent(
        text="caption",
        message_type=MessageType.PHOTO,
        source=admitted.source,
        media_urls=["/child/cache/image.jpg"],
        media_types=["image/jpeg"],
    )
    dispatched = []

    class _Feishu:
        async def build_forwarded_inbound_event(self, **kwargs):
            if kwargs.get("defer_media"):
                return admitted
            await release.wait()
            return hydrated

        async def _dispatch_inbound_event(self, event):
            dispatched.append(event)

    monkeypatch.setattr(
        "gateway.platforms.api_server._owner_import",
        lambda _module, symbol: (
            (lambda: _Feishu())
            if symbol == "_get_inprocess_feishu_adapter"
            else None
        ),
    )
    api._check_auth = MagicMock(return_value=None)
    api._read_json_body = AsyncMock(
        return_value=(
            {
                "schema_version": 1,
                "text": "caption",
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
    assert response.status == 202
    assert dispatched == []
    release.set()
    task = next(iter(api._background_tasks))
    await task
    await asyncio.sleep(0)
    assert dispatched == [hydrated]


@pytest.mark.asyncio
async def test_api_media_only_rehydration_failure_does_not_dispatch(monkeypatch):
    api = _api_adapter()
    admitted = MessageEvent(
        text="",
        source=SessionSource(
            platform=Platform.FEISHU, chat_id="oc_chat", user_id="ou_open"
        ),
    )
    dispatched = []

    class _Feishu:
        async def build_forwarded_inbound_event(self, **kwargs):
            if kwargs.get("defer_media"):
                return admitted
            raise RuntimeError("media download failed")

        async def _dispatch_inbound_event(self, event):
            dispatched.append(event)

    monkeypatch.setattr(
        "gateway.platforms.api_server._owner_import",
        lambda _module, symbol: (
            (lambda: _Feishu())
            if symbol == "_get_inprocess_feishu_adapter"
            else None
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
    assert response.status == 202
    task = next(iter(api._background_tasks))
    await task
    await asyncio.sleep(0)
    assert dispatched == []


@pytest.mark.asyncio
async def test_api_caption_survives_media_rehydration_failure(monkeypatch):
    api = _api_adapter()
    admitted = MessageEvent(
        text="caption",
        source=SessionSource(
            platform=Platform.FEISHU, chat_id="oc_chat", user_id="ou_open"
        ),
    )
    dispatched = []

    class _Feishu:
        async def build_forwarded_inbound_event(self, **kwargs):
            if kwargs.get("defer_media"):
                return admitted
            raise RuntimeError("media download failed")

        async def _dispatch_inbound_event(self, event):
            dispatched.append(event)

    monkeypatch.setattr(
        "gateway.platforms.api_server._owner_import",
        lambda _module, symbol: (
            (lambda: _Feishu())
            if symbol == "_get_inprocess_feishu_adapter"
            else None
        ),
    )
    api._check_auth = MagicMock(return_value=None)
    api._read_json_body = AsyncMock(
        return_value=(
            {
                "schema_version": 1,
                "text": "caption",
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
    assert response.status == 202
    task = next(iter(api._background_tasks))
    await task
    await asyncio.sleep(0)
    assert dispatched == [admitted]


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


# ---------------------------------------------------------------------------
# [owner T2-9] Container-side ownership of the inbound RPC (S2-4)
#
# The transport authenticated the caller but never checked *what* it was asked
# to serve, so drift between ``profile_endpoints`` and the process listening on
# an endpoint delivered one profile's traffic into another container. The
# decision lives in ``verify_inbound_target_profile``; these tests pin both the
# reject case and the two "cannot decide ⇒ do not reject" cases, because the
# latter two are what keep a version skew or an unlabelled container from
# becoming a total routing outage.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_ownership_notices(monkeypatch):
    from owner.feishu import profile_routing

    monkeypatch.delenv(profile_routing.CONTAINER_PROFILE_ENV, raising=False)
    profile_routing.reset_ownership_notices()
    yield
    profile_routing.reset_ownership_notices()


def test_forward_payload_carries_target_profile(monkeypatch):
    """The sender names the profile the event is addressed to."""
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
            captured.update(kwargs)
            return _Response()

    monkeypatch.setattr("aiohttp.ClientSession", _Session)

    asyncio.run(
        profile_routing._forward_to_profile_container(
            endpoint="http://profile.test",
            api_key="secret",
            profile="hermesxiyun",
            text="hello",
            open_id="ou_open",
            chat_id="oc_chat",
            chat_type="p2p",
            message_id="om_message",
        )
    )

    assert captured["json"][profile_routing.TARGET_PROFILE_KEY] == "hermesxiyun"


def test_card_action_payload_carries_target_profile(monkeypatch):
    """A click is addressed to the profile whose card state it acts on."""
    from owner.feishu import profile_routing

    captured = {}

    class _Response:
        status = 200

        def read(self):
            return b'{"card": null}'

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def _fake_urlopen(req, timeout=None):
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return _Response()

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    event = SimpleNamespace(
        operator=SimpleNamespace(open_id="ou_clicker", user_id=""),
        context=SimpleNamespace(open_chat_id="oc_chat"),
    )

    profile_routing._forward_card_action_sync(
        ("hermesxiyun", "http://profile.test", "secret"),
        event,
        {"hermes_profile": "hermesxiyun", "action": "expand"},
    )

    assert captured["body"][profile_routing.TARGET_PROFILE_KEY] == "hermesxiyun"


class TestContainerProfileIdentity:
    """Self-identity resolution — deliberately never guesses."""

    def test_env_var_wins(self, monkeypatch):
        from owner.feishu import profile_routing

        monkeypatch.setenv(profile_routing.CONTAINER_PROFILE_ENV, "from-env")
        monkeypatch.setattr(
            profile_routing, "_load_routing_config", lambda: {"container_profile": "from-config"}
        )
        assert profile_routing.container_profile_identity() == "from-env"

    def test_falls_back_to_config_key(self, monkeypatch):
        from owner.feishu import profile_routing

        monkeypatch.setattr(
            profile_routing, "_load_routing_config", lambda: {"container_profile": "from-config"}
        )
        assert profile_routing.container_profile_identity() == "from-config"

    def test_blank_env_falls_through_to_config(self, monkeypatch):
        from owner.feishu import profile_routing

        monkeypatch.setenv(profile_routing.CONTAINER_PROFILE_ENV, "   ")
        monkeypatch.setattr(
            profile_routing, "_load_routing_config", lambda: {"container_profile": "from-config"}
        )
        assert profile_routing.container_profile_identity() == "from-config"

    def test_undeterminable_returns_none_rather_than_default(self, monkeypatch):
        """No env, no config key ⇒ ``None``, never a guessed "default".

        A guessed value decides whether to *reject*, so guessing "default"
        would reject every correctly-addressed event the moment the real
        profile is anything else.
        """
        from owner.feishu import profile_routing

        monkeypatch.setattr(profile_routing, "_load_routing_config", lambda: {})
        assert profile_routing.container_profile_identity() is None


class TestInboundTargetProfileVerification:

    def test_matching_profile_is_accepted(self, monkeypatch):
        from owner.feishu import profile_routing

        monkeypatch.setenv(profile_routing.CONTAINER_PROFILE_ENV, "hermesxiyun")
        assert (
            profile_routing.verify_inbound_target_profile(
                {profile_routing.TARGET_PROFILE_KEY: "hermesxiyun"}
            )
            is None
        )

    def test_other_profile_is_rejected_with_an_attributable_reason(self, monkeypatch):
        from owner.feishu import profile_routing

        monkeypatch.setenv(profile_routing.CONTAINER_PROFILE_ENV, "hermesxiyun")
        reason = profile_routing.verify_inbound_target_profile(
            {profile_routing.TARGET_PROFILE_KEY: "someone-else"}
        )
        assert reason is not None
        assert "someone-else" in reason
        assert "hermesxiyun" in reason

    def test_absent_target_is_accepted_because_refusing_would_be_an_outage(
        self, monkeypatch
    ):
        """A sender that predates the check must not lose every message."""
        from owner.feishu import profile_routing

        monkeypatch.setenv(profile_routing.CONTAINER_PROFILE_ENV, "hermesxiyun")
        assert profile_routing.verify_inbound_target_profile({}) is None

    def test_unknown_identity_is_accepted_rather_than_guessed(self, monkeypatch):
        from owner.feishu import profile_routing

        monkeypatch.setattr(profile_routing, "_load_routing_config", lambda: {})
        assert (
            profile_routing.verify_inbound_target_profile(
                {profile_routing.TARGET_PROFILE_KEY: "anything"}
            )
            is None
        )

    def test_notice_is_emitted_once_per_process(self, monkeypatch, caplog):
        from owner.feishu import profile_routing

        monkeypatch.setenv(profile_routing.CONTAINER_PROFILE_ENV, "hermesxiyun")
        with caplog.at_level("WARNING"):
            for _ in range(3):
                profile_routing.verify_inbound_target_profile({})
        hits = [
            r for r in caplog.records if "carried no" in r.getMessage()
        ]
        assert len(hits) == 1

    def test_non_dict_payload_is_left_to_the_schema_check(self):
        from owner.feishu import profile_routing

        assert profile_routing.verify_inbound_target_profile(None) is None
        assert profile_routing.verify_inbound_target_profile("not-a-dict") is None


@pytest.mark.asyncio
async def test_api_rejects_inbound_addressed_to_another_profile(monkeypatch):
    """409 before the adapter is touched — never a silent local run."""
    from owner.feishu import profile_routing

    monkeypatch.setenv(profile_routing.CONTAINER_PROFILE_ENV, "hermesxiyun")
    api = _api_adapter()
    api._check_auth = MagicMock(return_value=None)
    api._read_json_body = AsyncMock(
        return_value=(
            {
                "schema_version": 1,
                "text": "hello",
                "open_id": "ou_open",
                "chat_id": "oc_chat",
                profile_routing.TARGET_PROFILE_KEY: "somebody-elses-profile",
            },
            None,
        )
    )
    seen = {}

    def _verifier(body):
        seen["ran"] = True
        return profile_routing.verify_inbound_target_profile(body)

    monkeypatch.setattr(
        "gateway.platforms.api_server._owner_import",
        lambda module, symbol: (
            _verifier if symbol == "verify_inbound_target_profile" else None
        ),
    )

    response = await api._handle_feishu_inbound(SimpleNamespace())
    payload = json.loads(response.text)
    assert seen.get("ran") is True
    assert response.status == 409
    assert payload["error"]["code"] == "profile_mismatch"
    assert api._background_tasks == set()


@pytest.mark.asyncio
async def test_api_serves_inbound_addressed_to_this_profile(monkeypatch):
    from owner.feishu import profile_routing

    monkeypatch.setenv(profile_routing.CONTAINER_PROFILE_ENV, "hermesxiyun")
    api = _api_adapter()
    api._check_auth = MagicMock(return_value=None)
    api._read_json_body = AsyncMock(
        return_value=(
            {
                "schema_version": 1,
                "text": "hello",
                "open_id": "ou_open",
                "chat_id": "oc_chat",
                profile_routing.TARGET_PROFILE_KEY: "hermesxiyun",
            },
            None,
        )
    )
    event = MessageEvent(
        text="hello",
        source=SessionSource(
            platform=Platform.FEISHU, chat_id="oc_chat", user_id="ou_open"
        ),
    )

    class _Feishu:
        build_forwarded_inbound_event = AsyncMock(return_value=event)

        async def _dispatch_inbound_event(self, _event):
            return None

    feishu = _Feishu()

    def _import(module, symbol):
        if symbol == "_get_inprocess_feishu_adapter":
            return lambda: feishu
        if symbol == "verify_inbound_target_profile":
            return profile_routing.verify_inbound_target_profile
        return None

    monkeypatch.setattr("gateway.platforms.api_server._owner_import", _import)

    response = await api._handle_feishu_inbound(SimpleNamespace())
    assert response.status == 202
    for task in list(api._background_tasks):
        await task


@pytest.mark.asyncio
async def test_api_tolerates_a_sender_that_predates_the_check(monkeypatch):
    """Absent ``target_profile`` must not break routing (version skew)."""
    from owner.feishu import profile_routing

    monkeypatch.setenv(profile_routing.CONTAINER_PROFILE_ENV, "hermesxiyun")
    api = _api_adapter()
    api._check_auth = MagicMock(return_value=None)
    api._read_json_body = AsyncMock(
        return_value=(
            {
                "schema_version": 1,
                "text": "hello",
                "open_id": "ou_open",
                "chat_id": "oc_chat",
            },
            None,
        )
    )
    event = MessageEvent(
        text="hello",
        source=SessionSource(
            platform=Platform.FEISHU, chat_id="oc_chat", user_id="ou_open"
        ),
    )

    class _Feishu:
        build_forwarded_inbound_event = AsyncMock(return_value=event)

        async def _dispatch_inbound_event(self, _event):
            return None

    feishu = _Feishu()

    def _import(module, symbol):
        if symbol == "_get_inprocess_feishu_adapter":
            return lambda: feishu
        if symbol == "verify_inbound_target_profile":
            return profile_routing.verify_inbound_target_profile
        return None

    monkeypatch.setattr("gateway.platforms.api_server._owner_import", _import)

    response = await api._handle_feishu_inbound(SimpleNamespace())
    assert response.status == 202
    for task in list(api._background_tasks):
        await task


def test_raising_verifier_does_not_take_routing_down(monkeypatch):
    """The API key is the authentication boundary; this check is depth."""
    api = _api_adapter()

    def _boom(_body):
        raise RuntimeError("verifier exploded")

    monkeypatch.setattr(
        "gateway.platforms.api_server._owner_import",
        lambda module, symbol: (
            _boom if symbol == "verify_inbound_target_profile" else None
        ),
    )
    from gateway.platforms import api_server

    assert api_server._owner_inbound_profile_rejection({"target_profile": "x"}) is None


def test_reaction_ownership_decision_is_recorded_beside_the_code():
    """The reactor-based route is a decision, and the asymmetry is stated.

    Pins the record itself (same discipline as T2-7's accepted-decision
    test): tightening or re-routing reactions later has to change this text
    too, so the choice cannot be reversed silently.
    """
    import inspect

    from plugins.platforms.feishu.adapter import FeishuAdapter

    src = inspect.getsource(FeishuAdapter._handle_reaction_event)
    assert "T2-9 (accepted decision" in src
    assert "from the REACTOR, not from the owner" in src
    # The card path routes by the artifact's own tag — the contrast is the
    # reason the asymmetry is explainable rather than looking like a bug.
    assert "try_route_card_action" in src
    # And the whitelist-skipped-in-groups consequence is spelled out.
    assert "skips the whitelist in group chats" in src


def test_group_reaction_route_skips_whitelist_as_documented(monkeypatch):
    """Pins the factual claim the comment above makes about group routing."""
    from owner.feishu import profile_routing

    monkeypatch.setattr(
        profile_routing,
        "_load_routing_config",
        lambda: {
            "whitelist": ["ou_whitelisted"],
            "chat_profile_routes": {},
            "user_profile_routes": {},
            "default_profile": "container-a",
            "profile_endpoints": {
                "container-a": {"url": "http://c.test", "api_key": "k"}
            },
        },
    )
    # DM: whitelist applies → main gateway (None).
    assert (
        profile_routing.resolve_profile_route("oc_dm", "ou_whitelisted", "p2p") is None
    )
    # Group: whitelist skipped → default_profile, i.e. the same destination the
    # whitelisted user's group *messages* take.
    route = profile_routing.resolve_profile_route("oc_group", "ou_whitelisted", "group")
    assert route is not None
    assert route[0] == "container-a"
