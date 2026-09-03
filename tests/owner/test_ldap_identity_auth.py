"""Regression tests: LDAP second-factor auth for X-Hermes-Identity traffic.

Contract asserted here (behavior, not source shape):

  Decision matrix (ldap_gate):
    1. enabled=false            → always allow
    2. password + bind success  → allow + 72h cache persisted
    3. password + bind fail     → deny_bad_credentials + cache evicted
    4. empty password           → deny_empty_password (never an anon bind)
    5. no password + valid cache → allow (the invisible path, zero binds)
    6. no password, never seen  → enforce=off allows / seen allows / always denies
    7. no password, seen+expired → enforce=seen denies / off allows
    8. LDAP down                → fail_open allows; fail_open=false denies
    9. negative cache window    → bind-fail login denied even under enforce=off
   10. invalid login chars      → deny_invalid_login (DN-injection guard)
   11. password rotation        → a successful rebind refreshes the 72h window
   12. persistence              → cache survives module reset (state file reload)

  Middleware integration (identity_routing_middleware):
   13. verdict deny_*  → 401 with distinguishable error code, nothing proxied
   14. allow           → request proxied WITHOUT X-Hermes-Identity-Password
   15. no ldap section → pass-through (fail-open when owner config absent)
"""

from __future__ import annotations

import asyncio
import textwrap
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from owner.gateway import ldap_auth


LDAP_YAML = """
ldap:
  enabled: true
  host: ldap.test.local
  port: 389
  use_ssl: false
  timeout_seconds: 5
  user_dn_template: "cn={login},cn=people,dc=westhpc,dc=com"
  enforce: "seen"
  cache_ttl_hours: 72
  negative_cache_seconds: 10
  fail_open_on_error: true
"""


@pytest.fixture
def ldap_home(tmp_path, monkeypatch):
    """Temp HERMES_HOME with an ldap: section + isolated caches."""
    home = tmp_path / ".hermes"
    home.mkdir()
    (home / "patch_feishu_profile.yaml").write_text(LDAP_YAML, encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(home))
    ldap_auth.reset_for_tests()
    yield home
    ldap_auth.reset_for_tests()


def _write_ldap_section(home: Path, extra: str = "", base: str = LDAP_YAML) -> None:
    (home / "patch_feishu_profile.yaml").write_text(base + extra, encoding="utf-8")


def _reload_config(home: Path):
    """Bypass the 60s TTL cache so config edits take effect immediately."""
    from owner.patch_config import invalidate_patch_feishu_profile_config_cache

    invalidate_patch_feishu_profile_config_cache()


class FakeBind:
    """Controllable stand-in for the ldap3 bind call.

    ``results`` maps user_dn → bool (bind verdict). DNs absent from the map
    raise a transport error (server down). ``calls`` records the DNs seen.
    """

    def __init__(self, results: dict | None = None, raise_for_unknown: bool = False):
        self.results = results or {}
        self.raise_for_unknown = raise_for_unknown
        self.calls: list[str] = []

    async def __call__(self, user_dn: str, password: str) -> tuple[bool, str | None]:
        self.calls.append(user_dn)
        if user_dn in self.results:
            return self.results[user_dn], None
        if self.raise_for_unknown:
            return False, "LDAPSocketOpenError"
        return False, None


def _fake_bind(fake: FakeBind):
    return patch.object(ldap_auth, "_bind", fake)


YANGTB_DN = "cn=yangtb,cn=people,dc=westhpc,dc=com"


# ---------------------------------------------------------------------------
# Decision matrix
# ---------------------------------------------------------------------------


