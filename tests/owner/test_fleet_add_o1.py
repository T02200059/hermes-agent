"""C05 fleet_add O1：dry-run 内核（零落盘）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from owner.scripts.fleet_add_lib import (
    FleetAddError,
    allocate_port,
    extract_ports_from_fleet,
    format_plan_text,
    load_overlay_yaml,
    merge_fixture_overlay,
    plan_fleet_add,
)
from owner.scripts import fleet_add as fleet_add_cli

FIXTURE = Path(__file__).parent / "fixtures" / "fleet_add_overlay.yaml"


@pytest.fixture
def fixture_overlay() -> dict:
    data = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def test_allocate_port_max_plus_one():
    assert allocate_port([26027, 26028, 26026]) == 26029
    assert allocate_port([]) == 26026
    with pytest.raises(FleetAddError):
        allocate_port([26027], preferred=26027)


def test_extract_ports(fixture_overlay):
    ports = extract_ports_from_fleet(fixture_overlay["fleet_profiles"])
    assert sorted(ports) == [26026, 26027, 26028]


def test_plan_dry_run_structured(fixture_overlay):
    plan = plan_fleet_add(
        ldap_uid="alice",
        display_name="爱丽丝",
        open_ids=["ou_alice"],
        tenant_user_ids=["ou_tenant_alice"],
        home_channel="oc_dm_alice",
        overlay=fixture_overlay,
        app_id="cli_fixture_app",
    )
    assert plan["mode"] == "dry-run"
    assert plan["phase"] == "O1"
    assert plan["port"]["allocated"] == 26029
    card = plan["person_card"]
    assert card["ldap"]["uid"] == "alice"
    assert card["docker"]["hermes_dir"] == "/data/hermes/profiles/alice"
    assert card["docker"]["home_dir"] == "/home/alice"
    assert card["api_server"]["url"] == "http://127.0.0.1:26029"
    # 密钥永不回显
    assert "fixture-shared-key" not in json.dumps(plan)
    assert card["api_server"]["api_key"].startswith("<redacted")
    assert plan["overlay_writes"]["user_profile_routes_additions"] == {
        "ou_alice": "alice"
    }
    assert "ou_alice" in plan["feishu_allowed_users"]["members"]
    assert "ou_tenant_alice" in plan["feishu_allowed_users"]["members"]
    assert plan["feishu_home_channel"]["feishu_home_channel"] == "oc_dm_alice"
    vols = plan["compose"]["volumes"]
    assert any(v.endswith(":/root") and "/home/alice" in v for v in vols)
    assert any("/root/.hermes" in v and "profiles/alice" in v for v in vols)
    assert any(":ro" in v for v in vols)
    assert plan["compose"]["environment"]["FEISHU_CONNECTION_MODE"] == "send_only"
    assert plan["compose"]["environment"]["HERMES_PROFILE"] == "alice"
    phases = {c["phase"] for c in plan["planned_commands"]}
    assert phases == {"O3", "O4"}
    text = format_plan_text(plan)
    assert "人卡草稿" in text
    assert "fixture-shared-key" not in text


def test_reject_duplicate_uid(fixture_overlay):
    with pytest.raises(FleetAddError, match="已存在"):
        plan_fleet_add(
            ldap_uid="yangtb",
            display_name="重复",
            open_ids=["ou_new"],
            overlay=fixture_overlay,
            app_id="cli_fixture_app",
        )


def test_reject_duplicate_open_id(fixture_overlay):
    with pytest.raises(FleetAddError, match="已占用"):
        plan_fleet_add(
            ldap_uid="newbie",
            display_name="新人",
            open_ids=["ou_yang"],
            overlay=fixture_overlay,
            app_id="cli_fixture_app",
        )


def test_cli_dry_run_zero_writes(tmp_path, fixture_overlay, monkeypatch):
    """CLI dry-run：不改真实 overlay、不碰夹具外文件。"""
    overlay_path = tmp_path / "overlay.yaml"
    overlay_path.write_text(
        yaml.safe_dump(fixture_overlay, allow_unicode=True),
        encoding="utf-8",
    )
    before = overlay_path.read_bytes()
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    # 避免读到用户真 overlay：显式 --overlay
    rc = fleet_add_cli.main(
        [
            "--ldap-uid",
            "carol",
            "--display-name",
            "卡洛",
            "--open-id",
            "ou_carol",
            "--overlay",
            str(overlay_path),
            "--app-id",
            "cli_fixture_app",
            "--json",
        ]
    )
    assert rc == 0
    assert overlay_path.read_bytes() == before


def test_cli_apply_refuses_production_paths(tmp_path, fixture_overlay):
    """O2：未 --allow-production 时拒绝默认 /data/hermes 路径。"""
    overlay_path = tmp_path / "overlay.yaml"
    overlay_path.write_text(
        __import__("yaml").safe_dump(fixture_overlay, allow_unicode=True),
        encoding="utf-8",
    )
    # 不传 --hermes-dir/--hub-home → 计划落在 /data/hermes → apply 应拒绝
    rc = fleet_add_cli.main(
        [
            "--ldap-uid",
            "alice",
            "--display-name",
            "爱丽丝",
            "--open-id",
            "ou_alice",
            "--overlay",
            str(overlay_path),
            "--app-id",
            "cli_fixture_app",
            "--apply",
        ]
    )
    assert rc == 1


def test_load_and_merge_fixture(tmp_path, fixture_overlay):
    base_path = tmp_path / "base.yaml"
    base_path.write_text("approvals:\n  allow_permanent: false\n", encoding="utf-8")
    base = load_overlay_yaml(str(base_path))
    merged = merge_fixture_overlay(base, fixture_overlay)
    assert "approvals" in merged
    assert "yangtb" in merged["fleet_profiles"]
