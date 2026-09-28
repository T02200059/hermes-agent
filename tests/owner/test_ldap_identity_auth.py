"""Regression tests: LDAP second-factor auth for X-Hermes-Identity traffic.

Contract asserted here (behavior, not source shape):

  Decision matrix (ldap_gate):
    1. enabled=false            → always allow
    2. password + bind success  → allow + 72h cache persisted
    3. password + bind fail     → deny_bad_credentials + cache evicted
    4. empty password           → deny_empty_password (never an anon bind)
    5. no password + valid cache → allow (the invisible path, zero binds)
    6. no password, never seen  → enforce=off allows; seen and always deny
                                   (T2-4: ``seen`` is a fail-closed alias of
                                   ``always`` — it used to allow a
                                   never-authenticated login, which let an
                                   attacker pass by picking a uid that never
                                   logged in)
    7. no password, seen+expired → enforce=seen (and always) denies / off allows
    8. LDAP down (transient)    → fail_open_on_error=false (default, T2-5) denies
                                   with deny_backend_unavailable; an explicit
                                   opt-in allows. `no_config` / `ldap3_missing`
                                   are permanent config errors → deny regardless
                                   of the switch. A *wrong* password is
                                   deny_bad_credentials, never merged with
                                   "could not verify"
    9. negative cache window    → bind-fail login denied even under enforce=off
   10. invalid login chars      → deny_invalid_login (DN-injection guard)
   11. password rotation        → a successful rebind refreshes the 72h window
   12. persistence              → cache survives module reset (state file reload)
   13. unrecognized enforce     → fails closed (treated as ``always``), not
                                   silently downgraded to ``off``

  Middleware integration (identity_routing_middleware):
   14. verdict deny_*  → 401 with distinguishable error code, nothing proxied
   15. allow           → request proxied WITHOUT X-Hermes-Identity-Password
   16. no ldap section → pass-through (fail-open when owner config absent)
   17. SSE response    → streamed chunk-by-chunk (never buffered wholesale)
   18. gate ordering   → the gate runs for *every* identity header, ahead of any
                         routing decision: a whitelist hit, a routable identity
                         and an unresolvable one are all gated alike, and a
                         denied claim never reaches the routing branches
                         (whitelist = "do not reverse-proxy", never "skip auth")
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


_FAR_FUTURE_EXPIRY = 4102444800.0  # 2100-01-01, comfortably inside cache_ttl semantics


def _seed_valid_cache(home: Path, login: str) -> None:
    """Seed the state file so ``login`` has a valid (non-expired) cache entry.

    Tests that assert *transport* behaviour (proxy forwarding, SSE streaming)
    need the gate's "invisible path" — a valid cache lets them proceed with no
    password header. They must not depend on the enforce policy, which since
    T2-4 rejects every unauthenticated request without a valid cache even under
    ``enforce=seen``.
    """
    (home / "ldap_identity_cache.json").write_text(
        '{"version": 2, "entries": {"%s": %r}, "seen": ["%s"]}'
        % (login, _FAR_FUTURE_EXPIRY, login),
        encoding="utf-8",
    )


class FakeBind:
    """Controllable stand-in for the ldap3 bind call.

    ``results`` maps user_dn → bool (bind verdict). DNs absent from the map
    raise a transport error (server down). ``calls`` records the DNs seen.
    """

    def __init__(
        self,
        results: dict | None = None,
        raise_for_unknown: bool = False,
        raise_with: str | None = None,
    ):
        self.results = results or {}
        self.raise_for_unknown = raise_for_unknown
        self.raise_with = raise_with
        self.calls: list[str] = []

    async def __call__(self, user_dn: str, password: str) -> tuple[bool, str | None]:
        self.calls.append(user_dn)
        if self.raise_with is not None:
            return False, self.raise_with
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
        """T2-4: a never-authenticated login must not be spared by ``seen``.

        The old matrix allowed it under ``seen``, so with no password header
        deployed every identity passed with zero authentication — ``seen`` and
        ``off`` were behaviourally identical in production. Only ``off`` may
        now allow, and it says so explicitly.
        """
        for enforce, expected in (
            ("off", ldap_auth.ALLOW),
            ("seen", ldap_auth.DENY_REAUTH_REQUIRED),
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
    async def test_unrecognized_enforce_value_fails_closed(self, ldap_home):
        """A typo in ``enforce`` must not silently disable the gate.

        ``enforce: "alway"`` used to fall through every branch and land on
        ALLOW — the gate would be off with no signal, the same silent-failure
        class as a dormant routing config (T2-3).
        """
        _write_ldap_section(
            ldap_home, base=LDAP_YAML.replace('enforce: "seen"', 'enforce: "alway"')
        )
        _reload_config(ldap_home)
        with _fake_bind(FakeBind(raise_for_unknown=True)):
            assert (
                await ldap_auth.ldap_gate("freshuser", None)
                == ldap_auth.DENY_REAUTH_REQUIRED
            )

    @pytest.mark.asyncio
    async def test_enforce_seen_and_always_share_one_verdict(self, ldap_home):
        """``seen`` is a legacy alias: both strict modes must agree everywhere.

        Guards against re-introducing a divergence between the two names, which
        is what made the old ``seen`` semantics look like a security mode.
        """
        cases = (
            ("freshuser", None),      # never authenticated, no password
            ("freshuser", "wrong"),   # never authenticated, bad password
            ("yangtb", None),         # expired cache, no password
        )
        for enforce in ("seen", "always"):
            verdicts = []
            for login, password in cases:
                ldap_auth.reset_for_tests()
                _write_ldap_section(
                    ldap_home,
                    base=LDAP_YAML.replace('enforce: "seen"', f'enforce: "{enforce}"'),
                )
                _reload_config(ldap_home)
                with _fake_bind(FakeBind({})):
                    verdicts.append(await ldap_auth.ldap_gate(login, password))
            assert verdicts == [
                ldap_auth.DENY_REAUTH_REQUIRED,
                ldap_auth.DENY_BAD_CREDENTIALS,
                ldap_auth.DENY_REAUTH_REQUIRED,
            ], f"enforce={enforce} 的判定与 always 不一致：{verdicts}"

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
        """T2-5: fail-open is an explicit opt-in, and only for transient errors.

        Default is now fail-closed and reports ``deny_backend_unavailable``
        (503), *not* ``deny_reauth_required`` — the credentials were never
        checked, so telling the caller to re-authenticate would be wrong.
        """
        # Fixture ships fail_open_on_error: true → explicit opt-in still works.
        with _fake_bind(FakeBind(raise_for_unknown=True)):
            assert await ldap_auth.ldap_gate("yangtb", "pw") == ldap_auth.ALLOW

        _write_ldap_section(
            ldap_home, base=LDAP_YAML.replace("fail_open_on_error: true", "fail_open_on_error: false")
        )
        _reload_config(ldap_home)
        with _fake_bind(FakeBind(raise_for_unknown=True)):
            assert (
                await ldap_auth.ldap_gate("yangtb", "pw")
                == ldap_auth.DENY_BACKEND_UNAVAILABLE
            )

    @pytest.mark.asyncio
    async def test_wrong_password_and_unverifiable_differ(self, ldap_home):
        """The T2-5 acceptance criterion: two failures, two outcomes.

        A *checked* wrong password is the caller's fault (401, re-prompt); an
        *unchecked* password is the backend's fault (503, retry later).
        Collapsing them is what let an outage turn any wrong password valid.
        """
        _write_ldap_section(
            ldap_home,
            base=LDAP_YAML.replace(
                "fail_open_on_error: true", "fail_open_on_error: false"
            ),
        )
        _reload_config(ldap_home)
        with _fake_bind(FakeBind({})):  # bind evaluates → credential rejection
            wrong = await ldap_auth.ldap_gate("yangtb", "definitely-wrong")
        with _fake_bind(FakeBind(raise_for_unknown=True)):  # bind unavailable
            unverifiable = await ldap_auth.ldap_gate("yangtb", "definitely-wrong")

        assert wrong == ldap_auth.DENY_BAD_CREDENTIALS
        assert unverifiable == ldap_auth.DENY_BACKEND_UNAVAILABLE
        assert wrong != unverifiable

    @pytest.mark.asyncio
    async def test_default_is_fail_closed_when_key_is_absent(self, ldap_home):
        """Without the key at all, an outage must not verify anything."""
        base = "\n".join(
            line
            for line in LDAP_YAML.splitlines()
            if not line.strip().startswith("fail_open_on_error:")
        )
        _write_ldap_section(ldap_home, base=base + "\n")
        _reload_config(ldap_home)
        with _fake_bind(FakeBind(raise_for_unknown=True)):
            assert (
                await ldap_auth.ldap_gate("yangtb", "pw")
                == ldap_auth.DENY_BACKEND_UNAVAILABLE
            )

    @pytest.mark.asyncio
    async def test_configuration_errors_deny_even_with_fail_open_on(
        self, ldap_home
    ):
        """``no_config`` / ``ldap3_missing`` are permanent, not transient.

        They mean the gate can never authenticate anyone here, so fail-open is
        never defensible — it would silently disable the gate for good. The
        fixture has ``fail_open_on_error: true``, which must not rescue them.
        """
        for error_class in ("no_config", "ldap3_missing"):
            ldap_auth.reset_for_tests()
            with _fake_bind(FakeBind(raise_with=error_class)):
                verdict = await ldap_auth.ldap_gate("yangtb", "pw")
            assert verdict == ldap_auth.DENY_BACKEND_UNAVAILABLE, (
                f"{error_class} 是永久性配置错误，不得因 fail_open_on_error=true 而放行"
            )

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
        self.forwarded_timeout = None

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
            recorder.forwarded_timeout = kwargs.get("timeout")
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
    async def test_backend_unavailable_returns_503(self, routing_home):
        """T2-5: an unchecked password must not be reported as a bad password.

        401 would tell the client to re-prompt for credentials, i.e. to keep
        retrying a check that cannot succeed. 503 says "retry later" and keeps
        the two failure modes distinguishable on the wire.
        """
        (routing_home / "patch_feishu_profile.yaml").write_text(
            ROUTING_YAML.replace(
                "fail_open_on_error: true", "fail_open_on_error: false"
            ),
            encoding="utf-8",
        )
        _reload_config(routing_home)
        middleware, _ = _make_middleware()
        req = _FakeRequest(
            {"X-Hermes-Identity": "yangtb", "X-Hermes-Identity-Password": "secret"}
        )
        with _fake_bind(FakeBind(raise_for_unknown=True)):
            resp = await middleware(req, _DenyHandler())
        assert resp.status == 503
        assert "ldap_backend_unavailable" in resp.text
        assert "ldap_auth_failed" not in resp.text

    @pytest.mark.asyncio
    async def test_allowed_request_proxies_without_identity_headers(self, routing_home):
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
        # The identity header must also be stripped: sub-profile gateways run
        # the same identity_routes config, so forwarding it makes the
        # sub-gateway proxy the request to itself (loop → 503).
        assert "x-hermes-identity" not in {
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


# ---------------------------------------------------------------------------
# T2-6: the gate is a step of its own, ahead of every routing decision
# ---------------------------------------------------------------------------


def _with_identity_whitelist(base: str = ROUTING_YAML, login: str = "yangtb") -> str:
    """Add ``identity_whitelist`` alongside the existing ``identity_routes``.

    The same uid appears in both lists on purpose: whitelist priority is the
    documented semantic, so the by-design branch when a request is let through
    is "root handles it, do not reverse-proxy".
    """
    return base + f"        identity_whitelist:\n          - {login}\n"


BROKEN_ENDPOINT_YAML = LDAP_YAML + """
feishu:
  bots:
    cli_test:
      user_routing:
        identity_routes:
          yangtb: hermesxiyun
        default_profile: hermesxiyun
        profile_endpoints: {}