class TestLdapGate:
    @pytest.mark.asyncio
    async def test_disabled_allows_everything(self, ldap_home):
        _write_ldap_section(ldap_home, base=LDAP_YAML.replace("enabled: true", "enabled: false"))
        _reload_config(ldap_home)
        with _fake_bind(FakeBind(raise_for_unknown=True)):
            assert await ldap_auth.ldap_gate("yangtb", "pw") == ldap_auth.ALLOW
            assert await ldap_auth.ldap_gate("yangtb", None) == ldap_auth.ALLOW

    @pytest.mark.asyncio
    async def test_bind_success_caches(self, ldap_home):
        fake = FakeBind({YANGTB_DN: True})
        with _fake_bind(fake):
            assert await ldap_auth.ldap_gate("yangtb", "secret") == ldap_auth.ALLOW
        assert fake.calls == [YANGTB_DN]
        assert ldap_auth._cache_get("yangtb") is not None
        assert (ldap_home / "ldap_identity_cache.json").exists()

    @pytest.mark.asyncio
    async def test_bind_failure_denies_and_evicts(self, ldap_home):
        with _fake_bind(FakeBind({YANGTB_DN: True})):
            await ldap_auth.ldap_gate("yangtb", "secret")
        with _fake_bind(FakeBind({})):  # every DN now fails
            assert await ldap_auth.ldap_gate("yangtb", "wrong") == ldap_auth.DENY_BAD_CREDENTIALS
        assert ldap_auth._cache_get("yangtb") is None

    @pytest.mark.asyncio
    async def test_empty_password_rejected_before_any_bind(self, ldap_home):
        fake = FakeBind(raise_for_unknown=True)
        with _fake_bind(fake):
            assert await ldap_auth.ldap_gate("yangtb", "") == ldap_auth.DENY_EMPTY_PASSWORD
            assert await ldap_auth.ldap_gate("yangtb", "   ") == ldap_auth.DENY_EMPTY_PASSWORD
        assert fake.calls == []

    @pytest.mark.asyncio
    async def test_cached_login_allows_without_bind(self, ldap_home):
        with _fake_bind(FakeBind({YANGTB_DN: True})):
            await ldap_auth.ldap_gate("yangtb", "secret")
        fake = FakeBind(raise_for_unknown=True)
        with _fake_bind(fake):
            assert await ldap_auth.ldap_gate("yangtb", None) == ldap_auth.ALLOW
        assert fake.calls == []

    @pytest.mark.asyncio
    async def test_unseen_login_enforce_matrix(self, tmp_path, monkeypatch, ldap_home):
        for enforce, expected in (
            ("off", ldap_auth.ALLOW),
            ("seen", ldap_auth.ALLOW),
            ("always", ldap_auth.DENY_REAUTH_REQUIRED),
        ):
            ldap_auth.reset_for_tests()
            (ldap_home / "patch_feishu_profile.yaml").write_text(
                LDAP_YAML.replace('enforce: "seen"', f'enforce: "{enforce}"'),
                encoding="utf-8",
            )
            _reload_config(ldap_home)
            with _fake_bind(FakeBind(raise_for_unknown=True)):
                assert await ldap_auth.ldap_gate("freshuser", None) == expected

    @pytest.mark.asyncio
    async def test_seen_then_expired_denies_under_seen(self, ldap_home):
        with _fake_bind(FakeBind({YANGTB_DN: True})):
            await ldap_auth.ldap_gate("yangtb", "secret")
        # Force expiry: rewrite the state file with a past timestamp.
        state = ldap_home / "ldap_identity_cache.json"
        state.write_text(
            '{"version": 2, "entries": {"yangtb": 1000}, "seen": ["yangtb"]}',
            encoding="utf-8",
        )
        ldap_auth.reset_for_tests()

        _write_ldap_section(
            ldap_home,
            base=LDAP_YAML.replace('enforce: "seen"', 'enforce: "seen"'),
        )
        _reload_config(ldap_home)
        with _fake_bind(FakeBind(raise_for_unknown=True)):
            assert await ldap_auth.ldap_gate("yangtb", None) == ldap_auth.DENY_REAUTH_REQUIRED

        _write_ldap_section(ldap_home, base=LDAP_YAML.replace('enforce: "seen"', 'enforce: "off"'))
        _reload_config(ldap_home)
        ldap_auth.reset_for_tests()
        with _fake_bind(FakeBind(raise_for_unknown=True)):
            assert await ldap_auth.ldap_gate("yangtb", None) == ldap_auth.ALLOW

    @pytest.mark.asyncio
    async def test_ldap_down_fail_open_vs_closed(self, ldap_home):
        fake = FakeBind(raise_for_unknown=True)
        with _fake_bind(fake):
            assert await ldap_auth.ldap_gate("yangtb", "pw") == ldap_auth.ALLOW

        _write_ldap_section(
            ldap_home, base=LDAP_YAML.replace("fail_open_on_error: true", "fail_open_on_error: false")
        )
        _reload_config(ldap_home)
        with _fake_bind(FakeBind(raise_for_unknown=True)):
            assert await ldap_auth.ldap_gate("yangtb", "pw") == ldap_auth.DENY_REAUTH_REQUIRED

    @pytest.mark.asyncio
    async def test_negative_cache_blocks_even_enforce_off(self, ldap_home):
        _write_ldap_section(ldap_home, base=LDAP_YAML.replace('enforce: "seen"', 'enforce: "off"'))
        _reload_config(ldap_home)
        with _fake_bind(FakeBind({})):  # bind fails
            assert await ldap_auth.ldap_gate("yangtb", "bad") == ldap_auth.DENY_BAD_CREDENTIALS
        # Inside the negative window: no-password requests are denied too.
        with _fake_bind(FakeBind(raise_for_unknown=True)):
            assert await ldap_auth.ldap_gate("yangtb", None) == ldap_auth.DENY_REAUTH_REQUIRED

    @pytest.mark.asyncio
    async def test_invalid_login_rejected(self, ldap_home):
        fake = FakeBind(raise_for_unknown=True)
        with _fake_bind(fake):
            assert await ldap_auth.ldap_gate("x,dc=evil", "pw") == ldap_auth.DENY_INVALID_LOGIN
            assert await ldap_auth.ldap_gate("a b", "pw") == ldap_auth.DENY_INVALID_LOGIN
            assert await ldap_auth.ldap_gate("", "pw") == ldap_auth.DENY_INVALID_LOGIN
        assert fake.calls == []

    @pytest.mark.asyncio
    async def test_rebind_refreshes_window(self, ldap_home):
        with _fake_bind(FakeBind({YANGTB_DN: True})):
            await ldap_auth.ldap_gate("yangtb", "secret")
        first_expiry = ldap_auth._cache_get("yangtb")
        assert first_expiry is not None
        with _fake_bind(FakeBind({YANGTB_DN: True})):
            await ldap_auth.ldap_gate("yangtb", "rotated")
        second_expiry = ldap_auth._cache_get("yangtb")
        assert second_expiry is not None and second_expiry >= first_expiry

    @pytest.mark.asyncio
    async def test_wrong_password_eviction_preserves_seen_marker(self, ldap_home):
        """P0 regression: password-rotation eviction must NOT destroy the
        ``seen`` marker.  Otherwise an attacker who knows a uid can send a
        wrong password, wait out the negative cache, and then request
        without a password under enforce=seen — which must still DENY."""
        # A user authenticates once (becomes 'seen', cached 72h).
        with _fake_bind(FakeBind({YANGTB_DN: True})):
            assert await ldap_auth.ldap_gate("yangtb", "secret") == ldap_auth.ALLOW
        assert ldap_auth._cache_get("yangtb") is not None

        # An attacker fires a wrong password for the same uid.
        with _fake_bind(FakeBind({})):
            assert await ldap_auth.ldap_gate("yangtb", "wrongguess") == ldap_auth.DENY_BAD_CREDENTIALS
        # Eviction cleared the valid-cache window but the login stays 'seen'.
        assert ldap_auth._cache_get("yangtb") is None
        assert ldap_auth._has_seen("yangtb") is True

        # After the negative window lapses, a password-less request under
        # enforce=seen must still be denied (reauth required).
        real_now = ldap_auth._now
        try:
            ldap_auth._now = lambda: real_now() + 11
            with _fake_bind(FakeBind(raise_for_unknown=True)):
                assert await ldap_auth.ldap_gate("yangtb", None) == ldap_auth.DENY_REAUTH_REQUIRED
        finally:
            ldap_auth._now = real_now

    @pytest.mark.asyncio
    async def test_cache_survives_module_state_reset(self, ldap_home):
        with _fake_bind(FakeBind({YANGTB_DN: True})):
            await ldap_auth.ldap_gate("yangtb", "secret")
        ldap_auth.reset_for_tests()
        fake = FakeBind(raise_for_unknown=True)
        with _fake_bind(fake):
            assert await ldap_auth.ldap_gate("yangtb", None) == ldap_auth.ALLOW
        assert fake.calls == []


