"""Regression: feishu auto-card must not swallow ``MEDIA:`` tags.

Bug (verified line-level): ``try_auto_card_on_end`` wrapped the whole response
(including literal ``MEDIA:<path>`` text) into a feishu card, set
``already_sent=True`` and returned ``("", "")``. Downstream:

  * ``run.py`` post-agent ``already_sent`` branch gated on ``if response`` →
    response was already cleared, so ``_deliver_media_from_response`` never ran.
  * ``_process_message_background`` gates media extraction on ``if response`` →
    falsy response, ``extract_media`` skipped.

Net: the file was never uploaded; the ``MEDIA:`` tag surfaced as plain text in
the card body.

Fix: ``try_auto_card_on_end`` now extracts + delivers MEDIA files *before*
handing the cleaned text to ``try_auto_card``. See
``owner/docs/feishu-autocard-media-delivery.md``.

These tests do not touch the network and do not import the live feishu adapter.
"""

from __future__ import annotations

import asyncio
import types
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.config import Platform
from owner.feishu import agent_end


def _make_runner(adapter, *, deliver_calls=None):
    """Build a minimal stand-in for GatewayRunner covering the methods the
    function under test actually touches."""
    adapters = {Platform.FEISHU: adapter}

    runner = types.SimpleNamespace(
        adapters=adapters,
        _deliver_media_from_response=_record_deliver(deliver_calls, adapter),
        _thread_metadata_for_source=lambda source, anchor: {"__meta": True},
        _reply_anchor_for_event=lambda event: None,
    )
    return runner


def _record_deliver(sink, adapter):
    async def _impl(response, event, adp):
        # Mirror the real gateway: route the file via send_document so the test
        # can assert the adapter actually received the upload call.
        from gateway.platforms.base import BasePlatformAdapter

        media_files, cleaned = adp.extract_media(response)
        media_files = BasePlatformAdapter.filter_media_delivery_paths(media_files)
        for path, _is_voice in media_files:
            await adp.send_document(
                chat_id=event.source.chat_id,
                file_path=path,
                metadata={"__meta": True},
            )
        if sink is not None:
            sink.append(cleaned)
        return None

    return _impl


def _adapter_with_tmp_file(tmp_path):
    """Return (adapter_mock, file_path) where file_path is a real on-disk file
    with a MEDIA-deliverable extension."""
    f = tmp_path / "free_pagecache.txt"
    f.write_text("dummy")

    adapter = MagicMock()
    adapter.name = "feishu"
    # extract_media is a real staticmethod on BasePlatformAdapter; we want the
    # real behaviour so the test exercises the actual tag-stripping regex.
    from gateway.platforms.base import BasePlatformAdapter

    adapter.extract_media = BasePlatformAdapter.extract_media
    adapter.send_document = AsyncMock(return_value=types.SimpleNamespace(success=True))
    adapter.send_multiple_images = AsyncMock(return_value=types.SimpleNamespace(success=True))
    adapter.send_video = AsyncMock(return_value=types.SimpleNamespace(success=True))
    adapter.send_voice = AsyncMock(return_value=types.SimpleNamespace(success=True))
    return adapter, str(f)


def _event_source(chat_id="oc_dm1"):
    source = types.SimpleNamespace(
        platform=Platform.FEISHU,
        chat_id=chat_id,
        thread_id=None,
    )
    event = types.SimpleNamespace(source=source, message_id="m_1")
    return event, source


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


