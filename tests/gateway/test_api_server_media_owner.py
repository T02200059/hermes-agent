"""Guard: GET /v1/media/{id} 的归属断言（T2-7 / T2-8 / T3-10）。

2026-10-23 重建。原文件在 `eee05c3090`（2026-10-20 摘除 715 个 owner 测试）被删，
但 `api_server.py` 的 `_media_owner_matches` docstring 一直声称
「pinned by ``tests/gateway/test_api_server_media_owner.py``」—— 引用指向一个
不存在的文件。更糟的是它既不在 `inventory.yaml`（无 `test_coverage` 断言）也不在
`coverage_gaps.txt`，两道关口都漏了，Check 7 一直报绿。

本文件重建为「记录事实」的守卫，而不是「宣布行为正确」的守卫。

## 一个必须纠正的旧断言（T3-10）

删掉的那版有一条：

    def test_ldap_identity_header_matches_a_routed_caller(self):
        matching = media_owner_token("sess-abc")
        assert _media_owner_matches(_Request(**{"X-Hermes-Identity": "sess-abc"}), matching)

它把 identity 头设成了 **session id 的值**，所以通过。真实 routed caller 发的是
登录名（`yangtb`），而注册摘要的是 session id —— 两者永不相等。那条测试证明的是
「这个分支可达」，不是「它能救回一个真实调用方」，属同义反复。

这里改为把该事实**正面钉住**（`TestIdentityBranchCannotRescueARoutedCaller`）：
identity 分支对真实调用方无效。任何"它能工作"的错觉都从这一条开始。

## 已接受的决策（不为它背书，只为让它可见）

「不声明任何身份头 → 放行」是 T2-7 明确接受的决策，记档于
`owner/docs/owner改动清单.md` §16.4。它有一条**必须被钉住的**性质：决策有两条独立
通路（下载侧未声明 / 注册侧无 owner），所以"只收紧下载侧"不构成修复。类名带
`Accepted` 是刻意的 —— 这些用例断言的是**已划定的边界**，让未来的收紧只能是有意为之
（改测试即改决策），不会作为某次重构的副作用悄悄发生。
"""

from __future__ import annotations

import hashlib

import pytest

pytest.importorskip("aiohttp")

from gateway.platforms.api_server import APIServerAdapter
from gateway.platforms.api_server_media import (
    ApiMediaStore,
    finalize_api_media,
    media_owner_token,
)

SESSION = "20261023_20260920_abc123"
LOGIN = "yangtb"


class _Request:
    """Minimal stand-in: the check only reads ``request.headers.get``."""

    def __init__(self, **headers: str) -> None:
        self.headers = headers


def _matches(**headers: str) -> bool:
    return APIServerAdapter._media_owner_matches(
        _Request(**headers), media_owner_token(SESSION)
    )


# ── 会命中的路径 ────────────────────────────────────────────────────────────

class TestSessionHeaderMatching:
    def test_same_session_header_matches(self):
        """客户端把服务器给它的 session id 回传 → 命中。

        这是注册侧唯一摘要过的值，因此也是**唯一**能命中的路径。
        """
        assert _matches(**{"X-Hermes-Session-Id": SESSION}) is True

    def test_different_session_header_does_not_match(self):
        assert _matches(**{"X-Hermes-Session-Id": "someone-else"}) is False

    def test_blank_session_header_counts_as_unasserted(self):
        """空白等于没声明 —— 走放行，而不是走"不匹配"。"""
        assert _matches(**{"X-Hermes-Session-Id": "   "}) is True

    def test_extra_correct_header_rescues_a_wrong_one(self):
        """多个头里只要有一个对就算命中（集合语义）。

        注意这只对 *session* 头有意义 —— identity 头永远进不了这个集合的有效成员，
        见下面的类。
        """
        assert _matches(
            **{"X-Hermes-Session-Id": "someone-else", "X-Hermes-Identity": SESSION}
        ) is True

    def test_unrelated_headers_are_ignored(self):
        assert _matches(**{"Authorization": "Bearer key"}) is True

    def test_empty_owner_never_matches_a_claim(self):
        """空 owner 由调用方（`if rec.owner and ...`）处理，不归本函数。"""
        assert APIServerAdapter._media_owner_matches(
            _Request(**{"X-Hermes-Session-Id": SESSION}), ""
        ) is False


# ── T3-10：identity 分支救不了真实调用方 ───────────────────────────────────