# ---------------------------------------------------------------------------
# Middleware integration
# ---------------------------------------------------------------------------


ROUTING_YAML = LDAP_YAML + """
feishu:
  bots:
    cli_test:
      user_routing:
        identity_routes:
          yangtb: hermesxiyun
        default_profile: hermesxiyun
        profile_endpoints:
          hermesxiyun:
            url: http://localhost:26026
            api_key: sk-test-key
"""


@pytest.fixture
def routing_home(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    (home / "patch_feishu_profile.yaml").write_text(ROUTING_YAML, encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("FEISHU_APP_ID", "cli_test")
    ldap_auth.reset_for_tests()
    yield home
    ldap_auth.reset_for_tests()


def _make_middleware():
    from gateway.platforms.api_server import APIServerAdapter

    adapter = object.__new__(APIServerAdapter)
    return adapter._make_identity_routing_middleware(), adapter


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
        self.requests: list[_FakeRequest] = []

    async def __call__(self, request):
        self.requests.append(request)
        from aiohttp import web

        return web.json_response({"ok": True})


class _DenyHandler:
    """Fails the test if reached — a denied request must never reach the app."""

    async def __call__(self, request):
        raise AssertionError("denied request reached the handler")


class _ProxyRecorder:
    """Stand-in for aiohttp.ClientSession.request inside the proxy path.

    The identity middleware proxies to a fake endpoint URL; tests must never
    issue a real HTTP call (a localhost URL could hit a live container).
    Records forwarded headers for password-stripping assertions.
    """

    def __init__(self):
        self.forwarded_headers: dict = {}

    def patch(self):
        import aiohttp

        recorder = self

        class _Ctx:
            def __init__(self, resp):
                self._resp = resp

            async def __aenter__(self):
                return self._resp

            async def __aexit__(self, *a):
                return False

        class _Resp:
            status = 200
            headers = {"content-type": "application/json"}

            async def read(self):
                return b'{"ok": true}'

        def fake_request(*args, **kwargs):
            recorder.forwarded_headers.update(kwargs.get("headers") or {})
            return _Ctx(_Resp())

        return patch.object(aiohttp.ClientSession, "request", fake_request)


class TestMiddleware:
    @pytest.mark.asyncio
    async def test_denied_bad_credentials_returns_401(self, routing_home):
        middleware, _ = _make_middleware()
        req = _FakeRequest(
            {"X-Hermes-Identity": "yangtb", "X-Hermes-Identity-Password": "wrong"}
        )
        with _fake_bind(FakeBind({})):
            resp = await middleware(req, _DenyHandler())
        assert resp.status == 401
        body = resp.text
        assert "ldap_auth_failed" in body

    @pytest.mark.asyncio
    async def test_denied_reauth_returns_401_code_required(self, routing_home):
        middleware, _ = _make_middleware()
        # Expired-but-seen login → reauth required.
        (routing_home / "ldap_identity_cache.json").write_text(
            '{"version": 2, "entries": {"yangtb": 1000}, "seen": ["yangtb"]}',
            encoding="utf-8",
        )
        req = _FakeRequest({"X-Hermes-Identity": "yangtb"})
        with _fake_bind(FakeBind(raise_for_unknown=True)):
            resp = await middleware(req, _DenyHandler())
        assert resp.status == 401
        assert "ldap_auth_required" in resp.text

    @pytest.mark.asyncio
    async def test_allowed_request_proxies_without_password_header(self, routing_home):
        middleware, _ = _make_middleware()
        handler = _RecordingHandler()
        recorder = _ProxyRecorder()

        req = _FakeRequest(
            {"X-Hermes-Identity": "yangtb", "X-Hermes-Identity-Password": "secret"}
        )
        with _fake_bind(FakeBind({YANGTB_DN: True})):
            with recorder.patch():
                resp = await middleware(req, handler)
        assert resp.status == 200
        assert "x-hermes-identity-password" not in {
            k.lower() for k in recorder.forwarded_headers
        }
        # DenyHandler proxy path — handler not called (request was proxied).
        assert handler.requests == []

    @pytest.mark.asyncio
    async def test_no_ldap_config_passthrough(self, tmp_path, monkeypatch, routing_home):
        home = routing_home
        no_ldap_yaml = ROUTING_YAML.replace(LDAP_YAML.lstrip("\n") + "\n", "")
        (home / "patch_feishu_profile.yaml").write_text(no_ldap_yaml, encoding="utf-8")
        from owner.patch_config import invalidate_patch_feishu_profile_config_cache

        invalidate_patch_feishu_profile_config_cache()
        ldap_auth.reset_for_tests()
        middleware, _ = _make_middleware()
        handler = _RecordingHandler()
        recorder = _ProxyRecorder()
        # No ldap: section → gate is a no-op; the identity route still proxies
        # (the local handler is never the target for a routed identity).
        req = _FakeRequest({"X-Hermes-Identity": "yangtb"})
        with recorder.patch():
            resp = await middleware(req, handler)
        assert resp.status == 200
        assert recorder.forwarded_headers, "request must have been proxied"
        assert handler.requests == []
