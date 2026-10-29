"""C05: fleet_profiles + user_routing 解析 / hub_only / endpoints 推导 / 归属校验."""

from __future__ import annotations

import pytest

from owner.feishu import profile_routing as pr


@pytest.fixture
def routing(monkeypatch):
    """Replace synthesized ``_load_routing_config`` with a controllable dict."""
    state: dict = {"cfg": {}}
    monkeypatch.setattr(pr, "_load_routing_config", lambda: state["cfg"], raising=True)
    monkeypatch.setattr(pr, "_ownership_notices", set(), raising=True)
    monkeypatch.delenv(pr.CONTAINER_PROFILE_ENV, raising=False)

    def _set(cfg: dict) -> None:
        state["cfg"] = cfg

    return _set


DM = "p2p"
GROUP = "group"


class TestRoutePriority:
    def test_no_config_returns_none(self, routing):
        routing({})
        assert pr.resolve_profile_route("chat1", "ou_a") is None

    def test_chat_route_wins_over_user_route(self, routing):
        routing(
            {
                "chat_profile_routes": {"chat1": "group-bot"},
                "user_profile_routes": {"ou_a": "personal-bot"},
                "profile_endpoints": {
                    "group-bot": {"url": "http://127.0.0.1:26021", "api_key": "k1"},
                    "personal-bot": {"url": "http://127.0.0.1:26022", "api_key": "k2"},
                },
                "hub_only_feishu": set(),
            }
        )
        got = pr.resolve_profile_route("chat1", "ou_a", DM)
        assert got == ("group-bot", "http://127.0.0.1:26021", "k1")

    def test_user_route_when_no_chat(self, routing):
        routing(
            {
                "user_profile_routes": {"ou_a": "yangtb"},
                "profile_endpoints": {
                    "yangtb": {"url": "http://127.0.0.1:26027", "api_key": "k"}
                },
                "hub_only_feishu": set(),
            }
        )
        assert pr.resolve_profile_route("", "ou_a", DM) == (
            "yangtb",
            "http://127.0.0.1:26027",
            "k",
        )

    def test_default_profile(self, routing):
        routing(
            {
                "default_profile": "fleet_default",
                "profile_endpoints": {
                    "fleet_default": {"url": "http://127.0.0.1:26020", "api_key": "d"}
                },
                "hub_only_feishu": set(),
            }
        )
        assert pr.resolve_profile_route("c", "ou_x", DM)[0] == "fleet_default"

    def test_missing_endpoint_returns_bound_empty_url(self, routing):
        """M3: bound profile without api_server must NOT look like Hub-local None."""
        routing(
            {
                "user_profile_routes": {"ou_a": "ghost"},
                "profile_endpoints": {},
                "hub_only_feishu": set(),
            }
        )
        assert pr.resolve_profile_route("", "ou_a", DM) == ("ghost", "", "")


class TestWhitelistAndHubOnly:
    def test_dm_open_id_whitelist_stays_on_hub(self, routing):
        routing(
            {
                "whitelist": ["ou_a"],
                "user_profile_routes": {"ou_a": "yangtb"},
                "profile_endpoints": {
                    "yangtb": {"url": "http://127.0.0.1:26027", "api_key": "k"}
                },
                "hub_only_feishu": set(),
            }
        )
        assert pr.resolve_profile_route("", "ou_a", DM) is None

    def test_group_skips_open_id_whitelist(self, routing):
        routing(
            {
                "whitelist": ["ou_a"],
                "user_profile_routes": {"ou_a": "yangtb"},
                "profile_endpoints": {
                    "yangtb": {"url": "http://127.0.0.1:26027", "api_key": "k"}
                },
                "hub_only_feishu": set(),
            }
        )
        assert pr.resolve_profile_route("oc_group", "ou_a", GROUP)[0] == "yangtb"

    def test_dm_hub_only_feishu_stays_on_hub(self, routing):
        routing(
            {
                "user_profile_routes": {"ou_a": "yangtb"},
                "profile_endpoints": {
                    "yangtb": {"url": "http://127.0.0.1:26027", "api_key": "k"}
                },
                "hub_only_feishu": {"yangtb"},
            }
        )
        assert pr.resolve_profile_route("", "ou_a", DM) is None

    def test_group_skips_hub_only_feishu(self, routing):
        routing(
            {
                "user_profile_routes": {"ou_a": "yangtb"},
                "profile_endpoints": {
                    "yangtb": {"url": "http://127.0.0.1:26027", "api_key": "k"}
                },
                "hub_only_feishu": {"yangtb"},
            }
        )
        assert pr.resolve_profile_route("oc_g", "ou_a", GROUP)[0] == "yangtb"