"""


def _write_routing(home: Path, text: str) -> None:
    (home / "patch_feishu_profile.yaml").write_text(text, encoding="utf-8")
    _reload_config(home)


class TestGateRunsBeforeRouting:
    """T2-6 —— 认证判定不再与路由判定耦合。

    改前 `ldap_gate` 位于「`resolve_api_identity_route` 成功返回」之后，于是
    有两条路绕过二次认证：命中 `identity_whitelist` 直接早返回；路由解析失败
    （未知 uid，或已登记 uid 的 `profile_endpoints` 配错）落到 default 路径。
    前者把「白名单」读成了「免认证」，后者让一条配置错误变成一条免认证通路。
    """

    @pytest.mark.asyncio
    async def test_whitelisted_identity_must_still_pass_the_gate(self, routing_home):
        """白名单只决定「不反代」，不决定「免认证」。"""
        _write_routing(routing_home, _with_identity_whitelist())
        middleware, _ = _make_middleware()
        req = _FakeRequest({"X-Hermes-Identity": "yangtb"})  # 不带密码
        with _fake_bind(FakeBind(raise_for_unknown=True)):
            resp = await middleware(req, _DenyHandler())
        assert resp.status == 401, (
            "白名单身份无凭据时被放行 ⇒ 白名单又一次成了认证绕行道"
        )
        assert "ldap_auth_required" in resp.text

    @pytest.mark.asyncio
    async def test_whitelisted_identity_with_valid_credentials_is_not_proxied(
        self, routing_home
    ):
        """门放行不等于反代：白名单的既有语义必须完好。"""
        _write_routing(routing_home, _with_identity_whitelist())
        _seed_valid_cache(routing_home, "yangtb")
        middleware, _ = _make_middleware()
        handler = _RecordingHandler()
        recorder = _ProxyRecorder()
        req = _FakeRequest({"X-Hermes-Identity": "yangtb"})
        with _fake_bind(FakeBind(raise_for_unknown=True)):
            with recorder.patch():
                resp = await middleware(req, handler)
        assert resp.status == 200
        assert len(handler.requests) == 1, "白名单身份应由 root gateway 本体处理"
        assert not recorder.forwarded_headers, "白名单身份不得被反代到子容器"

    @pytest.mark.asyncio
    async def test_unknown_identity_must_still_pass_the_gate(self, routing_home):
        """未知 uid 改前直接透传 ⇒ 「路由表里查不到」等价于「不必验证身份」。"""
        middleware, _ = _make_middleware()
        req = _FakeRequest({"X-Hermes-Identity": "nobody"})
        with _fake_bind(FakeBind(raise_for_unknown=True)):
            resp = await middleware(req, _DenyHandler())
        assert resp.status == 401
        assert "ldap_auth_required" in resp.text

    @pytest.mark.asyncio
    async def test_broken_endpoint_route_does_not_skip_the_gate(self, routing_home):
        """已登记 uid 的 endpoint 配错时，改前会退化为不受门保护的 default 路径。

        `resolve_api_identity_route()` 在该 profile 缺 `profile_endpoints` 条目时
        返回 None，调用点无法与「未知 uid」区分 —— 于是一条配置错误把本该受门
        保护的请求变成了免认证通路。
        """
        _write_routing(routing_home, BROKEN_ENDPOINT_YAML)
        middleware, _ = _make_middleware()
        req = _FakeRequest({"X-Hermes-Identity": "yangtb"})
        with _fake_bind(FakeBind(raise_for_unknown=True)):
            resp = await middleware(req, _DenyHandler())
        assert resp.status == 401
        assert "ldap_auth_required" in resp.text

    @pytest.mark.asyncio
    async def test_gate_rejection_precedes_the_whitelist_branch(self, routing_home):
        """顺序断言：门在路由判定之前，故一次拒绝不可能走到白名单/路由分支。

        用「白名单命中 + 明确密码错」把两条分支同时置于可达状态：若顺序回退，
        响应会由 401 变成透传 200。
        """
        _write_routing(routing_home, _with_identity_whitelist())
        middleware, _ = _make_middleware()
        req = _FakeRequest(
            {"X-Hermes-Identity": "yangtb", "X-Hermes-Identity-Password": "wrong"}
        )
        with _fake_bind(FakeBind({})):  # bind 可判定 → 凭据被拒
            resp = await middleware(req, _DenyHandler())
        assert resp.status == 401
        assert "ldap_auth_failed" in resp.text


class _SSEProxyRecorder:
    """Like _ProxyRecorder, but the fake upstream answers with an SSE stream
    and records the requested timeout so tests can assert the streaming
    contract (no wholesale buffering, unbounded total timeout).
    """

    def __init__(self, chunks=4):
        self.forwarded_headers: dict = {}
        self.forwarded_timeout = None
        self._chunks = chunks

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

        class _Content:
            async def iter_any(self):
                for i in range(recorder._chunks):
                    yield f"data: chunk-{i}\n\n".encode()

        class _Resp:
            status = 200
            headers = {"Content-Type": "text/event-stream"}
            content = _Content()

        def fake_request(*args, **kwargs):
            recorder.forwarded_headers.update(kwargs.get("headers") or {})
            recorder.forwarded_timeout = kwargs.get("timeout")
            return _Ctx(_Resp())

        return patch.object(aiohttp.ClientSession, "request", fake_request)


class TestSSEProxyStreaming:
    """SSE passthrough must go through a real aiohttp request/response cycle
    (StreamResponse.prepare() needs a genuine transport), so these tests run
    the middleware inside an aiohttp test server and fake only the upstream
    leg.
    """

    @staticmethod
    def _upstream_app(chunks: int):
        from aiohttp import web

        upstream_hits: dict = {"count": 0}

        async def handler(request):
            upstream_hits["count"] += 1
            resp = web.StreamResponse(
                status=200,
                headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"},
            )
            await resp.prepare(request)
            for i in range(chunks):
                await resp.write(f"data: chunk-{i}\n\n".encode())
            await resp.write_eof()
            return resp

        return web.Application(), handler, upstream_hits

    @pytest.mark.asyncio
    async def test_sse_response_streams_chunk_by_chunk(self, routing_home, unused_tcp_port):
        from aiohttp import web
        from aiohttp.test_utils import TestServer, TestClient

        app, handler, upstream_hits = self._upstream_app(chunks=4)
        app.router.add_route("POST", "/v1/chat/completions", handler)
        upstream = TestServer(app, port=unused_tcp_port)
        await upstream.start_server()

        routed = routing_home / "patch_feishu_profile.yaml"
        routed.write_text(
            ROUTING_YAML.replace(
                "http://localhost:26026", f"http://127.0.0.1:{unused_tcp_port}"
            ),
            encoding="utf-8",
        )
        from owner.patch_config import invalidate_patch_feishu_profile_config_cache

        invalidate_patch_feishu_profile_config_cache()

        # Transport assertion, not an auth assertion: use the gate's invisible
        # path (valid cache, no password) so the enforce policy is out of scope.
        _seed_valid_cache(routing_home, "yangtb")

        middleware, _ = _make_middleware()

        async def passthrough(request):
            raise AssertionError("routed identity must be proxied, not handled locally")

        proxy_app = web.Application(middlewares=[middleware])
        proxy_app.router.add_route("POST", "/v1/chat/completions", passthrough)
        proxy = TestServer(proxy_app)
        await proxy.start_server()

        client = TestClient(proxy)
        async with client:
            resp = await client.post(
                "/v1/chat/completions",
                json={"messages": [], "stream": True},
                headers={"X-Hermes-Identity": "yangtb"},
            )
            assert resp.status == 200
            assert "text/event-stream" in resp.headers["Content-Type"]
            text = await resp.text()
            for i in range(4):
                assert f"data: chunk-{i}" in text
        assert upstream_hits["count"] == 1

        await proxy.close()
        await upstream.close()

    @pytest.mark.asyncio
    async def test_non_stream_request_keeps_bounded_timeout(self, routing_home):
        middleware, _ = _make_middleware()
        handler = _RecordingHandler()
        recorder = _ProxyRecorder()
        # Transport assertion, not an auth assertion: use the gate's invisible
        # path (valid cache, no password) so the enforce policy is out of scope.
        _seed_valid_cache(routing_home, "yangtb")

        req = _FakeRequest({"X-Hermes-Identity": "yangtb"})
        with recorder.patch():
            resp = await middleware(req, handler)

        assert resp.status == 200
        # _FakeRequest._body is b"{}" — no "stream" key → buffered path.
        assert recorder.forwarded_timeout is not None
        assert recorder.forwarded_timeout.total == 120
        assert handler.requests == []