def test_media_tag_file_is_delivered_before_card(tmp_path, monkeypatch):
    """Core regression: the file is uploaded via send_document and the card body
    passed to try_auto_card no longer contains the literal ``MEDIA:`` tag."""
    adapter, file_path = _adapter_with_tmp_file(tmp_path)
    deliver_calls = []
    runner = _make_runner(adapter, deliver_calls=deliver_calls)
    event, source = _event_source()
    agent_result: dict = {}

    captured_body = {}

    async def _fake_try_auto_card(adapter_, body_text, meta, **kw):
        captured_body["body"] = body_text
        captured_body["footer"] = kw.get("footer", "")
        captured_body["force"] = kw.get("force")
        return types.SimpleNamespace(success=True, message_id="card_1")

    monkeypatch.setattr("owner.feishu.auto_card.try_auto_card", _fake_try_auto_card)

    response = f"Here is the file you asked for:\nMEDIA:{file_path}"
    out_resp, out_footer = _run(agent_end.try_auto_card_on_end(
        runner, source, event, agent_result, response, "",
    ))

    # 1. The file was actually uploaded.
    assert adapter.send_document.await_count == 1
    called_path = adapter.send_document.await_args.kwargs["file_path"]
    assert called_path == file_path

    # 2. The card body no longer leaks the MEDIA tag as plain text.
    assert "MEDIA:" not in captured_body["body"]
    assert file_path not in captured_body["body"]
    # The cleaned body still carries the surrounding prose.
    assert "Here is the file you asked for" in captured_body["body"]

    # 3. force=True preserved (cards still fire at agent:end).
    assert captured_body["force"] is True

    # 4. Return contract unchanged: downstream plain-text path must be skipped.
    assert out_resp == ""
    assert out_footer == ""
    assert agent_result.get("already_sent") is True


def test_no_media_tag_unchanged_behaviour(tmp_path, monkeypatch):
    """Regression: response without MEDIA tags behaves exactly as before — no
    extra send_document call, card gets the full text."""
    adapter, _ = _adapter_with_tmp_file(tmp_path)
    runner = _make_runner(adapter, deliver_calls=[])
    event, source = _event_source()
    agent_result: dict = {}

    captured_body = {}

    async def _fake_try_auto_card(adapter_, body_text, meta, **kw):
        captured_body["body"] = body_text
        return types.SimpleNamespace(success=True, message_id="card_1")

    monkeypatch.setattr("owner.feishu.auto_card.try_auto_card", _fake_try_auto_card)

    response = "Just a normal reply, nothing to attach here."
    out_resp, out_footer = _run(agent_end.try_auto_card_on_end(
        runner, source, event, agent_result, response, "",
    ))

    # No media → no upload attempt.
    assert adapter.send_document.await_count == 0
    # Card body carries the full original text.
    assert captured_body["body"] == response
    assert out_resp == ""
    assert agent_result.get("already_sent") is True


def test_response_is_only_media_tag_skips_card(tmp_path, monkeypatch):
    """Edge case: when the response is *only* the MEDIA tag, the cleaned text is
    empty. We must not fire try_auto_card(force=True) and send an empty card —
    the file is already delivered, so we short-circuit with already_sent=True."""
    adapter, file_path = _adapter_with_tmp_file(tmp_path)
    runner = _make_runner(adapter, deliver_calls=None)
    event, source = _event_source()
    agent_result: dict = {}

    async def _fail_if_called(*a, **kw):
        raise AssertionError("try_auto_card must not fire for an empty body")

    monkeypatch.setattr("owner.feishu.auto_card.try_auto_card", _fail_if_called)

    response = f"MEDIA:{file_path}"
    out_resp, out_footer = _run(agent_end.try_auto_card_on_end(
        runner, source, event, agent_result, response, "",
    ))

    # File still delivered.
    assert adapter.send_document.await_count == 1
    # No card sent (try_auto_card never called).
    assert out_resp == ""
    assert out_footer == ""
    assert agent_result.get("already_sent") is True


def test_non_feishu_platform_is_passthrough(tmp_path, monkeypatch):
    """Sanity: non-feishu platform returns inputs untouched, no media work."""
    adapter, _ = _adapter_with_tmp_file(tmp_path)
    runner = _make_runner(adapter, deliver_calls=None)
    source = types.SimpleNamespace(platform=Platform.TELEGRAM, chat_id="c1", thread_id=None)
    event = types.SimpleNamespace(source=source, message_id="m_1")
    agent_result: dict = {}

    async def _fail_if_called(*a, **kw):
        raise AssertionError("must not run on non-feishu platform")

    monkeypatch.setattr("owner.feishu.auto_card.try_auto_card", _fail_if_called)

    out_resp, out_footer = _run(agent_end.try_auto_card_on_end(
        runner, source, event, agent_result, "MEDIA:/tmp/x.txt", "",
    ))
    assert out_resp == "MEDIA:/tmp/x.txt"
    assert out_footer == ""
    assert "already_sent" not in agent_result
    assert adapter.send_document.await_count == 0
