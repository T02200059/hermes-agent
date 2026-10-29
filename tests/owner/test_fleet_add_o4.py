"""C05 fleet_add O4：compose up + health（mock runner；不依赖真 Docker）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from owner.scripts import fleet_add as fleet_add_cli
from owner.scripts.fleet_add_lib import (
    FleetAddError,
    apply_fleet_add_host,
    apply_fleet_add_up,
    build_up_plan,
    health_probe_urls,
    plan_fleet_add,
    probe_api_health,
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


def test_health_probe_urls_and_build_up_plan():
    urls = health_probe_urls("http://127.0.0.1:26029")
    assert urls[0] == "http://127.0.0.1:26029/health"
    assert "http://127.0.0.1:26029/" in urls or urls[-1].endswith("26029")
    up = build_up_plan(
        compose_file="/tmp/fa/compose/docker-compose.fleet-alice.yml",
        service_name="hermes-alice",
        api_url="http://127.0.0.1:26029",
        port=26029,
    )
    assert "docker compose -f" in up["up_cmd"]
    assert "up -d hermes-alice" in up["up_cmd"]
    assert "26029/health" in up["health"]["probe_urls"][0]
    assert any("stop" in s for s in up["rollback"])


def test_plan_includes_up_section(fixture_overlay, staged):
    plan = _plan(fixture_overlay, staged)
    assert plan["up"]["phase"] == "O4"
    assert plan["up"]["service"] == "hermes-alice"
    assert "compose_up" in [c["step"] for c in plan["planned_commands"]]
    assert "health" in [c["step"] for c in plan["planned_commands"]]
    assert "fixture-shared-key" not in json.dumps(plan)


def test_apply_up_dry_run_lists_commands_no_side_effects(fixture_overlay, staged):
    plan = _plan(fixture_overlay, staged)
    calls: list = []

    def runner(argv):
        calls.append(list(argv))
        return {"returncode": 0, "argv": list(argv)}

    result = apply_fleet_add_up(
        plan,
        execute=False,
        compose_runner=runner,
        health_get=lambda url, **kw: {"ok": True, "status": 200, "url": url},
    )
    assert result["mode"] == "dry-run-up"
    assert result["ok"] is True
    assert result["executed"] is False
    assert "up -d" in result["planned"]["up_cmd"]
    assert result["planned"]["health_probe_urls"]
    assert calls == []
    assert not staged["compose_file"].exists()


def test_apply_up_success_with_mocks(fixture_overlay, staged):
    plan = _plan(fixture_overlay, staged)
    apply_fleet_add_host(plan, stamp="o4pre", mock_useradd=True)
    assert staged["compose_file"].is_file()

    ran: list[list[str]] = []

    def runner(argv):
        ran.append(list(argv))
        return {"returncode": 0, "argv": list(argv), "stdout_tail": "Started", "stderr_tail": ""}

    def health(url, timeout=2.0):
        return {"ok": True, "status": 200, "url": url, "body_snip": "ok"}

    result = apply_fleet_add_up(
        plan,
        execute=True,
        compose_runner=runner,
        health_get=health,
        stamp="o4ok",
    )
    assert result["ok"] is True
    assert result["mode"] == "apply-up"
    assert result["executed"] is True
    assert ran and ran[0][:3] == ["docker", "compose", "-f"]
    assert "up" in ran[0] and "-d" in ran[0]
    assert result["health"]["ok"] is True
    assert result["error"] is None
    assert "fixture-shared-key" not in json.dumps(result)


def test_apply_up_health_failure_triggers_stop_and_rollback(fixture_overlay, staged):
    plan = _plan(fixture_overlay, staged)
    apply_fleet_add_host(plan, stamp="o4bad", mock_useradd=True)

    ran: list[list[str]] = []

    def runner(argv):
        ran.append(list(argv))
        return {"returncode": 0, "argv": list(argv)}

    def health(url, timeout=2.0):
        return {"ok": False, "status": 503, "url": url, "error": "http_error"}

    result = apply_fleet_add_up(
        plan,
        execute=True,
        compose_runner=runner,
        health_get=health,
        health_retries=1,
        health_retry_sleep=0,
        stamp="o4hf",
    )
    assert result["ok"] is False
    assert result["error"]["code"] == "health_failed"
    assert any("stop" in a for a in ran)
    assert any("stop" in str(s) or "回滚" in str(s) for s in result["rollback"])


def test_apply_up_compose_failure(fixture_overlay, staged):
    plan = _plan(fixture_overlay, staged)
    apply_fleet_add_host(plan, stamp="o4cf", mock_useradd=True)

    def runner(argv):
        return {
            "returncode": 1,
            "argv": list(argv),
            "stderr_tail": "compose boom",
            "stdout_tail": "",
        }

    result = apply_fleet_add_up(
        plan,
        execute=True,
        compose_runner=runner,
        health_get=lambda url, **kw: {"ok": True, "status": 200, "url": url},
        stamp="o4cf2",
    )
    assert result["ok"] is False
    assert result["error"]["code"] == "compose_up_failed"
    assert result["health"] is None


def test_apply_up_refuses_production(fixture_overlay):
    plan = plan_fleet_add(
        ldap_uid="alice",
        display_name="爱丽丝",
        open_ids=["ou_alice"],
        overlay=fixture_overlay,
        app_id="cli_fixture_app",
    )
    with pytest.raises(FleetAddError, match="生产路径"):
        apply_fleet_add_up(plan, execute=True, allow_production=False)


def test_probe_api_health_mock_success_and_fail():
    ok = probe_api_health(
        "http://127.0.0.1:9",
        retries=1,
        retry_sleep=0,
        health_get=lambda url, **kw: {"ok": True, "status": 200, "url": url},
    )
    assert ok["ok"] is True
    bad = probe_api_health(
        "http://127.0.0.1:9",
        retries=2,
        retry_sleep=0,
        health_get=lambda url, **kw: {"ok": False, "status": None, "url": url, "error": "timeout"},
    )
    assert bad["ok"] is False
    assert bad["error"] == "health_failed"
    assert len(bad["attempts"]) >= 2


def test_cli_dry_run_lists_o4_without_up(staged, fixture_overlay, capsys):
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
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "docker compose -f" in out
    assert "O4" in out
    assert not staged["compose_file"].exists()


def test_cli_apply_up_missing_compose_returns_nonzero(staged, fixture_overlay, capsys):
    # 不先 apply-host → compose 文件不存在
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
            "--apply-up",
            "--json",
        ]
    )
    assert rc == 2
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["ok"] is False
    assert data["error"]["code"] == "compose_file_missing"
