"""Feishu topic routing for explainer notices and interactive cards.

progress / recap / english must pass metadata.thread_id (and a reply anchor)
so cards stay in the topic. Interactive cards must use reply_in_thread, not
create with receive_id_type=thread_id (Feishu 99992402).
"""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from owner.explainers.common import (
    coerce_session_source,
    native_thread_id,
    reply_anchor_from_source,
    send_metadata_for_thread,
    unpack_explainer_route,
)
from owner.feishu import card_sender


def _running_loop():
    """Event loop running in a daemon thread (for run_coroutine_threadsafe)."""
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    return loop, thread


def _stop_loop(loop, thread):
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=2)
    loop.close()


def test_native_thread_id_ignores_root_id():
    source = SimpleNamespace(thread_id="omt_topic", root_id="om_quoted")
    assert native_thread_id(source) == "omt_topic"
    quoted_only = SimpleNamespace(root_id="om_quoted", thread_id=None)
    assert native_thread_id(quoted_only) == ""
    as_dict = coerce_session_source({"chat_id": "oc_x", "root_id": "om_quoted"})
    assert native_thread_id(as_dict) == ""
    assert send_metadata_for_thread(source=quoted_only) is None


def test_send_metadata_for_thread_and_main_chat():
    source = SimpleNamespace(thread_id="omt_t", message_id="om_user")
    assert send_metadata_for_thread(source=source) == {
        "thread_id": "omt_t",
        "reply_to_message_id": "om_user",
    }
    main = SimpleNamespace(platform="feishu", chat_id="oc_g", thread_id=None)
    assert send_metadata_for_thread(source=main) is None
    assert send_metadata_for_thread(thread_id="") is None
    assert send_metadata_for_thread("omt_t") == {"thread_id": "omt_t"}


def test_reply_anchor_prefers_source_message_id():
    source = SimpleNamespace(message_id="om_src", reply_to_message_id="om_parent")
    event = SimpleNamespace(message_id="om_event", reply_to_message_id="om_ev_parent")
    assert reply_anchor_from_source(source, event) == "om_src"


@pytest.mark.asyncio
async def test_progress_send_includes_thread_metadata(monkeypatch):
    from owner.explainers.progress import dispatcher as disp

    monkeypatch.setattr(disp, "load_kind_config", lambda kind: {"enabled": True, "timeout_ms": 1000})
    source = SimpleNamespace(
        platform="feishu",
        chat_id="oc_group",
        thread_id="omt_topic",
        message_id="om_user",
    )
    sent = {}

    class _Adapter:
        async def send(self, chat_id, body, metadata=None, **kwargs):
            sent["chat_id"] = chat_id
            sent["body"] = body
            sent["metadata"] = metadata
            return SimpleNamespace(success=True, message_id="om_card")

    inst = disp.ProgressExplainer.__new__(disp.ProgressExplainer)
    inst._chat_id = "oc_group"
    inst._thread_id = "omt_topic"
    inst._reply_to_message_id = "om_user"
    inst._send_metadata = send_metadata_for_thread("omt_topic", "om_user")
    inst._cfg = {}
    inst._session_id = "sid"
    inst._turn_id = ""
    inst._tracker = SimpleNamespace(
        record_explainer_sent=lambda: None,
        user_message="",
    )
    inst._turn_ctx = None
    inst._sending = False

    async def _explain(**kwargs):
        return "还在查资料"

    monkeypatch.setattr(inst, "_adapter", lambda: _Adapter())
    monkeypatch.setattr(inst, "_run_still_current", lambda: True)
    monkeypatch.setattr(inst, "_activity_summary", dict)
    monkeypatch.setattr(inst, "_hard_facts", lambda state, activity: {})
    monkeypatch.setattr(inst, "_fact_line", lambda activity: "")
    monkeypatch.setattr(inst, "_sync_identity_and_callbacks", lambda: None)
    monkeypatch.setattr(inst, "_resolve_agent", lambda: object())
    monkeypatch.setattr(
        inst,
        "_tracker",
        SimpleNamespace(
            user_message="",
            record_explainer_sent=lambda: None,
            state=lambda: {
                "silence_seconds_since_last_content": 999,
                "last_explainer_ts": None,
                "explainer_count": 0,
                "branch": "work",
                "digest_hash": "abc",
                "now": 0,
                "turn_started_at": 0,
            },
        ),
    )
    inst._last_digest_hash = None
    inst._cfg = {
        "enabled": True,
        "silence_seconds": 1,
        "min_interval_seconds": 0,
        "max_per_turn": 5,
        "cleanup_progress": False,
    }

    with patch("owner.explainers.progress.digest.build_digest", return_value="d"), patch(
        "owner.explainers.progress.explain.explain", new=_explain
    ), patch("owner.explainers.progress.dispatcher._stream_guard_tripped", return_value=False), patch(
        "agent.i18n.get_language", return_value="zh"
    ), patch("owner.explainers.persist.persist_notice"):
        await inst._tick_once()

    assert sent["chat_id"] == "oc_group"
    assert sent["metadata"] == {"thread_id": "omt_topic", "reply_to_message_id": "om_user"}
    # constructor path also captures the same metadata
    # (re-use source to confirm attribute wiring without spinning a tick)
    inst2 = disp.ProgressExplainer(
        runner=SimpleNamespace(),
        agent=object(),
        source=source,
        session_key="sk",
    )
    assert inst2._send_metadata == {
        "thread_id": "omt_topic",
        "reply_to_message_id": "om_user",
    }


