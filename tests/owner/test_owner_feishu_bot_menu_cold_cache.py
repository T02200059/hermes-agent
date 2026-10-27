"""Guard: a bot-menu click before the p2p chat_id cache is warm must not lie.

New-baseline owner test (2026-10-23). Not a localization divergence — it pins the
startup-window behaviour of this fork's Feishu bot menu.

Observed: right after a gateway restart, clicking the ``new`` menu item replied

    ⚠️ 未配置的菜单事件: event_key="new"
    请在 overlay.yaml → owner.feishu.bot_menu 中添加映射，例如: new: "/help"

while ``new`` had been mapped to ``/new`` in ``BUILTIN_BOT_MENU`` all along, and
the same click worked a minute later. Two independent defects produced that:

1. ``_process_bot_menu_click`` had ONE failure message for two different causes.
   A missing p2p chat_id (cache cold / written within the debounce window before
   the last shutdown) printed the unmapped-menu text, so the operator is told to
   add a overlay.yaml mapping that already exists — the message actively points at
   the wrong fix.
2. ``ChatIdCacheDebouncer`` persisted only via a 5s *daemon* timer with no
   ``flush()`` and no shutdown hook, so an orderly restart inside that window
   dropped the newest ``open_id → p2p_chat_id`` mapping. The next boot then
   started with the very cache miss described above.

These cases pin the message split and the persist-on-exit path. The underlying
routing (chat_id present → command injected) is covered by the existing suite.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock

import pytest

from owner.feishu import bot_menu
from owner.feishu.user_cache import ChatIdCacheDebouncer


def _run_click(monkeypatch, *, chat_id, event_key="new"):
    """Drive _process_bot_menu_click with a stubbed store and captured sends."""
    sent = []

    store = MagicMock()
    store.get_p2p_chat_id.return_value = chat_id

    monkeypatch.setattr(
        "owner.feishu.user_store.get_user_store", lambda adapter: store, raising=False
    )

    async def fake_send(adapter, *, label, chat_id, msg_type, payload):
        sent.append(json.loads(payload)["text"])

    monkeypatch.setattr(bot_menu, "_send_with_timeout", fake_send)

    asyncio.run(
        bot_menu._process_bot_menu_click(
            adapter=MagicMock(), data=MagicMock(), open_id="ou_test", event_key=event_key
        )
    )
    return sent


def test_cold_cache_reports_the_conversation_not_a_missing_mapping(monkeypatch):
    """A mapped key with no chat_id must NOT be reported as "未配置的菜单事件"."""
    sent = _run_click(monkeypatch, chat_id=None, event_key="new")

    assert len(sent) == 1
    text = sent[0]
    assert "未配置的菜单事件" not in text, (
        "a mapped key was reported as unmapped — the operator is sent to edit "
        f"overlay.yaml for nothing: {text!r}"
    )
    # Names the real cause and carries the mapping it actually has, so the reader
    # can tell "mapping missing" from "conversation cache not established yet".
    assert "会话缓存" in text
    assert "/new" in text


def test_cold_cache_still_reports_genuinely_unmapped_keys(monkeypatch):
    """An unknown key with no chat_id keeps the configuration guidance."""
    sent = _run_click(monkeypatch, chat_id=None, event_key="definitely_not_mapped")

    assert len(sent) == 1
    text = sent[0]
    assert "未配置的菜单事件" in text
    assert "overlay.yaml" in text


def test_debouncer_flush_persists_before_the_debounce_window_expires():
    """The restart window: mark_dirty + flush must reach disk immediately."""
    writes = []
    deb = ChatIdCacheDebouncer(save_fn=lambda: writes.append("saved"))

    deb.mark_dirty()
    assert writes == [], "mark_dirty must stay debounced (not a synchronous write)"

    deb.flush()
    assert writes == ["saved"], "flush must persist the pending write"


def test_debouncer_flush_is_a_noop_when_clean():
    writes = []
    deb = ChatIdCacheDebouncer(save_fn=lambda: writes.append("saved"))
    deb.flush()
    assert writes == []


def test_debouncer_flush_twice_writes_once():
    writes = []
    deb = ChatIdCacheDebouncer(save_fn=lambda: writes.append("saved"))
    deb.mark_dirty()
    deb.flush()
    deb.flush()
    assert writes == ["saved"]


def test_debouncer_flush_swallows_persist_errors():
    """atexit must not raise: a failed persist cannot abort the rest of shutdown."""
    def boom():
        raise OSError("disk full")

    deb = ChatIdCacheDebouncer(save_fn=boom)
    deb.mark_dirty()
    deb.flush()  # must not raise


def test_user_store_registers_flush_at_exit(monkeypatch, tmp_path):
    """The store wires its debouncer's flush into atexit at construction."""
    import atexit

    registered = []
    real_register = atexit.register
    monkeypatch.setattr(
        atexit, "register", lambda fn, *a, **k: registered.append(fn) or fn
    )
    try:
        from owner.feishu.user_store import FeishuUserStore

        store = FeishuUserStore(cache_path=tmp_path / "cache.json")
    finally:
        monkeypatch.setattr(atexit, "register", real_register)

    assert store._debouncer.flush in registered, (
        "FeishuUserStore must register debouncer.flush with atexit, or an orderly "
        "restart inside the 5s debounce window drops the newest chat_id mapping"
    )
