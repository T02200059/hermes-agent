"""C05 fleet_add 安全加固：apply 边界重验 + useradd argv（shell=False）+ 夹具防护。

对应审查两个中危：
1. plan 经对话/JSON 往返后 apply 不重验 uid/home_dir/hermes_dir → 注入 useradd；
   现于 plan 与 apply 两层跑同一白名单。
2. CLI ``--fixture`` 与 ``--overlay`` 同用时合并结果整体 dump 回真实 overlay →
   apply 模式下直接拒绝（dry-run/plan 不受限；现网 skill 只在 dry-run 用夹具）。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml

from owner.scripts import fleet_add as fleet_add_cli
from owner.scripts import fleet_add_lib as lib
from owner.scripts.fleet_add_lib import (
    FleetAddError,
    apply_fleet_add,
    apply_fleet_add_host,
    apply_fleet_add_up,
    plan_fleet_add,
    validate_host_path,
    validate_ldap_uid,
)

FIXTURE = Path(__file__).parent / "fixtures" / "fleet_add_overlay.yaml"


@pytest.fixture
def fixture_overlay() -> dict:
    data = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


@pytest.fixture
def staged(tmp_path, fixture_overlay):
    """O2/O3/O4 全链路可用的 tmp 树（overlay + profiles + home + compose）。"""
    overlay_path = tmp_path / "overlay.yaml"
    overlay_path.write_text(
        yaml.safe_dump(fixture_overlay, allow_unicode=True),
        encoding="utf-8",
    )
    hermes_dir = tmp_path / "profiles" / "alice"
    home_dir = tmp_path / "home" / "alice"
    hub_home = tmp_path / "hub"
    hub_home.mkdir()
    compose_file = hermes_dir / "docker-compose.yml"
    compose_link = tmp_path / "compose" / "docker-compose.fleet-alice.yml"
    return {
        "overlay_path": overlay_path,
        "hermes_dir": hermes_dir,
        "home_dir": home_dir,
        "hub_home": hub_home,
        "compose_file": compose_file,
        "compose_link": compose_link,
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
        hub_home=str(staged["hub_home"]),
    )


# ---------------------------------------------------------------------------
# 校验器本体
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "bad_uid",
    [
        "a$(touch pwn)",
        "alice`id`",
        "ali\nce",
        "evil uid",
        "alice;id",
        "alice|id",
        "- Leading-dash-user-with-weird-stuff-too-long-name-xxxxxxxx",
    ],
)
def test_validate_ldap_uid_rejects_injection(bad_uid):
    with pytest.raises(FleetAddError, match="ldap_uid"):
        validate_ldap_uid(bad_uid)


@pytest.mark.parametrize(
    "bad_path",
    [
        "/x; touch pwn",
        "/tmp/`pwn`",
        "/tmp/a$(id)",
        "/tmp/a\nb",
        "/tmp/x y",
        "relative/path",
        "",
    ],
)
def test_validate_host_path_rejects_injection(bad_path):
    with pytest.raises(FleetAddError):
        validate_host_path(bad_path, field="home_dir")


@pytest.mark.parametrize(
    "good_path",
    [
        "/home/alice",
        "/data/hermes/profiles/alice-team_2.v",
        "/tmp/fa/home/alice-x",
        "/srv/hermes/installs",
    ],
)
def test_validate_host_path_accepts_legit(good_path):
    assert validate_host_path(good_path, field="home_dir") == good_path


# ---------------------------------------------------------------------------
# plan 层（O1）：注入样例直接拒
# ---------------------------------------------------------------------------

def test_plan_rejects_home_dir_shell_injection(fixture_overlay, staged):
    with pytest.raises(FleetAddError, match="home_dir"):
        plan_fleet_add(
            ldap_uid="alice",
            display_name="爱丽丝",
            open_ids=["ou_alice"],
            overlay=fixture_overlay,
            app_id="cli_fixture_app",
            hermes_dir=str(staged["hermes_dir"]),
            home_dir="/x; touch pwn",
        )


def test_plan_rejects_hermes_dir_backtick_and_newline(fixture_overlay, staged):
    with pytest.raises(FleetAddError, match="hermes_dir"):
        plan_fleet_add(
            ldap_uid="alice",
            display_name="爱丽丝",
            open_ids=["ou_alice"],
            overlay=fixture_overlay,
            app_id="cli_fixture_app",
            hermes_dir="/tmp/`pwn`",
            home_dir=str(staged["home_dir"]),
        )
    with pytest.raises(FleetAddError, match="hermes_dir"):
        plan_fleet_add(
            ldap_uid="alice",
            display_name="爱丽丝",
            open_ids=["ou_alice"],
            overlay=fixture_overlay,
            app_id="cli_fixture_app",
            hermes_dir="/tmp/a\nb",
            home_dir=str(staged["home_dir"]),
        )


def test_plan_rejects_injected_uid(fixture_overlay, staged):
    for bad_uid in ("a$(touch pwn)", "alice`id`", "ali\nce"):
        with pytest.raises(FleetAddError, match="ldap_uid"):
            plan_fleet_add(
                ldap_uid=bad_uid,
                display_name="爱丽丝",
                open_ids=["ou_alice"],
                overlay=fixture_overlay,
                app_id="cli_fixture_app",
                hermes_dir=str(staged["hermes_dir"]),
                home_dir=str(staged["home_dir"]),
            )


def test_plan_rejects_relative_and_bad_root(fixture_overlay):
    with pytest.raises(FleetAddError, match="绝对路径"):
        plan_fleet_add(
            ldap_uid="alice",
            display_name="爱丽丝",
            open_ids=["ou_alice"],
            overlay=fixture_overlay,
            app_id="cli_fixture_app",
            home_dir="relative/home",
        )
    with pytest.raises(FleetAddError, match="hermes_root"):
        plan_fleet_add(
            ldap_uid="alice",
            display_name="爱丽丝",
            open_ids=["ou_alice"],
            overlay=fixture_overlay,
            app_id="cli_fixture_app",
            hermes_root="/tmp/r; rm -rf /",
        )


def test_plan_accepts_legit_paths_not_overblocked(fixture_overlay, staged):
    plan = plan_fleet_add(
        ldap_uid="alice",
        display_name="爱丽丝",
        open_ids=["ou_alice"],
        overlay=fixture_overlay,
        app_id="cli_fixture_app",
        hermes_dir="/srv/hermes/profiles/alice-team_2.v",
        home_dir="/srv/home/alice-x",
    )
    assert plan["person_card"]["docker"]["hermes_dir"] == (
        "/srv/hermes/profiles/alice-team_2.v"
    )
    assert plan["person_card"]["docker"]["home_dir"] == "/srv/home/alice-x"


# ---------------------------------------------------------------------------
# apply 层（O2/O3/O4）：plan 被篡改后重验仍拒
# ---------------------------------------------------------------------------

def test_apply_o2_rejects_tampered_uid(fixture_overlay, staged):
    plan = _plan(fixture_overlay, staged)
    bad = copy.deepcopy(plan)
    bad["ldap_uid"] = "evil$(id)"
    with pytest.raises(FleetAddError, match="ldap_uid"):
        apply_fleet_add(
            bad,
            overlay_path=staged["overlay_path"],
            overlay=fixture_overlay,
            stamp="inj1",
        )


def test_apply_o2_rejects_tampered_env_path(fixture_overlay, staged):
    plan = _plan(fixture_overlay, staged)
    bad = copy.deepcopy(plan)
    bad["feishu_allowed_users"]["target_profile_env"]["path"] = "/tmp/`pwn`/.env"
    with pytest.raises(FleetAddError, match="target_profile_env.path"):
        apply_fleet_add(
            bad,
            overlay_path=staged["overlay_path"],
            overlay=fixture_overlay,
            stamp="inj2",
        )


def test_apply_host_rejects_tampered_uid_and_paths(fixture_overlay, staged):
    plan = _plan(fixture_overlay, staged)
    for mutate in (
        {"ldap_uid": "evil`id`"},
        {"person_card": {**plan["person_card"], "docker": {
            **plan["person_card"]["docker"], "home_dir": "/x; touch pwn",
        }}},
    ):
        bad = copy.deepcopy(plan)
        bad.update(mutate)
        with pytest.raises(FleetAddError):
            apply_fleet_add_host(bad, stamp="inj3")
        # 先于任何写盘
        assert not staged["compose_file"].exists()

    bad = copy.deepcopy(plan)
    bad["seed"]["directories"] = ["/tmp/ok", "/tmp/bad; touch pwn"]
    with pytest.raises(FleetAddError, match="seed.directories"):
        apply_fleet_add_host(bad, stamp="inj4")
    assert not staged["compose_file"].exists()


def test_apply_up_rejects_tampered_uid_compose_service(fixture_overlay, staged):
    plan = _plan(fixture_overlay, staged)
    bad = copy.deepcopy(plan)
    bad["ldap_uid"] = "evil$(id)"
    with pytest.raises(FleetAddError, match="ldap_uid"):
        apply_fleet_add_up(bad, execute=False)

    bad = copy.deepcopy(plan)
    bad["up"]["compose_file"] = "/tmp/x; pwn.yml"
    with pytest.raises(FleetAddError, match="compose_file"):
        apply_fleet_add_up(bad, execute=False)

    bad = copy.deepcopy(plan)
    bad["up"]["service"] = "svc; rm -rf /"
    with pytest.raises(FleetAddError, match="服务名"):
        apply_fleet_add_up(bad, execute=False)


# ---------------------------------------------------------------------------
# useradd：argv 列表（shell=False），不执行 plan 回传的展示字符串
# ---------------------------------------------------------------------------

class _FakeProc:
    def __init__(self, returncode: int, stderr: str = ""):
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = ""


_SUPPORTED_LINUX = {
    "supported": True,
    "system": "Linux",
    "useradd_path": "/usr/sbin/useradd",
    "status": "available",
    "note": "",
}


def _patch_useradd_supported(monkeypatch, calls, id_rc: int):
    monkeypatch.setattr(
        lib, "host_useradd_support", lambda: dict(_SUPPORTED_LINUX)
    )

    def fake_run(argv, **kwargs):
        calls.append((list(argv), dict(kwargs)))
        if list(argv) == ["id", "alice"]:
            return _FakeProc(id_rc)
        return _FakeProc(0)

    monkeypatch.setattr(lib.subprocess, "run", fake_run)


def test_apply_host_useradd_runs_argv_without_shell(fixture_overlay, staged, monkeypatch):
    plan = _plan(fixture_overlay, staged)
    # 篡改 seed 里的展示命令：即使被往返篡改也不得被执行/回显
    plan["seed"]["host_commands"][0]["cmd"] = "touch /tmp/pwn-fleet-add"
    calls: list = []
    _patch_useradd_supported(monkeypatch, calls, id_rc=1)

    result = apply_fleet_add_host(plan, run_useradd=True, stamp="ua1")

    assert result["useradd"]["executed"] is True
    assert result["useradd"]["status"] == "ok"
    assert result["useradd"]["already_exists"] is False
    # 全部子进程均为 argv 列表，无 shell=True
    assert calls, "应真实调用 id/useradd"
    for argv, kwargs in calls:
        assert isinstance(argv, list)
        assert not kwargs.get("shell"), f"shell=True 禁用: {argv!r} {kwargs!r}"
        assert all(not str(a).startswith("touch /tmp/pwn") for a in argv)
    assert calls[0][0] == ["id", "alice"]
    assert calls[1][0] == [
        "useradd", "-m", "-d", str(staged["home_dir"]), "-s", "/bin/bash", "alice",
    ]
    # 展示串由校验后的值重建，不回显被篡改的 seed cmd
    assert "touch /tmp/pwn-fleet-add" not in json.dumps(result)


def test_apply_host_useradd_short_circuits_when_user_exists(fixture_overlay, staged, monkeypatch):
    plan = _plan(fixture_overlay, staged)
    calls: list = []
    _patch_useradd_supported(monkeypatch, calls, id_rc=0)

    result = apply_fleet_add_host(plan, run_useradd=True, stamp="ua2")

    assert result["useradd"]["status"] == "ok"
    assert result["useradd"]["already_exists"] is True
    assert len(calls) == 1  # id 命中即短路，等价旧 `id || useradd`
    assert calls[0][0] == ["id", "alice"]


def test_apply_host_useradd_missing_home_dir_is_structured_error(
    fixture_overlay, staged, monkeypatch
):
    plan = _plan(fixture_overlay, staged)
    del plan["person_card"]["docker"]["home_dir"]
    calls: list = []
    _patch_useradd_supported(monkeypatch, calls, id_rc=1)

    result = apply_fleet_add_host(plan, run_useradd=True, stamp="ua3")

    assert result["useradd"]["executed"] is False
    assert result["useradd"]["status"] == "error"
    assert "home_dir" in str(result["useradd"].get("error"))
    assert calls == []


# ---------------------------------------------------------------------------
# 夹具防护：--fixture 与 apply 同用直接拒绝（dry-run 不受限）
# ---------------------------------------------------------------------------

def _cli_apply_args(staged, *extra):
    return [
        "--ldap-uid", "alice",
        "--display-name", "爱丽丝",
        "--open-id", "ou_alice",
        "--overlay", str(staged["overlay_path"]),
        "--hermes-dir", str(staged["hermes_dir"]),
        "--home-dir", str(staged["home_dir"]),
        "--hermes-root", str(staged["hermes_root"]),
        "--compose-file", str(staged["compose_file"]),
        "--hub-home", str(staged["hub_home"]),
        "--app-id", "cli_fixture_app",
        "--fixture", str(FIXTURE),
        *extra,
    ]


def test_cli_rejects_fixture_with_apply(staged, capsys):
    before = staged["overlay_path"].read_bytes()
    rc = fleet_add_cli.main(_cli_apply_args(staged, "--apply", "--json"))
    assert rc == 1
    err = capsys.readouterr().err
    assert "fixture" in err and "apply" in err
    # 真实 overlay 未被夹具合并结果污染
    assert staged["overlay_path"].read_bytes() == before
    assert not (staged["hermes_dir"] / ".env").exists()


def test_cli_rejects_fixture_with_apply_host(staged, capsys):
    rc = fleet_add_cli.main(_cli_apply_args(staged, "--apply-host", "--json"))
    assert rc == 1
    assert "fixture" in capsys.readouterr().err
    assert not staged["compose_file"].exists()


def test_cli_rejects_fixture_with_apply_up(staged, capsys):
    rc = fleet_add_cli.main(_cli_apply_args(staged, "--apply-up", "--json"))
    assert rc == 1
    assert "fixture" in capsys.readouterr().err


def test_cli_fixture_dry_run_still_allowed(staged, capsys):
    before = staged["overlay_path"].read_bytes()
    rc = fleet_add_cli.main(_cli_apply_args(staged, "--json"))
    assert rc == 0
    out = capsys.readouterr().out
    assert '"phase": "O1"' in out
    # dry-run 零写盘
    assert staged["overlay_path"].read_bytes() == before
    assert not staged["compose_file"].exists()