@pytest.mark.asyncio
async def test_progress_send_main_chat_has_no_thread_metadata(monkeypatch):
    from owner.explainers.progress import dispatcher as disp

    monkeypatch.setattr(disp, "load_kind_config", lambda kind: {"enabled": True})
    source = SimpleNamespace(platform="feishu", chat_id="oc_group", thread_id=None)
    inst = disp.ProgressExplainer(
        runner=SimpleNamespace(),
        agent=object(),
        source=source,
        session_key="sk",
    )
    assert inst._send_metadata is None
    sent = {}

    class _Adapter:
        async def send(self, chat_id, body, metadata=None, **kwargs):
            sent["chat_id"] = chat_id
            sent["metadata"] = metadata
            return SimpleNamespace(success=True, message_id="om_card")

    inst._cfg = {
        "enabled": True,
        "silence_seconds": 1,
        "min_interval_seconds": 0,
        "max_per_turn": 5,
        "cleanup_progress": False,
    }
    inst._sending = False
    inst._last_digest_hash = None
    inst._session_id = "sid"
    inst._tracker = SimpleNamespace(
        user_message="",
        record_explainer_sent=lambda: None,
        state=lambda: {
            "silence_seconds_since_last_content": 999,
            "last_explainer_ts": None,
            "explainer_count": 0,
            "branch": "work",
            "digest_hash": "abc",
            "now": 0,
            "turn_started_at": 0,
        },
    )
    monkeypatch.setattr(inst, "_adapter", lambda: _Adapter())
    monkeypatch.setattr(inst, "_run_still_current", lambda: True)
    monkeypatch.setattr(inst, "_activity_summary", dict)
    monkeypatch.setattr(inst, "_hard_facts", lambda state, activity: {})
    monkeypatch.setattr(inst, "_fact_line", lambda activity: "")
    monkeypatch.setattr(inst, "_sync_identity_and_callbacks", lambda: None)
    monkeypatch.setattr(inst, "_resolve_agent", lambda: object())

    async def _explain(**kwargs):
        return "还在查资料"

    with patch("owner.explainers.progress.digest.build_digest", return_value="d"), patch(
        "owner.explainers.progress.explain.explain", new=_explain
    ), patch("owner.explainers.progress.dispatcher._stream_guard_tripped", return_value=False), patch(
        "agent.i18n.get_language", return_value="zh"
    ), patch("owner.explainers.persist.persist_notice"):
        await inst._tick_once()

    assert sent["chat_id"] == "oc_group"
    assert sent["metadata"] is None