class TestEndpointDerivation:
    def test_derive_from_fleet_profiles(self):
        fleet = {
            "yangtb": {
                "api_server": {"url": "http://127.0.0.1:26027", "api_key": "secret"},
                "hub_only": {"feishu": False, "api": False},
            },
            "hubops": {
                "hub_only": {"feishu": True, "api": True},
                # no api_server
            },
        }
        eps = pr._derive_profile_endpoints(fleet, None)
        assert eps == {
            "yangtb": {"url": "http://127.0.0.1:26027", "api_key": "secret"}
        }

    def test_legacy_profile_endpoints_fill_gaps(self):
        fleet = {
            "yangtb": {
                "api_server": {"url": "http://127.0.0.1:26027", "api_key": "a"},
            }
        }
        legacy = {
            "yangtb": {"url": "http://should-not-win", "api_key": "x"},
            "oldname": {"url": "http://127.0.0.1:26099", "api_key": "z"},
        }
        eps = pr._derive_profile_endpoints(fleet, legacy)
        assert eps["yangtb"]["url"] == "http://127.0.0.1:26027"
        assert eps["oldname"]["url"] == "http://127.0.0.1:26099"

    def test_hub_only_feishu_set(self):
        fleet = {
            "a": {"hub_only": {"feishu": True}},
            "b": {"hub_only": True},
            "c": {"hub_only": {"api": True}},
        }
        assert pr._hub_only_feishu_set(fleet) == {"a", "b"}


class TestIdentityTablesC06Ready:
    def test_derive_identity_from_fleet(self):
        fleet = {
            "yangtb": {
                "api_server": {"url": "http://127.0.0.1:1", "api_key": "k"},
                "ldap": {"uid": "yangtb"},
            },
            "hubops": {"hub_only": {"api": True}},
        }
        routes, wl = pr._derive_identity_tables(fleet, {})
        assert routes["yangtb"] == "yangtb"
        assert "hubops" in wl
        assert "hubops" not in routes

    def test_is_api_identity_whitelisted_reads_synthesized(self, routing):
        routing({"identity_whitelist": ["hubops"], "identity_routes": {}})
        assert pr.is_api_identity_whitelisted("hubops") is True
        assert pr.is_api_identity_whitelisted("yangtb") is False


class TestOwnership:
    def test_mismatch_rejects(self, routing, monkeypatch):
        routing({})
        monkeypatch.setenv(pr.CONTAINER_PROFILE_ENV, "yangtb")
        reason = pr.verify_inbound_target_profile({"target_profile": "liruiyang"})
        assert reason is not None
        assert "liruiyang" in reason

    def test_match_accepts(self, routing, monkeypatch):
        routing({})
        monkeypatch.setenv(pr.CONTAINER_PROFILE_ENV, "yangtb")
        assert pr.verify_inbound_target_profile({"target_profile": "yangtb"}) is None

    def test_absent_target_accepts(self, routing, monkeypatch):
        routing({})
        monkeypatch.setenv(pr.CONTAINER_PROFILE_ENV, "yangtb")
        assert pr.verify_inbound_target_profile({}) is None


class TestResolveByName:
    def test_by_name(self, routing):
        routing(
            {
                "profile_endpoints": {
                    "yangtb": {"url": "http://127.0.0.1:26027", "api_key": "k"}
                }
            }
        )
        assert pr.resolve_profile_route_by_name("yangtb") == (
            "yangtb",
            "http://127.0.0.1:26027",
            "k",
        )
        assert pr.resolve_profile_route_by_name("missing") is None



class TestMissingEndpointNoHubFallback:
    """M3: bound-but-broken routes stop local processing (no Hub fallback)."""

    @pytest.mark.asyncio
    async def test_try_route_notifies_and_returns_true(self, routing, monkeypatch):
        routing(
            {
                "user_profile_routes": {"ou_a": "ghost"},
                "profile_endpoints": {},
                "hub_only_feishu": set(),
            }
        )
        notified = []

        async def _notify(adapter, target, profile):
            notified.append((target, profile))

        monkeypatch.setattr(pr, "_notify_forward_failure", _notify)
        got = await pr.try_route_inbound_message(
            object(),
            chat_id="oc_dm",
            open_id="ou_a",
            chat_type="p2p",
            text="hi",
            message_id="om_1",
        )
        assert got is True
        assert notified == [("ou_a", "ghost")]


class TestLoadFailureLastGood:
    """M2: synthesis failure keeps last-good instead of empty Hub fallback.

    Deliberately does **not** use the ``routing`` fixture (which stubs
    ``_load_routing_config``).
    """

    def test_uses_last_good_when_overlay_raises(self, monkeypatch):
        good = {
            "user_profile_routes": {"ou_a": "yangtb"},
            "profile_endpoints": {
                "yangtb": {"url": "http://127.0.0.1:26027", "api_key": "k"}
            },
            "hub_only_feishu": set(),
            "whitelist": [],
            "chat_profile_routes": {},
            "identity_routes": {},
            "identity_whitelist": [],
            "fleet_profiles": {"yangtb": {}},
        }
        pr._last_good_routing_config = dict(good)

        def _boom():
            raise RuntimeError("overlay broken")

        monkeypatch.setattr(pr, "_load_overlay_and_patch", _boom)
        got = pr._load_routing_config()
        assert got["user_profile_routes"]["ou_a"] == "yangtb"
        assert got["profile_endpoints"]["yangtb"]["url"] == "http://127.0.0.1:26027"
