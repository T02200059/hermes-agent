"""T2-3 —— identity routing 的「未接线（dormant）」状态必须显式可观测。

背景：`resolve_api_identity_route()` 对「该 uid 不在 identity_routes 里」与
「整条 identity 链路从未接线」都返回 None，调用点无从区分。而后者会让
`ldap_gate` **永久不可达** —— 它位于「路由解析成功」之后（`api_server.py`
的 `identity_routing_middleware` 内），所以配置缺键时不会报错、不会拒绝，
只是静静地不做任何二次认证。这是「门存在但未生效」的典型形态，比「门不存在」
更危险：日志里看到的还是那句 `is unknown; falling through to default`，
读起来像「这个 uid 没配」而不是「整套机制是关的」。

本文件把该不变量焊死在三处：
  1. owner 侧诊断 `identity_routing_diagnostics()`
  2. 中间件日志（dormant 与 unknown 必须可区分；dormant 只提示一次）
  3. 准入端点响应（`allowed: false` 不得被读成「该用户被拒」）

并配对照组：同一探针在「已接线」配置下必须确实命中 ldap_gate，否则
「dormant 时 gate 未被调用」就是一句空断言。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from owner.feishu import profile_routing

APP_ID = "cli_test"

# 与现网同构：user_routing 非空（有 default_profile / profile_endpoints），
# 但**没有** identity_routes / identity_whitelist。
_BASE_HEAD = (
    "feishu:\n"
    "  bots:\n"
    f"    {APP_ID}:\n"
    "      user_routing:\n"
    "        default_profile: hermesxiyun\n"
    "        profile_endpoints:\n"
    "          hermesxiyun:\n"
    "            url: http://localhost:26026\n"
    "            api_key: sk-test-key\n"
)

# 8 空格缩进，落在 user_routing 之下
_ROUTES = "        identity_routes:\n          yangtb: hermesxiyun\n"
_WHITELIST = "        identity_whitelist:\n          - yangtb\n"


def _routing_yaml(extra: str = "") -> str:
    return _BASE_HEAD + extra


def _write(home: Path, yaml_text: str) -> None:
    (home / "patch_feishu_profile.yaml").write_text(yaml_text, encoding="utf-8")
    from owner.patch_config import invalidate_patch_feishu_profile_config_cache

    invalidate_patch_feishu_profile_config_cache()


@pytest.fixture
def routing_home(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    _write(home, _routing_yaml())
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("FEISHU_APP_ID", APP_ID)
    yield home


# ---------------------------------------------------------------------------
# 1. owner 侧诊断
# ---------------------------------------------------------------------------


class TestDiagnostics:
    def test_dormant_when_identity_keys_absent(self, routing_home):
        diag = profile_routing.identity_routing_diagnostics()
        assert diag["dormant"] is True
        assert diag["keys_present"] is False
        assert diag["identity_route_count"] == 0
        assert diag["identity_whitelist_count"] == 0
        assert diag["config_source"] == "loaded", (
            "user_routing 段本身加载成功，只是缺 identity 键 —— 成因必须可归因，"
            "不能与「配置段加载不到」混为一谈"
        )

    def test_keys_present_but_empty_is_still_dormant_and_distinguishable(
        self, routing_home
    ):
        """键存在但为空 ≠ 键缺失。两者都 dormant，但成因不同。"""
        _write(routing_home, _routing_yaml("        identity_routes: {}\n"))
        diag = profile_routing.identity_routing_diagnostics()
        assert diag["dormant"] is True
        assert diag["keys_present"] is True

    def test_routes_present_is_not_dormant(self, routing_home):
        _write(routing_home, _routing_yaml(_ROUTES))
        diag = profile_routing.identity_routing_diagnostics()
        assert diag["dormant"] is False
        assert diag["keys_present"] is True
        assert diag["identity_route_count"] == 1

    def test_whitelist_alone_is_enough_to_lift_dormancy(self, routing_home):
        _write(routing_home, _routing_yaml(_WHITELIST))
        diag = profile_routing.identity_routing_diagnostics()
        assert diag["dormant"] is False, (
            "只有 identity_whitelist 时链路同样会触发（白名单短路先于路由解析），"
            "不得判为 dormant"
        )
        assert diag["identity_whitelist_count"] == 1

    def test_unavailable_when_app_id_missing(self, routing_home, monkeypatch):
        """非飞书 api_server 节点：FEISHU_APP_ID 未设 → 配置段取不到。

        这本身是**另一种** dormant 成因（键可能配了也读不到），必须与
        「键缺失」区分开，否则排障会看错方向。
        """
        monkeypatch.delenv("FEISHU_APP_ID", raising=False)
        diag = profile_routing.identity_routing_diagnostics()
        assert diag["dormant"] is True
        assert diag["config_source"] == "unavailable"

    def test_never_raises_on_malformed_section(self, routing_home):
        _write(routing_home, _routing_yaml("        identity_routes: 42\n"))
        diag = profile_routing.identity_routing_diagnostics()
        assert diag["dormant"] is True
        assert diag["identity_route_count"] == 0


# ---------------------------------------------------------------------------
# 2. 中间件
# ---------------------------------------------------------------------------


class _FakeHeaders(dict):
    def get(self, key, default=""):  # type: ignore[override]
        return super().get(key, default)


class _FakeRequest:
    def __init__(self, headers: dict, method="POST", path="/v1/chat/completions"):
        self.headers = _FakeHeaders(headers)
        self.method = method
        self.path = path
        self.query_string = ""
        self.remote = "127.0.0.1"
        self._body = b"{}"

    async def read(self):
        return self._body


class _RecordingHandler:
    def __init__(self):
        self.requests: list = []

    async def __call__(self, request):
        self.requests.append(request)
        from aiohttp import web

        return web.json_response({"ok": True})


def _make_adapter():
    from gateway.platforms.api_server import APIServerAdapter

    return object.__new__(APIServerAdapter)


class _LdapGateProbe:
    """Patch owner.gateway.ldap_auth.ldap_gate and count invocations.

    ``_owner_import`` memoises the resolved attribute in ``_owner_lazy``, so
    patching the module alone would be ignored whenever an earlier call already
    cached the real function — the probe would then silently never fire and
    the assertions below would be vacuous. Clear the cache as part of patching.
    """

    def __init__(self):
        self.calls = 0

    def patch(self):
        from gateway.platforms import api_server as api_mod

        probe = self

        async def fake_gate(identity, password):
            probe.calls += 1
            return "allow"

        api_mod._owner_lazy.pop("owner.gateway.ldap_auth.ldap_gate", None)
        return patch.object(
            __import__("owner.gateway.ldap_auth", fromlist=["ldap_gate"]),
            "ldap_gate",
            fake_gate,
        )


class TestMiddlewareDormancy:
    @pytest.mark.asyncio
    async def test_dormant_identity_passes_through_and_warns_explicitly(
        self, routing_home, caplog
    ):
        middleware = _make_adapter()._make_identity_routing_middleware()
        handler = _RecordingHandler()
        caplog.set_level(logging.WARNING, logger="gateway.platforms.api_server")

        resp = await middleware(
            _FakeRequest({"X-Hermes-Identity": "yangtb"}), handler
        )
        assert resp.status == 200
        assert len(handler.requests) == 1, "dormant 时不得反代，必须透传"

        warnings = [
            r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING
        ]
        dormant_warnings = [m for m in warnings if "DORMANT" in m]
        assert dormant_warnings, "dormant 状态必须有显式告警，不能只报 'is unknown'"
        assert "ABSENT" in dormant_warnings[0], "告警须给出成因（键缺失 vs 键为空）"
        assert "no LDAP second-factor gate" in dormant_warnings[0]

    @pytest.mark.asyncio
    async def test_dormant_notice_emitted_once_per_middleware(
        self, routing_home, caplog
    ):
        middleware = _make_adapter()._make_identity_routing_middleware()
        handler = _RecordingHandler()
        caplog.set_level(logging.WARNING, logger="gateway.platforms.api_server")

        for _ in range(3):
            await middleware(_FakeRequest({"X-Hermes-Identity": "yangtb"}), handler)

        assert len(handler.requests) == 3
        dormant_warnings = [
            r.getMessage()
            for r in caplog.records
            if r.levelno >= logging.WARNING and "DORMANT" in r.getMessage()
        ]
        assert len(dormant_warnings) == 1, (
            "结构性状态按请求重复告警只会淹没日志 —— 应每中间件实例只提示一次"
        )

    @pytest.mark.asyncio
    async def test_dormant_means_ldap_gate_is_unreachable(self, routing_home):
        middleware = _make_adapter()._make_identity_routing_middleware()
        handler = _RecordingHandler()
        probe = _LdapGateProbe()

        with probe.patch():
            resp = await middleware(
                _FakeRequest(
                    {"X-Hermes-Identity": "yangtb", "X-Hermes-Identity-Password": "x"}
                ),
                handler,
            )
        assert resp.status == 200
        assert probe.calls == 0, (
            "路由未接线时 ldap_gate 位于早返回之后，永不执行 —— 既然一个密码为 'x' "
            "的请求都没被送到门前，说明二次认证整体不生效"
        )

    @pytest.mark.asyncio
    async def test_gate_probe_does_fire_when_routing_is_wired(self, routing_home):
        """对照组：同一探针在已接线配置下必须命中，否则上一条断言是空断言。"""
        _write(routing_home, _routing_yaml(_ROUTES))
        middleware = _make_adapter()._make_identity_routing_middleware()
        handler = _RecordingHandler()
        probe = _LdapGateProbe()

        with probe.patch():
            await middleware(
                _FakeRequest({"X-Hermes-Identity": "yangtb"}), handler
            )
        assert probe.calls == 1, (
            "已接线时 gate 必须被调用；探针未命中说明它已失效，会掩盖真实回归"
        )

    @pytest.mark.asyncio
    async def test_wired_but_unknown_identity_keeps_the_legacy_warning(
        self, routing_home, caplog
    ):
        """已接线但该 uid 不在表里 → 保持原措辞，不得误报 DORMANT。"""
        _write(routing_home, _routing_yaml(_ROUTES))
        middleware = _make_adapter()._make_identity_routing_middleware()
        handler = _RecordingHandler()
        caplog.set_level(logging.WARNING, logger="gateway.platforms.api_server")

        await middleware(_FakeRequest({"X-Hermes-Identity": "nobody"}), handler)

        messages = [
            r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING
        ]
        assert any("is unknown; falling through to default" in m for m in messages)
        assert not any("DORMANT" in m for m in messages), (
            "已接线却把「该 uid 未配置」报成 dormant，会让排障者以为整套机制是关的"
        )


# ---------------------------------------------------------------------------
# 3. 准入端点
# ---------------------------------------------------------------------------


class _FakeEndpointRequest:
    def __init__(self, identity: str):
        self.match_info = {"identity": identity}
        self.headers = _FakeHeaders({})


async def _call_access_endpoint(identity: str) -> dict:
    adapter = _make_adapter()
    adapter._check_auth = lambda request: None  # type: ignore[assignment]
    resp = await adapter._handle_ldap_identity_access(_FakeEndpointRequest(identity))
    assert resp.status == 200
    return json.loads(resp.text)


class TestAccessEndpointDormancy:
    @pytest.mark.asyncio
    async def test_reports_dormant_so_allowed_false_is_not_a_denial(
        self, routing_home
    ):
        payload = await _call_access_endpoint("yangtb")
        assert payload["allowed"] is False
        assert payload["routing_dormant"] is True, (
            "消费方（xy-portal 等）把 allowed:false 读成「该用户被拒」时会"
            "拒绝全部用户；必须显式告知这是网关未接线"
        )
        assert payload["routing_keys_present"] is False

    @pytest.mark.asyncio
    async def test_reports_not_dormant_when_wired(self, routing_home):
        _write(routing_home, _routing_yaml(_ROUTES))
        payload = await _call_access_endpoint("yangtb")
        assert payload["routing_dormant"] is False
        assert payload["routed"] is True
        assert payload["allowed"] is True

    @pytest.mark.asyncio
    async def test_wired_but_unknown_uid_is_a_per_user_answer(self, routing_home):
        _write(routing_home, _routing_yaml(_ROUTES))
        payload = await _call_access_endpoint("nobody")
        assert payload["routing_dormant"] is False
        assert payload["allowed"] is False
        assert payload["profile"] is None