def test_recap_route_remembers_thread_and_send_notice_passes_metadata():
    from owner.explainers.recap import auto as auto_mod

    with auto_mod._ROUTE_LOCK:
        auto_mod._SESSION_ROUTES.clear()
    with auto_mod._REF_LOCK:
        auto_mod._GATEWAY_REF = None
        auto_mod._ADAPTERS.clear()

    source = SimpleNamespace(
        platform="feishu",
        chat_id="oc_group",
        thread_id="omt_topic",
        message_id="om_user",
    )
    event = SimpleNamespace(source=source, text="hi")

    class FakeStore:
        def lookup_by_session_key(self, key):
            return SimpleNamespace(session_id="sid-topic", origin=source)

    class FakeGw:
        adapters = {"feishu": object()}
        session_store = FakeStore()

        def _session_key_for_source(self, src):
            return f"agent:main:feishu:group:{src.chat_id}:{src.thread_id}"

    auto_mod._on_pre_gateway_dispatch(event=event, gateway=FakeGw())
    with auto_mod._ROUTE_LOCK:
        routes = dict(auto_mod._SESSION_ROUTES)
    assert unpack_explainer_route(routes.get("sid-topic")) == (
        "feishu",
        "oc_group",
        "omt_topic",
        "om_user",
    )

    scheduled = {}

    def fake_sched(sid, **kw):
        scheduled["sid"] = sid
        scheduled.update(kw)

    with patch.object(auto_mod, "resolve_enabled", return_value=True), patch.object(
        auto_mod,
        "load_auto_config",
        return_value={"enabled": True, "min_turn_seconds": 180, "min_assistant_chars": 800},
    ), patch.object(auto_mod, "start_auto_recap", side_effect=fake_sched):
        auto_mod._on_session_end(
            session_id="sid-topic",
            completed=True,
            failed=False,
            interrupted=False,
            platform="feishu",
        )
    assert scheduled.get("chat_id") == "oc_group"
    assert scheduled.get("thread_id") == "omt_topic"
    assert scheduled.get("reply_to_message_id") == "om_user"

    sent = {}

    class _Adapter:
        async def send(self, chat_id, body, metadata=None, **kwargs):
            sent["chat_id"] = chat_id
            sent["metadata"] = metadata

    loop, thread = _running_loop()
    try:
        adapter = _Adapter()
        adapter._loop = loop
        with auto_mod._REF_LOCK:
            auto_mod._ADAPTERS["feishu"] = adapter
        ok = auto_mod._send_notice(
            "feishu",
            "oc_group",
            "📋 系统提示：回顾",
            {"timeout_ms": 1000},
            thread_id="omt_topic",
            reply_to_message_id="om_user",
        )
        assert ok is True
        assert sent["chat_id"] == "oc_group"
        assert sent["metadata"] == {
            "thread_id": "omt_topic",
            "reply_to_message_id": "om_user",
        }
    finally:
        _stop_loop(loop, thread)
        with auto_mod._REF_LOCK:
            auto_mod._ADAPTERS.clear()
        with auto_mod._ROUTE_LOCK:
            auto_mod._SESSION_ROUTES.clear()


def test_recap_send_notice_main_chat_metadata_is_none():
    from owner.explainers.recap import auto as auto_mod

    sent = {}

    class _Adapter:
        async def send(self, chat_id, body, metadata=None, **kwargs):
            sent["chat_id"] = chat_id
            sent["metadata"] = metadata

    loop, thread = _running_loop()
    try:
        adapter = _Adapter()
        adapter._loop = loop
        with auto_mod._REF_LOCK:
            auto_mod._ADAPTERS["feishu"] = adapter
        ok = auto_mod._send_notice(
            "feishu", "oc_group", "📋 系统提示：回顾", {"timeout_ms": 1000}
        )
        assert ok is True
        assert sent["chat_id"] == "oc_group"
        assert sent["metadata"] is None
    finally:
        _stop_loop(loop, thread)
        with auto_mod._REF_LOCK:
            auto_mod._ADAPTERS.clear()


def test_english_send_includes_thread_metadata():
    from owner.explainers.english import hook as eng

    with eng._ROUTE_LOCK:
        eng._SESSION_ROUTES.clear()
    source = SimpleNamespace(
        platform="feishu",
        chat_id="oc_group",
        thread_id="omt_topic",
        message_id="om_user",
    )
    event = SimpleNamespace(source=source, session_key="agent:main:feishu:group:oc_group:omt_topic")
    eng._on_pre_gateway_dispatch(event=event, source=source, session_key=event.session_key)
    with eng._ROUTE_LOCK:
        route = unpack_explainer_route(eng._SESSION_ROUTES[event.session_key])
    assert route == ("feishu", "oc_group", "omt_topic", "om_user")

    sent = {}

    class _Adapter:
        async def send(self, chat_id, body, metadata=None, **kwargs):
            sent["chat_id"] = chat_id
            sent["metadata"] = metadata
            return SimpleNamespace(success=True, message_id="om_card")

    loop, thread = _running_loop()
    try:
        adapter = _Adapter()
        adapter._loop = loop
        with eng._REF_LOCK:
            eng._ADAPTERS["feishu"] = adapter
        with patch.object(eng, "explain_sync", return_value="这是中文解说"), patch(
            "owner.explainers.persist.persist_notice"
        ):
            eng._bg_translate_and_send(
                response_text="The service is healthy now.",
                cfg={"timeout_ms": 1000},
                platform="feishu",
                chat_id="oc_group",
                session_id="sid",
                detection={"reason": "english"},
                thread_id="omt_topic",
                reply_to_message_id="om_user",
            )
        assert sent["chat_id"] == "oc_group"
        assert sent["metadata"] == {
            "thread_id": "omt_topic",
            "reply_to_message_id": "om_user",
        }
    finally:
        _stop_loop(loop, thread)
        with eng._REF_LOCK:
            eng._ADAPTERS.clear()
        with eng._ROUTE_LOCK:
            eng._SESSION_ROUTES.clear()


