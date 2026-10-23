"""Guard: 飞书多 profile 路由与归属校验（偿还 `feishu-profile-routing` 债务）。

2026-10-23 新基线守卫。此前登记在 `owner/validation/coverage_gaps.txt`：

    feishu-profile-routing  tests/owner/test_feishu_profile_routing.py removed
    2026-10-20; whitelist bypass, chat-over-user priority, restart re-resolution unpinned

按 §2.2.0 偿还策略撤销登记。

## 三条不变量

1. **白名单只在 DM 生效**。群聊里跳过白名单，落到 `user_profile_routes` →
   `default_profile`。若白名单在群聊也生效，一个用户只要在私聊里被加白，
   他在**任何群**里的消息都会绕过群的路由配置 —— 那是把 DM 的信任级别挪用到了群。
2. **chat 优先于 user**。同一 profile 里同时配了 `chat_profile_routes[chat_id]` 与
   `user_profile_routes[open_id]` 时，前者胜。反了会让"这个群该去 A 容器"被
   "这个人在 B 容器"覆盖 —— 群里的协作上下文落到个人容器。
3. **归属校验的失败方向是不对称的**（T2-9，刻意设计）：
   - 两侧都识别出且不一致 → **拒绝**（唯一该拒的情况）
   - 目标缺失（旧发送方）→ 放行 + 告警一次
   - 自身身份不可判定 → 放行 + 告警一次

   后两者若改成拒绝，一次版本错配或一个没打标签的容器就会让整个多 profile
   路由**全线 503** —— 比它要防的误路由更糟。

## 一个必须钉住的坑：白名单不是认证绕过

`is_api_identity_whitelisted` 只决定「不反代」（交 root 本体处理），**不决定
免认证**。T2-6 之前白名单命中会 early return，于是"由 root 处理"被读成"无需
二次因子"—— 而 identity 头是任何人能设的声明。本文件的用例钉住"函数语义只到
路由为止"，中间件的顺序由 `test_owner_identity_routing_middleware.py` 钉。
"""

from __future__ import annotations

import pytest

from owner.feishu import profile_routing as pr


# ── 测试夹具：用固定配置替换配置文件读取 ──────────────────────────────────

@pytest.fixture
def routing(monkeypatch):
    """安装一个可控的 routing 配置；返回 setter。

    直接替换 `_load_routing_config` 而不是写临时 yaml：本文件测的是**判定逻辑**，
    不是配置解析（那是 `owner/patch_config.py` 的事，另有测试）。
    """
    state: dict = {"cfg": {}}
    monkeypatch.setattr(pr, "_load_routing_config", lambda: state["cfg"], raising=True)
    monkeypatch.setattr(pr, "_ownership_notices", set(), raising=True)
    monkeypatch.delenv(pr.CONTAINER_PROFILE_ENV, raising=False)

    def _set(cfg: dict) -> None:
        state["cfg"] = cfg

    _set.__dict__["state"] = state
    return _set


DM = "p2p"
GROUP = "group"


# ── 路由优先级 ────────────────────────────────────────────────────────────

