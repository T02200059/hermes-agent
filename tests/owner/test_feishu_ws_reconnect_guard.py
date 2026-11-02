"""Feishu WS reconnect guard: policy, single-flight, cap, conn-url timeout wrap."""

from __future__ import annotations

import asyncio
import types
from types import SimpleNamespace

import pytest

from owner.feishu import ws_reconnect_guard as guard


@pytest.fixture(autouse=True)
def _clear_states():
    guard.clear_states()
    yield
    guard.clear_states()


def test_supervisor_wait_first_vs_interval():
    p = guard.WsReconnectPolicy(
        first_supervisor_retry_s=30.0, supervisor_retry_interval_s=600.0
    )
    assert guard.supervisor_wait_s(0, p) == 30.0
    assert guard.supervisor_wait_s(1, p) == 600.0
    assert guard.supervisor_wait_s(5, p) == 600.0


def test_should_stop_auto_retry():
    p = guard.WsReconnectPolicy(max_failures=3)
    assert not guard.should_stop_auto_retry(2, p)
    assert guard.should_stop_auto_retry(3, p)


def test_note_link_up_clears_stop_latch():
    adapter = object()
    st = guard._state_for(adapter)
    st.failures = 9
    st.stopped = True
    guard.note_link_up(adapter)
    assert st.failures == 0
    assert st.stopped is False


def test_apply_ws_client_overrides_forces_count_and_wraps(monkeypatch):
    monkeypatch.setattr(
        guard,
        "load_policy",
        lambda: guard.WsReconnectPolicy(
            enabled=True, sdk_reconnect_count=2, conn_url_timeout_s=7.0
        ),
    )
    client = SimpleNamespace(
        _reconnect_count=-1,
        _get_conn_url=lambda: "wss://example/ws",
    )
    guard.apply_ws_client_overrides(client, adapter=object())
    assert client._reconnect_count == 2
    assert getattr(client, "_owner_conn_url_wrapped", False) is True
    # shim installed; calling wrapped get_conn_url still works
    assert client._get_conn_url() == "wss://example/ws"


def test_supervise_rebuilds_then_caps(monkeypatch):
    monkeypatch.setattr(
        guard,
        "load_policy",
        lambda: guard.WsReconnectPolicy(
            enabled=True,
            first_supervisor_retry_s=0.01,
            supervisor_retry_interval_s=0.01,
            max_failures=2,
        ),
    )

    async def scenario():
        status = []
        stub = SimpleNamespace(
            _running=True,
            _ws_future=None,
            _ws_client=object(),
            connect_calls=0,
            connect_should_fail=99,
        )

        def write(context, **kw):
            status.append((context, kw.get("platform_state")))

        stub._write_runtime_status_safe = write

        async def _connect_websocket():
            stub.connect_calls += 1
            stub.connect_should_fail -= 1
            raise RuntimeError("simulated restart failure")

        stub._connect_websocket = _connect_websocket

        fut = asyncio.get_running_loop().create_future()
        fut.set_result(None)
        stub._ws_future = fut

        task = asyncio.ensure_future(guard.supervise_websocket_thread(stub))
        for _ in range(500):
            await asyncio.sleep(0.01)
            st = guard._state_for(stub)
            if st.stopped:
                break
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return stub, status, guard._state_for(stub)

    stub, status, st = asyncio.run(scenario())
    assert stub.connect_calls >= 2
    assert st.stopped is True
    assert st.failures >= 2
    assert any(c == "ws_reconnect_cap" for c, _ in status)


def test_supervise_single_flight(monkeypatch):
    monkeypatch.setattr(
        guard,
        "load_policy",
        lambda: guard.WsReconnectPolicy(
            enabled=True,
            first_supervisor_retry_s=0.01,
            supervisor_retry_interval_s=0.01,
            max_failures=50,
        ),
    )

    async def scenario():
        stub = SimpleNamespace(
            _running=True,
            _ws_future=None,
            _ws_client=object(),
            inflight_max=0,
            current=0,
            connect_calls=0,
        )
        stub._write_runtime_status_safe = lambda *a, **k: None

        async def _connect_websocket():
            stub.connect_calls += 1
            stub.current += 1
            stub.inflight_max = max(stub.inflight_max, stub.current)
            await asyncio.sleep(0.05)
            stub.current -= 1
            # leave a live undead future so supervisor parks on shield
            live = asyncio.get_running_loop().create_future()
            stub._ws_future = live

        stub._connect_websocket = _connect_websocket
        dead = asyncio.get_running_loop().create_future()
        dead.set_result(None)
        stub._ws_future = dead

        task = asyncio.ensure_future(guard.supervise_websocket_thread(stub))
        for _ in range(200):
            await asyncio.sleep(0.01)
            if stub.connect_calls >= 1 and stub._ws_future is not dead:
                if not stub._ws_future.done():
                    break
        stub._running = False
        stub._ws_client = None
        # complete live future so supervise can exit
        if stub._ws_future is not None and not stub._ws_future.done():
            stub._ws_future.set_result(None)
        try:
            await asyncio.wait_for(task, timeout=2.0)
        except TimeoutError:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        return stub

    stub = asyncio.run(scenario())
    assert stub.connect_calls >= 1
    assert stub.inflight_max == 1


def test_adapter_glue_delegates_supervise():
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "plugins/platforms/feishu/adapter.py"
    text = src.read_text(encoding="utf-8")
    assert "supervise_websocket_thread as _owner_supervise" in text
    assert "apply_ws_client_overrides" in text
    assert "note_link_up" in text
