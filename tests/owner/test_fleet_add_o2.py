"""C05 fleet_add O2：apply 写 overlay + allowlist + home（tmp_path，不碰生产）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from owner.scripts import fleet_add as fleet_add_cli
from owner.scripts.fleet_add_lib import (
    FleetAddError,
    apply_fleet_add,
    is_production_path,
    merge_csv_ids,
    plan_fleet_add,
    read_dotenv_file,
    upsert_dotenv_key,
)

FIXTURE = Path(__file__).parent / "fixtures" / "fleet_add_overlay.yaml"


@pytest.fixture
def fixture_overlay() -> dict:
    data = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


@pytest.fixture
def staged(tmp_path, fixture_overlay):
    """夹具 overlay + 空目标/Hub 树，全部在 tmp_path 下。"""
    overlay_path = tmp_path / "overlay.yaml"
    # 合并进「已有」overlay 文件（模拟运维副本）
    overlay_path.write_text(
        yaml.safe_dump(fixture_overlay, allow_unicode=True),
        encoding="utf-8",
    )
    hermes_dir = tmp_path / "profiles" / "alice"
    hub_home = tmp_path / "hub"
    hermes_dir.mkdir(parents=True)
    hub_home.mkdir(parents=True)
    # Hub 已有其它人白名单，apply 须 merge
    (hub_home / ".env").write_text(
        "FEISHU_ALLOWED_USERS=ou_yang,ou_li\nOTHER=keep-me\n",
        encoding="utf-8",
    )
    return {
        "overlay_path": overlay_path,
        "hermes_dir": hermes_dir,
        "hub_home": hub_home,
        "tmp_path": tmp_path,
    }


def _plan(fixture_overlay, staged, **kwargs):
    return plan_fleet_add(
        ldap_uid=kwargs.get("ldap_uid", "alice"),
        display_name=kwargs.get("display_name", "爱丽丝"),
        open_ids=kwargs.get("open_ids", ["ou_alice"]),
        tenant_user_ids=kwargs.get("tenant_user_ids", ["tid_alice"]),
        home_channel=kwargs.get("home_channel", "oc_dm_alice"),
        overlay=fixture_overlay,
        app_id="cli_fixture_app",
        hermes_dir=str(staged["hermes_dir"]),
        hub_home=str(staged["hub_home"]),
        hub_allow_all=kwargs.get("hub_allow_all", False),
    )


def test_is_production_path():
    assert is_production_path("/data/hermes/overlay.yaml")
    assert is_production_path("/data/hermes/profiles/alice/.env")
    assert not is_production_path("/tmp/fleet-add/overlay.yaml")


def test_merge_csv_ids():
    assert merge_csv_ids("a,b", ["b", "c"]) == "a,b,c"
    assert merge_csv_ids("", ["ou_x"]) == "ou_x"


def test_upsert_dotenv_preserves_others(tmp_path):
    p = tmp_path / ".env"
    p.write_text("A=1\nB=2\n", encoding="utf-8")
    upsert_dotenv_key(p, "B", "9")
    upsert_dotenv_key(p, "C", "3")
    text = p.read_text(encoding="utf-8")
    assert "A=1" in text
    assert "B=9" in text
    assert "C=3" in text


def test_apply_writes_overlay_allowlist_home(fixture_overlay, staged):
    plan = _plan(fixture_overlay, staged)
    result = apply_fleet_add(
        plan,
        overlay_path=staged["overlay_path"],
        overlay=fixture_overlay,
        stamp="teststamp",
    )
    assert result["mode"] == "apply"
    assert result["phase"] == "O2"
    assert "fixture-shared-key" not in json.dumps(result)

    # overlay：人卡 + 路由
    ov = yaml.safe_load(staged["overlay_path"].read_text(encoding="utf-8"))
    assert "alice" in ov["fleet_profiles"]
    card = ov["fleet_profiles"]["alice"]
    assert card["api_server"]["api_key"] == "fixture-shared-key-not-real"
    assert card["display_name"] == "爱丽丝"
    routes = ov["feishu"]["bots"]["cli_fixture_app"]["user_routing"][
        "user_profile_routes"
    ]
    assert routes["ou_alice"] == "alice"
    assert routes["ou_yang"] == "yangtb"  # 旧路由保留

    # 备份存在
    assert result["backups"]["overlay"]
    assert Path(result["backups"]["overlay"]).is_file()

    # 目标 allowlist + home
    target_env = read_dotenv_file(staged["hermes_dir"] / ".env")
    assert "ou_alice" in target_env["FEISHU_ALLOWED_USERS"].split(",")
    assert "tid_alice" in target_env["FEISHU_ALLOWED_USERS"].split(",")
    assert target_env["FEISHU_HOME_CHANNEL"] == "oc_dm_alice"

    # Hub merge
    hub_env = read_dotenv_file(staged["hub_home"] / ".env")
    members = hub_env["FEISHU_ALLOWED_USERS"].split(",")
    assert members[:2] == ["ou_yang", "ou_li"]
    assert "ou_alice" in members and "tid_alice" in members
    assert hub_env["OTHER"] == "keep-me"

    # config.yaml 规范位
    cfg = yaml.safe_load((staged["hermes_dir"] / "config.yaml").read_text(encoding="utf-8"))
    hc = cfg["platforms"]["feishu"]["home_channel"]
    assert hc["chat_id"] == "oc_dm_alice"
    assert hc["platform"] == "feishu"
    assert "回滚" in "\n".join(result["rollback"])


def test_apply_hub_allow_all_skips_hub(fixture_overlay, staged):
    plan = _plan(fixture_overlay, staged, hub_allow_all=True)
    before = (staged["hub_home"] / ".env").read_text(encoding="utf-8")
    apply_fleet_add(
        plan,
        overlay_path=staged["overlay_path"],
        overlay=fixture_overlay,
        stamp="s2",
    )
    assert (staged["hub_home"] / ".env").read_text(encoding="utf-8") == before
    # 目标仍写
    assert (staged["hermes_dir"] / ".env").is_file()


def test_apply_refuses_production(fixture_overlay):
    plan = plan_fleet_add(
        ldap_uid="alice",
        display_name="爱丽丝",
        open_ids=["ou_alice"],
        overlay=fixture_overlay,
        app_id="cli_fixture_app",
        # 默认 hermes_dir/hub → /data/hermes
    )
    with pytest.raises(FleetAddError, match="生产路径"):
        apply_fleet_add(
            plan,
            overlay_path="/data/hermes/overlay.yaml",
            overlay=fixture_overlay,
            allow_production=False,
        )


def test_apply_duplicate_uid_fails(fixture_overlay, staged):
    # 先对合法新人出 plan，再篡改 ldap_uid 指向已有键，覆盖 apply 守卫
    plan = _plan(fixture_overlay, staged)
    bad = dict(plan)
    bad["ldap_uid"] = "yangtb"
    bad["person_card"] = dict(plan["person_card"])
    bad["overlay_writes"] = {
        **plan["overlay_writes"],
        "user_profile_routes_additions": {"ou_brand_new": "yangtb"},
    }
    with pytest.raises(FleetAddError, match="已存在"):
        apply_fleet_add(
            bad,
            overlay_path=staged["overlay_path"],
            overlay=fixture_overlay,
            stamp="dup",
        )


def test_apply_missing_api_key_fails(tmp_path):
    overlay = {
        "fleet_profiles": {},
        "feishu": {"bots": {"app": {"user_routing": {"user_profile_routes": {}}}}},
    }
    overlay_path = tmp_path / "overlay.yaml"
    overlay_path.write_text(yaml.safe_dump(overlay), encoding="utf-8")
    hermes_dir = tmp_path / "profiles" / "zoe"
    hub = tmp_path / "hub"
    hermes_dir.mkdir(parents=True)
    hub.mkdir()
    plan = plan_fleet_add(
        ldap_uid="zoe",
        display_name="佐伊",
        open_ids=["ou_zoe"],
        overlay=overlay,
        app_id="app",
        hermes_dir=str(hermes_dir),
        hub_home=str(hub),
        preferred_port=26026,
    )
    with pytest.raises(FleetAddError, match="api_key"):
        apply_fleet_add(plan, overlay_path=overlay_path, overlay=overlay, stamp="nokey")


def test_cli_apply_on_fixture_temp(staged, fixture_overlay):
    rc = fleet_add_cli.main(
        [
            "--ldap-uid",
            "alice",
            "--display-name",
            "爱丽丝",
            "--open-id",
            "ou_alice",
            "--tenant-user-id",
            "tid_alice",
            "--home-channel",
            "oc_dm_alice",
            "--overlay",
            str(staged["overlay_path"]),
            "--hermes-dir",
            str(staged["hermes_dir"]),
            "--hub-home",
            str(staged["hub_home"]),
            "--app-id",
            "cli_fixture_app",
            "--apply",
            "--json",
        ]
    )
    assert rc == 0
    ov = yaml.safe_load(staged["overlay_path"].read_text(encoding="utf-8"))
    assert "alice" in ov["fleet_profiles"]
    target = read_dotenv_file(staged["hermes_dir"] / ".env")
    assert target["FEISHU_HOME_CHANNEL"] == "oc_dm_alice"


def test_cli_dry_run_still_default(staged, fixture_overlay):
    before = staged["overlay_path"].read_bytes()
    rc = fleet_add_cli.main(
        [
            "--ldap-uid",
            "alice",
            "--display-name",
            "爱丽丝",
            "--open-id",
            "ou_alice",
            "--overlay",
            str(staged["overlay_path"]),
            "--hermes-dir",
            str(staged["hermes_dir"]),
            "--hub-home",
            str(staged["hub_home"]),
            "--app-id",
            "cli_fixture_app",
        ]
    )
    assert rc == 0
    assert staged["overlay_path"].read_bytes() == before
    assert not (staged["hermes_dir"] / ".env").exists()
