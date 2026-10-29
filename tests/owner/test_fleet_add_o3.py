"""C05 fleet_add O3：宿主机种子 + 三层挂载 compose（tmp；默认不 useradd / 不上容器）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from owner.scripts import fleet_add as fleet_add_cli
from owner.scripts.fleet_add_lib import (
    FleetAddError,
    apply_fleet_add_host,
    build_compose_service_draft,
    host_useradd_support,
    plan_fleet_add,
    render_compose_yaml,
)

FIXTURE = Path(__file__).parent / "fixtures" / "fleet_add_overlay.yaml"


@pytest.fixture
def fixture_overlay() -> dict:
    data = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


@pytest.fixture
def staged(tmp_path, fixture_overlay):
    overlay_path = tmp_path / "overlay.yaml"
    overlay_path.write_text(
        yaml.safe_dump(fixture_overlay, allow_unicode=True),
        encoding="utf-8",
    )
    hermes_dir = tmp_path / "profiles" / "alice"
    home_dir = tmp_path / "home" / "alice"
    compose_file = tmp_path / "compose" / "docker-compose.fleet-alice.yml"
    return {
        "overlay_path": overlay_path,
        "hermes_dir": hermes_dir,
        "home_dir": home_dir,
        "compose_file": compose_file,
        "tmp_path": tmp_path,
        "hermes_root": tmp_path,
        "code_dir": tmp_path / "code",
        "venv_dir": tmp_path / "venv-docker",
    }


def _plan(fixture_overlay, staged, **kwargs):
    return plan_fleet_add(
        ldap_uid=kwargs.get("ldap_uid", "alice"),
        display_name=kwargs.get("display_name", "爱丽丝"),
        open_ids=kwargs.get("open_ids", ["ou_alice"]),
        overlay=fixture_overlay,
        app_id="cli_fixture_app",
        hermes_dir=str(staged["hermes_dir"]),
        home_dir=str(staged["home_dir"]),
        hermes_root=str(staged["hermes_root"]),
        code_dir=str(staged["code_dir"]),
        venv_dir=str(staged["venv_dir"]),
        compose_file=str(staged["compose_file"]),
        hub_home=str(staged["tmp_path"] / "hub"),
    )


def test_compose_draft_three_layer_not_single_home():
    draft = build_compose_service_draft(
        ldap_uid="alice",
        port=26029,
        hermes_dir="/tmp/fa/profiles/alice",
        home_dir="/tmp/fa/home/alice",
        code_dir="/tmp/fa/code",
        venv_dir="/tmp/fa/venv-docker",
    )
    vols = draft["volumes"]
    assert any(v.endswith(":/opt/hermes-agent:ro") for v in vols)
    assert any(v.endswith(":/opt/venv:ro") for v in vols)
    assert any(v.endswith(":/root") and "home/alice" in v for v in vols)
    assert any("/root/.hermes" in v and "profiles/alice" in v for v in vols)
    # .hermes 必须排在 home 之后（叠挂）
    idx_root = next(i for i, v in enumerate(vols) if v.rstrip().endswith(":/root"))
    idx_hermes = next(i for i, v in enumerate(vols) if "/root/.hermes" in v)
    assert idx_hermes > idx_root
    # 禁止「只有 home」语义
    assert len([v for v in vols if ":/root" in v]) >= 2


def test_render_compose_yaml_guards_single_home():
    draft = build_compose_service_draft(
        ldap_uid="alice",
        port=26029,
        hermes_dir="/tmp/p/alice",
        home_dir="/tmp/h/alice",
    )
    yaml_text = render_compose_yaml(draft)
    assert "profiles" in yaml_text or "/root/.hermes" in yaml_text
    assert ":ro" in yaml_text
    assert "FEISHU_CONNECTION_MODE: send_only" in yaml_text or "send_only" in yaml_text
    doc = yaml.safe_load(yaml_text)
    vols = doc["services"]["hermes-alice"]["volumes"]
    assert any("/root/.hermes" in v for v in vols)

    bad = dict(draft)
    bad["volumes"] = ["/tmp/h/alice:/root"]
    with pytest.raises(FleetAddError, match="三层|单挂"):
        render_compose_yaml(bad)


def test_plan_includes_seed_and_compose_yaml(fixture_overlay, staged):
    plan = _plan(fixture_overlay, staged)
    assert plan["compose_file"] == str(staged["compose_file"])
    assert "services:" in plan["compose_yaml"]
    assert "/root/.hermes" in plan["compose_yaml"]
    seed = plan["seed"]
    assert str(staged["hermes_dir"]) in seed["directories"]
    assert plan["host_useradd"]["status"] in {"unsupported", "available"}
    assert "fixture-shared-key" not in json.dumps(plan)


def test_apply_host_writes_dirs_and_compose(fixture_overlay, staged):
    plan = _plan(fixture_overlay, staged)
    result = apply_fleet_add_host(plan, stamp="o3t1", mock_useradd=True)
    assert result["mode"] == "apply-host"
    assert result["phase"] == "O3"
    assert staged["compose_file"].is_file()
    text = staged["compose_file"].read_text(encoding="utf-8")
    assert "/root/.hermes" in text
    assert ":ro" in text
    assert str(staged["home_dir"]) in text
    assert staged["hermes_dir"].is_dir()
    assert (staged["hermes_dir"] / "memories").is_dir()
    assert (staged["hermes_dir"] / "config.yaml").is_file()
    assert (staged["hermes_dir"] / ".env").is_file()
    env = (staged["hermes_dir"] / ".env").read_text(encoding="utf-8")
    assert "fixture-shared-key" not in env
    assert "FEISHU_APP_SECRET" not in env
    assert result["useradd"]["status"] == "mocked"
    assert result["useradd"]["executed"] is False
    # 无生产密钥泄漏
    assert "fixture-shared-key" not in json.dumps(result)


def test_apply_host_skips_useradd_by_default(fixture_overlay, staged):
    plan = _plan(fixture_overlay, staged)
    result = apply_fleet_add_host(plan, stamp="o3t2", run_useradd=False)
    assert result["useradd"]["executed"] is False
    assert result["useradd"]["status"] in {
        "skipped_flag_off",
        "unsupported",
    }


def test_apply_host_refuses_production(fixture_overlay):
    plan = plan_fleet_add(
        ldap_uid="alice",
        display_name="爱丽丝",
        open_ids=["ou_alice"],
        overlay=fixture_overlay,
        app_id="cli_fixture_app",
    )
    with pytest.raises(FleetAddError, match="生产路径"):
        apply_fleet_add_host(plan, allow_production=False)


def test_apply_host_idempotent_seed(fixture_overlay, staged):
    plan = _plan(fixture_overlay, staged)
    apply_fleet_add_host(plan, stamp="a", mock_useradd=True)
    # 预写非 stub 内容，第二次不得覆盖
    cfg = staged["hermes_dir"] / "config.yaml"
    cfg.write_text("model:\n  default: keep-me\n", encoding="utf-8")
    result = apply_fleet_add_host(plan, stamp="b", mock_useradd=True)
    assert "keep-me" in cfg.read_text(encoding="utf-8")
    skipped = [w for w in result["written"] if w.get("kind") == "minimal_config"]
    assert skipped and skipped[0].get("skipped") == "already_exists"


def test_cli_apply_host_on_tmp(staged, fixture_overlay):
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
            "--home-dir",
            str(staged["home_dir"]),
            "--compose-file",
            str(staged["compose_file"]),
            "--hermes-root",
            str(staged["hermes_root"]),
            "--code-dir",
            str(staged["code_dir"]),
            "--venv-dir",
            str(staged["venv_dir"]),
            "--hub-home",
            str(staged["tmp_path"] / "hub"),
            "--app-id",
            "cli_fixture_app",
            "--apply-host",
            "--json",
        ]
    )
    assert rc == 0
    assert staged["compose_file"].is_file()
    doc = yaml.safe_load(staged["compose_file"].read_text(encoding="utf-8"))
    vols = doc["services"]["hermes-alice"]["volumes"]
    assert any("/root/.hermes" in v for v in vols)
    assert any(v.endswith(":ro") for v in vols)


def test_cli_dry_run_still_default_no_host_writes(staged, fixture_overlay):
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
            "--home-dir",
            str(staged["home_dir"]),
            "--compose-file",
            str(staged["compose_file"]),
            "--app-id",
            "cli_fixture_app",
        ]
    )
    assert rc == 0
    assert not staged["compose_file"].exists()
    assert not staged["hermes_dir"].exists()


def test_host_useradd_support_reports_platform():
    info = host_useradd_support()
    assert "system" in info
    assert info["status"] in {"unsupported", "available"}
