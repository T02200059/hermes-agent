#!/usr/bin/env python3
"""C05 fleet_add：舰队开户 CLI（默认 dry-run；O2 apply / O3 apply-host / O4 apply-up）。

用法（本机假夹具 dry-run；**夹具只许 dry-run**）::

    python -m owner.scripts.fleet_add \
      --ldap-uid alice --display-name 爱丽丝 \
      --open-id ou_alice --fixture /path/to/fixture.yaml

用法（对 temp 副本 O2 apply；--fixture 不得与任何 --apply* 同用，
否则合并结果会把夹具假数据 dump 回 overlay）::

    python -m owner.scripts.fleet_add \
      --ldap-uid alice --display-name 爱丽丝 \
      --open-id ou_alice --tenant-user-id tid_alice \
      --home-channel oc_dm_alice \
      --overlay /tmp/fleet-add-demo/overlay.yaml \
      --hermes-dir /tmp/fleet-add-demo/profiles/alice \
      --hub-home /tmp/fleet-add-demo/hub \
      --app-id cli_fixture_app --apply

用法（对 temp O3 种子+三层 compose，不上容器）::

    python -m owner.scripts.fleet_add \
      --ldap-uid alice --display-name 爱丽丝 \
      --open-id ou_alice \
      --hermes-dir /tmp/fleet-add-demo/profiles/alice \
      --home-dir /tmp/fleet-add-demo/home/alice \
      --hermes-root /tmp/fleet-add-demo \
      --app-id cli_fixture_app --apply-host

用法（O4：对已写 compose 的 temp 做 up+health；单测用 mock，勿对生产）::

    python -m owner.scripts.fleet_add \
      --ldap-uid alice --display-name 爱丽丝 --open-id ou_alice \
      --hermes-dir /tmp/fleet-add-demo/profiles/alice \
      --home-dir /tmp/fleet-add-demo/home/alice \
      --hermes-root /tmp/fleet-add-demo \
      --app-id cli_fixture_app --apply-host --apply-up

设计：``owner/docs/design/c05-feishu-user-routing/fleet-add.md``。
O4 ``--apply-up`` 才 docker compose up + 探活；默认 dry 只列命令。
默认拒绝 ``/data/hermes`` 生产路径（``--allow-production`` 才放行）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Hermes 舰队开户（默认 dry-run；--apply=O2；--apply-host=O3；--apply-up=O4）"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例 (dry-run；--fixture 仅限 dry-run):\n"
            "  python -m owner.scripts.fleet_add \\\n"
            "    --ldap-uid alice --display-name 爱丽丝 \\\n"
            "    --open-id ou_alice --fixture tests/owner/fixtures/fleet_add_overlay.yaml\n"
            "\n"
            "示例 (O2 apply 到 temp；勿带 --fixture):\n"
            "  python -m owner.scripts.fleet_add \\\n"
            "    --ldap-uid alice --display-name 爱丽丝 \\\n"
            "    --open-id ou_alice --home-channel oc_dm_alice \\\n"
            "    --overlay /tmp/fa/overlay.yaml --hermes-dir /tmp/fa/profiles/alice \\\n"
            "    --hub-home /tmp/fa/hub \\\n"
            "    --app-id cli_fixture_app --apply\n"
            "\n"
            "示例 (O3 apply-host 到 temp；勿带 --fixture):\n"
            "  python -m owner.scripts.fleet_add \\\n"
            "    --ldap-uid alice --display-name 爱丽丝 --open-id ou_alice \\\n"
            "    --hermes-dir /tmp/fa/profiles/alice --home-dir /tmp/fa/home/alice \\\n"
            "    --hermes-root /tmp/fa \\\n"
            "    --app-id cli_fixture_app --apply-host\n"
            "\n"
            "示例 (O4 apply-up dry 计划已含在默认 dry-run；执行须 --apply-up):\n"
            "  python -m owner.scripts.fleet_add \\\n"
            "    --ldap-uid alice --display-name 爱丽丝 --open-id ou_alice \\\n"
            "    --hermes-dir /tmp/fa/profiles/alice --home-dir /tmp/fa/home/alice \\\n"
            "    --hermes-root /tmp/fa \\\n"
            "    --app-id cli_fixture_app --apply-host --apply-up\n"
        ),
    )
    p.add_argument("--ldap-uid", required=True, help="主键 LDAP uid（= 逻辑 profile）")
    p.add_argument("--display-name", required=True, help="中文展示名")
    p.add_argument(
        "--open-id",
        action="append",
        default=[],
        dest="open_ids",
        help="飞书 ou_*（可多次）；写入 user_profile_routes 与 allowlist",
    )
    p.add_argument(
        "--tenant-user-id",
        action="append",
        default=[],
        dest="tenant_user_ids",
        help="飞书 tenant user_id（可多次；与 ou 一并进 allowlist）",
    )
    p.add_argument(
        "--home-channel",
        default="",
        help="FEISHU_HOME_CHANNEL（优先 oc_* DM chat_id）",
    )
    p.add_argument("--hub-only-feishu", action="store_true")
    p.add_argument("--hub-only-api", action="store_true")
    p.add_argument("--hermes-dir", default="", help="覆盖 docker.hermes_dir（apply 时目标 profile 根）")
    p.add_argument("--home-dir", default="", help="覆盖 docker.home_dir")
    p.add_argument("--port", type=int, default=None, help="指定端口；默认 max(已用)+1")
    p.add_argument(
        "--used-port",
        action="append",
        type=int,
        default=[],
        dest="used_ports",
        help="额外已占用端口（夹具；可多次）",
    )
    p.add_argument(
        "--overlay",
        default="",
        help="overlay.yaml 路径（默认 $HERMES_HOME/overlay.yaml；apply 写此文件）",
    )
    p.add_argument(
        "--fixture",
        default="",
        help=(
            "假 overlay YAML（与 --overlay 合并；测试/对话 dry-run 用，无真 key。"
            "禁止与 --apply/--apply-host/--apply-up 同用：合并结果会被整体 "
            "dump 回 overlay，夹具假数据将污染真实配置）"
        ),
    )
    p.add_argument("--app-id", default="", help="feishu.bots.<app_id>（多 bot 时必填）")
    p.add_argument("--code-dir", default="", help="compose 代码 RO 源路径")
    p.add_argument("--venv-dir", default="", help="compose venv-docker RO 源路径")
    p.add_argument("--hermes-root", default="", help="推导 profiles 根，默认 /data/hermes")
    p.add_argument("--hub-home", default="", help="Hub HERMES_HOME，默认 /data/hermes")
    p.add_argument(
        "--compose-file",
        default="",
        help="O3 compose 实体路径（默认 <hermes-dir>/docker-compose.yml；并在 <hermes-root>/compose/docker-compose.fleet-<uid>.yml 建软链）",
    )
    p.add_argument(
        "--hub-allow-all",
        action="store_true",
        help="跳过 Hub FEISHU_ALLOWED_USERS 双写（文档钉死 ALLOW_ALL）",
    )
    p.add_argument(
        "--api-key",
        default="",
        help="apply 时显式舰队共用 api_key（不回显；缺省从 overlay 人卡复用）",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="只打印计划（默认）",
    )
    p.add_argument(
        "--apply",
        action="store_true",
        help="O2：写 overlay + allowlist + home（仍不 docker/useradd）",
    )
    p.add_argument(
        "--apply-host",
        action="store_true",
        help="O3：种子 profiles/ + 写三层 compose（不上容器；useradd 默认只列）",
    )
    p.add_argument(
        "--run-useradd",
        action="store_true",
        help="O3 配合 --apply-host：在 Linux 上真实执行 useradd（Mac 仍 unsupported）",
    )
    p.add_argument(
        "--apply-up",
        action="store_true",
        help="O4：docker compose up -d + 探活 api_server.url（可先 --apply-host；默认拒生产）",
    )
    p.add_argument(
        "--allow-production",
        action="store_true",
        help="允许 apply/apply-host/apply-up 写 /data/hermes 生产路径（危险；默认拒绝）",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="stdout 只打 JSON（计划或 apply 结果；密钥已脱敏）",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    # 延迟 import，保证 ``python owner/scripts/fleet_add.py`` 也能跑
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    from owner.scripts.fleet_add_lib import (
        DEFAULT_CODE_DIR,
        DEFAULT_HERMES_ROOT,
        DEFAULT_HUB_HOME,
        DEFAULT_VENV_DIR,
        FleetAddError,
        apply_fleet_add,
        apply_fleet_add_host,
        apply_fleet_add_up,
        format_apply_text,
        format_host_apply_text,
        format_plan_text,
        format_up_apply_text,
        load_overlay_yaml,
        merge_fixture_overlay,
        plan_fleet_add,
    )

    args = _parse_args(argv)

    # 防护：夹具只许 dry-run。--fixture 与任何 apply 模式同用时，合并结果
    # （含夹具假 fleet_profiles/路由）会被整体 dump 回 --overlay 指向的真实
    # overlay / 写进种子与 compose，故直接拒绝；plan/dry-run 不受此限制。
    if args.fixture.strip() and (args.apply or args.apply_host or args.apply_up):
        print(
            "错误: --fixture 是测试/对话用假夹具，禁止与 "
            "--apply/--apply-host/--apply-up 同用（合并结果会把夹具假数据 "
            "dump 回 overlay/写盘）。请去掉 --fixture 后重试；dry-run 不受限。",
            file=sys.stderr,
        )
        return 1

    overlay_path = args.overlay.strip() or str(
        Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes")) / "overlay.yaml"
    )
    overlay = load_overlay_yaml(overlay_path)
    if args.fixture.strip():
        fixture = load_overlay_yaml(args.fixture.strip())
        overlay = merge_fixture_overlay(overlay, fixture)

    try:
        plan = plan_fleet_add(
            ldap_uid=args.ldap_uid,
            display_name=args.display_name,
            open_ids=args.open_ids,
            tenant_user_ids=args.tenant_user_ids,
            home_channel=args.home_channel or None,
            hub_only_feishu=args.hub_only_feishu,
            hub_only_api=args.hub_only_api,
            hermes_dir=args.hermes_dir or None,
            home_dir=args.home_dir or None,
            preferred_port=args.port,
            extra_used_ports=args.used_ports,
            overlay=overlay,
            app_id=args.app_id or os.environ.get("FEISHU_APP_ID", ""),
            code_dir=args.code_dir or DEFAULT_CODE_DIR,
            venv_dir=args.venv_dir or DEFAULT_VENV_DIR,
            hermes_root=args.hermes_root or DEFAULT_HERMES_ROOT,
            hub_home=args.hub_home or DEFAULT_HUB_HOME,
            hub_allow_all=args.hub_allow_all,
            compose_file=args.compose_file or None,
        )
    except FleetAddError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1

    results: list[dict] = []

    if args.apply:
        try:
            result = apply_fleet_add(
                plan,
                overlay_path=overlay_path,
                overlay=overlay,
                shared_api_key=args.api_key or None,
                allow_production=args.allow_production,
            )
        except FleetAddError as exc:
            print(f"错误: {exc}", file=sys.stderr)
            return 1
        results.append(result)

    if args.apply_host:
        try:
            host_result = apply_fleet_add_host(
                plan,
                allow_production=args.allow_production,
                run_useradd=args.run_useradd,
            )
        except FleetAddError as exc:
            print(f"错误: {exc}", file=sys.stderr)
            return 1
        results.append(host_result)

    if args.apply_up:
        try:
            up_result = apply_fleet_add_up(
                plan,
                allow_production=args.allow_production,
                execute=True,
            )
        except FleetAddError as exc:
            print(f"错误: {exc}", file=sys.stderr)
            return 1
        results.append(up_result)

    if results:
        if args.json:
            payload: dict | list = results[0] if len(results) == 1 else {"results": results}
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            for result in results:
                phase = result.get("phase")
                if phase == "O3":
                    print(format_host_apply_text(result))
                elif phase == "O4":
                    print(format_up_apply_text(result))
                else:
                    print(format_apply_text(result))
        # O4 执行失败时非 0，便于脚本编排
        if any(r.get("phase") == "O4" and r.get("ok") is False for r in results):
            return 2
        return 0

    if args.json:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
    else:
        print(format_plan_text(plan))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
