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
                    whitelist:
                      - ou_whitelist
                    chat_profile_routes:
                      oc_team: team-a
                    user_profile_routes:
                      ou_alice: alice
                    default_profile: guest
                    profile_endpoints:
                      alice:
                        url: http://localhost:9101
                        api_key: secret123
                      guest:
                        url: http://localhost:9100
                        api_key: secret123
                      team-a:
                        url: http://localhost:9102
                        api_key: secret123
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


class TestRestartRoutingOwnerS172:
    """[owner §17.2] /restart follows the profile route: routed user → forward
    to their container; whitelist / unrouted user → main gateway restarts."""

    def _patch_home(self, home: Path):
        return patch("hermes_constants.get_hermes_home", return_value=home)

    def test_restart_resolves_route_for_routed_user(self, hermes_home_with_profile_config):
        # A user with a user_profile_routes entry (or default_profile) gets a
        # route even when the text is /restart — routing no longer inspects text.
        from owner.feishu.profile_routing import resolve_profile_route

        with self._patch_home(hermes_home_with_profile_config):
            route = resolve_profile_route("oc_x", "ou_alice")
            assert route is not None

    def test_restart_still_local_for_whitelist_user(self, hermes_home_with_profile_config):
        from owner.feishu.profile_routing import resolve_profile_route

        with self._patch_home(hermes_home_with_profile_config):
            assert resolve_profile_route("oc_x", "ou_whitelist") is None

    def test_local_only_symbols_removed(self):
        # _should_route_text / _LOCAL_ONLY_COMMANDS are gone; importing them fails.
        import owner.feishu.profile_routing as pr

        assert not hasattr(pr, "_should_route_text")
        assert not hasattr(pr, "_LOCAL_ONLY_COMMANDS")


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


class TestReactionRouting:
    """[owner] multi-profile routing: reaction events follow the user route.

    A reaction by a routed user on this bot's message must forward the
    synthetic ``reaction:added:<emoji>`` text to the sub-profile container
    (same contract as inbound messages) instead of being processed on the
    main gateway, which does not own that conversation.
    """

    def _patch_home(self, home: Path):
        return patch("hermes_constants.get_hermes_home", return_value=home)

    def _build_reaction_adapter(self, *, chat_type: str = "group"):
        """Minimal FeishuAdapter wired for _handle_reaction_event.

        The GET-message lookup returns our own bot message (so the
        only-own-message guard passes); the profile-routing forward is
        patched to record calls. ``chat_type`` controls the DM/group semantics
        of resolve_profile_route (whitelist applies to DM only).
        """
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, Mock

        from gateway.config import PlatformConfig
        from plugins.platforms.feishu.adapter import FeishuAdapter

        adapter = FeishuAdapter(PlatformConfig())
        adapter._app_id = "cli_self_app"
        adapter._bot_open_id = "ou_self_bot"
        adapter._bot_user_id = "u_self_bot"

        msg = SimpleNamespace(
            sender=SimpleNamespace(sender_type="app", id="cli_self_app", id_type="app_id"),
            chat_id="oc_alice_chat",
            chat_type=chat_type,
        )
        response = SimpleNamespace(
            success=lambda: True, data=SimpleNamespace(items=[msg])
        )
        adapter._client = SimpleNamespace(
            im=SimpleNamespace(
                v1=SimpleNamespace(
                    message=SimpleNamespace(get=Mock(return_value=response))
                )
            )
        )
        adapter._build_get_message_request = Mock(return_value=object())
        adapter._run_blocking = AsyncMock(
            return_value=SimpleNamespace(
                success=lambda: True, data=SimpleNamespace(items=[msg])
            )
        )
        adapter._handle_message_with_guards = AsyncMock()
        adapter._resolve_sender_profile = AsyncMock(
            return_value={"user_id": "u_alice", "user_name": "Alice", "user_id_alt": None}
        )
        adapter.get_chat_info = AsyncMock(return_value={"name": "Test Chat"})
        return adapter

    def _reaction_event_data(self, *, open_id: str = "ou_alice"):
        from types import SimpleNamespace

        event = SimpleNamespace(
            message_id="om_own_msg",
            user_id=SimpleNamespace(open_id=open_id, user_id=None, union_id=None),
            reaction_type=SimpleNamespace(emoji_type="THUMBSUP"),
        )
        return SimpleNamespace(event=event)

    @pytest.mark.asyncio
    async def test_routed_reaction_forwards_and_skips_local(
        self, hermes_home_with_profile_config
    ):
        import asyncio
        from unittest.mock import AsyncMock

        forwarded = {}

        async def _fake_forward(**kwargs):
            forwarded.update(kwargs)
            return True

        adapter = self._build_reaction_adapter()
        with self._patch_home(hermes_home_with_profile_config):
            with patch(
                "owner.feishu.profile_routing._forward_to_profile_container",
                new=_fake_forward,
            ):
                await adapter._handle_reaction_event(
                    "im.message.reaction.created_v1",
                    self._reaction_event_data(open_id="ou_alice"),
                )

        # The synthetic reaction text was forwarded for the routed user …
        assert forwarded.get("text") == "reaction:added:THUMBSUP"
        assert forwarded.get("open_id") == "ou_alice"
        # … and the main gateway never processed it locally.
        adapter._handle_message_with_guards.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_whitelist_reaction_stays_local(
        self, hermes_home_with_profile_config
    ):
        from unittest.mock import AsyncMock

        # DM context: whitelist applies in p2p, so ou_whitelist stays local.
        adapter = self._build_reaction_adapter(chat_type="p2p")
        with self._patch_home(hermes_home_with_profile_config):
            with patch(
                "owner.feishu.profile_routing._forward_to_profile_container",
                new=AsyncMock(return_value=True),
            ) as fwd:
                await adapter._handle_reaction_event(
                    "im.message.reaction.created_v1",
                    self._reaction_event_data(open_id="ou_whitelist"),
                )
                fwd.assert_not_awaited()

        # Whitelisted user → synthetic reaction event handled locally.
        adapter._handle_message_with_guards.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_forward_failure_still_skips_local(
        self, hermes_home_with_profile_config
    ):
        """Routed user + down container → notify + drop; never serve locally
        (same no-fallback contract as try_route_inbound_message)."""
        import asyncio
        from unittest.mock import AsyncMock

        adapter = self._build_reaction_adapter()
        with self._patch_home(hermes_home_with_profile_config):
            with patch(
                "owner.feishu.profile_routing._forward_to_profile_container",
                new=AsyncMock(return_value=False),
            ):
                with patch(
                    "owner.feishu.profile_routing._notify_forward_failure",
                    new=AsyncMock(),
                ):
                    await adapter._handle_reaction_event(
                        "im.message.reaction.created_v1",
                        self._reaction_event_data(open_id="ou_alice"),
                    )

        adapter._handle_message_with_guards.assert_not_awaited()
