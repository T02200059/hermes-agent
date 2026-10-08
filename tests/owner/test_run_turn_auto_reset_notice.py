"""T2-20 A3 簇 7b-3 —— ``gateway/run_turn.py::_hmwa_deliver_auto_reset_notice`` 的重置通知。

宿主 ``GatewayTurnMixin`` 未挂到 ``GatewayRunner`` 的 MRO 上，故这里直接驱动该方法**本体**
（规则 ⑪）：断言对象是**行为** —— 到底发不发、发哪条。

本簇是「**保我方**」：上游把这块从「policy 门 + 4 种原因 + 4 行 notice」窄化成
「只 `suspended` + 固定 3 行文案」（且它自己的 docstring 仍写着 *policy-gated*、`gateway/config.py`
里的策略配置也还在），故把 BASE 的行为重落进宿主。**上游的 sidecar 部分照取**
（`_AUTO_RESET_CONTEXT_NOTES`、`turn_sidecar_notes`、continuity note、`auto_reset_reason` 清理）。

注：`gateway.run._AUTO_RESET_CONTEXT_NOTES` 在我方当前 `run.py` 里**不存在**（上游新增的常量，
A4 才随上游 `run.py` 到位，见规则 ⑳），故测试里显式注入上游形态的单项目字典。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from gateway.config import Platform
from gateway.run_turn import GatewayTurnMixin
from gateway.session import SessionSource

# BASE（`00b2e03c80`）的硬编码英文 —— 本簇「保我方」的逐字基线（验收脚本再用 AST 复核一次）
BASE_NOTICE = (
    "◐ Session automatically reset ({reason}). Conversation history cleared.\n"
    "Use /resume to browse and restore a previous session.\n"
    "Adjust reset timing in config.yaml under session_reset."
)
BASE_REASON = {
    "suspended": "previous session was stopped or interrupted",
    "resume_pending_expired": "gateway restart recovery timed out",
    "daily": "daily schedule at {hour}:00",
    "idle": "inactive for {duration}",
}
# 上游 `gateway.run._AUTO_RESET_CONTEXT_NOTES` 的形态（**只有 suspended 一项** + 回退）
UP_CONTEXT_NOTES = {
    "suspended": "[System note: The user's previous session was stopped and suspended. "
                 "This is a fresh conversation with no prior context.]",
}


class _Policy:
    def __init__(self, *, notify=True, had_activity=True, idle_minutes=90, at_hour=4,
                 exclude=()):
        self.notify = notify
        self.idle_minutes = idle_minutes
        self.at_hour = at_hour
        self.notify_exclude_platforms = set(exclude)


class _FakeAdapter:
    def __init__(self):
        self.sent: list[str] = []

    async def send(self, *args, **kwargs):
        self.sent.append(args[1] if len(args) > 1 else kwargs.get("content", ""))


class _Runner(GatewayTurnMixin):
    def __init__(self, policy, *, had_activity=True):
        self._policy = policy
        self._had_activity = had_activity
        self.adapter = _FakeAdapter()
        self.session_store = SimpleNamespace(
            config=SimpleNamespace(get_reset_policy=lambda **kw: policy),
        )

    def _delivery_adapter_for(self, source):
        return self.adapter

    def _thread_metadata_for_source(self, source, event_message_id=None):
        return {}

    def _reset_notice_session_info(self, source):
        return ""


def _entry(reason):
    return SimpleNamespace(auto_reset_reason=reason, reset_has_activity=True)


def _source(platform=Platform.TELEGRAM):
    return SessionSource(platform=platform, chat_id="c1", user_id="u1", chat_type="dm")


def _drive(*, lang, reason, policy=None, had_activity=True, platform=Platform.TELEGRAM):
    policy = policy or _Policy()
    runner = _Runner(policy, had_activity=had_activity)
    entry = _entry(reason)
    entry.reset_had_activity = had_activity
    sidecar: list[str] = []
    import gateway.run as run_mod

    with patch.dict("os.environ", {"HERMES_LANGUAGE": lang}), \
         patch.object(run_mod, "_AUTO_RESET_CONTEXT_NOTES", UP_CONTEXT_NOTES, create=True), \
         patch("gateway.run_turn.build_channel_continuity_note", return_value=None):
        asyncio.run(
            runner._hmwa_deliver_auto_reset_notice(entry, _source(platform), sidecar)
        )
    return runner, entry, sidecar


def _notice(reason, **fmt):
    return BASE_NOTICE.format(reason=BASE_REASON[reason].format(**fmt))


# ------------------------------------------------------------------ 4 种原因 × 逐字
class TestReasonBranches:

    def test_suspended_verbatim(self):
        r, _e, sidecar = _drive(lang="en", reason="suspended")
        assert r.adapter.sent == [_notice("suspended")]
        assert sidecar == [UP_CONTEXT_NOTES["suspended"]]

    def test_resume_pending_expired_verbatim(self):
        r, _e, _s = _drive(lang="en", reason="resume_pending_expired")
        assert r.adapter.sent == [_notice("resume_pending_expired")]

    def test_daily_verbatim(self):
        r, _e, _s = _drive(lang="en", reason="daily", policy=_Policy(at_hour=4))
        assert r.adapter.sent == [_notice("daily", hour=4)]

    def test_idle_hours_and_minutes(self):
        r, _e, _s = _drive(lang="en", reason="idle", policy=_Policy(idle_minutes=90))
        assert r.adapter.sent == [_notice("idle", duration="1h 30m")]

    def test_idle_whole_hours(self):
        r, _e, _s = _drive(lang="en", reason="idle", policy=_Policy(idle_minutes=120))
        assert r.adapter.sent == [_notice("idle", duration="2h")]

    def test_idle_minutes_only(self):
        r, _e, _s = _drive(lang="en", reason="idle", policy=_Policy(idle_minutes=45))
        assert r.adapter.sent == [_notice("idle", duration="45m")]

    def test_localized(self):
        r, _e, _s = _drive(lang="zh", reason="daily", policy=_Policy(at_hour=4))
        assert r.adapter.sent and r.adapter.sent[0] != _notice("daily", hour=4)
        assert "会话已自动重置" in r.adapter.sent[0]


# ------------------------------------------------------------------ policy 门（上游删掉的那部分）
class TestPolicyGate:

    def test_idle_suppressed_when_policy_notify_off(self):
        r, _e, _s = _drive(lang="en", reason="idle", policy=_Policy(notify=False))
        assert r.adapter.sent == []

    def test_idle_suppressed_without_activity(self):
        r, _e, _s = _drive(lang="en", reason="idle", had_activity=False)
        assert r.adapter.sent == []

    def test_platform_excluded(self):
        r, _e, _s = _drive(
            lang="en", reason="daily",
            policy=_Policy(exclude={Platform.TELEGRAM.value}),
        )
        assert r.adapter.sent == []

    @pytest.mark.parametrize("reason", ["suspended", "resume_pending_expired"])
    def test_always_notify_regardless_of_policy(self, reason):
        """suspended / 重启恢复超时是「会话被静默换掉」，必须通知（不看 policy）。"""
        r, _e, _s = _drive(lang="en", reason=reason, policy=_Policy(notify=False))
        assert r.adapter.sent, f"{reason} 应无视 policy.notify 照常通知"


# ------------------------------------------------------------------ sidecar / 清理（取上游部分）
class TestUpstreamSidecarParts:

    def test_sidecar_note_appended(self):
        _r, _e, sidecar = _drive(lang="en", reason="suspended")
        assert len(sidecar) == 1 and "System note" in sidecar[0]

    def test_non_suspended_reason_uses_fallback_note(self):
        """上游的常量只有 `suspended` 一项，其余走 `.get(..., suspended)` 回退。"""
        _r, _e, sidecar = _drive(lang="en", reason="daily")
        assert sidecar == [UP_CONTEXT_NOTES["suspended"]]

    def test_reason_cleared_even_when_not_notified(self):
        _r, entry, _s = _drive(lang="en", reason="idle", policy=_Policy(notify=False))
        assert entry.auto_reset_reason is None

    def test_no_leftover_placeholders(self):
        for lang in ("en", "zh"):
            for reason in ("suspended", "resume_pending_expired", "daily", "idle"):
                r, _e, _s = _drive(lang=lang, reason=reason)
                assert r.adapter.sent
                assert "{" not in r.adapter.sent[0] and "gateway." not in r.adapter.sent[0]
