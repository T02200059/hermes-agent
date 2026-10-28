"""C05: overlay-shaped fleet_profiles → synthesized routing config."""

from __future__ import annotations

import pytest

from owner.feishu import profile_routing as pr


@pytest.fixture
def overlay_sources(monkeypatch):
    state = {"overlay": {}, "patch": {}}

    def _load():
        return state["overlay"], state["patch"]

    monkeypatch.setattr(pr, "_load_overlay_and_patch", _load, raising=True)
    monkeypatch.delenv("FEISHU_APP_ID", raising=False)
    return state


def test_synthesizes_endpoints_and_hub_only(overlay_sources, monkeypatch):
    monkeypatch.setenv("FEISHU_APP_ID", "cli_test")
    overlay_sources["overlay"] = {
        "fleet_profiles": {
            "yangtb": {
                "api_server": {
                    "url": "http://127.0.0.1:26027",
                    "api_key": "k-yangtb",
                },
                "hub_only": {"feishu": False, "api": False},
            },
            "hubops": {
                "hub_only": {"feishu": True, "api": True},
            },
        },
        "feishu": {
            "bots": {
                "cli_test": {
                    "user_routing": {
                        "user_profile_routes": {"ou_yang": "yangtb"},
                        "default_profile": "hubops",
                        "whitelist": ["ou_whitelist"],
                    }
                }
            }
        },
    }
    cfg = pr._load_routing_config()
    assert cfg["profile_endpoints"]["yangtb"]["url"] == "http://127.0.0.1:26027"
    assert "hubops" not in cfg["profile_endpoints"]
    assert "hubops" in cfg["hub_only_feishu"]
    assert cfg["user_profile_routes"]["ou_yang"] == "yangtb"
    assert cfg["default_profile"] == "hubops"
    assert "ou_whitelist" in cfg["whitelist"]

    # DM hub_only
    assert pr.resolve_profile_route("", "ou_nobody", "p2p") is None  # default hubops hub_only
    # routed user
    assert pr.resolve_profile_route("", "ou_yang", "p2p") == (
        "yangtb",
        "http://127.0.0.1:26027",
        "k-yangtb",
    )
    # open_id whitelist
    assert pr.resolve_profile_route("", "ou_whitelist", "p2p") is None


def test_patch_fallback_when_overlay_empty(overlay_sources, monkeypatch):
    monkeypatch.setenv("FEISHU_APP_ID", "cli_x")
    overlay_sources["patch"] = {
        "fleet_profiles": {
            "liruiyang": {
                "api_server": {"url": "http://127.0.0.1:26028", "api_key": "p"},
            }
        },
        "feishu": {
            "bots": {
                "cli_x": {
                    "user_routing": {
                        "user_profile_routes": {"ou_li": "liruiyang"},
                    }
                }
            }
        },
    }
    cfg = pr._load_routing_config()
    assert cfg["profile_endpoints"]["liruiyang"]["api_key"] == "p"
    assert pr.resolve_profile_route("", "ou_li")[0] == "liruiyang"
