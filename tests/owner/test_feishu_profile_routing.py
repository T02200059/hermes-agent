"""Tests for owner/feishu/profile_routing.py."""

from __future__ import annotations

import textwrap
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def hermes_home_with_profile_config():
    """Yield a temp HERMES_HOME containing patch_feishu_profile.yaml."""
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp) / ".hermes"
        home.mkdir()
        (home / "patch_feishu_profile.yaml").write_text(
            textwrap.dedent(
                """
                feishu:
                  user_routing:
                    internal_api_key: secret123
                    whitelist:
                      - ou_whitelist
                    chat_profile_routes:
                      oc_team: team-a
                    user_profile_routes:
                      ou_alice: alice
                    default_profile: guest
                    profile_endpoints:
                      alice: http://localhost:9101
                      guest: http://localhost:9100
                      team-a: http://localhost:9102
                """
            ),
            encoding="utf-8",
        )
        yield home


class TestResolveProfileRoute:
    def _patch_home(self, home: Path):
        return patch("hermes_constants.get_hermes_home", return_value=home)

    def test_whitelist_bypasses_routing(self, hermes_home_with_profile_config):
        from owner.feishu.profile_routing import resolve_profile_route

        with self._patch_home(hermes_home_with_profile_config):
            assert resolve_profile_route("oc_x", "ou_whitelist") is None

    def test_chat_route_has_priority_over_user_route(
        self, hermes_home_with_profile_config
    ):
        from owner.feishu.profile_routing import resolve_profile_route

        with self._patch_home(hermes_home_with_profile_config):
            route = resolve_profile_route("oc_team", "ou_alice")
            assert route is not None
            assert route[0] == "team-a"
            assert route[1] == "http://localhost:9102"
            assert route[2] == "secret123"

    def test_user_route_resolves(self, hermes_home_with_profile_config):
        from owner.feishu.profile_routing import resolve_profile_route

        with self._patch_home(hermes_home_with_profile_config):
            route = resolve_profile_route("oc_other", "ou_alice")
            assert route is not None
            assert route[0] == "alice"
            assert route[1] == "http://localhost:9101"
            assert route[2] == "secret123"

    def test_default_profile_resolves(self, hermes_home_with_profile_config):
        from owner.feishu.profile_routing import resolve_profile_route

        with self._patch_home(hermes_home_with_profile_config):
            route = resolve_profile_route("oc_x", "ou_unknown")
            assert route is not None
            assert route[0] == "guest"
            assert route[1] == "http://localhost:9100"

    def test_no_route_when_no_config(self):
        from owner.feishu.profile_routing import resolve_profile_route

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / ".hermes"
            home.mkdir()
            with self._patch_home(home):
                assert resolve_profile_route("oc_x", "ou_x") is None


class TestResolveProfileRouteByName:
    def _patch_home(self, home: Path):
        return patch("hermes_constants.get_hermes_home", return_value=home)

    def test_resolves_known_profile(self, hermes_home_with_profile_config):
        from owner.feishu.profile_routing import resolve_profile_route_by_name

        with self._patch_home(hermes_home_with_profile_config):
            route = resolve_profile_route_by_name("alice")
            assert route is not None
            assert route[0] == "alice"
            assert route[1] == "http://localhost:9101"
            assert route[2] == "secret123"

    def test_unknown_profile_returns_none(self, hermes_home_with_profile_config):
        from owner.feishu.profile_routing import resolve_profile_route_by_name

        with self._patch_home(hermes_home_with_profile_config):
            assert resolve_profile_route_by_name("nobody") is None


class TestShouldRouteText:
    def test_normal_text_routes(self):
        from owner.feishu.profile_routing import _should_route_text

        assert _should_route_text("hello") is True
        assert _should_route_text("/new") is True
        assert _should_route_text("/model gpt-4") is True

    def test_restart_command_does_not_route(self):
        from owner.feishu.profile_routing import _should_route_text

        assert _should_route_text("/restart") is False
        assert _should_route_text("/restart@mybot") is False
        assert _should_route_text("  /Restart  ") is False

    def test_empty_and_non_command_text_routes(self):
        from owner.feishu.profile_routing import _should_route_text

        assert _should_route_text("") is True
        assert _should_route_text(None) is True
        assert _should_route_text("plain text") is True


class TestPatchFeishuProfileLoader:
    def test_loads_top_level_config(self):
        from owner.patch_config import load_patch_feishu_profile_config

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / ".hermes"
            home.mkdir()
            (home / "patch_feishu_profile.yaml").write_text(
                "feishu:\n  user_routing:\n    default_profile: guest\n",
                encoding="utf-8",
            )
            with patch("hermes_constants.get_hermes_home", return_value=home):
                with patch(
                    "owner.patch_config._feishu_profile_cache",
                    {"path": None, "mtime": None, "data": None, "last_load": 0},
                ):
                    cfg = load_patch_feishu_profile_config(force=True)
                    assert cfg.get("feishu", {}).get("user_routing", {}).get(
                        "default_profile"
                    ) == "guest"

    def test_missing_file_returns_empty_dict(self):
        from owner.patch_config import load_patch_feishu_profile_config

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / ".hermes"
            home.mkdir()
            with patch("hermes_constants.get_hermes_home", return_value=home):
                with patch(
                    "owner.patch_config._feishu_profile_cache",
                    {"path": None, "mtime": None, "data": None, "last_load": 0},
                ):
                    cfg = load_patch_feishu_profile_config(force=True)
                    assert cfg == {}
