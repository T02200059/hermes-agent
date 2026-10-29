#!/usr/bin/env python3
"""C05 fleet_add：舰队开户 CLI（默认 dry-run；``--apply``=O2；``--apply-host``=O3）。

用法（本机假夹具 dry-run）::

    python -m owner.scripts.fleet_add \
      --ldap-uid alice --display-name 爱丽丝 \
      --open-id ou_alice --fixture /path/to/fixture.yaml

用法（对 temp 副本 O2 apply）::

    python -m owner.scripts.fleet_add \
      --ldap-uid alice --display-name 爱丽丝 \
      --open-id ou_alice --tenant-user-id tid_alice \
      --home-channel oc_dm_alice \
      --overlay /tmp/fleet-add-demo/overlay.yaml \
      --hermes-dir /tmp/fleet-add-demo/profiles/alice \
      --hub-home /tmp/fleet-add-demo/hub \
      --fixture tests/owner/fixtures/fleet_add_overlay.yaml \
      --app-id cli_fixture_app --apply

用法（对 temp O3 种子+三层 compose，不上容器）::

    python -m owner.scripts.fleet_add \
      --ldap-uid alice --display-name 爱丽丝 \
      --open-id ou_alice \
      --hermes-dir /tmp/fleet-add-demo/profiles/alice \
      --home-dir /tmp/fleet-add-demo/home/alice \
      --compose-file /tmp/fleet-add-demo/compose/docker-compose.fleet-alice.yml \
      --hermes-root /tmp/fleet-add-demo \
      --fixture tests/owner/fixtures/fleet_add_overlay.yaml \
      --app-id cli_fixture_app --apply-host

设计：``owner/docs/design/c05-feishu-user-routing/fleet-add.md``。
O3 写 profiles 种子与三层挂载 compose；**不** docker up（O4）；useradd 默认只列。
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
            "Hermes 舰队开户（默认 dry-run；--apply=O2；--apply-host=O3 种子+compose）"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例 (dry-run):\n"
            "  python -m owner.scripts.fleet_add \\\n"
            "    --ldap-uid alice --display-name 爱丽丝 \\\n"
            "    --open-id ou_alice --fixture tests/owner/fixtures/fleet_add_overlay.yaml\n"
            "\n"
            "示例 (O2 apply 到 temp):\n"
            "  python -m owner.scripts.fleet_add \\\n"
            "    --ldap-uid alice --display-name 爱丽丝 \\\n"
            "    --open-id ou_alice --home-channel oc_dm_alice \\\n"
            "    --overlay /tmp/fa/overlay.yaml --hermes-dir /tmp/fa/profiles/alice \\\n"
            "    --hub-home /tmp/fa/hub --fixture tests/owner/fixtures/fleet_add_overlay.yaml \\\n"
            "    --app-id cli_fixture_app --apply\n"
            "\n"
            "示例 (O3 apply-host 到 temp):\n"
            "  python -m owner.scripts.fleet_add \\\n"
            "    --ldap-uid alice --display-name 爱丽丝 --open-id ou_alice \\\n"
            "    --hermes-dir /tmp/fa/profiles/alice --home-dir /tmp/fa/home/alice \\\n"
            "    --compose-file /tmp/fa/compose/docker-compose.fleet-alice.yml \\\n"
            "    --fixture tests/owner/fixtures/fleet_add_overlay.yaml \\\n"
            "    --app-id cli_fixture_app --apply-host\n"
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
        help="假 overlay YAML（与 --overlay 合并；测试/对话用，无真 key）",
    )
    p.add_argument("--app-id", default="", help="feishu.bots.<app_id>（多 bot 时必填）")
    p.add_argument("--code-dir", default="", help="compose 代码 RO 源路径")
    p.add_argument("--venv-dir", default="", help="compose venv-docker RO 源路径")
    p.add_argument("--hermes-root", default="", help="推导 profiles 根，默认 /data/hermes")
    p.add_argument("--hub-home", default="", help="Hub HERMES_HOME，默认 /data/hermes")
    p.add_argument(
        "--compose-file",
        default="",
        help="O3 将写的 compose YAML 路径（默认 <hermes-root>/compose/docker-compose.fleet-<uid>.yml）",
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
        "--allow-production",
        action="store_true",
        help="允许 apply/apply-host 写 /data/hermes 生产路径（危险；默认拒绝）",
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
        format_apply_text,
        format_host_apply_text,
        format_plan_text,
        load_overlay_yaml,
        merge_fixture_overlay,
        plan_fleet_add,
    )

    args = _parse_args(argv)

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

    if results:
        if args.json:
            payload: dict | list = results[0] if len(results) == 1 else {"results": results}
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            for result in results:
                if result.get("phase") == "O3":
                    print(format_host_apply_text(result))
                else:
                    print(format_apply_text(result))
        return 0

    if args.json:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
    else:
        print(format_plan_text(plan))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