class TestRoutePriority:
    def test_no_config_returns_none(self, routing):
        routing({})
        assert pr.resolve_profile_route("chat1", "ou_a") is None

    def test_chat_route_wins_over_user_route(self, routing):
        """**核心不变量**：chat 优先于 user。

        反了的话，一个被配置到个人容器的用户发出的群消息会离开群的协作上下文。
        """
        routing({
            "chat_profile_routes": {"chat1": "group-bot"},
            "user_profile_routes": {"ou_a": "personal-bot"},
            "profile_endpoints": {
                "group-bot": {"url": "http://g:1", "api_key": "kg"},
                "personal-bot": {"url": "http://p:1", "api_key": "kp"},
            },
        })
        got = pr.resolve_profile_route("chat1", "ou_a")
        assert got is not None
        assert got[0] == "group-bot", "user 路由覆盖了 chat 路由"
        assert got[1] == "http://g:1"

    def test_user_route_used_when_no_chat_route(self, routing):
        routing({
            "user_profile_routes": {"ou_a": "personal-bot"},
            "profile_endpoints": {"personal-bot": {"url": "http://p:1", "api_key": "kp"}},
        })
        got = pr.resolve_profile_route("chat1", "ou_a")
        assert got == ("personal-bot", "http://p:1", "kp")

    def test_default_profile_is_the_last_resort(self, routing):
        routing({
            "default_profile": "fallback",
            "profile_endpoints": {"fallback": {"url": "http://f:1", "api_key": ""}},
        })
        got = pr.resolve_profile_route("chat9", "ou_unknown")
        assert got == ("fallback", "http://f:1", "")

    def test_no_route_and_no_default_returns_none(self, routing):
        """返回 None = 主网关处理，这是正常路径而非错误。"""
        routing({"user_profile_routes": {"ou_a": "p"}, "profile_endpoints": {}})
        assert pr.resolve_profile_route("chat1", "ou_other") is None

    def test_empty_chat_id_skips_chat_routes(self, routing):
        """`chat_id` 为空时不能拿空串去查表（可能撞上一个 "" 键）。"""
        routing({
            "chat_profile_routes": {"": "wrong"},
            "user_profile_routes": {"ou_a": "right"},
            "profile_endpoints": {
                "wrong": {"url": "http://w:1"}, "right": {"url": "http://r:1"},
            },
        })
        got = pr.resolve_profile_route("", "ou_a")
        assert got is not None and got[0] == "right"


# ── 白名单：DM only ──────────────────────────────────────────────────────

class TestWhitelistIsDmOnly:
    def _cfg(self):
        return {
            "whitelist": ["ou_vip"],
            "user_profile_routes": {"ou_vip": "personal"},
            "profile_endpoints": {"personal": {"url": "http://p:1", "api_key": "k"}},
        }

    def test_whitelisted_dm_goes_to_root(self, routing):
        """DM 里白名单命中 → None（主网关处理）。"""
        routing(self._cfg())
        assert pr.resolve_profile_route("chat1", "ou_vip", DM) is None

    def test_whitelisted_user_in_a_group_is_still_routed(self, routing):
        """**关键不变量**：群聊里白名单不生效，仍按 user 路由走。

        若白名单在群聊也生效，私聊被加白的用户在任何群都绕过群路由 —— 群里的
        消息落到主网关，与其它成员的处理路径不一致。
        """
        routing(self._cfg())
        got = pr.resolve_profile_route("chat_group", "ou_vip", GROUP)
        assert got is not None, "群聊里白名单被误用了"
        assert got[0] == "personal"

    def test_non_whitelisted_dm_is_routed(self, routing):
        """非白名单的 DM 用户正常路由（不会被白名单逻辑误伤）。"""
        routing({
            "whitelist": ["ou_vip"],
            "user_profile_routes": {"ou_vip": "personal", "ou_other": "personal"},
            "profile_endpoints": {"personal": {"url": "http://p:1", "api_key": "k"}},
        })
        got = pr.resolve_profile_route("chat1", "ou_other", DM)
        assert got is not None and got[0] == "personal"

    def test_whitelist_as_a_bare_string_is_honoured(self, routing):
        """单值配置（字符串）与列表同义 —— 手写 yaml 时很容易写成标量。"""
        routing({
            "whitelist": "ou_vip",
            "user_profile_routes": {"ou_vip": "personal"},
            "profile_endpoints": {"personal": {"url": "http://p:1"}},
        })
        assert pr.resolve_profile_route("c", "ou_vip", DM) is None

    def test_whitelist_with_invalid_type_is_treated_as_empty(self, routing):
        """配置写错类型时不能崩，也不能把人放进来。"""
        routing({
            "whitelist": {"ou_vip": True},   # dict：非法
            "user_profile_routes": {"ou_vip": "personal"},
            "profile_endpoints": {"personal": {"url": "http://p:1"}},
        })
        got = pr.resolve_profile_route("c", "ou_vip", DM)
        assert got is not None, "非法类型的白名单被当成了命中"


# ── endpoint 配置错误：一律 None（交主网关），不炸 ────────────────────────

