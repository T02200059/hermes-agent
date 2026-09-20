"""飞书告警卡（notice card）：状态类告警在 auto-card 路径上带 header 标题。

背景：``agent._emit_warning`` → ``status_callback`` → ``adapter.send`` 这条
链路会被 ``try_auto_card`` 包成 interactive card，但 ``make_auto_card`` 只有
body、没有 header —— 告警和普通长回复在飞书里长得一模一样。本组测试锁定
``owner.feishu.auto_card`` 的 notice-card 分支：命中规则前缀 → 带 header，
其余消息 → 维持原样（无 header）。

不联网，不导入 live feishu adapter。
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from owner.feishu import auto_card

# stream_guard._build_message 的真实告警文案（warn_only 灰度形态）
_STREAM_GUARD_ALERT = (
    "⚠️ [stream-guard] 检测到生成退化（思考/输出阶段边界循环），灰度观察模式，本轮未中止。\n"
    "   判定：阶段终止语 22.4/KB、风格签名 ×14.9（基线 1.0/KB）、零进展 0；命中 2 项信号（阈值 2）\n"
    "   窗口 1205 字符；通道 text；模型 deepseek-v4.1-flash"
)

_PLAIN_LONG = "普通长回复。\n" * 30


# ---------------------------------------------------------------------------
# 规则匹配
# ---------------------------------------------------------------------------

def test_default_rules_match_stream_guard_alert():
    rule = auto_card.match_notice_rule(_STREAM_GUARD_ALERT)
    assert rule is not None
    assert rule["title"] == "⚠️ [stream-guard] 生成退化告警"
    assert rule["template"] == "orange"


def test_leading_whitespace_still_matches():
    """format_message() 会 strip，但上游可能的缩进不应破坏匹配。"""
    assert auto_card.match_notice_rule("\n  " + _STREAM_GUARD_ALERT) is not None


def test_plain_text_does_not_match():
    assert auto_card.match_notice_rule(_PLAIN_LONG) is None
    assert auto_card.match_notice_rule("") is None


def test_progress_explainer_notice_rule_pins_prefix():
    """[owner] progress_explainer 旁白前缀与本规则表防漂移锚点。

    dispatcher 投递文案 = prompt.PREFIX + 旁白正文；本规则的 prefix 须与
    PREFIX 字面一致，否则旁白在飞书上静默退回无标题卡片（fail-open，
    无报错——唯一护栏就是这条测试）。
    """
    from owner.progress_explainer.prompt import PREFIX

    rule = auto_card.match_notice_rule(PREFIX + "正在检索日志，稍候。")
    assert rule is not None
    assert rule["prefix"] == PREFIX
    assert rule["title"] == "🧭 进度旁白"
    assert rule["template"] == "blue"
    # 完整投递形态（含 fact_line）也应命中
    assert auto_card.match_notice_rule(PREFIX + "正文\nterminal — iteration 3/8") is not None


def test_embedded_prefix_mid_body_does_not_match():
    """前缀必须在**开头** —— 正文里引用告警文案的正常回复不该被套告警标题。"""
    quoted = "下面是我对这条告警的解读：\n⚠️ [stream-guard] 检测到生成退化 ...\n以上。"
    assert auto_card.match_notice_rule(quoted) is None


# ---------------------------------------------------------------------------
# 卡片构造
# ---------------------------------------------------------------------------

def test_notice_card_has_header_and_body():
    rule = auto_card.match_notice_rule(_STREAM_GUARD_ALERT)
    assert rule is not None
    card = auto_card.make_notice_card(_STREAM_GUARD_ALERT, rule)

    assert card["schema"] == "2.0"
    assert card["header"]["title"] == {
        "content": "⚠️ [stream-guard] 生成退化告警",
        "tag": "plain_text",
    }
    assert card["header"]["template"] == "orange"
    body = card["body"]["elements"][0]["content"]
    # strip_prefix：标题已表达的部分不再在正文首行重复
    assert not body.startswith("⚠️ [stream-guard]")
    assert body.startswith("检测到生成退化（")
    # 正文其余行完整保留
    assert "窗口 1205 字符" in body


def test_auto_card_still_has_no_header():
    """对照组：非告警正文走原路径，结构不变（无 header 键）。"""
    card = auto_card.make_auto_card(_PLAIN_LONG)
    assert "header" not in card


def test_strip_prefix_false_keeps_full_body():
    rule = dict(auto_card.get_notice_rules()[0], strip_prefix=False)
    card = auto_card.make_notice_card(_STREAM_GUARD_ALERT, rule)
    assert card["body"]["elements"][0]["content"] == _STREAM_GUARD_ALERT


def test_body_never_emptied_when_text_is_prefix_only():
    rule = auto_card.get_notice_rules()[0]
    card = auto_card.make_notice_card(rule["prefix"], rule)
    assert card["body"]["elements"][0]["content"].strip()


# ---------------------------------------------------------------------------
# patch.yaml 覆盖
# ---------------------------------------------------------------------------

def test_patch_yaml_overrides_default_rules():
    override = {
        "feishu_card": {
            "notice_titles": [
                {"prefix": "🔥 custom", "title": "自定义告警", "template": "red"}
            ]
        }
    }
    with patch.object(auto_card, "_load_patch_owner_config", return_value=override):
        assert auto_card.match_notice_rule("🔥 custom 出事了") is not None
        # 默认规则被替换（不是追加）
        assert auto_card.match_notice_rule(_STREAM_GUARD_ALERT) is None


def test_empty_rule_list_disables_notice_cards():
    with patch.object(
        auto_card, "_load_patch_owner_config", return_value={"feishu_card": {"notice_titles": []}}
    ):
        assert auto_card.match_notice_rule(_STREAM_GUARD_ALERT) is None


def test_malformed_rule_list_falls_back_to_defaults():
    with patch.object(
        auto_card, "_load_patch_owner_config", return_value={"feishu_card": {"notice_titles": "oops"}}
    ):
        assert auto_card.match_notice_rule(_STREAM_GUARD_ALERT) is not None


def test_rule_missing_prefix_is_skipped():
    override = {
        "feishu_card": {
            "notice_titles": [{"title": "无前缀"}, {"prefix": "✅ ok", "title": "有前缀"}]
        }
    }
    with patch.object(auto_card, "_load_patch_owner_config", return_value=override):
        assert auto_card.match_notice_rule("✅ ok 完成") is not None
        assert auto_card.match_notice_rule("无前缀 文本") is None


# ---------------------------------------------------------------------------
# try_auto_card 端到端
# ---------------------------------------------------------------------------

class _FakeAdapter:
    """只暴露 try_auto_card 用到的面：send_card + 可选 lock。"""

    def __init__(self):
        self.sent = []

    async def send_card(self, chat_id, card, metadata=None):
        self.sent.append(card)

        class _R:
            success = True
            message_id = "om_test"
            error = None

        return _R()


def _run_auto_card(adapter, text, **kwargs):
    with patch.object(auto_card, "is_feishu_streaming_disabled", return_value=True):
        return asyncio.run(
            auto_card.try_auto_card(adapter, text, {}, chat_id="oc_test", **kwargs)
        )


def test_try_auto_card_wraps_alert_in_header_card():
    adapter = _FakeAdapter()
    result = _run_auto_card(adapter, _STREAM_GUARD_ALERT)

    assert result is not None and result.success
    assert len(adapter.sent) == 1
    card = adapter.sent[0]
    assert card["header"]["title"]["content"] == "⚠️ [stream-guard] 生成退化告警"
    assert card["header"]["template"] == "orange"
    assert not card["body"]["elements"][0]["content"].startswith("⚠️ [stream-guard]")


def test_try_auto_card_leaves_plain_long_text_headerless():
    adapter = _FakeAdapter()
    _run_auto_card(adapter, _PLAIN_LONG)

    assert len(adapter.sent) == 1
    assert "header" not in adapter.sent[0]


def test_try_auto_card_alert_shorter_than_threshold_falls_through():
    """阈值以下不建卡（退回纯文本），既有行为不被 notice-card 分支改变。"""
    adapter = _FakeAdapter()
    with patch.object(auto_card, "get_auto_card_threshold", return_value=10_000):
        result = _run_auto_card(adapter, _STREAM_GUARD_ALERT)
    assert result is None
    assert adapter.sent == []