"""Unit tests for owner/feishu/card_sender._resolve_receive_target.

Covers chat_type normalization (p2p vs dm from upstream SessionSource),
case insensitivity, group untouched, DM missing open_id fail-open,
empty chat_id (auto_card legacy path), sender_open_id fallback/priority,
empty/falsy open_id values, None/empty metadata, and warning logging with context.
"""

import logging

from owner.feishu.card_sender import _resolve_receive_target


def test_resolve_receive_target_chat_type_normalized():
    """DM 场景下 chat_type 既可能是 'p2p'（原始事件）也可能是 'dm'（SessionSource 归一化后），都要走 DM 分支"""
    # chat_type="p2p" + 有 open_id → (open_id, "open_id")
    assert _resolve_receive_target("oc_xxx", {"chat_type": "p2p", "open_id": "ou_yyy"}) == ("ou_yyy", "open_id")
    # chat_type="dm" + 有 open_id → (open_id, "open_id")
    assert _resolve_receive_target("oc_xxx", {"chat_type": "dm", "open_id": "ou_yyy"}) == ("ou_yyy", "open_id")
    # group + 有 open_id → (chat_id, "chat_id")
    assert _resolve_receive_target("oc_xxx", {"chat_type": "group", "open_id": "ou_yyy"}) == ("oc_xxx", "chat_id")
    # DM + 无 open_id → (chat_id, "chat_id") + warning (fail-open, does not raise)
    assert _resolve_receive_target("oc_xxx", {"chat_type": "dm"}) == ("oc_xxx", "chat_id")
    # 空 chat_id + 有 open_id（auto_card 退化场景，adapter._chat_id 为空串）→ (open_id, "open_id")
    assert _resolve_receive_target("", {"chat_type": "dm", "open_id": "ou_yyy"}) == ("ou_yyy", "open_id")


def test_resolve_receive_target_case_insensitive():
    assert _resolve_receive_target("oc_xxx", {"chat_type": "DM", "open_id": "ou_yyy"}) == ("ou_yyy", "open_id")
    assert _resolve_receive_target("oc_xxx", {"chat_type": "P2P", "open_id": "ou_yyy"}) == ("ou_yyy", "open_id")


def test_resolve_receive_target_none_metadata():
    """metadata=None / 空 dict / 缺 chat_type 三种空形态都安全 fall-through"""
    assert _resolve_receive_target("oc_xxx", None) == ("oc_xxx", "chat_id")
    assert _resolve_receive_target("oc_xxx", {}) == ("oc_xxx", "chat_id")
    assert _resolve_receive_target("oc_xxx", {"open_id": "ou_xxx"}) == ("oc_xxx", "chat_id")


def test_resolve_receive_target_sender_open_id_fallback_and_priority():
    """DM 场景下 open_id 优先；缺失/空 open_id 时回退 sender_open_id；两者都有时优先 open_id"""
    # 仅 sender_open_id → 用 sender
    assert _resolve_receive_target("oc_xxx", {"chat_type": "dm", "sender_open_id": "ou_sender"}) == ("ou_sender", "open_id")
    assert _resolve_receive_target("oc_xxx", {"chat_type": "p2p", "sender_open_id": "ou_sender"}) == ("ou_sender", "open_id")

    # open_id 为空串 + sender_open_id → 回退 sender（or 链处理 falsy）
    assert _resolve_receive_target("oc_xxx", {"chat_type": "dm", "open_id": "", "sender_open_id": "ou_sender"}) == ("ou_sender", "open_id")

    # 两者都有 → 优先 open_id（代码中 open_id 先 or）
    assert _resolve_receive_target("oc_xxx", {"chat_type": "dm", "open_id": "ou_primary", "sender_open_id": "ou_sender"}) == ("ou_primary", "open_id")

    # open_id 为空 + 无 sender → 仍走 fail-open（和无 open_id 行为一致）
    assert _resolve_receive_target("oc_xxx", {"chat_type": "dm", "open_id": ""}) == ("oc_xxx", "chat_id")


def test_resolve_receive_target_dm_missing_open_id_logs_warning(caplog):
    """DM 缺 open_id（及 sender_open_id）时必须打带完整上下文的 warning（chat_id + metadata_keys）"""
    caplog.set_level(logging.WARNING)

    # 纯 DM 无任何 open 信息
    result = _resolve_receive_target("oc_xxx", {"chat_type": "dm"})
    assert result == ("oc_xxx", "chat_id")
    assert len(caplog.records) >= 1
    log_msg = caplog.records[-1].getMessage()
    assert "DM metadata missing open_id; falling back to chat_id (will likely 230001)" in log_msg
    assert "chat_id='oc_xxx'" in log_msg
    assert "metadata_keys=['chat_type']" in log_msg

    caplog.clear()

    # 有其他 metadata key 但无 open_id 系列
    result2 = _resolve_receive_target("oc_yyy", {"chat_type": "p2p", "session_key": "abc", "foo": 1})
    assert result2 == ("oc_yyy", "chat_id")
    log_msg2 = caplog.records[-1].getMessage()
    assert "chat_id='oc_yyy'" in log_msg2
    assert "'foo'" in log_msg2 and "'session_key'" in log_msg2