class TestEndpointMisconfig:
    def test_missing_endpoint_for_resolved_profile_returns_none(self, routing):
        routing({
            "user_profile_routes": {"ou_a": "ghost"},
            "profile_endpoints": {},
        })
        assert pr.resolve_profile_route("c", "ou_a") is None

    def test_endpoint_without_url_returns_none(self, routing):
        routing({
            "user_profile_routes": {"ou_a": "p"},
            "profile_endpoints": {"p": {"api_key": "k"}},
        })
        assert pr.resolve_profile_route("c", "ou_a") is None

    def test_legacy_plain_string_endpoint_is_supported(self, routing):
        """历史上 `profile_endpoints` 的值可以是裸 URL 字符串。"""
        routing({
            "user_profile_routes": {"ou_a": "p"},
            "profile_endpoints": {"p": "http://legacy:1"},
        })
        assert pr.resolve_profile_route("c", "ou_a") == ("p", "http://legacy:1", "")

    def test_non_dict_endpoints_returns_none(self, routing):
        routing({
            "user_profile_routes": {"ou_a": "p"},
            "profile_endpoints": ["not", "a", "dict"],
        })
        assert pr.resolve_profile_route("c", "ou_a") is None


# ── 按名字解析（改名后仍能重解析）─────────────────────────────────────────

class TestResolveByName:
    def test_resolves_an_explicit_profile(self, routing):
        routing({"profile_endpoints": {"p": {"url": "http://p:1", "api_key": "k"}}})
        assert pr.resolve_profile_route_by_name("p") == ("p", "http://p:1", "k")

    def test_unknown_name_returns_none(self, routing):
        routing({"profile_endpoints": {}})
        assert pr.resolve_profile_route_by_name("ghost") is None

    def test_empty_name_returns_none(self, routing):
        routing({"profile_endpoints": {"p": {"url": "http://p:1"}}})
        assert pr.resolve_profile_route_by_name("") is None

    def test_reresolves_after_endpoint_changes(self, routing):
        """**重启重解析**：同一名字在配置变更后应给出新 endpoint。

        如果实现把结果缓存住了，改配置后旧 URL 会被一直用下去 —— 容器迁移后
        流量仍打向旧地址，且没有任何报错。
        """
        routing({"profile_endpoints": {"p": {"url": "http://old:1"}}})
        first = pr.resolve_profile_route_by_name("p")
        assert first is not None and first[1] == "http://old:1"

        routing({"profile_endpoints": {"p": {"url": "http://new:1", "api_key": "k2"}}})
        second = pr.resolve_profile_route_by_name("p")
        assert second == ("p", "http://new:1", "k2"), "配置变更后仍在用旧 endpoint"


# ── API identity 路由与白名单 ─────────────────────────────────────────────

class TestApiIdentity:
    def test_identity_route_resolves(self, routing):
        routing({
            "identity_routes": {"yangtb": "p"},
            "profile_endpoints": {"p": {"url": "http://p:1", "api_key": "k"}},
        })
        assert pr.resolve_api_identity_route("yangtb") == ("p", "http://p:1", "k")

    def test_unknown_identity_returns_none(self, routing):
        routing({"identity_routes": {"a": "p"}, "profile_endpoints": {"p": {"url": "u"}}})
        assert pr.resolve_api_identity_route("b") is None

    def test_empty_identity_returns_none(self, routing):
        routing({"identity_routes": {"": "p"}, "profile_endpoints": {"p": {"url": "u"}}})
        assert pr.resolve_api_identity_route("") is None

    def test_identity_whitelist_membership(self, routing):
        routing({"identity_whitelist": ["yangtb"]})
        assert pr.is_api_identity_whitelisted("yangtb") is True
        assert pr.is_api_identity_whitelisted("other") is False

    def test_identity_whitelist_invalid_type_is_empty(self, routing):
        routing({"identity_whitelist": 42})
        assert pr.is_api_identity_whitelisted("yangtb") is False

    def test_identity_whitelist_scalar_string(self, routing):
        routing({"identity_whitelist": "yangtb"})
        assert pr.is_api_identity_whitelisted("yangtb") is True


# ── 归属校验（T2-9）：不对称失败方向 ─────────────────────────────────────

