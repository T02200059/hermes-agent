"""Ownership assertion on GET /v1/media/{id}.

An entry records a digest of the session that registered it. A caller is
accepted when it presents that same session (or the LDAP identity it was routed
by). A caller that asserts nothing is let through — those are infrastructure
callers holding the API key, and entries written before the owner field existed
carry no owner at all.

That last rule is an **accepted decision**, not an oversight (T2-7). It is
recorded together with its residual risk in ``owner/docs/owner改动清单.md``
§16.4, and ``TestAcceptedUnattributedAccess`` below pins it in behaviour — so a
future tightening has to change a test, i.e. has to be deliberate. The
acceptance has **two** independent entry points: the download side (asserted
here) and the registration side (a turn carrying no session header stores an
entry with no owner, which skips the check altogether).
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


class _Request:
    """Minimal stand-in: the check only reads ``request.headers.get``."""

    def __init__(self, **headers: str) -> None:
        self.headers = headers


def _matches(**headers: str) -> bool:
    owner = media_owner_token("sess-abc")
    return APIServerAdapter._media_owner_matches(_Request(**headers), owner)


class TestMediaOwnerMatches:
    def test_same_session_header_matches(self):
        assert _matches(**{"X-Hermes-Session-Id": "sess-abc"}) is True

    def test_different_session_header_does_not_match(self):
        assert _matches(**{"X-Hermes-Session-Id": "sess-other"}) is False

    def test_ldap_identity_header_matches_a_routed_caller(self):
        """A routed caller is registered under its session and carries both."""
        matching = media_owner_token("sess-abc")
        assert APIServerAdapter._media_owner_matches(
            _Request(**{"X-Hermes-Identity": "sess-abc"}), matching
        ) is True

    def test_one_of_several_headers_is_enough(self):
        assert _matches(
            **{"X-Hermes-Session-Id": "sess-other", "X-Hermes-Identity": "sess-abc"}
        ) is True

    def test_unattributable_request_is_allowed(self):
        """No owner headers → infrastructure caller; never lock it out.

        Accepted decision (T2-7) — see the module docstring and
        ``TestAcceptedUnattributedAccess`` for the bound being accepted.
        """
        assert _matches() is True

    def test_blank_owner_headers_count_as_unasserted(self):
        assert _matches(**{"X-Hermes-Session-Id": "   "}) is True

    def test_unrelated_headers_are_ignored(self):
        assert _matches(**{"Authorization": "Bearer key"}) is True

    def test_empty_owner_never_matches_a_claim(self):
        """Legacy entries (no owner) are handled by the caller, not here."""
        assert APIServerAdapter._media_owner_matches(
            _Request(**{"X-Hermes-Session-Id": "sess-abc"}), ""
        ) is False


class TestAcceptedUnattributedAccess:
    """T2-7 —— 「什么都不声明」的放行是有意接受的决策，不是疏漏。

    类名用 "Accepted" 是有意的：这些用例断言的是**已接受的边界**，不为该行为
    背书。把决策钉在行为上，使未来的收紧只能是有意为之（改测试即改决策），而
    不会作为某次重构的副作用悄悄发生。

    「不声明即放行」有**两条独立**通路，两条都要钉住：
      ① 下载侧 —— 请求不声明任何身份头 → `_media_owner_matches` 返回 True；
      ② 注册侧 —— 注册该条目的回合没带 session id → 条目 `owner=""`，下载侧
         `if rec.owner and ...` 整段跳过，**根本不调用** `_media_owner_matches`。
    因此「只收紧下载侧」不构成修复：收紧必须两条一起改。
    """

    def test_download_side_accepts_an_unattributed_request(self):
        """通路①：未声明 → 放行；`media_id` 即唯一归属凭据。

        id 是 96 bit 的 `secrets.token_urlsafe`，且只交给注册方，因此实际暴露面
        是「id 泄漏」（前端日志 / 截图 / 转发链接），而不是「被猜出」。
        """
        assert _matches() is True

    def test_registration_side_stores_such_entries_without_an_owner(self, tmp_path):
        """通路②：注册侧无 session id → owner 为空（`finalize_api_media` 默认 owner=""）。

        空 owner 的条目在下载侧不产生任何断言，故与「下载侧未声明」是相互独立的
        第二条通路。
        """
        store = ApiMediaStore(root=tmp_path / "store")
        src = tmp_path / "report.md"
        src.write_text("hello", encoding="utf-8")
        _, files, _ = finalize_api_media(f"MEDIA:{src}\n", store)  # owner 缺省
        assert len(files) == 1
        rec = store.get(files[0]["id"])
        assert rec is not None
        assert rec.owner == "", "无 session 的回合 → 条目不带 owner"
        # 于是下载侧的守卫 `if rec.owner and ...` 不会调用本函数 —— 即便请求
        # 声明了别人的会话，也不会走到这里被判 False。
        assert APIServerAdapter._media_owner_matches(
            _Request(**{"X-Hermes-Session-Id": "someone-else"}), rec.owner
        ) is False

    def test_the_accepted_decision_is_recorded_beside_the_code(self):
        """记档要求本身也要被钉住：docstring 必须点名「已接受」并给出出处。

        否则「接受」只活在文档里，代码旁没有任何提示 —— 下一个人看到
        `if not tokens: return True` 仍会当 bug 去修。

        空白先归一化：`__doc__` 保留源码折行与缩进，直接子串匹配会让断言随
        排版变化而红/绿，那不是契约。
        """
        doc = " ".join((APIServerAdapter._media_owner_matches.__doc__ or "").split())
        assert "accepted decision" in doc
        assert "§16.4" in doc
        assert "the media id is the only ownership credential" in doc
        assert "both must change together" in doc


class TestOwnerTokenDeliberatelyUnkeyed:
    """T2-8 —— 盐加在「会话 id 派生」上，**不加**在归属摘要上。这是决策。

    ``owner/docs/owner改动清单.md`` §16.5 的理由：本函数的输入是**调用方送来的
    串**，而盐在服务端作用于送到的那串本身，所以它只能关掉「离线算出一个派生
    id」，关不掉「提交一个已知 id」与「什么都不声明」两条主路 —— 付了成本而边界
    未动。同一个派生 id 在 ``/api/sessions/{id}``（无归属校验）处**确实是 bearer
    凭据**，盐加在那里的收益才是实的。因此本用例把「这里保持不加盐」钉住：未来
    若有人出于「都该加盐」的本能改掉它，媒体条目命名会连带失配 —— 那必须是一次
    有意的决定，而不是某次收紧的副作用。
    """

    def test_owner_token_stays_a_plain_digest(self):
        assert media_owner_token("sess-abc") == hashlib.sha256(b"sess-abc").hexdigest()[:16]
        assert media_owner_token("") == ""
        assert media_owner_token("   ") == ""

    def test_the_split_is_recorded_beside_the_code(self):
        """两个 docstring 都要给出 §16.5 与 T2-8 的落点，否则决策只活在文档里。"""
        for doc_callable in (
            APIServerAdapter._media_owner_matches,
            APIServerAdapter._handle_media_download,
        ):
            doc = " ".join((doc_callable.__doc__ or "").split())
            assert "T2-8" in doc
            assert "§16.5" in doc


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
