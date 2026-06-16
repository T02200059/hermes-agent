"""Unit tests for owner/feishu/card_sender._resolve_receive_target.

Covers chat_type normalization (p2p vs dm from upstream SessionSource),
case insensitivity, group untouched, DM missing open_id fail-open,
and empty chat_id (auto_card legacy path where adapter._chat_id=="").
"""

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