def test_english_send_main_chat_metadata_is_none():
    from owner.explainers.english import hook as eng

    sent = {}

    class _Adapter:
        async def send(self, chat_id, body, metadata=None, **kwargs):
            sent["metadata"] = metadata
            return SimpleNamespace(success=True, message_id="om_card")

    loop, thread = _running_loop()
    try:
        adapter = _Adapter()
        adapter._loop = loop
        with eng._REF_LOCK:
            eng._ADAPTERS["feishu"] = adapter
        with patch.object(eng, "explain_sync", return_value="这是中文解说"), patch(
            "owner.explainers.persist.persist_notice"
        ):
            eng._bg_translate_and_send(
                response_text="The service is healthy now.",
                cfg={"timeout_ms": 1000},
                platform="feishu",
                chat_id="oc_group",
                session_id="sid",
                detection={"reason": "english"},
            )
        assert sent["metadata"] is None
    finally:
        _stop_loop(loop, thread)
        with eng._REF_LOCK:
            eng._ADAPTERS.clear()


def test_resolve_card_delivery_thread_vs_main():
    assert card_sender._resolve_card_delivery(
        "oc_g", {"thread_id": "omt_t", "reply_to_message_id": "om_u"}
    ) == ("reply", "om_u")
    assert card_sender._resolve_card_delivery("oc_g", {"thread_id": "omt_t"}) == (
        "thread_pending",
        "omt_t",
    )
    assert card_sender._resolve_card_delivery("oc_g", None) == ("create", "oc_g", "chat_id")
    assert card_sender._resolve_card_delivery("oc_g", {}) == ("create", "oc_g", "chat_id")
    # thread must not collapse to chat_id-only
    mode = card_sender._resolve_card_delivery("oc_g", {"thread_id": "omt_t"})[0]
    assert mode != "create"


@pytest.mark.asyncio
async def test_send_card_uses_reply_in_thread_not_create_by_thread_id():
    adapter = MagicMock()
    captured = {}

    class _Resp:
        def success(self):
            return True

    async def _retry(**kwargs):
        captured.update(kwargs)
        return _Resp()

    adapter._feishu_send_with_retry = _retry
    adapter._finalize_send_result = MagicMock(
        return_value=SimpleNamespace(success=True, error=None, message_id="om_card")
    )
    adapter._fetch_last_message_in_thread = AsyncMock(return_value="om_last")

    result = await card_sender.send_card(
        adapter,
        chat_id="oc_g",
        card={"schema": "2.0"},
        metadata={"thread_id": "omt_t", "reply_to_message_id": "om_user"},
    )
    assert result.success is True
    assert captured["reply_to"] == "om_user"
    assert captured["metadata"]["thread_id"] == "omt_t"
    assert captured["msg_type"] == "interactive"
    adapter._fetch_last_message_in_thread.assert_not_called()


@pytest.mark.asyncio
async def test_send_card_fetches_last_thread_message_when_anchor_missing():
    adapter = MagicMock()
    captured = {}

    class _Resp:
        def success(self):
            return True

    async def _retry(**kwargs):
        captured.update(kwargs)
        return _Resp()

    adapter._feishu_send_with_retry = _retry
    adapter._finalize_send_result = MagicMock(
        return_value=SimpleNamespace(success=True, error=None, message_id="om_card")
    )
    adapter._fetch_last_message_in_thread = AsyncMock(return_value="om_last")

    result = await card_sender.send_card(
        adapter,
        chat_id="oc_g",
        card={"schema": "2.0"},
        metadata={"thread_id": "omt_t"},
    )
    assert result.success is True
    assert captured["reply_to"] == "om_last"
    assert captured["metadata"]["reply_to_message_id"] == "om_last"
    adapter._fetch_last_message_in_thread.assert_awaited_once_with("omt_t")


@pytest.mark.asyncio
async def test_send_card_refuses_create_by_thread_id_without_anchor():
    adapter = MagicMock()
    adapter._feishu_send_with_retry = AsyncMock()
    adapter._fetch_last_message_in_thread = AsyncMock(return_value=None)

    result = await card_sender.send_card(
        adapter,
        chat_id="oc_g",
        card={"schema": "2.0"},
        metadata={"thread_id": "omt_t"},
    )
    assert result.success is False
    assert "reply_in_thread" in (result.error or "")
    adapter._feishu_send_with_retry.assert_not_called()


