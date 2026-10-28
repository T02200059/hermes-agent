"""C27-resume-card: Feishu /resume interactive number card builders + dispatch."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from owner.feishu import resume_card as rc


def _sessions(n: int = 4):
    return [
        {"id": f"s{i}", "title": f"Session {i}", "preview": f"preview {i}"}
        for i in range(1, n + 1)
    ]


def test_build_resume_card_schema_and_buttons():
    with patch.object(rc, "t", side_effect=lambda key, **kw: {
        "gateway.resume.list_preview_suffix": f" — _{kw.get('preview')}_",
        "gateway.resume.list_item_numbered": f"{kw.get('index')}. **{kw.get('title')}**{kw.get('preview_part')}",
        "gateway.resume.list_footer_numbered": "footer",
        "gateway.resume.card_title": "Resume recent session",
    }.get(key, key)):
        card = rc.build_resume_card(
            header_text="HEADER",
            sessions=_sessions(4),
            session_key="feishu:dm:ou_x",
            source_dict={"platform": "feishu", "chat_id": "oc_1", "user_id": "ou_x"},
        )
    assert card["schema"] == "2.0"
    assert card["header"]["template"] == "blue"
    assert "Resume recent session" in card["header"]["title"]["content"]
    elements = card["body"]["elements"]
    assert elements[0]["tag"] == "markdown"
    assert "HEADER" in elements[0]["content"]
    rows = [e for e in elements if e.get("tag") == "column_set"]
    # 4 buttons → 2 rows (3 + 1)
    assert len(rows) == 2
    buttons = []
    for row in rows:
        for col in row["columns"]:
            buttons.extend(col["elements"])
    assert [b["text"]["content"] for b in buttons] == ["1", "2", "3", "4"]
    assert buttons[0]["type"] == "primary"
    assert buttons[1]["type"] == "default"
    assert buttons[0]["value"]["hermes_action"] == "resume_select"
    assert buttons[0]["value"]["resume_index"] == 1
    assert buttons[0]["value"]["session_title"] == "Session 1"
    assert buttons[0]["value"]["source_dict"]["chat_id"] == "oc_1"


def test_build_resume_card_ten_sessions_four_rows():
    with patch.object(rc, "t", side_effect=lambda key, **kw: key):
        card = rc.build_resume_card(
            header_text="H",
            sessions=_sessions(10),
            session_key="k",
            source_dict={},
        )
    rows = [e for e in card["body"]["elements"] if e.get("tag") == "column_set"]
    assert len(rows) == 4  # 3+3+3+1


@pytest.mark.asyncio
async def test_send_resume_card_success_via_rest():
    adapter = MagicMock()
    adapter._client = object()
    with patch(
        "owner.feishu.card_sender.send_card_via_rest",
        new_callable=AsyncMock,
        return_value=SimpleNamespace(success=True, message_id="mid-1", error=None),
    ) as send_rest:
        with patch.object(rc, "t", side_effect=lambda key, **kw: key):
            result = await rc.send_resume_card(
                adapter,
                chat_id="oc_1",
                header_text="H",
                sessions=_sessions(2),
                session_key="k",
                source_dict={"platform": "feishu", "chat_id": "oc_1"},
            )
    assert result.success is True
    send_rest.assert_awaited_once()
    adapter.send.assert_not_called()


@pytest.mark.asyncio
async def test_send_resume_card_falls_back_to_plain_text():
    adapter = MagicMock()
    adapter._client = object()
    adapter.send = AsyncMock()
    with patch(
        "owner.feishu.card_sender.send_card_via_rest",
        new_callable=AsyncMock,
        return_value=SimpleNamespace(success=False, message_id=None, error="boom"),
    ):
        with patch.object(rc, "t", side_effect=lambda key, **kw: {
            "gateway.resume.list_preview_suffix": "",
            "gateway.resume.list_item_numbered": f"{kw.get('index')}. {kw.get('title')}",
            "gateway.resume.list_footer_numbered": "footer",
            "gateway.resume.card_title": "title",
        }.get(key, key)):
            result = await rc.send_resume_card(
                adapter,
                chat_id="oc_1",
                header_text="H",
                sessions=_sessions(1),
                session_key="k",
            )
    assert result.success is False
    assert "plain text fallback" in (result.error or "")
    adapter.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_try_send_resume_card_list_injects_metadata():
    adapter = MagicMock()
    adapter.send_resume_card = AsyncMock()
    source = SimpleNamespace(
        chat_id="oc_1",
        chat_type="p2p",
        user_id="ou_owner",
        user_id_alt=None,
        to_dict=lambda: {"platform": "feishu", "chat_id": "oc_1", "user_id": "ou_owner"},
    )
    event = SimpleNamespace(metadata={"thread_id": "t1"})
    out = await rc.try_send_resume_card_list(
        adapter,
        source=source,
        event=event,
        titled_sessions=_sessions(2),
        session_key="k",
        header_text="H",
    )
    assert out == ""
    kwargs = adapter.send_resume_card.await_args.kwargs
    assert kwargs["metadata"]["chat_type"] == "p2p"
    assert kwargs["metadata"]["open_id"] == "ou_owner"
    assert kwargs["metadata"]["thread_id"] == "t1"
    assert kwargs["source_dict"]["user_id"] == "ou_owner"


def _mock_card_adapter():
    adapter = MagicMock()
    adapter._card_response.side_effect = (
        lambda card_data=None, **kw: SimpleNamespace(card=card_data)
    )
    return adapter


def test_build_done_card_has_no_buttons():
    card = rc.build_done_card(2, "Project A", "张三")
    assert card["schema"] == "2.0"
    assert card["header"]["template"] == "green"
    assert "Project A" in card["header"]["title"]["content"]
    body = card["body"]["elements"][0]["content"]
    assert "张三" in body
    assert "2" in body
    assert not any(
        e.get("tag") == "column_set" or e.get("tag") == "button"
        for e in card["body"]["elements"]
    )


def test_build_failed_card_submit_failed():
    card = rc.build_failed_card(
        reason="submit_failed", resume_index=1, session_title="S1"
    )
    assert card["header"]["template"] == "orange"
    assert "💡" in card["header"]["title"]["content"]
    assert "失败" in card["header"]["title"]["content"]
    assert "S1" in card["body"]["elements"][0]["content"]


def test_handle_resume_rejects_foreign_operator():
    adapter = _mock_card_adapter()
    adapter._loop_accepts_callbacks = MagicMock(return_value=True)
    submitted = []
    adapter._submit_on_loop = lambda loop, coro: (submitted.append(coro), True)[1]
    event = SimpleNamespace(operator=SimpleNamespace(open_id="ou_other"))
    source_dict = {"platform": "feishu", "chat_id": "oc_1", "user_id": "ou_owner", "chat_type": "dm"}
    with patch("gateway.session.SessionSource") as SS:
        SS.from_dict.return_value = SimpleNamespace(user_id="ou_owner", chat_id="oc_1")
        resp = rc.handle_resume_card_action(
            adapter=adapter,
            event=event,
            action_value={
                "resume_index": 1,
                "session_title": "Session 1",
                "source_dict": source_dict,
            },
            loop=object(),
        )
    assert submitted == []  # rejected before dispatch
    assert resp.card is not None
    assert "💡" in resp.card["header"]["title"]["content"]


def test_handle_resume_dispatches_and_freezes_card():
    adapter = _mock_card_adapter()
    adapter._loop_accepts_callbacks = MagicMock(return_value=True)
    submitted = []

    def _submit(_loop, coro):
        submitted.append(coro)
        coro.close()
        return True

    adapter._submit_on_loop = _submit
    event = SimpleNamespace(operator=SimpleNamespace(open_id="ou_owner"))
    source_dict = {"platform": "feishu", "chat_id": "oc_1", "user_id": "ou_owner", "chat_type": "dm"}
    fake_source = SimpleNamespace(user_id="ou_owner", chat_id="oc_1")
    with patch("gateway.session.SessionSource") as SS:
        SS.from_dict.return_value = fake_source
        with patch(
            "owner.feishu.sender_name_helpers.operator_display_name",
            return_value="小明",
        ):
            resp = rc.handle_resume_card_action(
                adapter=adapter,
                event=event,
                action_value={
                    "resume_index": 2,
                    "session_title": "Session 2",
                    "source_dict": source_dict,
                },
                loop=object(),
            )
    assert len(submitted) == 1
    assert resp.card["header"]["template"] == "green"
    assert "Session 2" in resp.card["header"]["title"]["content"]
    assert "小明" in resp.card["body"]["elements"][0]["content"]
    assert not any(
        e.get("tag") == "column_set" or e.get("tag") == "button"
        for e in resp.card["body"]["elements"]
    )


def test_handle_resume_submit_failed_returns_failure_card():
    adapter = _mock_card_adapter()
    adapter._loop_accepts_callbacks = MagicMock(return_value=True)
    closed = []

    def _submit(_loop, coro):
        closed.append(coro)
        coro.close()
        return False

    adapter._submit_on_loop = _submit
    event = SimpleNamespace(operator=SimpleNamespace(open_id="ou_owner"))
    source_dict = {"platform": "feishu", "chat_id": "oc_1", "user_id": "ou_owner", "chat_type": "dm"}
    with patch("gateway.session.SessionSource") as SS:
        SS.from_dict.return_value = SimpleNamespace(user_id="ou_owner", chat_id="oc_1")
        with patch(
            "owner.feishu.sender_name_helpers.operator_display_name",
            return_value="小明",
        ):
            resp = rc.handle_resume_card_action(
                adapter=adapter,
                event=event,
                action_value={
                    "resume_index": 3,
                    "session_title": "Session 3",
                    "source_dict": source_dict,
                },
                loop=object(),
            )
    assert len(closed) == 1
    assert resp.card["header"]["template"] == "orange"
    assert "💡" in resp.card["header"]["title"]["content"]
    assert "失败" in resp.card["header"]["title"]["content"]


def test_dispatch_resume_card_action_delegates():
    adapter = MagicMock()
    with patch.object(rc, "handle_resume_card_action", return_value="ok") as handle:
        out = rc.dispatch_resume_card_action(
            adapter,
            event=SimpleNamespace(),
            action_value={"resume_index": 1, "hermes_action": "resume_select"},
            loop=None,
        )
    assert out == "ok"
    handle.assert_called_once()


def test_adapter_exposes_send_resume_card():
    from plugins.platforms.feishu.adapter import FeishuAdapter

    assert hasattr(FeishuAdapter, "send_resume_card")
    assert hasattr(FeishuAdapter, "_handle_resume_card_action")