class TestIdentityBranchCannotRescueARoutedCaller:
    """已知不对称：注册摘要 session，校验却额外接受 identity。

    危害方向是**无效救援**而非误杀 —— 加进集合只可能让更多请求命中，不会拒绝谁。
    但它也从未救过任何人：注册侧 5 个调用点全部 `owner=session_id`，从不摘要登录名。

    这些用例把事实钉住，使下面两条路不会被误认为可行：
      - 以为「routed caller 带 identity 头就够了」（实际仍返回 404）；
      - 以为「删掉 identity 分支会破坏 routed caller」（实际不会，它本来就没生效）。
    """

    def test_login_name_does_not_match_a_session_registered_entry(self):
        """真实形态：identity 是登录名，注册用的是 session id → 不命中。"""
        assert _matches(**{"X-Hermes-Identity": LOGIN}) is False

    def test_identity_only_matches_when_it_happens_to_equal_the_session_id(self):
        """identity 头只有在**恰好等于 session id** 时才命中。

        这正是旧用例的构造方式（`X-Hermes-Identity: "sess-abc"`），它证明的是
        分支可达，不是能力可用。保留这条是为了让"同义反复"这件事本身留痕。
        """
        assert APIServerAdapter._media_owner_matches(
            _Request(**{"X-Hermes-Identity": SESSION}), media_owner_token(SESSION)
        ) is True

    def test_a_routed_caller_that_sends_only_identity_gets_a_404(self):
        """只有 identity 头的 routed caller 现状就是 404 —— 与 T3-10 记载一致。"""
        assert _matches(**{"X-Hermes-Identity": LOGIN}) is False

    def test_the_digests_differ_by_construction(self):
        """两个摘要不可能相等 —— 除非 session_id 与登录名字面相同（不会发生）。"""
        assert media_owner_token(SESSION) != media_owner_token(LOGIN)


# ── 已接受的决策：「不声明即放行」──────────────────────────────────────────

class TestAcceptedUnattributedAccess:
    """T2-7：两条独立通路都必须被钉住，否则"只收紧一半"会被当成修复。"""

    def test_download_side_accepts_an_unattributed_request(self):
        """通路①：下载侧未声明任何身份头 → 放行；`media_id` 即唯一归属凭据。

        id 是 96 bit 的 `secrets.token_urlsafe`，只交给注册方，所以实际暴露面是
        「id 泄漏」（前端日志 / 截图 / 转发链接），而不是「被猜出」。
        """
        assert _matches() is True

    def test_registration_side_stores_such_entries_without_an_owner(self, tmp_path):
        """通路②：注册侧无 session id → owner 为空 → 下载侧整段跳过校验。"""
        store = ApiMediaStore(root=tmp_path / "store")
        src = tmp_path / "report.md"
        src.write_text("hello", encoding="utf-8")

        _, files, _ = finalize_api_media(f"MEDIA:{src}\n", store)  # owner 缺省
        assert len(files) == 1
        rec = store.get(files[0]["id"])
        assert rec is not None
        assert rec.owner == "", "无 session 的回合 → 条目不带 owner"

        # 空 owner ⇒ 下载侧 `if rec.owner and ...` 短路，请求带谁的 id 都不会被拒。
        assert APIServerAdapter._media_owner_matches(
            _Request(**{"X-Hermes-Session-Id": "someone-else"}), rec.owner
        ) is False

    def test_the_accepted_decision_is_recorded_beside_the_code(self):
        """记档要求本身也要钉住，否则"接受"只活在文档里。

        下一个人看到 `if not tokens: return True` 仍会当 bug 去修。空白先归一化 ——
        `__doc__` 保留源码折行，直接子串匹配会随排版变红/绿，那不是契约。
        """
        doc = " ".join((APIServerAdapter._media_owner_matches.__doc__ or "").split())
        assert "accepted decision" in doc
        assert "§16.4" in doc
        assert "the media id is the only ownership credential" in doc
        assert "both must change together" in doc


# ── 归属摘要刻意不加盐（T2-8 / §16.5）─────────────────────────────────────

class TestOwnerTokenDeliberatelyUnkeyed:
    """盐加在「会话 id 派生」上，**不加**在归属摘要上 —— 这是决策。

    §16.5 的理由：本函数的输入是**调用方送来的串**，盐在服务端作用于送到的那串
    本身，只能关掉「离线算出一个派生 id」，关不掉「提交已知 id」与「什么都不声明」
    两条主路 —— 付了成本而边界未动。同一个派生 id 在 `/api/sessions/{id}`（无归属
    校验）处确实是 bearer 凭据，盐加在那里的收益才是实的。
    """

    def test_owner_token_stays_a_plain_digest(self):
        assert media_owner_token("sess-abc") == hashlib.sha256(b"sess-abc").hexdigest()[:16]
        assert media_owner_token("") == ""
        assert media_owner_token("   ") == ""

    def test_the_split_is_recorded_beside_the_code(self):
        for fn in (
            APIServerAdapter._media_owner_matches,
            APIServerAdapter._handle_media_download,
        ):
            doc = " ".join((fn.__doc__ or "").split())
            assert "T2-8" in doc
            assert "§16.5" in doc