class TestInboundOwnership:
    def test_matching_target_is_accepted(self, routing, monkeypatch):
        monkeypatch.setenv(pr.CONTAINER_PROFILE_ENV, "p1")
        routing({})
        assert pr.verify_inbound_target_profile({pr.TARGET_PROFILE_KEY: "p1"}) is None

    def test_mismatched_target_is_rejected_with_a_reason(self, routing, monkeypatch):
        """唯一该拒绝的情况：两侧都识别出且不一致。

        返回原因字符串而不是布尔 —— 调用方要把它变成显式 409，让误配
        以"可归因的失败"出现，而不是对话悄悄落进错误容器。
        """
        monkeypatch.setenv(pr.CONTAINER_PROFILE_ENV, "p1")
        routing({})
        reason = pr.verify_inbound_target_profile({pr.TARGET_PROFILE_KEY: "p2"})
        assert reason is not None
        assert "p2" in reason and "p1" in reason

    def test_absent_target_is_accepted(self, routing, monkeypatch):
        """旧发送方不带 `target_profile` → 放行。

        改拒会让版本错配期间的流量全灭 —— 比误路由更糟。
        """
        monkeypatch.setenv(pr.CONTAINER_PROFILE_ENV, "p1")
        routing({})
        assert pr.verify_inbound_target_profile({}) is None

    def test_unknown_own_identity_is_accepted(self, routing, monkeypatch):
        """自身身份不可判定 → 放行。

        猜一个身份会让"猜错 → 全拒"或"猜对 → 检查形同虚设"，两者都不可接受。
        """
        monkeypatch.delenv(pr.CONTAINER_PROFILE_ENV, raising=False)
        routing({})
        assert pr.verify_inbound_target_profile({pr.TARGET_PROFILE_KEY: "p2"}) is None

    def test_non_dict_body_is_accepted(self, routing):
        assert pr.verify_inbound_target_profile("not-a-dict") is None
        assert pr.verify_inbound_target_profile(None) is None

    def test_identity_from_config_fallback(self, routing, monkeypatch):
        """不设 env 时，`user_routing.container_profile` 提供身份。"""
        monkeypatch.delenv(pr.CONTAINER_PROFILE_ENV, raising=False)
        routing({pr.CONTAINER_PROFILE_CONFIG_KEY: "p1"})
        assert pr.verify_inbound_target_profile({pr.TARGET_PROFILE_KEY: "p1"}) is None
        assert pr.verify_inbound_target_profile({pr.TARGET_PROFILE_KEY: "p2"}) is not None

    def test_env_takes_precedence_over_config(self, routing, monkeypatch):
        monkeypatch.setenv(pr.CONTAINER_PROFILE_ENV, "from-env")
        routing({pr.CONTAINER_PROFILE_CONFIG_KEY: "from-config"})
        assert pr.container_profile_identity() == "from-env"

    def test_no_guess_when_neither_is_set(self, routing, monkeypatch):
        """**关键**：不得回退到 "default" 或当前 profile 名。

        猜测会让检查要么全拒（猜错）要么形同虚设（恰好都匹配）。
        """
        monkeypatch.delenv(pr.CONTAINER_PROFILE_ENV, raising=False)
        routing({})
        assert pr.container_profile_identity() is None

    def test_warning_fires_once_per_process(self, routing, monkeypatch):
        """重复的结构性问题只告警一次，否则每个请求刷一行。"""
        monkeypatch.setenv(pr.CONTAINER_PROFILE_ENV, "p1")
        routing({})
        msgs: list = []
        monkeypatch.setattr(pr.logger, "warning", lambda f, *a: msgs.append(f % a if a else f))

        for _ in range(5):
            pr.verify_inbound_target_profile({})

        absent = [m for m in msgs if "target_profile" in str(m)]
        assert len(absent) == 1, f"告警响了 {len(absent)} 次（应恰好 1 次）"

    def test_reset_notices_rearms_the_warning(self, routing, monkeypatch):
        monkeypatch.setenv(pr.CONTAINER_PROFILE_ENV, "p1")
        routing({})
        msgs: list = []
        monkeypatch.setattr(pr.logger, "warning", lambda f, *a: msgs.append(f % a if a else f))

        pr.verify_inbound_target_profile({})
        pr.reset_ownership_notices()
        pr.verify_inbound_target_profile({})

        assert len(msgs) == 2, "reset 之后应重新告警一次"