@pytest.mark.asyncio
async def test_send_card_main_chat_still_creates_on_chat_id():
    adapter = MagicMock()
    captured = {}

    class _Resp:
        def success(self):
            return True

    async def _retry(**kwargs):
        captured.update(kwargs)
        return _Resp()

    adapter._feishu_send_with_retry = _retry
    adapter._finalize_send_result = MagicMock(
        return_value=SimpleNamespace(success=True, error=None, message_id="om_card")
    )

    result = await card_sender.send_card(
        adapter, chat_id="oc_g", card={"schema": "2.0"}, metadata=None
    )
    assert result.success is True
    assert captured["reply_to"] is None
    assert captured["chat_id"] == "oc_g"


@pytest.mark.asyncio
async def test_send_card_via_rest_replies_in_thread_not_chat_id():
    adapter = MagicMock()
    adapter._app_id = "app"
    adapter._app_secret = "secret"
    adapter._connection_mode = "websocket"
    posts = []

    class _Resp:
        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_post(url, headers=None, json=None, timeout=None):
        posts.append({"url": url, "json": json})
        if "tenant_access_token" in url:
            return _Resp({"tenant_access_token": "tok"})
        return _Resp({"code": 0, "data": {"message_id": "om_card"}})

    with patch("requests.post", side_effect=fake_post):
        result = await card_sender.send_card_via_rest(
            adapter,
            "oc_g",
            {"schema": "2.0"},
            metadata={"thread_id": "omt_t", "reply_to_message_id": "om_user"},
        )
    assert result.success is True
    assert result.message_id == "om_card"
    card_posts = [p for p in posts if "/messages/" in p["url"] or "receive_id_type" in p["url"]]
    assert len(card_posts) == 1
    assert card_posts[0]["url"].endswith("/im/v1/messages/om_user/reply")
    assert card_posts[0]["json"]["reply_in_thread"] is True
    assert card_posts[0]["json"]["msg_type"] == "interactive"
    assert "receive_id_type=thread_id" not in card_posts[0]["url"]
    assert "receive_id_type=chat_id" not in card_posts[0]["url"]


@pytest.mark.asyncio
async def test_send_card_via_rest_main_chat_still_uses_chat_id():
    adapter = MagicMock()
    adapter._app_id = "app"
    adapter._app_secret = "secret"
    adapter._connection_mode = "websocket"
    posts = []

    class _Resp:
        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_post(url, headers=None, json=None, timeout=None):
        posts.append({"url": url, "json": json})
        if "tenant_access_token" in url:
            return _Resp({"tenant_access_token": "tok"})
        return _Resp({"code": 0, "data": {"message_id": "om_card"}})

    with patch("requests.post", side_effect=fake_post):
        result = await card_sender.send_card_via_rest(
            adapter, "oc_g", {"schema": "2.0"}, metadata=None
        )
    assert result.success is True
    card_posts = [p for p in posts if "im/v1/messages" in p["url"]]
    assert any("receive_id_type=chat_id" in p["url"] for p in card_posts)
    assert card_posts[-1]["json"]["receive_id"] == "oc_g"


@pytest.mark.asyncio
async def test_send_card_via_rest_refuses_chat_id_fallback_without_anchor():
    adapter = MagicMock()
    adapter._app_id = "app"
    adapter._app_secret = "secret"
    adapter._connection_mode = "websocket"
    posts = []

    class _Resp:
        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_post(url, headers=None, json=None, timeout=None):
        posts.append({"url": url, "json": json})
        if "tenant_access_token" in url:
            return _Resp({"tenant_access_token": "tok"})
        return _Resp({"code": 0, "data": {"message_id": "om_card"}})

    def fake_get(url, headers=None, params=None, timeout=None):
        return _Resp({"code": 0, "data": {"items": []}})

    with patch("requests.post", side_effect=fake_post), patch("requests.get", side_effect=fake_get):
        result = await card_sender.send_card_via_rest(
            adapter, "oc_g", {"schema": "2.0"}, metadata={"thread_id": "omt_t"}
        )
    assert result.success is False
    assert "reply_in_thread" in (result.error or "")
    # token request only — no create-by-chat_id / create-by-thread_id
    assert all("receive_id_type=" not in p["url"] for p in posts)
    assert all("/reply" not in p["url"] for p in posts)
